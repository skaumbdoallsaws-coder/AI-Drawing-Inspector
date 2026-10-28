"""An employee car park beside the warehouse (site-dressing plan S3).

Research defaults (docs/facility-site-dressing-plan.md):
- 90-degree stalls 2.75 x 5.5 m (9 x 18 ft) on a 7.375 m (24 ft) two-way aisle, sizes chosen to be
  exact in binary so stall and aisle edges meet exactly, as the parking review requires;
- 0.75 stalls per 1,000 sq ft of building;
- accessible stalls by the federal table (one in six of them van stalls), at the end nearest the
  employee door;
- its own driveway on a street-facing edge, apart from the truck driveway, never through the truck
  court or the truck drive.
Geometry is square to the building; everything is a stated assumption, not a design check.
"""
from __future__ import annotations

import math

STALL_WIDTH, STALL_DEPTH, AISLE = 2.75, 5.5, 7.375
ACCESSIBLE_WIDTH, VAN_WIDTH = 4.0, 4.875  # stall plus its 1.52 m access aisle (car 2.44 m, van 3.35 m)
STALLS_PER_1000_SQFT = 0.75
SQFT_PER_SQM = 10.7639
CAR_DRIVE_WIDTH = 7.32
WALKWAY_METERS = 3.0        # clear strip kept along the building
DOOR_CORNER_METERS = 3.0    # the employee door keeps this far from the building's corners
WALL_FACE_METERS = 0.2      # the walk starts here, outside the planner's 0.3 m wall that straddles the outline
CLEAR_OF_TRUCKS_METERS = 2.0  # and this from the truck court and drive
TRUCK_GAP_METERS = 30.0     # the car driveway keeps this far from the truck driveway
GRID_OFFSETS = ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))  # metres from the building's corner
MAX_CAR_DRIVE_METERS = 90.0  # a car park further from its street than this is not "at the front"
ENOUGH_SHARE = 0.9          # the parking ratio is a guide (0.37-0.78 per 1,000 sq ft in the research):
                            # 90% of it is enough before the building is cut back for more
CANDIDATES = 8              # largest free rectangles tried
OCCUPIED = 2 / 3            # share of standard stalls given a parked car
DOOR_WIDTH_METERS = 1.8     # the employee entrance, a double door where the walk meets the wall
# A Ford F-150 whose own glass, tyres, bumper and lights the 3D view keeps (the user chose it, 2026-10-23;
# the earlier sedan and roadster show as one flat colour). Each gets an everyday colour, about as common as
# on US roads, and silver instead of the model's gold grille and rims.
CAR_ASSETS = ("asset-gym-field-pickup-apex",)
PAINTS = ("#f1f1ee", "#16181b", "#62676b", "#b9bdc1", "#f1f1ee", "#1f3a6b", "#16181b", "#8e1b1f",
          "#62676b", "#f1f1ee", "#b9bdc1", "#16181b", "#2e4a37", "#f1f1ee", "#62676b", "#6e5643")
PAINT_KEY, TRIM_KEY = "p:world/APEX%20vehicle_paint#0", "p:world/APEX%20gold#0"
ACCESSIBLE_TABLE = ((25, 1), (50, 2), (75, 3), (100, 4), (150, 5), (200, 6), (300, 7), (400, 8), (500, 9))
WHITE, BLUE, YELLOW = "#ffffff", "#2f80ed", "#facc15"
ZONE_ID = "zn-employee-parking"
MARKING_PREFIX, PLACEMENT_PREFIX, ROUTE_PREFIX = "fm-car-park-", "pl-car-park-", "rt-car-park-"


def stalls_needed(building_square_meters: float) -> int:
    return max(1, math.ceil(building_square_meters * SQFT_PER_SQM / 1000 * STALLS_PER_1000_SQFT))


def accessible_needed(stalls: int) -> int:
    for limit, count in ACCESSIBLE_TABLE:
        if stalls <= limit:
            return count
    return max(10, math.ceil(stalls * 0.02))


def _turn(geometry, bearing):
    """A property-frame shape in the building's axes."""
    import numpy as np
    import shapely
    from .site_plan import _to_plan
    return shapely.transform(geometry, lambda xy: np.array([_to_plan(bearing, x, z) for x, z in xy]))


def _layout(rect, needed, door):
    """Stalls in a rectangle (building axes): one row and its aisle, or two rows each side of one.

    Returns the rows actually used, shortened to the stalls needed and anchored at the end nearest
    the employee door, with the accessible stalls first; None when the rectangle is too shallow.
    """
    u0, w0, u1, w1 = rect
    along_u = (u1 - u0) >= (w1 - w0)
    length, depth = (u1 - u0, w1 - w0) if along_u else (w1 - w0, u1 - u0)
    if depth >= 2 * STALL_DEPTH + AISLE:
        rows, depth_used = 2, 2 * STALL_DEPTH + AISLE
    elif depth >= STALL_DEPTH + AISLE:
        rows, depth_used = 1, STALL_DEPTH + AISLE
    else:
        return None
    accessible = accessible_needed(needed)
    vans = max(1, math.ceil(accessible / 6))
    wide = [VAN_WIDTH] * vans + [ACCESSIBLE_WIDTH] * (accessible - vans)
    # Which end of the rows and which side of the depth are nearer the employee door.
    a_lo, a_hi = (u0, u1) if along_u else (w0, w1)
    d_lo, d_hi = (w0, w1) if along_u else (u0, u1)
    door_a, door_d = (door[0], door[1]) if along_u else (door[1], door[0])
    from_low = abs(door_a - a_lo) <= abs(door_a - a_hi)
    near_low = abs(door_d - d_lo) <= abs(door_d - d_hi)
    d_start = d_lo if near_low else d_hi - depth_used
    if rows == 2:
        bands = [(d_start, d_start + STALL_DEPTH, +1), (d_start + STALL_DEPTH + AISLE, d_start + depth_used, -1)]
        aisle = (d_start + STALL_DEPTH, d_start + STALL_DEPTH + AISLE)
    elif near_low:  # the row against the building side, its aisle beyond
        bands = [(d_start, d_start + STALL_DEPTH, +1)]
        aisle = (d_start + STALL_DEPTH, d_start + depth_used)
    else:
        bands = [(d_start + AISLE, d_start + depth_used, -1)]
        aisle = (d_start, d_start + AISLE)
    stalls, placed = [], 0
    for band_index, (b0, b1, toward_aisle) in enumerate(bands):
        widths = (wide if band_index == (0 if near_low else len(bands) - 1) else []) + \
            [STALL_WIDTH] * int(length // STALL_WIDTH)
        run = 0.0
        for width in widths:
            if run + width > length + 1e-6 or placed >= needed:
                break
            a_center = (a_lo + run + width / 2) if from_low else (a_hi - run - width / 2)
            kind = "van" if width == VAN_WIDTH else "accessible" if width == ACCESSIBLE_WIDTH else "standard"
            center = (a_center, (b0 + b1) / 2)
            stalls.append({"u": center[0] if along_u else center[1], "w": center[1] if along_u else center[0],
                           "along": width, "into": STALL_DEPTH, "kind": kind, "towardAisle": toward_aisle})
            run += width
            placed += 1
    if not stalls:
        return None
    used = max(abs(s["u" if along_u else "w"] - (a_lo if from_low else a_hi)) + s["along"] / 2 for s in stalls)
    a0, a1 = (a_lo, a_lo + used) if from_low else (a_hi - used, a_hi)
    box = (a0, d_start, a1, d_start + depth_used) if along_u else (d_start, a0, d_start + depth_used, a1)
    aisle_line = ((a0, sum(aisle) / 2), (a1, sum(aisle) / 2)) if along_u else ((sum(aisle) / 2, a0), (sum(aisle) / 2, a1))
    return {"rect": box, "alongU": along_u, "stalls": stalls, "aisle": aisle_line, "rows": rows}


def plan_car_park(region, building, court, truck_drive, truck_entrance, frontages, rails, lot, bearing,
                  needed) -> dict | None:
    """The car park and its driveway (property frame in, building axes out), or None when none fits.

    region: where the car park may go (the paved lot inside the setbacks). frontages: the streets'
    driveway stretches for a car-width drive (site_plan._frontages).
    """
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points, unary_union
    from .site_access import circle_around
    from .site_plan import _drive_to_frontage, _largest_rectangle, _to_plan, _to_property
    keep_out = [building.buffer(WALKWAY_METERS, join_style=2), court.buffer(CLEAR_OF_TRUCKS_METERS, join_style=2)]
    if truck_drive is not None:
        keep_out.append(truck_drive.buffer(CLEAR_OF_TRUCKS_METERS, join_style=2))
    free = region.difference(unary_union(keep_out))
    if free.is_empty:
        return None
    if truck_entrance is not None:  # the car driveway keeps its distance from the truck driveway
        disc = circle_around(Point(truck_entrance), TRUCK_GAP_METERS)
        frontages = [(road, line, [(index, part) for index, piece in pieces
                                   for part in getattr(piece.difference(disc), "geoms", [piece.difference(disc)])
                                   if part.geom_type == "LineString" and part.length > 0.5])
                     for road, line, pieces in frontages]
        frontages = [item for item in frontages if item[2]]
    if not frontages:
        return None
    # Only where a short driveway can reach a street-facing edge: the largest open spaces are often
    # far from the street (woods, the back of the lot) and would crowd out the right place.
    reach = MAX_CAR_DRIVE_METERS + 2 * STALL_DEPTH + AISLE
    free = free.intersection(unary_union([piece.buffer(reach) for _road, _line, pieces in frontages
                                          for _index, piece in pieces]))
    if free.is_empty:
        return None
    turned = _turn(free, bearing)
    min_u, min_w, max_u, max_w = turned.bounds
    # The grid is laid out from the building's corner, so the same lot and building give the same car park wherever
    # the site point (the geocoded address) falls: from the site point it moved up to a metre (bayport-moved,
    # 2026-10-25). Where the grid starts decides which largest rectangles the search finds, so it starts from a few
    # offsets and keeps the best car park: from the corner alone Bayport fitted 25 of 30 stalls in two rows.
    corner_u, corner_w = _turn(building, bearing).bounds[:2]
    door_point = nearest_points(building.exterior, free.centroid)[0]
    door = _to_plan(bearing, door_point.x, door_point.y)
    obstacles = unary_union([building, court] + ([truck_drive] if truck_drive is not None else []))
    best = None
    for offset_u, offset_w in GRID_OFFSETS:
        start_u, start_w = corner_u + offset_u, corner_w + offset_w
        us = start_u + np.arange(math.floor(min_u - start_u), math.ceil(max_u - start_u) + 1.0)
        ws = start_w + np.arange(math.floor(min_w - start_w), math.ceil(max_w - start_w) + 1.0)
        if len(us) < 2 or len(ws) < 2:
            continue
        # A cell counts only when all four of its corners are inside. With its centre alone the car park could
        # overshoot the property line or a clearance by up to half a metre (live at Bayport, 2026-10-24: 0.27 m
        # past the 4th Ave N line).
        gu, gw = np.meshgrid(us, ws)
        corners = contains_xy(turned.buffer(1e-6, join_style=2), gu, gw)
        cells = corners[:-1, :-1] & corners[1:, :-1] & corners[:-1, 1:] & corners[1:, 1:]
        for _ in range(CANDIDATES):
            found = _largest_rectangle(cells)
            if not found:
                break
            row, col, rows, cols = found
            cells[row:row + rows, col:col + cols] = False
            rect = (float(us[col]), float(ws[row]), float(us[col + cols]), float(ws[row + rows]))
            layout = _layout(rect, needed, door)
            if layout is None:
                continue
            u0, w0, u1, w1 = layout["rect"]
            lot_park = Polygon([_to_property(bearing, u, w) for u, w in ((u0, w0), (u1, w0), (u1, w1), (u0, w1))])
            saved = Polygon([(round(x, 3), round(z, 3)) for x, z in lot_park.exterior.coords])  # as the area is saved
            if not free.buffer(1e-6, join_style=2).covers(saved):  # a notch narrower than a cell
                continue
            drive = (_aisle_drive(layout["aisle"], bearing, frontages, obstacles, rails, lot)
                     or _drive_to_frontage(lot_park, obstacles, frontages, rails, bearing, lot, CAR_DRIVE_WIDTH))
            if drive is None:
                continue
            strip = LineString(drive["line"]).buffer(CAR_DRIVE_WIDTH / 2, cap_style=2, join_style=2)
            kept = [s for s in layout["stalls"]
                    if not Polygon([_to_property(bearing, s["u"] + du, s["w"] + dw) for du, dw in
                                    _stall_corners(s, layout["alongU"])]).intersects(strip.buffer(-0.01))]
            score = (len(kept), -drive["lengthMeters"])
            if best is None or score > best[0]:
                best = (score, dict(layout, stalls=kept, drive=drive, park=lot_park, door=door))
    if best is None:
        return None
    result = best[1]
    result["needed"] = needed
    corners = [_to_plan(bearing, x, z) for x, z in list(building.exterior.coords)[:-1]]
    result["door"], result["doorNormal"] = _door((min(u for u, _ in corners), min(w for _, w in corners),
                                                  max(u for u, _ in corners), max(w for _, w in corners)),
                                                 result["rect"], result["door"])
    return result


def _aisle_drive(aisle, bearing, frontages, obstacles, rails, lot) -> dict | None:
    """The car park's own two-way aisle carried straight on to the street, when it points at a driveway stretch
    of a street-facing edge within reach: the shortest, plainest way in (the user, 2026-10-24: "the two way
    parking lanes on the employee parking lot should expand to the street"). None when neither end can."""
    from shapely.geometry import LineString, Point
    from .site_plan import _to_property
    (au, aw), (bu, bw) = aisle
    best = None
    for (su, sw), (eu, ew) in (((au, aw), (bu, bw)), ((bu, bw), (au, aw))):  # leave by either end
        length = math.hypot(eu - su, ew - sw)
        if length < 1.0:
            return None
        du, dw = (eu - su) / length, (ew - sw) / length
        start = _to_property(bearing, eu, ew)
        ray = LineString([start, _to_property(bearing, eu + du * MAX_CAR_DRIVE_METERS, ew + dw * MAX_CAR_DRIVE_METERS)])
        for road, line, pieces in frontages:
            for index, piece in pieces:
                hit = ray.intersection(piece)
                if hit.is_empty:
                    continue
                point = min((Point(c) for part in getattr(hit, "geoms", [hit]) for c in part.coords),
                            key=lambda p: p.distance(Point(start)))
                path = LineString([start, (point.x, point.y)]) if point.distance(Point(start)) > 0.01 else None
                if path is None or (best is not None and path.length >= best[0].length):
                    continue
                strip = path.buffer(CAR_DRIVE_WIDTH / 2 - 0.25, cap_style=2)
                if (strip.intersects(obstacles) or not lot.buffer(0.05).covers(path)
                        or any(rail.intersects(path) for rail in rails)):
                    continue
                best = (path, road, line, point, index)
    if best is None:
        return None
    path, road, line, point, index = best
    return {"road": road["label"], "kind": road["kind"], "lengthMeters": round(path.length, 1),
            "toRoadMeters": round(line.distance(point), 1), "fromAisle": True,
            "line": [list(c) for c in path.coords], "entrance": {"edgeIndex": index, "x": round(point.x, 3),
                                                               "z": round(point.y, 3)}}


def _door(building, park, guess):
    """The employee door on the wall facing the car park, clear of the corners, and that wall's outward
    normal (building axes), so the walk can leave the wall square to it."""
    bu0, bw0, bu1, bw1 = building
    pu0, pw0, pu1, pw1 = park
    gaps = {(0, -1): bw0 - pw1, (0, 1): pw0 - bw1, (-1, 0): bu0 - pu1, (1, 0): pu0 - bu1}
    normal = max(gaps, key=gaps.get)  # the side the car park lies beyond, the furthest when it is off a corner

    def clamp(value, low, high):
        return min(max(value, low), high)
    if normal[1]:
        u = clamp(clamp(guess[0], pu0, pu1), bu0 + DOOR_CORNER_METERS, bu1 - DOOR_CORNER_METERS)
        return (u, bw1 if normal[1] > 0 else bw0), normal
    w = clamp(clamp(guess[1], pw0, pw1), bw0 + DOOR_CORNER_METERS, bw1 - DOOR_CORNER_METERS)
    return (bu1 if normal[0] > 0 else bu0, w), normal


def _stall_corners(stall, along_u):
    du, dw = (stall["along"] / 2, stall["into"] / 2) if along_u else (stall["into"] / 2, stall["along"] / 2)
    return ((-du, -dw), (du, -dw), (du, dw), (-du, dw))


def _frame(parking: dict, origin: tuple[float, float]):
    """Building axes to the new plan's frame (x = u - origin u, z = w - origin w), exactly.

    Offsets within the car park are multiples of 1/16 m from a corner snapped to the same grid (a shift of
    at most 3 cm), so stall and aisle edges coincide exactly."""
    pu0, pw0 = parking["rect"][:2]
    corner_x, corner_z = round((pu0 - origin[0]) * 16) / 16, round((pw0 - origin[1]) * 16) / 16
    return (lambda u: round(corner_x + (u - pu0), 4)), (lambda w: round(corner_z + (w - pw0), 4))


def door_opening(parking: dict, origin: tuple[float, float], width: float, depth: float) -> dict:
    """The employee entrance as a perimeter-wall opening, centred where the walk meets the wall
    (plan edges 0 south, 1 east, 2 north, 3 west, each run counter-clockwise from its first corner)."""
    X, Z = _frame(parking, origin)
    x, z = X(parking["door"][0]), Z(parking["door"][1])
    edge, along, length = {(0, -1): (0, x, width), (1, 0): (1, z, depth), (0, 1): (2, width - x, width),
                           (-1, 0): (3, depth - z, depth)}[tuple(parking["doorNormal"])]
    start = min(max(along - DOOR_WIDTH_METERS / 2, 0.0), length - DOOR_WIDTH_METERS)
    return {"edge": edge, "startMeters": round(start, 3), "endMeters": round(start + DOOR_WIDTH_METERS, 3)}


def paint_for(index: int) -> dict:
    """Body paint and silver trim for parked pickup `index`, spread evenly over PAINTS. Applied after the design
    is saved, as its own review (site_paint.py)."""
    return {"representation": "overview", "overrides": [
        {"key": TRIM_KEY, "color": "#b4b9be", "roughness": 0.3, "metalness": 0.75},
        {"key": PAINT_KEY, "color": PAINTS[index * 7 % len(PAINTS)], "roughness": 0.32, "metalness": 0.35}]}


def operations(parking: dict, origin: tuple[float, float], catalog: dict | None) -> list[dict]:
    """Zone, stall paint, aisle and entry markings, crosswalk to the door, and cars (when the library has them),
    in the new plan's frame (x = u - origin u, z = w - origin w)."""
    along_u = parking["alongU"]
    ops = []
    pu0, pw0, pu1, pw1 = parking["rect"]
    X, Z = _frame(parking, origin)

    def paint(key, kind, u, w, width, depth, color=WHITE, text="", rotation=0.0, role="parking"):
        ops.append({"op": "add_floor_marking", "floorMarking": {
            "markingId": MARKING_PREFIX + key, "markingType": kind, "label": key.replace("-", " ").title(),
            "semanticRole": role, "transform": {"position": {"x": X(u), "y": 0.008, "z": Z(w)},
                                                "rotationDegrees": rotation},
            "width": round(width, 3), "depth": round(depth, 3), "fillColor": color, "strokeColor": color, "opacity": 1,
            "text": text, "positionMode": "manual", "metadata": {"authoredIn": "site_dressing_car_park"}, "evidence": []}})

    ops.append({"op": "add_zone", "zone": {
        "zoneId": ZONE_ID, "zoneType": "workcell", "label": f"Employee parking - {len(parking['stalls'])} stalls",
        "boundary": [{"x": X(u), "z": Z(w)} for u, w in ((pu0, pw0), (pu1, pw0), (pu1, pw1), (pu0, pw1))],
        "floorElevation": 0, "anchors": [], "evidence": []}})
    for index, stall in enumerate(parking["stalls"]):
        width, depth = (stall["along"], stall["into"]) if along_u else (stall["into"], stall["along"])
        if stall["kind"] == "standard":
            paint(f"stall-{index + 1:03}", "parking_box", stall["u"], stall["w"], width, depth)
        else:
            paint(f"stall-{index + 1:03}", "parking_box", stall["u"], stall["w"], width, depth, BLUE,
                  "VAN" if stall["kind"] == "van" else "ACCESSIBLE")
    (au, aw), (bu, bw) = parking["aisle"]
    paint("aisle-center", "dashed_line", (au + bu) / 2, (aw + bw) / 2, 0.12, math.hypot(bu - au, bw - aw), YELLOW,
          rotation=90.0 if along_u else 0.0, role="decorative")

    def aisle(key, label, points, width, kind, color):
        ops.append({"op": "add_aisle", "routeId": ROUTE_PREFIX + key, "aisle": {
            "label": label, "centerline": [{"x": X(u), "y": 0, "z": Z(w)} for u, w in points], "corridorWidth": width,
            "aisleKind": kind, "direction": "two_way", "color": color, "clearanceEvidenceStatus": "unverified"}})
    # The drive aisle end to end (the parking review's vehicle corridor, edge to edge with every stall).
    aisle("aisle", "Car park aisle", [(au, aw), (bu, bw)], AISLE, "material", "#6b7280")
    # The employee walk leaves the door square to the wall, from outside the wall, crosses the walkway strip and
    # ends a metre into the car park; when the car park is off to the side, it turns along the middle of the strip.
    door_u, door_w = parking["door"]
    nu, nw = parking["doorNormal"]
    near_u, near_w = min(max(door_u, pu0), pu1), min(max(door_w, pw0), pw1)
    gap = (near_u - door_u) * nu + (near_w - door_w) * nw  # from the wall line to the car park's near edge
    side = (near_u - door_u) if nw else (near_w - door_w)  # along the wall
    tu, tw = (1, 0) if nw else (0, 1)

    def out(distance, along=0.0):
        return door_u + nu * distance + tu * along, door_w + nw * distance + tw * along
    label = WALL_FACE_METERS + 0.4  # the door's floor text, just outside the wall
    walkway = None
    if gap > label + 0.6:
        if abs(side) < 1e-6:
            points = [out(WALL_FACE_METERS), out(gap + 1.0)]
            crossing = gap - label - 0.4
            paint("crosswalk", "crosswalk", *out((label + 0.4 + gap) / 2), 3.0 if nw else crossing,
                  crossing if nw else 3.0, role="pedestrian_lane")
        else:
            beside = side + math.copysign(1.0, side)
            points = [out(WALL_FACE_METERS), out(gap / 2), out(gap / 2, beside), out(gap + 1.0, beside)]
        aisle("walk", "Walk to the employee entrance", points, 1.5, "pedestrian", "#22c55e")
        from shapely.geometry import LineString
        walkway = LineString(points).buffer(1.0, cap_style=2)  # stalls it crosses stay empty
    paint("door-label", "floor_text", *out(label), 9.0, 0.6, WHITE, "EMPLOYEE ENTRANCE",
          rotation=0.0 if nw else 90.0, role="decorative")
    if catalog:
        cars = [catalog[asset] for asset in CAR_ASSETS if asset in catalog]
        standard = [s for s in parking["stalls"] if s["kind"] == "standard"]
        from shapely.geometry import box
        for index, stall in enumerate(standard):
            if not cars or index % 3 == 2:  # about a third left free
                continue
            du, dw = (stall["along"] / 2, stall["into"] / 2) if along_u else (stall["into"] / 2, stall["along"] / 2)
            if walkway is not None and walkway.intersects(box(stall["u"] - du, stall["w"] - dw, stall["u"] + du,
                                                              stall["w"] + dw)):
                continue  # the walk to the door passes through this stall
            car = cars[(index // 3 + index) % len(cars)]
            # Nose in toward the aisle: yaw so the car's forward axis points at the aisle.
            yaw = (0.0 if stall["towardAisle"] > 0 else 180.0) if along_u else (90.0 if stall["towardAisle"] > 0 else -90.0)
            half = math.radians(yaw) / 2
            ops.append({"op": "place_asset", "placement": {
                "placementId": f"{PLACEMENT_PREFIX}{index + 1:03}", "assetId": car["assetId"],
                "assetDefinitionRevision": car["assetDefinitionRevision"],
                "transform": {"position": {"x": X(stall["u"]), "y": 0, "z": Z(stall["w"])},
                              "quaternion": {"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)}, "scale": 1},
                "positionMode": "manual", "snapRelationship": None,
                "metadata": {"instanceLabel": f"Parked car {index + 1}", "inputMethod": "site-dressing-car-park"}}})
    return ops


def clear_previous(layout: dict) -> list[dict]:
    """Delete an earlier car park's zone, paint and cars, so a new plan can replace it."""
    ops = [{"op": "delete_placement", "placementId": p["placementId"]} for p in layout.get("placements", [])
           if str(p.get("placementId", "")).startswith(PLACEMENT_PREFIX)]
    ops += [{"op": "delete_floor_marking", "markingId": m["markingId"]} for m in layout.get("floorMarkings", [])
            if str(m.get("markingId", "")).startswith(MARKING_PREFIX)]
    ops += [{"op": "delete_route", "routeId": r["routeId"]} for r in layout.get("routes", [])
            if str(r.get("routeId", "")).startswith(ROUTE_PREFIX)]
    ops += [{"op": "delete_zone", "zoneId": ZONE_ID} for z in layout.get("zones", []) if z.get("zoneId") == ZONE_ID]
    return ops
