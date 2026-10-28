"""A warehouse concept on a traced outline (find-and-build plan, step B).

Given an outline (usually existing pavement traced from the photo, site_trace.py) and the site's
roads (site_roads.py), it works out one option per dock side:
- the largest rectangular building that fits the outline, turned to its long side, leaving a
  lane all round and a truck court on the dock side;
- dock doors along that wall;
- receiving and shipping zones along the dock wall, with storage behind;
- the truck court, and a drive from it to the road that serves that side. With a property line,
  the drive leaves only through an edge that faces that street (site_access.py), clear of
  intersections and rail crossings, through a new entrance.

Sage compares the options, chooses the dock side with its reasons, and stages the returned
operations for review. Deterministic geometry; every dimension is a stated assumption, not a
verified standard.
"""
from __future__ import annotations

import math

from .site_context import ROAD_KINDS, normalize_site_area  # noqa: F401  (ROAD_KINDS documents the kinds used)

KIND_RANK = {"highway": 0, "arterial": 0, "ramp": 1, "local": 2, "service": 3, "private": 3, "alley": 4,
             "parking_aisle": 5}
KIND_PENALTY_METERS = {0: 0.0, 1: 60.0, 2: 120.0, 3: 200.0, 4: 260.0, 5: 300.0}
SIDES = ("south", "east", "north", "west")  # plan edges 0-3
DEFAULTS = {"truckCourtDepthMeters": 40.0, "laneMeters": 6.0, "dockDoorWidthMeters": 3.0,
            "dockDoorSpacingMeters": 4.3, "wallHeightMeters": 10.0, "stagingDepthMeters": 18.0,
            "driveWidthMeters": 12.0}
MIN_BUILDING_METERS = 20.0
SMOOTH_METERS = 10.0
MAX_DOORS = 40
GRID_METERS = 1.0
SLAB_ID = "fs-warehouse-slab"
FRONTAGE_STEP_METERS = 10.0  # driveway positions tried along each street-facing stretch
BEND_PENALTY_METERS = 5.0   # a straight drive beats one with a bend of about the same length
TRIM_STEP_METERS = 6        # a building is shortened in these steps to open a corridor for its drive
APRON_METERS = 18.3         # concrete truck apron along the dock wall (60 ft); the rest of the court is asphalt
PAVING_GRID_METERS = 2.0    # the paved yard follows the lot in steps of this size, square to the building
MIN_PAVING_TILE_SQUARE_METERS = 200.0  # smaller leftovers along a crooked edge stay green
MIN_PAVING_TILE_SIDE_METERS = 6.0
MAX_GROUND_TILES = 64       # keeps the plan within one Sage batch
STREET_EDGE_METERS = 4.0    # the driveway is paved out to about this far from the street centreline
PAVING_COLORS = {"slab": "#9da1a4", "apron": "#a7abae", "asphalt": "#4a4f55"}
# The user's look for the building (warehouse 5, 2026-10-23): cyan panels on dark joints, a white band along the top.
WALL_FINISH = {"color": "#06b6d4", "jointColor": "#16191b", "jointWidthMeters": 0.012, "panelHeightMeters": 1.2}
TOP_BAND = {"heightMeters": 1.0, "color": "#ffffff"}
MAX_WALL_PANELS = 5000      # the wall finish's panel budget (wall_finishes.py)
# The InspectorPro logo, centred and large on the two walls beside the dock wall (the user's request,
# 2026-10-23), when the app has the image: a 1254 px square icon, framed to its visible pixels.
LOGO_IMAGE = "/generated/facility-wall-art/cfbcc7042f47d63506feb1ff94d9e6dd6a173d87c1e3088f618fc5e52952d0c2.png"
LOGO_UV = [27 / 1254, 1 - 1226 / 1254, 1227 / 1254, 1 - 29 / 1254]
LOGO_HEIGHT_METERS = 6.5
# A white crosshair target painted at the centre of the most open stretch of yard (the user's request,
# 2026-10-23), when the app has the image: a 1254 px square, framed to its visible pixels.
TARGET_IMAGE = "/generated/facility-wall-art/841df2c1d207a9ce1e458eaa8226416163a83ff5eb52ef68786c31bdcd13c6b4.png"
TARGET_UV = [90 / 1254, 1 - 1164 / 1254, 1164 / 1254, 1 - 90 / 1254]
TARGET_METERS = 12.0
MAX_TRIM_SHARE = 0.4        # by at most this share of its dock wall
COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def _to_plan(bearing: float, x: float, z: float) -> tuple[float, float]:
    """Property metres into the axes of a building turned to `bearing` (plan north on that bearing)."""
    b = math.radians(bearing)
    return x * math.cos(b) - z * math.sin(b), x * math.sin(b) + z * math.cos(b)


def _to_property(bearing: float, u: float, w: float) -> tuple[float, float]:
    b = math.radians(bearing)
    return u * math.cos(b) + w * math.sin(b), -u * math.sin(b) + w * math.cos(b)


def _largest_rectangle(cells) -> tuple[int, int, int, int] | None:
    """The largest all-true axis-aligned rectangle in a boolean grid: (row, col, rows, cols)."""
    best, heights = None, [0] * cells.shape[1]
    for row in range(cells.shape[0]):
        for col in range(cells.shape[1]):
            heights[col] = heights[col] + 1 if cells[row, col] else 0
        stack = []
        for col in range(len(heights) + 1):
            height = heights[col] if col < len(heights) else 0
            start = col
            while stack and stack[-1][1] >= height:
                start, top = stack.pop()
                area = top * (col - start)
                if top and (best is None or area > best[2] * best[3]):
                    best = (row - top + 1, start, top, col - start)
            stack.append((start, height))
    return best


def _outward_bearing(bearing: float, side: str) -> float:
    """The compass bearing a building wall faces: plan south faces bearing + 180, and so on."""
    return (bearing + {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}[side]) % 360


def _compass(degrees: float) -> str:
    return COMPASS[round(degrees / 45) % 8]


def _doors(length: float, settings: dict) -> list[tuple[float, float]]:
    width, spacing = settings["dockDoorWidthMeters"], settings["dockDoorSpacingMeters"]
    count = min(MAX_DOORS, max(0, int((length - 10.0 - width) // spacing) + 1))
    used = (count - 1) * spacing + width if count else 0.0
    first = (length - used) / 2
    return [(round(first + i * spacing, 2), round(first + i * spacing + width, 2)) for i in range(count)]


def plan_warehouse(layout: dict, site: dict, outline: list[dict], dock_side: str | None = None,
                   options: dict | None = None, record_outline: bool = False, catalog: dict | None = None) -> dict:
    """Options for a warehouse on the outline, one per dock side, and the operations for the chosen one."""
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import LineString, Point, Polygon
    settings = {**DEFAULTS, **{key: float(value) for key, value in (options or {}).items() if key in DEFAULTS}}
    shape = Polygon([(p["x"], p["z"]) for p in outline])
    if not shape.is_valid or shape.area < 400:
        raise ValueError("The outline must be a simple polygon of at least 400 square metres")
    # A traced edge is ragged along trees and grass; fill notches up to about 20 m across so they
    # do not shrink the building. The design replaces the pavement, so the edge is a guide, not a wall.
    smoothed = shape.buffer(SMOOTH_METERS, join_style=2).buffer(-SMOOTH_METERS, join_style=2)
    if smoothed.geom_type == "Polygon" and smoothed.is_valid:
        shape = smoothed
    lot = Polygon([(p["x"], p["z"]) for p in site["property"]["boundary"]]) if site.get("property") else None
    space = shape
    if lot is not None:
        # Building and truck court stay inside the lot and clear of each edge's requested setback.
        from shapely.ops import unary_union
        prop = site["property"]
        ring = [(p["x"], p["z"]) for p in prop["boundary"]]
        kind = lambda i: "street" if i in prop["streetEdges"] else "rear" if i in prop["rearEdges"] else "side"  # noqa: E731
        strips = [LineString([ring[i], ring[(i + 1) % len(ring)]]).buffer(prop["setbacksMeters"][kind(i)])
                  for i in range(len(ring)) if prop["setbacksMeters"][kind(i)] > 0]
        inset = lot.difference(unary_union(strips)) if strips else lot
        space = shape.intersection(inset)
        if space.is_empty:
            raise ValueError("No part of the outline is inside the lot and clear of its setbacks")
    roads = [road for road in (site.get("roads") or {}).get("items", []) if road["kind"] in KIND_RANK]
    rails = [LineString([(p["x"], p["z"]) for p in road["line"]])
             for road in (site.get("roads") or {}).get("items", []) if road["kind"] == "railroad"]
    region = space if space.geom_type == "Polygon" else max(space.geoms, key=lambda part: part.area)
    frontages = _frontages(site, roads, rails, settings["driveWidthMeters"]) if lot is not None else None
    best_by_facing = {}
    for bearing in _candidate_bearings(shape):
        for item in _options_at(bearing, region, lot, roads, rails, settings, frontages):
            current = best_by_facing.get(item["facing"])
            if item["fits"] and (current is None or not current["fits"]
                                 or item["buildingAreaSquareMeters"] > current["buildingAreaSquareMeters"] + 1):
                best_by_facing[item["facing"]] = item
            elif current is None:
                best_by_facing[item["facing"]] = item
    results = [best_by_facing[facing] for facing in ("north", "east", "south", "west") if facing in best_by_facing]
    usable = [item for item in results if item["fits"]]
    if not usable:
        raise ValueError("No dock side leaves room for a building of at least 20 x 20 m")

    def preference(item):
        drive = item["drive"]
        rank = KIND_RANK.get(drive["kind"], 9) if drive else 9
        return (drive is None, rank, -round(item["buildingAreaSquareMeters"] / 500), drive["lengthMeters"] if drive else 0)
    chosen = next((item for item in usable if item["facing"] == dock_side), None) if dock_side else None
    chosen = chosen or min(usable, key=preference)
    parking = None
    if lot is not None and frontages:
        # The car park may use the whole lot inside its setbacks, not only today's pavement: it is paved anyway.
        chosen, parking = _with_car_park(chosen, site, lot, roads, rails, frontages, settings, inset)
        results = [chosen if item.get("facing") == chosen["facing"] else item for item in results]
    chosen["_geometry"]["parking"] = parking
    operations = _operations(layout, site, chosen, chosen["_geometry"]["bearing"], settings)
    from .site_parking import operations as car_park_operations
    from .site_trucks import operations as truck_court_operations
    from .site_interior import operations as interior_layout_operations
    parking_operations = car_park_operations(parking, chosen["_geometry"]["origin"], catalog) if parking else []
    truck_operations = truck_court_operations(chosen["_geometry"], settings, catalog)
    interior_operations = interior_layout_operations(chosen["_geometry"], settings, catalog)
    car_park = ({"stalls": len(parking["stalls"]), "stallsNeeded": parking["needed"], "rows": parking["rows"],
                 "accessibleStalls": sum(1 for stall in parking["stalls"] if stall["kind"] != "standard"),
                 "parkedCars": sum(1 for op in parking_operations if op["op"] == "place_asset"),
                 "driveway": {key: value for key, value in parking["drive"].items() if key != "line"}}
                if parking else {"available": False,
                                 "reason": "No room for a car park with its own driveway on a street-facing edge."})
    # The same routes the saved site context derives (site_context.normalize_site_context), for the planner's reader.
    from .site_access import vehicle_routes
    staged = next((op["siteContext"]["property"] for op in operations if op["op"] == "set_site_context"), None)
    routes = vehicle_routes({"property": staged, "roads": site.get("roads")}) if staged else []
    if record_outline:
        # The traced outline is kept as existing pavement in the same batch, after any set_site_context
        # (which replaces the area list), so the two can never undo each other.
        position = 1 if operations[0]["op"] == "set_site_context" else 0
        operations.insert(position, {"op": "upsert_site_area", "area": _existing_area(site, outline)})
    return {
        "readOnly": True,
        "options": [{key: value for key, value in item.items() if key != "_geometry"} for item in results],
        "chosen": chosen["facing"],
        "chosenBecause": "requested" if dock_side and chosen["facing"] == dock_side else
                         "its drive reaches the highest-class road, then the largest building, then the shortest drive",
        "operations": operations,
        "carPark": car_park,
        "parkingOperations": parking_operations,
        "truckCourt": {"trucksAtDocks": sum(1 for op in truck_operations if op["op"] == "place_asset"),
                       "circulation": "counter-clockwise: in along the outside of the court, back along the dock "
                                      "wall with the building on the driver's side"},
        "truckOperations": truck_operations,
        "routesToMainRoad": [{key: route[key] for key in ("use", "mainRoad", "roads", "lengthMeters", "localStreetMeters",
                                                          "railCrossingsAtGrade")} for route in routes],
        "appearance": {"walls": "cyan panels with a 1 m white band along the top",
                       "logos": sum(len((op["wallSettings"]["exteriorFinish"] or {}).get("artworks", []))
                                    for op in operations if op["op"] == "set_perimeter_walls" and op["wallSettings"]),
                       "groundMarks": sum(len(op["ground"].get("marks", []))
                                          for op in operations if op["op"] == "set_ground" and op["ground"]),
                       "employeeEntrance": any(len(op["wallSettings"]["openings"]) > len(chosen["_geometry"]["doors"])
                                               for op in operations if op["op"] == "set_perimeter_walls"
                                               and op["wallSettings"]),
                       "paint": "The trucks, pickups and racks arrive unpainted. Once this design is approved "
                                "and saved, plan_design_paint prepares their colours as a second review."},
        "interior": {"rackRows": sum(1 for op in interior_operations if op["op"] == "place_asset_array"),
                     "rackBays": sum(op["count"] for op in interior_operations if op["op"] == "place_asset_array"),
                     "aisles": sum(1 for op in interior_operations if op["op"] == "add_aisle"),
                     "forklifts": sum(1 for op in interior_operations if op["op"] == "place_asset"),
                     "aisleWidthMeters": 3.7, "forklift": "counterbalance"},
        "interiorOperations": interior_operations,
        "staging": "Stage these operations first, as one batch and in this order: set_site_context replaces the "
                   "site's area list, so put any other area change after them. Then stage parkingOperations (the "
                   "car park's zone, stall paint and parked cars) and truckOperations (the truck court's dock zone, "
                   "circulation arrows and trucks at the doors) and interiorOperations (rack rows, aisles, floor "
                   "markings, charging bay and forklifts) after them, in batches of up to 50."
                   + (" They already record the traced outline as existing pavement; do not stage it separately."
                      if record_outline else ""),
        "assumptions": {**settings,
                        "notes": ["Options are keyed by the compass way the dock wall faces. Each uses the building "
                                  "angle, among the outline's long edges, that fits the largest building.",
                                  "Truck court depth suits 53 ft trailers backing in; confirm with local rules.",
                                  "Drives are 12 m reservations, straight or with one bend, never across a "
                                  "railway or through the building. With a property line they leave through an "
                                  "edge within 15 m of the street's centreline, at least 23 m from an "
                                  "intersection and 30 m from a rail crossing; turning paths are not checked.",
                                  "When no drive fits, the building is shortened along its dock wall in 6 m "
                                  "steps to open a corridor; the option says by how much "
                                  "(shortenedForDriveMeters).",
                                  "Notches in the traced edge up to about 20 m across are smoothed out first.",
                                  "The employee car park has 2.74 x 5.49 m stalls at 90 degrees on a 7.32 m two-way "
                                  "aisle, 0.75 stalls per 1,000 sq ft of building, accessible stalls by the federal "
                                  "table nearest the employee door, and its own driveway at least 30 m from the "
                                  "truck driveway; it keeps clear of the truck court and drive. When it does not "
                                  "fit, the building gives way in 6 m steps (shortenedForCarParkMeters)."]
                                 + ([] if any(op["op"] == "upsert_floor_surface" for op in operations) else
                                    ["The layout already has floor finishes, so no concrete slab is included; a "
                                     "slab over the whole building would overlap them."])},
    }


def _candidate_bearings(shape) -> list[float]:
    """Building angles worth trying: the outline's long axis and its longest edges, squared both ways."""
    rectangle = shape.minimum_rotated_rectangle
    corners = list(rectangle.exterior.coords)[:4]
    axes = []
    long_side = max(((corners[i], corners[(i + 1) % 4]) for i in range(4)), key=lambda side: math.dist(*side))
    axes.append(math.degrees(math.atan2(long_side[1][0] - long_side[0][0], long_side[1][1] - long_side[0][1])) % 180)
    ring = list(shape.simplify(5.0).exterior.coords)
    edges = sorted(((math.dist(a, b), math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 180)
                    for a, b in zip(ring, ring[1:])), reverse=True)
    axes += [angle for length, angle in edges[:4] if length >= 30]
    found = []
    for axis in axes:
        for turn in (axis, (axis + 90) % 180):
            if all(min(abs(turn - other), 180 - abs(turn - other)) > 3 for other in found):
                found.append(turn)
    return [(axis - 90) % 360 for axis in found]


def _frontages(site: dict, roads: list[dict], rails: list, width: float) -> list[tuple[dict, list]]:
    """Each street's driveway stretches along the lot edge (site_access.frontage)."""
    from shapely.geometry import LineString
    from .site_access import CORNER_CLEARANCE_METERS, RAIL_CLEARANCE_METERS, frontage, junctions, rail_crossings
    ring = [(p["x"], p["z"]) for p in site["property"]["boundary"]]
    lines = [(road, LineString([(p["x"], p["z"]) for p in road["line"]])) for road in roads]
    found = []
    for road, line in lines:
        blocked = [(point, CORNER_CLEARANCE_METERS) for point in junctions(line, [o for r, o in lines if r is not road])]
        blocked += [(point, RAIL_CLEARANCE_METERS) for point in rail_crossings(line, rails)]
        pieces = frontage(ring, line, blocked, width)
        if pieces:
            found.append((road, line, pieces))
    return found


def _corners(su, sw, eu, ew, around):
    """Bend points for drives square to the building: straight, one bend, or two bends whose middle
    stretch runs just clear of the building and court (`around` = u_lo, u_hi, w_lo, w_hi)."""
    u_lo, u_hi, w_lo, w_hi = around
    if abs(su - eu) < 0.5 or abs(sw - ew) < 0.5:  # straight, and square to the building
        yield []
    yield [(su, ew)]
    yield [(eu, sw)]
    for w in (w_lo, w_hi):
        yield [(su, w), (eu, w)]
    for u in (u_lo, u_hi):
        yield [(u, sw), (u, ew)]


def _drive_to_frontage(court, building, frontages, rails, bearing, lot, width) -> dict | None:
    """The shortest drive from the court's open sides to a driveway on a street-facing edge.

    The drive's centreline keeps half its width from the building and from the lot line, so the
    whole drive stays clear and inside; only its last stretch, into the driveway, meets the lot line.
    """
    from shapely.geometry import LineString
    from shapely.ops import substring
    from shapely.prepared import prep
    half = width / 2
    core = lot.buffer(-(half - 0.25), join_style=2)
    open_sides = court.exterior.difference(building.buffer(half, join_style=2))
    if core.is_empty or open_sides.is_empty:
        return None
    blocked, inside_core, inside_lot = prep(building.buffer(half - 0.25, join_style=2)), prep(core), prep(lot.buffer(0.05))
    rail_tests = [prep(rail) for rail in rails]
    starts = [piece.interpolate(share, normalized=True) for piece in getattr(open_sides, "geoms", [open_sides])
              if piece.geom_type == "LineString" and piece.length > 0.1 for share in (0.0, 0.5, 1.0)]
    corners = [_to_plan(bearing, x, z) for shape in (building, court) for part in getattr(shape, "geoms", [shape])
               for x, z in part.exterior.coords]
    around = (min(u for u, _ in corners) - half, max(u for u, _ in corners) + half,
              min(w for _, w in corners) - half, max(w for _, w in corners) + half)
    best = None
    for road, line, pieces in frontages:
        penalty = KIND_PENALTY_METERS[KIND_RANK[road["kind"]]]
        for index, piece in pieces:
            steps = max(1, int(piece.length // FRONTAGE_STEP_METERS))
            for step in range(steps + 1):
                end = piece.interpolate(step / steps, normalized=True)
                eu, ew = _to_plan(bearing, end.x, end.y)
                for start in starts:
                    su, sw = _to_plan(bearing, start.x, start.y)
                    for bends in _corners(su, sw, eu, ew, around):
                        points = [(start.x, start.y)] + [_to_property(bearing, u, w) for u, w in bends] + [(end.x, end.y)]
                        points = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 0.01]
                        if len(points) < 2:
                            continue
                        path = LineString(points)
                        score = path.length + penalty + (len(points) - 2) * BEND_PENALTY_METERS
                        if best is not None and score >= best[0]:
                            continue
                        if (path.length > 400 or blocked.intersects(path) or not inside_lot.covers(path)
                                or not inside_core.covers(substring(path, 0, max(0.0, path.length - half)))
                                or any(test.intersects(path) for test in rail_tests)):
                            continue
                        best = (score, road, line, path, end, index)
    if best is None:
        return None
    _score, road, line, path, end, index = best
    return {"road": road["label"], "kind": road["kind"], "lengthMeters": round(path.length, 1),
            "toRoadMeters": round(line.distance(end), 1),
            "line": [list(point) for point in path.coords],
            "entrance": {"edgeIndex": index, "x": round(end.x, 3), "z": round(end.y, 3)}}


def _options_at(bearing, region, lot, roads, rails, settings, frontages=None) -> list[dict]:
    """The four dock options for a building turned to `bearing` (plan north on that compass bearing)."""
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import Polygon
    turned = Polygon([_to_plan(bearing, x, z) for x, z in region.exterior.coords])
    inner = turned.buffer(-settings["laneMeters"], join_style=2)
    if inner.is_empty:
        return []
    if inner.geom_type != "Polygon":
        inner = max(inner.geoms, key=lambda part: part.area)
    min_u, min_w, max_u, max_w = inner.bounds
    us = np.arange(min_u + GRID_METERS / 2, max_u, GRID_METERS)
    ws = np.arange(min_w + GRID_METERS / 2, max_w, GRID_METERS)
    if not len(us) or not len(ws):
        return []
    grid_u, grid_w = np.meshgrid(us, ws)
    found = _largest_rectangle(contains_xy(inner, grid_u, grid_w))
    if not found:
        return []
    row, col, rows, cols = found
    base = (min_u + col * GRID_METERS, min_w + row * GRID_METERS, cols * GRID_METERS, rows * GRID_METERS)
    results = []
    for side in SIDES:
        facing = _outward_bearing(bearing, side)
        quadrant = ("north", "east", "south", "west")[round(facing / 90) % 4]
        shape = _arrange(bearing, side, base, settings, lot, frontages, rails, roads)
        if shape is None:
            results.append({"facing": quadrant, "fits": False, "reason": "The court leaves too little building."})
            continue
        if shape["drive"] is None and frontages:
            # No room for a drive to the street: shorten the building along its dock wall, from either
            # end, until a corridor opens.
            wall = base[2] if side in ("south", "north") else base[3]
            for trim in range(TRIM_STEP_METERS, int(wall * MAX_TRIM_SHARE) + 1, TRIM_STEP_METERS):
                found = [item for item in (
                    _arrange(bearing, side, base, settings, lot, frontages, rails, roads, low=float(trim)),
                    _arrange(bearing, side, base, settings, lot, frontages, rails, roads, high=float(trim)))
                    if item is not None and item["drive"] is not None]
                if found:
                    shape = min(found, key=lambda item: item["drive"]["lengthMeters"])
                    break
        results.append(_option(bearing, side, quadrant, facing, shape, settings, lot, region, base))
    return results


def _arrange(bearing, side, base, settings, lot, frontages, rails, roads, low=0.0, high=0.0, back=0.0) -> dict | None:
    """The building and court for one dock side inside `base` (u0, w0, span_u, span_w), with its truck drive.

    The dock wall is shortened by `low` and `high` metres at its ends, and the building by `back` on its
    side away from the docks; None when that leaves less than MIN_BUILDING_METERS.
    """
    from shapely.geometry import Polygon
    u0, w0, span_u, span_w = base
    court = settings["truckCourtDepthMeters"]
    if side in ("south", "north"):
        width, depth = span_u - low - high, span_w - court - back
        bu0 = u0 + low
        bw0 = w0 + (court if side == "south" else 0.0) + (back if side == "north" else 0.0)
    else:
        width, depth = span_u - court - back, span_w - low - high
        bu0 = u0 + (court if side == "west" else 0.0) + (back if side == "east" else 0.0)
        bw0 = w0 + low
    if min(width, depth) < MIN_BUILDING_METERS:
        return None
    court_box = {"south": (bu0, bw0 - court, bu0 + width, bw0),
                 "north": (bu0, bw0 + depth, bu0 + width, bw0 + depth + court),
                 "west": (bu0 - court, bw0, bu0, bw0 + depth),
                 "east": (bu0 + width, bw0, bu0 + width + court, bw0 + depth)}[side]
    court_plan = [(court_box[0], court_box[1]), (court_box[2], court_box[1]), (court_box[2], court_box[3]),
                  (court_box[0], court_box[3])]
    court_property = Polygon([_to_property(bearing, u, w) for u, w in court_plan])
    building_property = Polygon([_to_property(bearing, u, w) for u, w in
                                 ((bu0, bw0), (bu0 + width, bw0), (bu0 + width, bw0 + depth), (bu0, bw0 + depth))])
    if lot is not None and frontages is not None:
        drive = _drive_to_frontage(court_property, building_property, frontages, rails, bearing, lot,
                                   settings["driveWidthMeters"])
    else:
        drive = _drive_to_road(court_box, side, bearing, building_property, roads, rails)
    return {"width": width, "depth": depth, "origin": (bu0, bw0), "court": court_property,
            "building": building_property, "drive": drive, "trims": (float(low), float(high), float(back))}


def _option(bearing, side, quadrant, facing, shape, settings, lot, region, base, for_car_park=0.0) -> dict:
    """An option's summary for Sage, keeping its geometry for the operations."""
    width, depth, drive = shape["width"], shape["depth"], shape["drive"]
    doors = _doors(width if side in ("south", "north") else depth, settings)
    for_drive = sum(shape["trims"]) - for_car_park
    return {
        "facing": quadrant, "fits": True, "facingBearingDegrees": round(facing, 1),
        "buildingBearingDegrees": round(bearing, 1),
        "buildingWidthMeters": round(width, 1), "buildingDepthMeters": round(depth, 1),
        "buildingAreaSquareMeters": round(width * depth, 1), "dockDoors": len(doors),
        "truckCourtDepthMeters": settings["truckCourtDepthMeters"],
        "drive": {key: value for key, value in drive.items() if key != "line"} if drive else None,
        **({"shortenedForDriveMeters": for_drive} if for_drive else {}),
        **({"shortenedForCarParkMeters": for_car_park} if for_car_park else {}),
        "_geometry": {"bearing": bearing, "side": side, "origin": shape["origin"], "court": shape["court"],
                      "building": shape["building"], "lot": lot, "doors": doors, "drive": drive,
                      "size": (width, depth), "paving": region, "base": base, "trims": shape["trims"]},
    }


def _with_car_park(option, site, lot, roads, rails, frontages, settings, room):
    """The chosen option with an employee car park (site_parking.py) and its own driveway.

    When there is no room near the street, the building gives way in TRIM_STEP_METERS steps: first
    from its back (away from the docks), then from either end of the dock wall, until every stall
    needed (ENOUGH_SHARE of the ratio) fits within MAX_CAR_DRIVE_METERS of its driveway. Otherwise the fullest, then nearest, car
    park found is kept. Returns (option, car park), or (option, None) when no car park reaches a street.
    """
    from shapely.geometry import LineString
    from .site_parking import CAR_DRIVE_WIDTH, ENOUGH_SHARE, MAX_CAR_DRIVE_METERS, plan_car_park, stalls_needed
    car_frontages = _frontages(site, roads, rails, CAR_DRIVE_WIDTH)
    if not car_frontages:
        return option, None
    geometry = option["_geometry"]
    bearing, side, base = geometry["bearing"], geometry["side"], geometry["base"]
    low, high, back = geometry["trims"]
    reach = max(base[2], base[3]) * MAX_TRIM_SHARE
    tries = [(0.0, 0.0, 0.0)] + [move for step in range(TRIM_STEP_METERS, int(reach) + 1, TRIM_STEP_METERS)
                                 for move in ((0.0, 0.0, float(step)), (float(step), 0.0, 0.0), (0.0, float(step), 0.0))]
    best = None
    for add_low, add_high, add_back in tries:
        shape = _arrange(bearing, side, base, settings, lot, frontages, rails, roads,
                         low + add_low, high + add_high, back + add_back)
        if shape is None or shape["drive"] is None:
            continue
        truck = shape["drive"]
        strip = LineString(truck["line"]).buffer(settings["driveWidthMeters"] / 2, cap_style=2, join_style=2)
        entrance = (truck["entrance"]["x"], truck["entrance"]["z"]) if truck.get("entrance") else None
        needed = stalls_needed(shape["width"] * shape["depth"])
        parking = plan_car_park(room, shape["building"], shape["court"], strip, entrance,
                                car_frontages, rails, lot, bearing, needed)
        if parking is None:
            continue
        candidate = (_option(bearing, side, option["facing"], option["facingBearingDegrees"], shape, settings, lot,
                             geometry["paving"], base, for_car_park=add_low + add_high + add_back), parking)
        full, length = len(parking["stalls"]) >= ENOUGH_SHARE * needed, parking["drive"]["lengthMeters"]
        if full and length <= MAX_CAR_DRIVE_METERS:
            return candidate
        rank = (full, len(parking["stalls"]) if not full else 0, -length)
        if best is None or rank > best[0]:
            best = (rank, candidate)
    return best[1] if best is not None else (option, None)


def _drive_to_road(court_box, side, bearing, building, roads, rails) -> dict | None:
    """Without a property line: a straight drive from the court's outer edge to the nearest good road."""
    from shapely.geometry import LineString, Point
    outer = {"south": ((court_box[0] + court_box[2]) / 2, court_box[1]),
             "north": ((court_box[0] + court_box[2]) / 2, court_box[3]),
             "west": (court_box[0], (court_box[1] + court_box[3]) / 2),
             "east": (court_box[2], (court_box[1] + court_box[3]) / 2)}[side]
    start = Point(_to_property(bearing, *outer))
    best = None
    for road in roads:
        line = LineString([(p["x"], p["z"]) for p in road["line"]])
        path = LineString([start, line.interpolate(line.project(start))])
        if (path.length > 400 or path.crosses(building) or path.within(building)
                or any(path.intersects(rail) for rail in rails)):
            continue  # no drive through the building or across a railway
        score = path.length + KIND_PENALTY_METERS[KIND_RANK[road["kind"]]]
        if best is None or score < best[0]:
            best = (score, road, path)
    if not best:
        return None
    _score, road, path = best
    reach = max(0.0, path.length - {"highway": 9.0, "arterial": 7.0, "local": 4.5}.get(road["kind"], 3.0))
    if reach < 1.0:
        return None
    path = LineString([path.coords[0], path.interpolate(reach).coords[0]])
    return {"road": road["label"], "kind": road["kind"], "lengthMeters": round(path.length, 1),
            "line": [list(point) for point in path.coords], "entrance": None}


def _ring(polygon) -> list[dict]:
    """A polygon's outline in millimetres, without the repeated points that rounding can leave."""
    points = []
    for x, z in list(polygon.exterior.coords)[:-1]:
        point = {"x": round(x, 3), "z": round(z, 3)}
        if not points or point != points[-1]:
            points.append(point)
    while len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _existing_area(site: dict, outline: list[dict]) -> dict:
    """The traced outline as a reference area, labelled with the photo it came from."""
    from shapely.geometry import Polygon
    names = {"usgs_naip": "USGS NAIP", "usgs_imagery": "USGS imagery", "mngeo_metro": "Met Council 2025 photo"}
    photo = (site.get("imagery") or [{}])[0]
    label = "Existing pavement (" + names.get(photo.get("source"), "site photo") + \
        (f", {photo['captured']}" if photo.get("captured") else "") + ")"
    shape, tolerance = Polygon([(p["x"], p["z"]) for p in outline]), 0.5
    while len(shape.exterior.coords) - 1 > 48:
        shape, tolerance = shape.simplify(tolerance, preserve_topology=True), tolerance * 1.5
    return {"areaId": "area-existing-pavement", "label": label[:120], "kind": "existing_pavement", "surface": "asphalt",
            "boundary": [{"x": round(x, 3), "z": round(z, 3)} for x, z in list(shape.exterior.coords)[:-1]]}


def _drive_legs(drive: dict, bearing: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A drive's straight legs square to the building (turned frame), the last one carried on across the verge
    to the street."""
    points = [_to_plan(bearing, x, z) for x, z in drive["line"]]
    out = max(0.0, drive.get("toRoadMeters", 0.0) - STREET_EDGE_METERS)
    if out and len(points) > 1:
        (au, aw), (bu, bw) = points[-2], points[-1]
        length = math.hypot(bu - au, bw - aw) or 1.0
        points[-1] = (bu + (bu - au) / length * out, bw + (bw - aw) / length * out)
    return [(a, b) for a, b in zip(points, points[1:]) if abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5]


def _drive_rects(drive: dict, half: float, bearing: float) -> list[tuple]:
    """A drive's legs as rectangles square to the building, paved on across the verge to the street."""
    return [((min(au, bu) - half, min(aw, bw) - half, max(au, bu) + half, max(aw, bw) + half), "asphalt")
            for (au, aw), (bu, bw) in _drive_legs(drive, bearing)]


def _paving(layout: dict, option: dict, bearing: float, settings: dict) -> list[dict]:
    """Ground tiles for the paved lot, square to the building, in the new plan's frame.

    The building (under its slab), the concrete apron along the dock wall, the asphalt rest of the court
    and the drive (out to the street) are tiled exactly. The rest of the paving follows the traced
    pavement inside the setbacks in PAVING_GRID_METERS steps, keeping only tiles big enough to read as
    straight-edged yard; crooked leftovers stay green. Tiles never overlap: each grid cell is used once.
    """
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import Polygon
    geometry = option["_geometry"]
    width, depth = geometry["size"]
    u0, w0 = geometry["origin"]
    side, court = geometry["side"], settings["truckCourtDepthMeters"]
    apron = min(APRON_METERS, court)
    building = (u0, w0, u0 + width, w0 + depth)
    courts = {"east": [((u0 + width, w0, u0 + width + apron, w0 + depth), "apron"),
                       ((u0 + width + apron, w0, u0 + width + court, w0 + depth), "asphalt")],
              "west": [((u0 - apron, w0, u0, w0 + depth), "apron"),
                       ((u0 - court, w0, u0 - apron, w0 + depth), "asphalt")],
              "north": [((u0, w0 + depth, u0 + width, w0 + depth + apron), "apron"),
                        ((u0, w0 + depth + apron, u0 + width, w0 + depth + court), "asphalt")],
              "south": [((u0, w0 - apron, u0 + width, w0), "apron"),
                        ((u0, w0 - court, u0 + width, w0 - apron), "asphalt")]}[side]
    rects = [(building, "slab")] + courts
    if geometry["drive"]:
        rects += _drive_rects(geometry["drive"], settings["driveWidthMeters"] / 2, bearing)
    parking = geometry.get("parking")
    if parking:
        from .site_parking import CAR_DRIVE_WIDTH
        rects.append((parking["rect"], "asphalt"))
        rects += _drive_rects(parking["drive"], CAR_DRIVE_WIDTH / 2, bearing)
    yard = geometry["paving"]
    turned = Polygon([_to_plan(bearing, x, z) for x, z in yard.exterior.coords]) if yard is not None else None
    min_u = min([r[0] for r, _ in rects] + ([turned.bounds[0]] if turned is not None else []))
    min_w = min([r[1] for r, _ in rects] + ([turned.bounds[1]] if turned is not None else []))
    max_u = max([r[2] for r, _ in rects] + ([turned.bounds[2]] if turned is not None else []))
    max_w = max([r[3] for r, _ in rects] + ([turned.bounds[3]] if turned is not None else []))
    us = sorted({round(v, 3) for v in np.arange(min_u, max_u, PAVING_GRID_METERS)} | {round(max_u, 3)}
                | {round(v, 3) for r, _ in rects for v in (r[0], r[2])})
    ws = sorted({round(v, 3) for v in np.arange(min_w, max_w, PAVING_GRID_METERS)} | {round(max_w, 3)}
                | {round(v, 3) for r, _ in rects for v in (r[1], r[3])})
    us, ws = np.array(us), np.array(ws)
    cu, cw = np.meshgrid((us[:-1] + us[1:]) / 2, (ws[:-1] + ws[1:]) / 2)
    kinds = ["slab", "apron", "asphalt", "yard"]
    material = np.full(cu.shape, -1)
    for rect, kind in reversed(rects):  # earlier rectangles win
        inside = (cu > rect[0]) & (cu < rect[2]) & (cw > rect[1]) & (cw < rect[3])
        material[inside] = kinds.index(kind)
    if turned is not None:
        material[(material == -1) & contains_xy(turned, cu, cw)] = kinds.index("yard")
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation", 0))
    tiles = []
    for index, kind in enumerate(kinds):
        free = material == index
        while free.any() and len(tiles) < MAX_GROUND_TILES:
            found = _largest_rectangle(free)
            if not found:
                break
            row, col, rows, cols = found
            box = (us[col], ws[row], us[col + cols], ws[row + rows])
            free[row:row + rows, col:col + cols] = False
            if kind == "yard" and ((box[2] - box[0]) * (box[3] - box[1]) < MIN_PAVING_TILE_SQUARE_METERS
                                   or min(box[2] - box[0], box[3] - box[1]) < MIN_PAVING_TILE_SIDE_METERS):
                break  # the rest are smaller still: crooked leftovers stay green
            tiles.append({"surfaceId": f"gr-{kind}-{len(tiles) + 1}",
                          "minX": round(float(box[0] - u0), 3), "maxX": round(float(box[2] - u0), 3),
                          "minZ": round(float(box[1] - w0), 3), "maxZ": round(float(box[3] - w0), 3),
                          "startElevation": floor, "endElevation": floor, "slopeAxis": "x",
                          "color": PAVING_COLORS["asphalt" if kind == "yard" else kind]})
    return tiles


def _ground_marks(tiles: list[dict]) -> list[dict]:
    """The target at the centre of the largest open yard tile (not the court, a drive or the car park),
    the paving most visible from the air; none when the app lacks the image or the lot has no yard."""
    from pathlib import Path
    yards = [tile for tile in tiles if tile["surfaceId"].startswith("gr-yard-")]
    if not yards or not (Path(__file__).resolve().parents[2] / TARGET_IMAGE.lstrip("/")).is_file():
        return []
    tile = max(yards, key=lambda t: (t["maxX"] - t["minX"]) * (t["maxZ"] - t["minZ"]))
    size = min(TARGET_METERS, 0.6 * min(tile["maxX"] - tile["minX"], tile["maxZ"] - tile["minZ"]))
    return [{"markId": "gm-target", "label": "Crosshair target", "imagePath": TARGET_IMAGE,
             "uv": [round(v, 6) for v in TARGET_UV], "x": round((tile["minX"] + tile["maxX"]) / 2, 3),
             "z": round((tile["minZ"] + tile["maxZ"]) / 2, 3), "widthMeters": round(size, 3),
             "depthMeters": round(size, 3), "rotationDegrees": 0.0}]


def _wall_finish(width: float, depth: float, height: float, dock_edge: int, openings: list[dict], *,
                 color: str = WALL_FINISH["color"], band_color: str | None = TOP_BAND["color"],
                 logo_edges: list[int] | None = None) -> dict:
    """The building's exterior: 2 m panels (wider on a very large building, to stay within the panel
    budget) in `color`, a band along the top in `band_color` (none when None), and the logo on `logo_edges`
    (by default the walls either side of the dock wall)."""
    panel = 2.0
    while 2 * (math.ceil(width / panel) + math.ceil(depth / panel)) * math.ceil(
            height / WALL_FINISH["panelHeightMeters"]) > MAX_WALL_PANELS:
        panel *= 2
    finish = {**WALL_FINISH, "color": color, "panelWidthMeters": panel}
    below = height
    if band_color:
        finish["bands"] = [{"bottomMeters": round(height - TOP_BAND["heightMeters"], 3),
                            "heightMeters": TOP_BAND["heightMeters"], "color": band_color}]
        below = height - TOP_BAND["heightMeters"]
    edges = sorted(((dock_edge + 1) % 4, (dock_edge + 3) % 4)) if logo_edges is None else sorted(set(logo_edges))
    logos = _logos(width, depth, below, edges, openings)
    if logos:
        finish["artworks"] = logos
    return finish


def _logos(width: float, depth: float, below_band: float, edges: list[int], openings: list[dict]) -> list[dict]:
    """The logo centred on each of `edges` between the ground and the band; moved clear of a door in its
    way, or left off that wall when it cannot be."""
    from pathlib import Path
    if not (Path(__file__).resolve().parents[2] / LOGO_IMAGE.lstrip("/")).is_file():
        return []
    tall = min(LOGO_HEIGHT_METERS, 0.75 * below_band)
    wide = tall * (LOGO_UV[2] - LOGO_UV[0]) / (LOGO_UV[3] - LOGO_UV[1])
    logos = []
    for edge in edges:
        length = width if edge in (0, 2) else depth
        doors = [(o["startMeters"] - 0.5, o["endMeters"] + 0.5) for o in openings if o["edge"] == edge]
        candidates = [(length - wide) / 2] + [end for _, end in doors] + [start - wide for start, _ in doors]
        free = [s for s in candidates if 0.5 <= s <= length - wide - 0.5
                and not any(s < end and s + wide > start for start, end in doors)]
        if not free:
            continue
        start = min(free, key=lambda s: abs(s - (length - wide) / 2))
        logos.append({"artworkId": f"inspectorpro-logo-{edge}", "edge": edge, "startMeters": round(start, 3),
                      "widthMeters": round(wide, 3), "bottomMeters": round((below_band - tall) / 2, 3),
                      "heightMeters": round(tall, 3), "imagePath": LOGO_IMAGE, "uv": [round(v, 6) for v in LOGO_UV]})
    return logos


def _slab(layout: dict, width: float, depth: float) -> list[dict]:
    """A plain concrete slab over the whole building, so the floor reads as solid. Finishes may not overlap,
    so it is left out when the layout has finishes of its own (a slab from an earlier plan is replaced)."""
    finishes = ((layout.get("extensions") or {}).get("facilityFloorSurfaces") or {}).get("surfaces") or []
    if any(row.get("surfaceId") != SLAB_ID for row in finishes):
        return []
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation", 0))
    return [{"op": "upsert_floor_surface", "surface": {
        "surfaceId": SLAB_ID, "label": "Concrete slab", "elevation": floor, "material": "concrete",
        "color": "#b8bbbd", "roughness": 0.9,
        "boundary": [{"x": 0.0, "z": 0.0}, {"x": width, "z": 0.0}, {"x": width, "z": depth}, {"x": 0.0, "z": depth}]}}]


def _operations(layout: dict, site: dict, option: dict, bearing: float, settings: dict) -> list[dict]:
    geometry = option["_geometry"]
    width, depth = option["buildingWidthMeters"], option["buildingDepthMeters"]
    side = geometry["side"]
    edge = SIDES.index(side)
    origin = _to_property(bearing, *geometry["origin"])
    plan = dict(((layout.get("extensions") or {}).get("facilityPlan") or {}))
    plan_settings = {"widthMeters": width, "depthMeters": depth,
                     "gridSpacingMeters": float(plan.get("gridSpacingMeters", 1.0)),
                     "majorGridSpacingMeters": float(plan.get("majorGridSpacingMeters", 5.0))}
    stage = min(settings["stagingDepthMeters"], (depth if side in ("south", "north") else width) / 3)
    wall = width if side in ("south", "north") else depth
    half = wall / 2

    def band(start, end):
        """A staging band along the dock wall from `start` to `end` metres along it."""
        if side == "south":
            return [(start, 0.0), (end, 0.0), (end, stage), (start, stage)]
        if side == "north":
            return [(width - end, depth - stage), (width - start, depth - stage), (width - start, depth), (width - end, depth)]
        if side == "east":
            return [(width - stage, start), (width, start), (width, end), (width - stage, end)]
        return [(0.0, depth - end), (stage, depth - end), (stage, depth - start), (0.0, depth - start)]

    storage = {"south": [(0.0, stage), (width, stage), (width, depth), (0.0, depth)],
               "north": [(0.0, 0.0), (width, 0.0), (width, depth - stage), (0.0, depth - stage)],
               "east": [(0.0, 0.0), (width - stage, 0.0), (width - stage, depth), (0.0, depth)],
               "west": [(stage, 0.0), (width, 0.0), (width, depth), (stage, depth)]}[side]

    def zone(zone_id, zone_type, label, points):
        return {"op": "add_zone", "zone": {"zoneId": zone_id, "zoneType": zone_type, "label": label,
                "boundary": [{"x": round(x, 3), "z": round(z, 3)} for x, z in points],
                "floorElevation": 0, "anchors": [], "evidence": []}}

    # A new plan replaces an earlier one: its zones go, and its walls are cleared before the plan size
    # changes (a smaller plan would not hold the old wall's door openings).
    extensions = layout.get("extensions") or {}
    from .site_parking import clear_previous
    from .site_trucks import clear_previous as clear_trucks
    from .site_interior import clear_previous as clear_interior
    redo = clear_previous(layout) + clear_trucks(layout) + clear_interior(layout) + [{"op": "delete_zone", "zoneId": zone_id} for zone_id in ("zn-receiving", "zn-shipping", "zn-storage")
            if any(zone.get("zoneId") == zone_id for zone in layout.get("zones", []))]
    if extensions.get("facilityPerimeterWalls"):
        redo.append({"op": "set_perimeter_walls", "wallSettings": None})
    if extensions.get("facilityGround"):
        redo.append({"op": "set_ground", "ground": None})
    openings = [{"edge": edge, "startMeters": start, "endMeters": end} for start, end in geometry["doors"]]
    if geometry.get("parking"):  # the employee entrance where the walk from the car park meets the wall
        from .site_parking import door_opening
        door = door_opening(geometry["parking"], geometry["origin"], width, depth)
        if not any(o["edge"] == door["edge"] and o["startMeters"] < door["endMeters"] and o["endMeters"] > door["startMeters"]
                   for o in openings):
            openings.append(door)
    tiles = _paving(layout, option, bearing, settings)
    ground = {"schemaVersion": 1, "surfaces": tiles, **({"marks": marks} if (marks := _ground_marks(tiles)) else {})}
    operations = redo + [
        {"op": "set_plan_settings", "planSettings": plan_settings},
        {"op": "set_building_pose", "buildingPose": {"x": round(origin[0], 3), "z": round(origin[1], 3),
                                                     "bearingDegrees": round(bearing, 3)}},
        {"op": "set_perimeter_walls", "wallSettings": {
            "boundarySource": "plan", "heightMeters": settings["wallHeightMeters"], "thicknessMeters": 0.3,
            "openings": sorted(openings, key=lambda o: (o["edge"], o["startMeters"])),
            "exteriorFinish": _wall_finish(width, depth, settings["wallHeightMeters"], edge, openings)}},
        {"op": "set_ground", "ground": ground},
        *_slab(layout, width, depth),
        zone("zn-receiving", "receiving", "Receiving", band(0.0, half)),
        zone("zn-shipping", "shipping", "Shipping", band(half, wall)),
        zone("zn-storage", "storage", "Storage", storage),
        # The court meets the dock wall with the drive's 2 cm margin, so millimetre rounding of a turned
        # outline cannot leave a sliver over the building.
        {"op": "upsert_site_area", "area": {"areaId": "area-truck-court", "label": "Truck court", "kind": "truck_court",
            "surface": "concrete",
            "boundary": _ring(geometry["court"].difference(geometry["building"].buffer(0.02, join_style=2)))}},
    ]
    from shapely.geometry import LineString
    drive, parking, truck_strip = geometry["drive"], geometry.get("parking"), None
    if drive:
        strip = LineString(drive["line"]).buffer(settings["driveWidthMeters"] / 2, cap_style=2, join_style=2)
        # The drive meets the court, never runs under the building, and stops at the lot line, each with a
        # 2 cm margin so millimetre rounding of the stored outline cannot make an overlap or an overhang.
        strip = strip.difference(geometry["court"].buffer(0.02, join_style=2))
        strip = strip.difference(geometry["building"].buffer(0.02, join_style=2))
        if geometry["lot"] is not None:
            strip = strip.intersection(geometry["lot"].buffer(-0.02, join_style=2))
        if strip.geom_type != "Polygon":
            strip = max(getattr(strip, "geoms", []), key=lambda part: part.area, default=strip)
        operations.append({"op": "upsert_site_area", "area": {"areaId": "area-truck-drive",
            "label": f"Truck drive to {drive['road']}", "kind": "drive", "surface": "asphalt",
            "boundary": _ring(strip)}})
        truck_strip = strip
    if parking:
        from .site_parking import CAR_DRIVE_WIDTH
        park = parking["park"]
        operations.append({"op": "upsert_site_area", "area": {"areaId": "area-employee-parking",
            "label": "Employee parking", "kind": "parking", "surface": "asphalt", "boundary": _ring(park)}})
        car = LineString(parking["drive"]["line"]).buffer(CAR_DRIVE_WIDTH / 2, cap_style=2, join_style=2)
        for keep_clear in [park, geometry["court"], geometry["building"]] + ([truck_strip] if truck_strip else []):
            car = car.difference(keep_clear.buffer(0.02, join_style=2))
        if geometry["lot"] is not None:
            car = car.intersection(geometry["lot"].buffer(-0.02, join_style=2))
        if car.geom_type != "Polygon":
            car = max(getattr(car, "geoms", []), key=lambda part: part.area, default=car)
        if car.geom_type == "Polygon" and not car.is_empty:
            operations.append({"op": "upsert_site_area", "area": {"areaId": "area-car-drive",
                "label": f"Car drive to {parking['drive']['road']}", "kind": "drive", "surface": "asphalt",
                "boundary": _ring(car)}})
    entrances_new = []
    if drive and drive.get("entrance"):
        entrances_new.append({"entranceId": "entrance-truck", **drive["entrance"], "use": "trucks",
                              "widthMeters": settings["driveWidthMeters"]})
    if parking and parking["drive"].get("entrance"):
        from .site_parking import CAR_DRIVE_WIDTH
        entrances_new.append({"entranceId": "entrance-cars", **parking["drive"]["entrance"], "use": "cars",
                              "widthMeters": CAR_DRIVE_WIDTH})
    if entrances_new and site.get("property"):
        prop = dict(site["property"])
        entrances = [e for e in prop.get("entrances", []) if e["entranceId"] not in ("entrance-truck", "entrance-cars")]
        context = {key: value for key, value in site.items() if key in (
            "version", "georeference", "buildingPose", "imagery", "property", "areas")}
        context["property"] = {key: value for key, value in {**prop, "entrances": entrances + entrances_new}.items()
                               if key in ("boundary", "source", "sourceLabel", "setbacksMeters", "streetEdges",
                                          "rearEdges", "entrances")}
        operations.insert(0, {"op": "set_site_context", "siteContext": context})
    return operations
