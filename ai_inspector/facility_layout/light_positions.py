"""Clear spots for a light fitting: an outdoor pole light in a car park or yard, or a wall light by a door.

Asked for "a pole light at the truck yard's south end", Sage put one on a truck lane's painted text, and it had no
way to work out a wall mounting by hand. This read-only helper returns ready placements (transform and, for a wall
light, snapRelationship) for place_asset, from the layout's own geometry:

- A pole (any light fitting that is not wall-mounted) stands, best first, on the strip between two parking rows
  parked head to head, on an unpainted island between two painted lanes, or near the zone's edge. Never in a bay
  or a bay's approach, in a painted lane (the strip between two long parallel lines with direction arrows between
  them, running on past the lines' ends), on paint, in a route corridor or on another placement, within
  SPACING of another pole (a light at least POLE_HEIGHT tall: a bollard, an uplight or a festoon string keeps no
  pole away, 2026-11-05), or where the layout's zones refuse equipment.
- A wall-mounted fitting goes on the outside face of a wall beside each opening in the zone's walls (a gap between
  two wall segments in line), its back on the wall, as high as the wall allows up to WALL_LIGHT_TOP. A wall has no
  lintel over a gap, so a light "over the door" goes beside it, at the top of the wall. A mount in a walkway, or
  outside every zone that takes equipment, is left out and counted under "skipped".

A new pole light standing exactly on one of these spots skips the parking review (cleared_pole_spots, called by
operation_proposals.prepare): the server checks the spot again itself, by these rules, on the layout as proposed. A
light placed anywhere else in a car park, by hand, is reviewed as before.

These are layout-geometry suggestions, not a lighting design.
"""
from collections.abc import Mapping
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from .asset_orientation import yaw_quaternion
from .ground import supports_footprint
from .spatial import _NON_PLACEMENT_ZONE_TYPES, _quaternion, _rotate_vector, oriented_box_polygon

NAME = "suggest_facility_light_positions"
# The helper is for a light with no position from the user. Its texts once read as a rule that only its spots were
# allowed, and Sage refused a pole the user put at x 312, z 197.5 in a car park. Every text about placing lights says:
USER_POSITION = ("When the user gives a light's position, place it there with place_asset, even off the helper's "
                 "spots: in a car park or yard it is then staged for review, which is expected, not a reason to "
                 "refuse or move it.")
SPACING = 10.0              # m between suggested lights, and from the lights already there
EDGE_INSET = 2.5            # m in from the zone's edge
EDGE_BAND = 12.0            # m from the named edge that a spot may be
CLEARANCE = 0.75            # m from a pole's base to paint, bays, lanes, corridors and placements
STRIP_CLEARANCE = 0.2       # m: between head-to-head bays the base only has to fit between the bays' ends
HEAD_TO_HEAD_GAP = (0.3, 3.0)   # m between the facing ends of two bays parked head to head
LONG_LINE = (0.3, 10.0)     # a painted line at most 0.3 m wide and at least 10 m long can edge a lane
LANE_WIDTH = (2.5, 15.0)    # m between the two lines of a lane or an island
LANE_EXTENSION = 6.0        # m a painted lane runs on past its lines' ends (where vehicles turn in and out)
AREA_ROLES = {"pedestrian_lane", "forklift_lane", "keep_clear"}   # painted areas that are kept clear
OVERHEAD = 4.5              # m above the floor: a placement this high does not block the ground
POLE_HEIGHT = 3.0           # m: a light at least this tall is a pole; a lower one (a bollard) keeps no pole away
WALL_LIGHT_TOP = 4.6        # m above the floor, the highest a wall light goes
WALL_LIGHT_LOWEST = 2.2     # m above the floor, the lowest (above a door head)
WALL_GAP = 0.003            # m between a wall light's back plate and the wall
OPENING = (0.6, 6.0)        # m: a gap this wide between two wall segments in line is an opening
MATCH = 0.01                # m: a pole this close to a spot stands on it (spots are given to the millimetre)
EDGES = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
SKIPPED = {
    "inWalkway": "mounts left out: the light would stand in a walkway or route corridor",
    "outsideZones": ("mounts left out: the outside of the wall is in no zone that takes equipment, so the layout "
                     "would refuse the light there"),
}
LIMITATIONS = [
    "Spots come from the layout's geometry: painted lanes, bays and their approaches, paint, route corridors, "
    "placements and other lights. Unpainted drive areas, vehicle swept paths and buried services are not known.",
    "A suggestion is not a lighting design: no light levels, uniformity, glare or spill, electrical, foundation or "
    "wall-fixing checks.",
]


def tool_spec():
    return {"name": NAME, "description":
        "Suggest clear spots for a light fitting, ready for place_asset: an outdoor pole light in a car park or truck "
        "yard, or a wall light beside a room's outside door, for a light with no position from the user. "
        + USER_POSITION + " Give the light's assetId (search_industrial_assets "
        "'pole light' or 'wall light'), the zoneId it lights or whose door it is, and the edge if the user names one "
        "(north is +z, east +x). Poles: best first on the strip between parking rows parked head to head, on an "
        "unpainted island between two painted lanes, or near the zone's edge; never in a bay or its approach, a "
        "painted lane (two long lines with direction arrows between them), on paint, a walkway or route corridor, or "
        "within 10 m of another pole light. A pole light's LED head faces straight down, so its turn does not matter. "
        "Wall lights: on the outside face of the wall beside each door opening (a gap between wall segments), back "
        "plate (-Z) on the wall, lens facing down and out, as high as the wall allows up to 4.6 m; a wall has no "
        "lintel over a gap, so a light 'over the door' goes beside it at the top of the wall. Copy a position's "
        "transform and snapRelationship into place_asset exactly (a wall light needs its snapRelationship), with a "
        "new placementId and instanceLabel. Light fittings come lit. Layout geometry only, not a lighting design.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["assetId", "zoneId"],
            "properties": {
                "assetId": {"type": "string", "minLength": 1, "maxLength": 128},
                "zoneId": {"type": "string", "pattern": "^zn-[A-Za-z0-9][A-Za-z0-9._:-]*$", "maxLength": 128},
                "edge": {"enum": sorted(EDGES)},
                "count": {"type": "integer", "minimum": 1, "maximum": 12}}}}


def _definition(record):
    value = record.get("definition")
    return value if isinstance(value, Mapping) else record


def _tags(record):
    return {str(tag) for tag in (_definition(record).get("tags") or record.get("tags") or [])}


def _aabb(record):
    box = ((_definition(record).get("geometry") or {}).get("aabb")) or {}
    return box.get("minimum"), box.get("maximum")


def _label(placement):
    return str((placement.get("metadata") or {}).get("instanceLabel") or placement["placementId"])


def _record_for(catalog, placement):
    """PLACEMENT's catalog record at its own revision, or None. CATALOG maps an assetId (the current catalog) or an
    (assetId, revision) pair (a proposal's pinned definitions) to a record."""
    record = (catalog.get((placement.get("assetId"), placement.get("assetDefinitionRevision")))
              or catalog.get(placement.get("assetId")))
    if record and record.get("assetDefinitionRevision") == placement.get("assetDefinitionRevision"):
        return record
    return None


def _footprint(placement, record):
    """The placement's plan footprint: its catalog box, turned and moved as the placement is."""
    low, high = _aabb(record)
    if not low or not high:
        return None
    q = _quaternion(placement["transform"]["quaternion"])
    p = placement["transform"]["position"]
    corners = [_rotate_vector((x, 0.0, z), q) for x in (low["x"], high["x"]) for z in (low["z"], high["z"])]
    return Polygon([(p["x"] + c[0], p["z"] + c[2]) for c in corners]).convex_hull


def _mark_polygon(mark):
    p = mark["transform"]["position"]
    return Polygon(oriented_box_polygon((p["x"], p["z"]), (mark["width"] / 2, mark["depth"] / 2),
                                        math.radians(mark["transform"].get("rotationDegrees", 0))))


def _axes(shape):
    """(centre, unit long axis, half length, half width) of a rectangle. The axis points +x (or +z when it runs
    along z), so lines that lie along each other measure along them the same way."""
    rectangle = shape.minimum_rotated_rectangle
    centre = rectangle.centroid
    if rectangle.geom_type != "Polygon":
        return (centre.x, centre.y), (1.0, 0.0), 0.0, 0.0
    points = list(rectangle.exterior.coords)[:4]
    sides = [(points[i], points[(i + 1) % 4]) for i in (0, 1)]
    lengths = [math.dist(a, b) for a, b in sides]
    (a, b), length = (sides[0], lengths[0]) if lengths[0] >= lengths[1] else (sides[1], lengths[1])
    axis = ((b[0] - a[0]) / length, (b[1] - a[1]) / length) if length else (1.0, 0.0)
    if axis[0] < -1e-9 or (abs(axis[0]) <= 1e-9 and axis[1] < 0):
        axis = (-axis[0], -axis[1])
    return (centre.x, centre.y), axis, max(lengths) / 2, min(lengths) / 2


def _strip(centre, axis, half_length, half_width):
    """A rectangle around CENTRE, HALF_LENGTH along AXIS and HALF_WIDTH across it."""
    ux, uz = axis
    vx, vz = -uz, ux
    cx, cz = centre
    return Polygon([(cx + sx * ux * half_length + sy * vx * half_width, cz + sx * uz * half_length + sy * vz * half_width)
                    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def _parallel(a, b):
    return abs(a[0] * b[1] - a[1] * b[0]) < 0.02


def _is_bay(mark):
    # A staging box (material staged in front of a dock door) is paint, not a bay a vehicle drives into.
    return mark.get("markingType") == "parking_box" and mark.get("semanticRole") != "staging"


def _bays(marks):
    """Each parking bay with its approach: the bay's length again beyond each end that does not meet another bay
    parked head to head. Also the midpoints between head-to-head bays (the strips where a pole can stand)."""
    bays = [(_mark_polygon(m),) + _axes(_mark_polygon(m)) for m in marks if _is_bay(m)]
    shapes, strips = [], []
    for index, (shape, centre, axis, half_length, half_width) in enumerate(bays):
        shapes.append(shape)
        for end in (-1, 1):
            tip = (centre[0] + end * axis[0] * half_length, centre[1] + end * axis[1] * half_length)
            facing = None
            for other_index, (_, other_centre, other_axis, other_half, _) in enumerate(bays):
                if other_index == index or not _parallel(axis, other_axis):
                    continue
                along = (other_centre[0] - centre[0]) * axis[0] + (other_centre[1] - centre[1]) * axis[1]
                across = abs(-(other_centre[0] - centre[0]) * axis[1] + (other_centre[1] - centre[1]) * axis[0])
                gap = end * along - half_length - other_half
                if along * end > 0 and across < 0.3 and HEAD_TO_HEAD_GAP[0] <= gap <= HEAD_TO_HEAD_GAP[1]:
                    facing = gap
                    break
            if facing is None:
                shapes.append(_strip((tip[0] + end * axis[0] * half_length, tip[1] + end * axis[1] * half_length),
                                     axis, half_length, half_width))
            elif end == 1:   # one midpoint per pair
                strips.append((tip[0] + axis[0] * facing / 2, tip[1] + axis[1] * facing / 2))
    return shapes, strips


def _lanes(marks):
    """Painted lanes (kept clear) and unpainted islands between two lanes (where a pole can stand), from the long
    thin lines: two neighbouring parallel lines with a direction arrow between them edge a lane."""
    lines = []
    for mark in marks:
        if mark.get("markingType") not in ("solid_line", "dashed_line"):
            continue
        shape = _mark_polygon(mark)
        centre, axis, half_length, half_width = _axes(shape)
        if 2 * half_width <= LONG_LINE[0] and 2 * half_length >= LONG_LINE[1]:
            lines.append((centre, axis, half_length))
    arrows = [Point(m["transform"]["position"]["x"], m["transform"]["position"]["z"])
              for m in marks if m.get("markingType") == "direction_arrow"]
    pairs = []
    for i, (centre, axis, half_length) in enumerate(lines):
        normal = (-axis[1], axis[0])
        offset = centre[0] * normal[0] + centre[1] * normal[1]
        start = centre[0] * axis[0] + centre[1] * axis[1]
        neighbours = []
        for j, (other, other_axis, other_half) in enumerate(lines):
            if j == i or not _parallel(axis, other_axis):
                continue
            across = other[0] * normal[0] + other[1] * normal[1] - offset
            other_start = other[0] * axis[0] + other[1] * axis[1]
            overlap = min(start + half_length, other_start + other_half) - max(start - half_length, other_start - other_half)
            if LANE_WIDTH[0] <= across <= LANE_WIDTH[1] and overlap > LONG_LINE[1] / 2:
                neighbours.append((across, j, other_start, other_half))
        if neighbours:
            across, j, other_start, other_half = min(neighbours)
            low = max(start - half_length, other_start - other_half)
            high = min(start + half_length, other_start + other_half)
            sideways, lengthways = offset + across / 2, (low + high) / 2   # the strip's middle, in line coordinates
            centre = (normal[0] * sideways + axis[0] * lengthways, normal[1] * sideways + axis[1] * lengthways)
            pairs.append({"lines": (i, j), "axis": axis, "centre": centre,
                          "halfLength": (high - low) / 2, "halfWidth": across / 2})
    for pair in pairs:
        pair["shape"] = _strip(pair["centre"], pair["axis"], pair["halfLength"], pair["halfWidth"])
        pair["lane"] = any(pair["shape"].contains(arrow) for arrow in arrows)
    lanes = [p for p in pairs if p["lane"]]
    lane_lines = {line for p in lanes for line in p["lines"]}
    islands = [p for p in pairs if not p["lane"] and set(p["lines"]) <= lane_lines]
    kept = [_strip(p["centre"], p["axis"], p["halfLength"] + LANE_EXTENSION, p["halfWidth"]) for p in lanes]
    return kept, islands


def _zoning(layout):
    """The zones that take equipment, and those that forbid it (aisles, exclusions, safety zones and the like)."""
    allowed, banned = [], []
    for zone in layout.get("zones", []):
        points = zone.get("boundary") or []
        if len(points) >= 3:
            shape = Polygon([(p["x"], p["z"]) for p in points])
            (banned if str(zone.get("zoneType") or "") in _NON_PLACEMENT_ZONE_TYPES else allowed).append(shape)
    return allowed, banned


def _zoned(footprint, zoning):
    """As the layout's zone rule: inside a zone that takes equipment, overlapping none that forbids it."""
    allowed, banned = zoning
    if any(shape.intersection(footprint).area > 1e-9 for shape in banned):
        return False
    return not allowed or any(shape.buffer(1e-6).contains(footprint) for shape in allowed)


def _ground_y(layout, zone, footprint):
    """The level ground under a footprint, or None (a slope, a step or no ground)."""
    ground = (layout.get("extensions") or {}).get("facilityGround")
    floor = float(zone.get("floorElevation", 0))
    if not isinstance(ground, Mapping) or not ground.get("surfaces"):
        return floor
    centre = footprint.centroid
    for surface in ground["surfaces"]:
        if (surface["startElevation"] == surface["endElevation"]
                and surface["minX"] <= centre.x <= surface["maxX"] and surface["minZ"] <= centre.y <= surface["maxZ"]):
            y = float(surface["startElevation"])
            return y if supports_footprint(ground, list(footprint.exterior.coords)[:-1], y) else None
    return None


def _edge_distance(edge, bounds, x, z):
    minx, minz, maxx, maxz = bounds
    return {"north": maxz - z, "south": z - minz, "east": maxx - x, "west": x - minx}[edge]


def _pole_candidates(layout, catalog, asset, zone, edge, at=None, turn=None):
    """The clear spots for a pole of ASSET in ZONE, best first, before spacing: [(order, x, y, z, where, clearance)],
    and the lights standing near the zone, [(x, z)]. AT keeps only the spots within MATCH of a plan point (x, z);
    TURN (a quaternion) turns the pole's base, which the suggestions leave unturned."""
    area = Polygon([(p["x"], p["z"]) for p in zone["boundary"]])
    floor = float(zone.get("floorElevation", 0))
    near = prep(area.buffer(30.0))
    polygons = (_definition(asset).get("geometry") or {}).get("footprintPolygons") or []
    if polygons:
        base = Polygon([(p["x"], p["z"]) for p in polygons[0]])
    else:
        low, high = _aabb(asset)
        base = Polygon([(low["x"], low["z"]), (high["x"], low["z"]), (high["x"], high["z"]), (low["x"], high["z"])])
    if turn is not None:
        base = Polygon([(v[0], v[2]) for v in (_rotate_vector((px, 0.0, pz), turn)
                                               for px, pz in list(base.exterior.coords)[:-1])])
    marks = [m for m in layout.get("floorMarkings", [])
             if near.contains(Point(m["transform"]["position"]["x"], m["transform"]["position"]["z"]))]
    bays, strips = _bays(marks)
    lanes, islands = _lanes(marks)
    paint = []
    for mark in marks:
        kind = mark.get("markingType")
        if _is_bay(mark):
            continue
        shape = _mark_polygon(mark)
        if kind in ("solid_line", "dashed_line") and min(mark["width"], mark["depth"]) > LONG_LINE[0] \
                and mark.get("semanticRole") not in AREA_ROLES:
            continue   # an asphalt or decorative fill, not a line
        paint.append(shape)
    corridors = []
    for route in layout.get("routes", []):
        points = [(p["x"], p["z"]) for p in route.get("centerline") or []]
        if len(points) >= 2 and route.get("corridorWidth", 0) > 0:
            corridor = LineString(points).buffer(route["corridorWidth"] / 2)
            if corridor.intersects(area):
                corridors.append(corridor)
    placed, lights = [], []
    for placement in layout.get("placements", []):
        record = _record_for(catalog, placement)
        p = placement["transform"]["position"]
        if record is None or not near.contains(Point(p["x"], p["z"])):
            continue
        low, high = _aabb(record)
        tags = _tags(record)
        if ("lighting" in tags and "wall-mounted" not in tags and low and high
                and float(high["y"]) - float(low["y"]) >= POLE_HEIGHT):
            lights.append((p["x"], p["z"]))
        if low and float(p["y"]) + float(low["y"]) >= floor + OVERHEAD:
            continue
        shape = _footprint(placement, record)
        if shape is not None:
            placed.append(shape)
    blocked = unary_union(bays + lanes + paint + corridors + placed)
    blocked_test = prep(blocked)
    bays_test = prep(unary_union(bays + paint + placed)) if (bays or paint or placed) else None

    candidates = [(0, x, z, "on the strip between parking rows parked head to head") for x, z in strips]
    for island in islands:
        half = island["halfLength"] - 1.5
        steps = max(1, int(2 * half // 2.0))
        for k in range(steps + 1):
            t = -half + 2 * half * k / steps
            candidates.append((1, island["centre"][0] + island["axis"][0] * t, island["centre"][1] + island["axis"][1] * t,
                               "on the unpainted island between two painted lanes"))
    inner = area.buffer(-EDGE_INSET)
    if not inner.is_empty and inner.geom_type == "Polygon":
        ring = inner.exterior
        for k in range(int(ring.length)):
            point = ring.interpolate(k)
            candidates.append((2, point.x, point.y, f"{EDGE_INSET:g} m in from the zone's edge"))
    if at is not None:
        candidates = [item for item in candidates if abs(item[1] - at[0]) <= MATCH and abs(item[2] - at[1]) <= MATCH]
    bounds = area.bounds
    zoning = _zoning(layout)
    found = []
    for kind, x, z, where in candidates:
        if edge and _edge_distance(edge, bounds, x, z) > EDGE_BAND:
            continue
        footprint = Polygon([(x + px, z + pz) for px, pz in list(base.exterior.coords)[:-1]])
        if not area.contains(footprint) or not _zoned(footprint, zoning):
            continue
        if kind == 0:
            if bays_test is not None and bays_test.intersects(footprint.buffer(STRIP_CLEARANCE)):
                continue
            if any(c.intersects(footprint.buffer(STRIP_CLEARANCE)) for c in corridors):
                continue
        elif blocked_test.intersects(footprint.buffer(CLEARANCE)):
            continue
        y = _ground_y(layout, zone, footprint)
        if y is None:
            continue
        clear = blocked.distance(footprint) if not blocked.is_empty else 99.0
        order = (kind, _edge_distance(edge, bounds, x, z) if edge else 0.0, -round(clear, 1))
        found.append((order, x, y, z, where, clear))
    found.sort(key=lambda item: item[0])
    return found, lights


def _pole_positions(layout, catalog, asset, zone, edge, count):
    found, lights = _pole_candidates(layout, catalog, asset, zone, edge)
    chosen = []
    for _, x, y, z, where, clear in found:
        if any(math.dist((x, z), other) < SPACING for other in lights + [(c[0], c[2]) for c in chosen]):
            continue
        chosen.append((x, y, z, where, clear))
        if len(chosen) == count:
            break
    return [{"where": where, "clearanceMeters": round(min(clear, 99.0), 2),
             "placement": {"assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
                           "transform": {"position": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
                                         "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
                           "snapRelationship": None}}
            for x, y, z, where, clear in chosen], {}


def _inverse(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def _walls(layout, catalog, area):
    """The upright walls along the zone's edge: (placement, record, centre, axis, start, end, thickness)."""
    edge = prep(area.exterior.buffer(0.5))
    result = []
    for placement in layout.get("placements", []):
        record = _record_for(catalog, placement)
        if record is None or "wall" not in _tags(record):
            continue
        q = _quaternion(placement["transform"]["quaternion"])
        up = _rotate_vector((0.0, 1.0, 0.0), q)
        if abs(up[1] - 1) > 1e-6 or abs(float(placement["transform"].get("scale", 1)) - 1) > 1e-8:
            continue
        shape = _footprint(placement, record)
        if shape is None or not edge.contains(shape.centroid):
            continue
        centre, axis, half_length, half_width = _axes(shape)
        along = centre[0] * axis[0] + centre[1] * axis[1]
        result.append((placement, record, centre, axis, along - half_length, along + half_length, 2 * half_width))
    return result


def _wall_positions(layout, catalog, asset, zone, edge, count):
    area = Polygon([(p["x"], p["z"]) for p in zone["boundary"]])
    floor = float(zone.get("floorElevation", 0))
    low, high = _aabb(asset)
    half_width, height = float(high["x"]), float(high["y"]) - float(low["y"])
    corridors = [LineString([(p["x"], p["z"]) for p in r["centerline"]]).buffer(r["corridorWidth"] / 2)
                 for r in layout.get("routes", []) if len(r.get("centerline") or []) >= 2 and r.get("corridorWidth", 0) > 0]
    walls = _walls(layout, catalog, area)
    zoning = _zoning(layout)
    skipped = {}
    lines = {}
    for wall in walls:
        _, _, centre, axis, _, _, _ = wall
        offset = -centre[0] * axis[1] + centre[1] * axis[0]
        key = (round(math.degrees(math.atan2(axis[1], axis[0])) % 180), round(offset * 20))
        lines.setdefault(key, []).append(wall)
    result = []
    for segments in lines.values():
        segments.sort(key=lambda wall: wall[4])
        for before, after in zip(segments, segments[1:]):
            gap = after[4] - before[5]
            if not OPENING[0] <= gap <= OPENING[1]:
                continue
            axis = before[3]
            middle_along = (before[5] + after[4]) / 2
            normal = (-axis[1], axis[0])
            line_offset = before[2][0] * normal[0] + before[2][1] * normal[1]
            middle = (axis[0] * middle_along + normal[0] * line_offset, axis[1] * middle_along + normal[1] * line_offset)
            outward = None
            for sign in (1, -1):
                probe = Point(middle[0] + sign * normal[0], middle[1] + sign * normal[1])
                if not area.contains(probe) and area.contains(Point(middle[0] - sign * normal[0], middle[1] - sign * normal[1])):
                    outward = (sign * normal[0], sign * normal[1])
            if outward is None:
                continue
            heading = math.degrees(math.atan2(outward[0], outward[1])) % 360
            facing = min(EDGES, key=lambda name: math.dist(EDGES[name], outward))
            if edge and facing != edge:
                continue
            for wall, along in ((before, before[5] - half_width - 0.1), (after, after[4] + half_width + 0.1)):
                position = _mount(wall, along, outward, heading, floor, half_width, height, asset)
                if position is None:
                    continue
                spot = position["placement"]["transform"]["position"]
                footprint = _strip((spot["x"], spot["z"]), (axis[0], axis[1]), half_width, abs(float(low["z"])))
                if any(corridor.intersects(footprint) for corridor in corridors):
                    skipped["inWalkway"] = skipped.get("inWalkway", 0) + 1
                    continue
                if not _zoned(footprint, zoning):
                    skipped["outsideZones"] = skipped.get("outsideZones", 0) + 1
                    continue
                position["where"] = (f"on the outside face of {_label(wall[0])} ({wall[0]['placementId']}), beside the "
                                     f"{gap:.1f} m opening in the {facing} wall, facing {facing}")
                result.append(position)
    return result[:count], skipped


def _mount(wall, along, outward, heading, floor, half_width, height, asset):
    """A wall attachment of ASSET on WALL's outward face, centred ALONG the wall, or None if it does not fit."""
    placement, record, centre, axis, start, end, _ = wall
    if along - half_width < start - 1e-9 or along + half_width > end + 1e-9:
        return None
    a_low, a_high = _aabb(record)
    b_low, _ = _aabb(asset)
    q = _quaternion(placement["transform"]["quaternion"])
    local_out = _rotate_vector((outward[0], 0.0, outward[1]), _inverse(q))
    if abs(abs(local_out[0]) - 1) < 1e-6:
        face, normal = ("positive_x" if local_out[0] > 0 else "negative_x"), "x"
    elif abs(abs(local_out[2]) - 1) < 1e-6:
        face, normal = ("positive_z" if local_out[2] > 0 else "negative_z"), "z"
    else:
        return None
    p = placement["transform"]["position"]
    on_line = (centre[0] + axis[0] * (along - (centre[0] * axis[0] + centre[1] * axis[1])),
               centre[1] + axis[1] * (along - (centre[0] * axis[0] + centre[1] * axis[1])))
    local = _rotate_vector((on_line[0] - p["x"], 0.0, on_line[1] - p["z"]), _inverse(q))
    top = float(p["y"]) + float(a_high["y"])
    base = min(top - height - 0.05, floor + WALL_LIGHT_TOP)
    if base < floor + WALL_LIGHT_LOWEST:
        return None
    local_y = base - float(p["y"])
    positive = face.startswith("positive")
    depth = (float(a_high[normal]) + WALL_GAP - float(b_low["z"]) if positive
             else float(a_low[normal]) - WALL_GAP + float(b_low["z"]))
    relationship = {"family": "wall_attachment", "supportPlacementId": placement["placementId"],
                    "supportAssetDefinitionRevision": placement["assetDefinitionRevision"], "face": face,
                    "localY": round(local_y, 6), "normalGapMeters": WALL_GAP}
    if normal == "x":
        relationship["localZ"] = round(local[2], 6)
        vector = (depth, relationship["localY"], relationship["localZ"])
    else:
        relationship["localX"] = round(local[0], 6)
        vector = (relationship["localX"], relationship["localY"], depth)
    offset = _rotate_vector(vector, q)
    position = {"x": float(p["x"]) + offset[0] + 0.0, "y": float(p["y"]) + offset[1] + 0.0,
                "z": float(p["z"]) + offset[2] + 0.0}
    return {"clearanceMeters": None,
            "placement": {"assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
                          "transform": {"position": position, "quaternion": yaw_quaternion(heading), "scale": 1},
                          "snapRelationship": relationship}}


def cleared_pole_spots(layout, catalog, placement_ids):
    """3c: which of PLACEMENT_IDS (new placements in LAYOUT, the layout as proposed) are pole lights standing on a spot
    this helper clears, checked here by its own rules rather than taken from the batch: within MATCH of a spot of a
    zone it stands in (a head-to-head strip, an island between lanes, the edge inset) and at its height, its base
    (turned as placed) clear of bays and their approaches, painted lanes, paint, route corridors and other placements,
    on level ground, in a zone that takes equipment, upright and unscaled, and SPACING from every other light (the
    batch's own included). A light anywhere else, as placed by hand, is not cleared. CATALOG maps assetId, or
    (assetId, revision), to catalog records. Returns {placementId: where}."""
    placements = {item["placementId"]: item for item in layout.get("placements", [])}
    cleared = {}
    for placement_id in placement_ids:
        placement = placements.get(placement_id)
        record = _record_for(catalog, placement) if placement else None
        if record is None or "lighting" not in _tags(record) or "wall-mounted" in _tags(record):
            continue
        transform = placement["transform"]
        turn = _quaternion(transform.get("quaternion") or {"x": 0, "y": 0, "z": 0, "w": 1})
        if abs(float(transform.get("scale", 1)) - 1) > 1e-8 or _rotate_vector((0.0, 1.0, 0.0), turn)[1] < 1 - 1e-6:
            continue
        p = transform["position"]
        x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
        others = dict(layout, placements=[item for item in layout["placements"] if item["placementId"] != placement_id])
        for zone in layout.get("zones", []):
            points = zone.get("boundary") or []
            if len(points) < 3 or not Polygon([(v["x"], v["z"]) for v in points]).contains(Point(x, z)):
                continue
            found, lights = _pole_candidates(others, catalog, record, zone, None, at=(x, z), turn=turn)
            spot = next((item for item in found if abs(item[2] - y) <= MATCH), None)
            if spot and all(math.dist((x, z), light) >= SPACING for light in lights):
                cleared[placement_id] = spot[4]
                break
    return cleared


def suggest_light_positions(layout, catalog, arguments):
    """Ready place_asset placements for a light fitting in or by a zone (see the module docstring)."""
    asset = catalog.get(arguments["assetId"])
    if asset is None:
        raise ValueError("That asset is not in the catalog: search_industrial_assets for 'pole light' or 'wall light'.")
    tags = _tags(asset)
    if "lighting" not in tags:
        raise ValueError(f"{NAME} places light fittings (catalog tag lighting) only.")
    zone = next((z for z in layout.get("zones", []) if z.get("zoneId") == arguments["zoneId"]), None)
    if zone is None or len(zone.get("boundary") or []) < 3:
        raise ValueError("That zone is not in the saved layout.")
    low, high = _aabb(asset)
    if not low or not high:
        raise ValueError("This light has no catalog geometry to place.")
    wall = "wall-mounted" in tags
    edge, count = arguments.get("edge"), int(arguments.get("count", 3))
    positions, skipped = (_wall_positions if wall else _pole_positions)(layout, catalog, asset, zone, edge, count)
    result = {"assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
              "zoneId": zone["zoneId"], "method": "wall" if wall else "pole", "edge": edge, "positions": positions,
              "howToUse": ("For a light with no position from the user, place it with place_asset at one of "
                           "these positions, best first: copy its placement.transform and placement.snapRelationship "
                           "exactly, and add a new placementId, positionMode locked and an instanceLabel. It comes "
                           "lit; it needs no finish step. A pole light placed exactly at one of these positions skips "
                           "the car park review when you preview it (the server checks the spot again). "
                           + USER_POSITION),
              "limitations": LIMITATIONS}
    if skipped:
        result["skipped"] = {key: f"{number} {SKIPPED[key]}" for key, number in sorted(skipped.items())}
    if positions:
        return result
    if not wall:
        result["none"] = ("No clear spot was found" + (f" within {EDGE_BAND:g} m of the {edge} edge" if edge else "")
                          + ". Try another edge or zone, or ask the user where the light should go.")
    elif skipped:
        result["none"] = "No mount beside a door is clear (see skipped). Ask the user where the light should go."
    else:
        result["none"] = ("No opening was found in the walls along this zone's edge. Name the room (zone) whose door "
                          "it is, or ask the user where the light should go.")
    return result
