"""Floor-plan import FP2: walls, rooms and the outline from a drawing's layers
(docs/facility-floor-plan-import-plan.md, sections 7 and 8).

Deterministic geometry over the roles the user gave the drawing's layers (the saved underlay's `layers`): nothing is
read from layer names, line weights or text styles, and nothing is guessed. The result lists every candidate with
what happens to it and why, and the native operations for the ones that pass. The import route stages those as a
proposal the user reviews; a conversion is never applied directly (operation_proposals, the
"floor-plan-conversion" origin).

- Wall centerlines ("wall_centerline"): each straight piece is a wall of the thickness the user gives.
- Wall faces ("wall_faces"): two parallel straight lines between 5 cm and the largest wall thickness apart that
  overlap by 10 cm or more, with no other parallel line between them, are the faces of one wall: its centerline runs
  halfway between them over their overlap and its thickness is their distance. A line that pairs on both of its
  sides over the same stretch makes those walls ambiguous (refused, never guessed). A line without a partner (a
  jamb, the end of a wall, furniture) is listed, not converted.
- Pieces of one wall are joined where they touch or overlap, and across a gap exactly as wide as a wall that ends in
  it (a T drawn with faces); any other gap is an opening and stays. Two walls whose ends meet at a corner both reach
  past it by half the other's thickness (an L, so the corner is filled); a wall end that stops short of another
  wall's centerline by less than their half thicknesses is carried to it (a T).
- Curves stay drawing: arcs, circles, ellipses, splines, and polyline runs that bend gently or bow.
- Rooms ("room_boundary"): each closed outline is a zone of the type the user chooses (there is no "room" type, and
  a label never sets one); exactly one text inside it (on a "text" or "room_boundary" layer) names it. Outlines
  that are open, cross themselves, are tiny or repeat another are listed, not converted; one that holds other rooms
  is refused until they are left out.
- Outline ("perimeter"): a closed loop becomes the plan's outer walls (a polygon boundary); two nested loops that
  stay one distance apart are the outer and inner faces of those walls. The floor stays the plan's rectangle.
- Doors ("door", FP3): a swing (an arc turning 60 to 120 degrees) hinged at one jamb of a break 0.5 to 4 m wide
  between two pieces of a wall and shut against the other jamb (or two of half the width hinged at both jambs, a
  double door) joins the pieces into one wall with an opening there; interior openings are full height, and the door
  leaf and its swing are not modelled. A swing drawn on both sides of one jamb (a door that swings both ways) is one
  door. On the outer walls a swing hinged on an edge of the outline and shut along it is a door only with its leaf
  drawn (an unbroken outline has no jambs to confirm it), and it waits for the door height. Swings that disagree
  about a break, or one that fits two breaks, leave the door unclear and the break stays. A door drawn as one
  polyline (its leaf and its swing) reads like one drawn as a line and an arc.
- Columns ("column") come in a later phase: listed, not converted.

Existing walls and zones are never changed: a candidate whose id is already in the layout is reported as there (or
edited since) and left alone, and one that lands on a wall or zone already on the plan is refused. The outer walls
are replaced only when the user says so, and the review says what the replacement drops.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

CONVERTER_VERSION = "fp-convert-2"
ANGLE_TOLERANCE = math.radians(1.0)  # parallel or collinear
SIN_TOLERANCE = math.sin(ANGLE_TOLERANCE)
GENTLE_BEND = math.radians(25.0)  # a turn below this between straight runs makes them part of a curve
TOLERANCE = 0.005  # meters: points this close coincide; lines this close are one line
CLOSE_GAP = 0.01  # meters: an outline that comes back to within 1 cm of its start is closed
MIN_WALL_METERS = 0.1
MIN_THICKNESS, MAX_THICKNESS = 0.05, 2.0
MIN_HEIGHT, MAX_HEIGHT = 0.5, 30.0
DEFAULT_THICKNESS = 0.2
DEFAULT_OUTLINE_THICKNESS = 0.3
DEFAULT_MAX_THICKNESS = 0.6
MIN_OVERLAP = 0.1
MIN_ROOM_AREA = 0.5
MIN_OUTLINE_AREA = 0.25
MAX_ZONE_VERTICES = 256
MAX_OUTLINE_VERTICES = 128
MAX_WALLS = 128  # the layout's interior-wall limit, walls already there and new ones together
MAX_OPERATIONS = 500  # the operation kernel's transaction limit
MAX_PIECES = 20000  # straight pieces on the wall layers
MAX_LOOPS = 5000  # closed outlines on the room and outline layers
MAX_SETTINGS_IDS = 2000
MAX_LISTED = 200
MAX_SOURCES = 50
MIN_DOOR_WIDTH, MAX_DOOR_WIDTH = 0.5, 4.0  # meters between a door's jambs
SWEEP_LIMITS = (math.radians(60.0), math.radians(120.0))  # a door swing turns about a right angle
DOOR_SLACK = 0.05  # meters: how far a hinge or a shut leaf may sit off the wall's faces or its jamb
SAME_ZONE_OVERLAP = 0.9  # a new room that shares this much (intersection over union) with a zone is that zone
WALL_COLOR = "#45484b"
ZONE_TYPES = ("workcell", "storage", "staging", "receiving", "shipping", "inspection", "aisle", "dock", "charging",
              "safety", "exclusion", "utility", "service", "operator")
STRAIGHT_TYPES = frozenset({"LINE", "LWPOLYLINE", "POLYLINE"})
WALL_ROLES = ("wall_centerline", "wall_faces")
LOOP_ROLES = ("room_boundary", "perimeter")
CANDIDATE_ID = re.compile(r"(iw|zn|ol|dr)-fp-[a-f0-9]{16}")

MESSAGES = {
    # Candidates that are not added.
    "wall_settings": "Give the wall height to add the walls.",
    "too_short": "Shorter than 0.1 m.",
    "thickness": "Its faces are not 0.05 to 2 m apart.",
    "ambiguous_faces": "A line here pairs on both of its sides, so which lines are this wall's faces is unclear.",
    "overlapping_walls": "It overlaps another wall from the drawing; check the layer is drawn as faces, not "
                         "centerlines.",
    "wall_there": "A wall is already on the plan here.",
    "outside_plan": "Outside the plan.",
    "plan_size": "Set the plan size first.",
    "invalid": "The plan does not accept it.",
    "duplicate": "The same outline is drawn twice.",
    "holds_rooms": "Other rooms lie inside it; leave them out to keep this one.",
    "zone_type": "Choose its zone type.",
    "zone_there": "A zone already covers this room.",
    "outline_settings": "Give the outer wall height to add the outer walls.",
    "choose_outline": "Choose which outline is the building.",
    "other_outline": "Another outline was chosen.",
    "too_many_corners": "It has more corners than the plan's outer walls take (128).",
    "replace_needed": "The plan already has outer walls; choose Replace to swap them.",
    "edited": "Changed since it was converted; left as it is.",
    "door_host_left_out": "Its wall is left out.",
    "door_settings": "Give the outer doors' height to add the outer walls with their doors, or leave the doors out.",
    "door_ambiguous": "The door swings here disagree, or one fits another break too, so the door is unclear; the "
                      "wall keeps its break.",
    # Drawn entities that are not converted.
    "curve": "A curve: it stays as drawing.",
    "no_matching_face": "No matching face line: not a wall.",
    "wall_end": "The end of a wall (its jamb or cap).",
    "open_outline": "Not closed: it does not enclose an area.",
    "crosses_itself": "It crosses itself.",
    "too_small": "Too small to be a room.",
    "too_many_vertices": "More corners than a zone takes (256).",
    "later_phase": "Columns are converted in a later step; it stays as drawing.",
    "door_unmatched": "A door swing that fits no break in a wall and no edge of the outer walls: it stays drawing.",
    "door_leaf_missing": "A door swing on the outer walls without its door leaf: an arc alone is not enough to cut a "
                         "door there; it stays drawing.",
    "door_part": "On a door layer but no part of a door found: it stays drawing.",
}


class ConversionSettingsError(ValueError):
    pass


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConversionSettingsError(f"{name} must be a number.")
    if not low <= value <= high:
        raise ConversionSettingsError(f"{name} must be between {low:g} and {high:g} m.")
    return float(value)


def _closed(value, name: str, allowed: set, required: frozenset = frozenset()) -> dict:
    if not isinstance(value, dict) or not set(value) <= allowed or not required <= set(value):
        raise ConversionSettingsError(f"{name} takes " + ", ".join(sorted(allowed)) + ".")
    return value


def _candidate(value, name: str) -> str:
    if not isinstance(value, str) or not CANDIDATE_ID.fullmatch(value):
        raise ConversionSettingsError(f"{name} must be a candidate id from the conversion.")
    return value


def normalize_settings(value) -> dict:
    """The conversion request's settings, closed and checked (ConversionSettingsError). Each part is optional, and so
    are the wall and outer wall heights: what has no height is listed and not added, while the thicknesses and the
    outline chosen apply at once."""
    source = _closed({} if value is None else value, "settings", {"walls", "rooms", "outline", "doors", "excluded"})
    out = {"walls": None, "rooms": None, "outline": None, "doors": None, "excluded": []}
    walls = source.get("walls")
    if walls is not None:
        walls = _closed(walls, "walls", {"heightMeters", "thicknessMeters", "maxThicknessMeters"})
        out["walls"] = {
            "heightMeters": None if walls.get("heightMeters") is None
            else _number(walls["heightMeters"], "Wall height", MIN_HEIGHT, MAX_HEIGHT),
            "thicknessMeters": _number(walls.get("thicknessMeters", DEFAULT_THICKNESS), "Wall thickness",
                                       MIN_THICKNESS, MAX_THICKNESS),
            "maxThicknessMeters": _number(walls.get("maxThicknessMeters", DEFAULT_MAX_THICKNESS),
                                          "Largest wall thickness", MIN_THICKNESS, MAX_THICKNESS),
        }
    rooms = source.get("rooms")
    if rooms is not None:
        rooms = _closed(rooms, "rooms", {"zoneType", "types"})
        kind = rooms.get("zoneType")
        if kind is not None and kind not in ZONE_TYPES:
            raise ConversionSettingsError("rooms.zoneType must be one of " + ", ".join(ZONE_TYPES) + ".")
        types = rooms.get("types", {})
        if not isinstance(types, dict) or len(types) > MAX_SETTINGS_IDS:
            raise ConversionSettingsError("rooms.types maps room ids to zone types.")
        for key, item in types.items():
            _candidate(key, "A rooms.types key")
            if item not in ZONE_TYPES:
                raise ConversionSettingsError("rooms.types values must be one of " + ", ".join(ZONE_TYPES) + ".")
        out["rooms"] = {"zoneType": kind, "types": dict(sorted(types.items()))}
    outline = source.get("outline")
    if outline is not None:
        outline = _closed(outline, "outline", {"heightMeters", "thicknessMeters", "loop", "replace"})
        loop = outline.get("loop")
        if loop is not None:
            _candidate(loop, "outline.loop")
        if not isinstance(outline.get("replace", False), bool):
            raise ConversionSettingsError("outline.replace must be true or false.")
        out["outline"] = {
            "heightMeters": None if outline.get("heightMeters") is None
            else _number(outline["heightMeters"], "Outer wall height", MIN_HEIGHT, MAX_HEIGHT),
            "thicknessMeters": _number(outline.get("thicknessMeters", DEFAULT_OUTLINE_THICKNESS),
                                       "Outer wall thickness", MIN_THICKNESS, MAX_THICKNESS),
            "loop": loop,
            "replace": outline.get("replace", False),
        }
    doors = source.get("doors")
    if doors is not None:
        doors = _closed(doors, "doors", {"heightMeters"})
        out["doors"] = {"heightMeters": None if doors.get("heightMeters") is None
                        else _number(doors["heightMeters"], "Door height", MIN_HEIGHT, MAX_HEIGHT)}
    excluded = source.get("excluded", [])
    if not isinstance(excluded, list) or len(excluded) > MAX_SETTINGS_IDS:
        raise ConversionSettingsError(f"excluded lists at most {MAX_SETTINGS_IDS} candidate ids.")
    out["excluded"] = sorted({_candidate(item, "An excluded id") for item in excluded})
    return out


# ---------------------------------------------------------------------------------------------------------------
# Small vector helpers (points are (x, z) tuples in layout meters).


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _unit(a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 0 else (0.0, 0.0)


def _turn(d1, d2) -> float:
    """The angle between two directions, 0 to pi."""
    return math.atan2(abs(_cross(d1, d2)), _dot(d1, d2))


def _parallel(d1, d2) -> bool:
    return abs(_cross(d1, d2)) <= SIN_TOLERANCE


def _along(origin, direction, distance):
    return (origin[0] + direction[0] * distance, origin[1] + direction[1] * distance)


def _r(value: float, places: int = 6) -> float:
    result = round(value, places)
    return 0.0 if result == 0 else result


def _xz(point) -> dict:
    return {"x": _r(point[0]), "z": _r(point[1])}


def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _transformer(alignment: dict, origin):
    """Stored drawing point (relative to the geometry's origin) -> layout (x, z) meters: the Plan view's toLayout
    (static/facility_layout_floor_plan.js) on the absolute drawing point."""
    source = alignment["sourceOrigin"]
    shift_u, shift_v = origin[0] - source["u"], origin[1] - source["v"]
    scale = alignment["metersPerDrawingUnit"]
    angle = alignment["rotationDegrees"] * math.pi / 180
    cos, sin = math.cos(angle), math.sin(angle)
    tx, tz = alignment["translationMeters"]["x"], alignment["translationMeters"]["z"]

    def apply(point):
        du, dv = (shift_u + point[0]) * scale, (shift_v + point[1]) * scale
        return (tx + cos * du - sin * dv, tz + sin * du + cos * dv)
    return apply


class _Grid:
    """A uniform grid over boxes, for neighbor searches in a bounded number of cells."""

    def __init__(self, cell: float):
        self.cell = cell
        self.cells = {}

    def _span(self, box):
        cell = self.cell
        return (range(math.floor(box[0] / cell), math.floor(box[2] / cell) + 1),
                range(math.floor(box[1] / cell), math.floor(box[3] / cell) + 1))

    def add(self, key, box):
        columns, rows = self._span(box)
        for i in columns:
            for j in rows:
                self.cells.setdefault((i, j), []).append(key)

    def near(self, box):
        columns, rows = self._span(box)
        found = set()
        for i in columns:
            for j in rows:
                found.update(self.cells.get((i, j), ()))
        return found


def _box(a, b, margin=0.0):
    return (min(a[0], b[0]) - margin, min(a[1], b[1]) - margin, max(a[0], b[0]) + margin,
            max(a[1], b[1]) + margin)


# ---------------------------------------------------------------------------------------------------------------
# Straight pieces of polylines.


def _dedupe(points, closed):
    out = []
    for point in points:
        if not out or math.dist(point, out[-1]) > 1e-6:
            out.append(point)
    if closed and len(out) > 2 and math.dist(out[0], out[-1]) <= 1e-6:
        out.pop()
    return out


def _straight_pieces(points, closed):
    """[(a, b, curved)]: the straight runs of a polyline. Consecutive segments that turn by less than a degree are one
    run; a run whose points stray more than TOLERANCE from its chord bows (a curve drawn in short steps), and runs that
    meet at less than GENTLE_BEND belong to one curve. Linear in the number of points."""
    points = _dedupe(points, closed)
    if len(points) < 2:
        return []
    segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    if closed and len(points) > 2:
        segments.append((points[-1], points[0]))
    runs = []  # [first segment index, last segment index]
    for index in range(len(segments)):
        if runs and _turn(_unit(*segments[index - 1]), _unit(*segments[index])) < ANGLE_TOLERANCE:
            runs[-1][1] = index
        else:
            runs.append([index, index])
    if closed and len(runs) > 1 and _turn(_unit(*segments[-1]), _unit(*segments[0])) < ANGLE_TOLERANCE:
        last = runs.pop()  # the closing run carries on into the first one
        runs[0] = [last[0], runs[0][1] + len(segments)]
    curved = []
    for first, last in runs:
        start = segments[first % len(segments)][0]
        end = segments[last % len(segments)][1]
        direction = _unit(start, end)
        bows = direction == (0.0, 0.0) or any(
            abs(_cross(direction, _sub(segments[index % len(segments)][1], start))) > TOLERANCE
            for index in range(first, last))
        curved.append(bows)
    count = len(runs)
    joints = range(count) if closed and count > 1 else range(count - 1)
    for index in joints:
        following = (index + 1) % count
        left = segments[runs[index][1] % len(segments)]
        right = segments[runs[following][0] % len(segments)]
        if _turn(_unit(*left), _unit(*right)) < GENTLE_BEND:
            curved[index] = curved[following] = True
    return [(segments[first % len(segments)][0], segments[last % len(segments)][1], curved[index])
            for index, (first, last) in enumerate(runs)]


# ---------------------------------------------------------------------------------------------------------------
# Walls.


class _Wall:
    __slots__ = ("a", "b", "thickness", "sources", "layers", "kind", "flag", "openings")

    def __init__(self, a, b, thickness, sources, layers, kind, flag=None, openings=()):
        self.a, self.b, self.thickness = a, b, thickness
        self.sources, self.layers, self.kind, self.flag = set(sources), set(layers), kind, flag
        self.openings = list(openings)  # [(p, q)]: door openings, their ends as points on the wall's line

    @property
    def length(self):
        return math.dist(self.a, self.b)

    def direction(self):
        return _unit(self.a, self.b)


def _face_walls(pieces, max_gap):
    """Walls from pairs of parallel face lines. PIECES: [(a, b, entity_id, layer)]. Returns (walls, ids of the
    pieces that pair)."""
    info = []
    for a, b, entity, layer in pieces:
        d = _unit(a, b)
        info.append((a, b, d, (-d[1], d[0]), math.dist(a, b), entity, layer))
    reach = max_gap + TOLERANCE
    grid = _Grid(max(1.0, 2 * reach))
    for index, item in enumerate(info):
        grid.add(index, _box(item[0], item[1], reach))

    def relation(i, j):
        """(side, gap, low, high) of piece j seen from piece i's line (low..high: their overlap along i), or None when
        j is not parallel to i on one side of it."""
        a, _b, d, n, length = info[i][:5]
        aj, bj, dj = info[j][:3]
        if not _parallel(d, dj):
            return None
        e1, e2 = _dot(n, _sub(aj, a)), _dot(n, _sub(bj, a))
        if e1 * e2 <= 0 or abs(e1 - e2) > TOLERANCE:
            return None
        s1, s2 = _dot(d, _sub(aj, a)), _dot(d, _sub(bj, a))
        return (1 if e1 > 0 else -1), (abs(e1) + abs(e2)) / 2, max(0.0, min(s1, s2)), min(length, max(s1, s2))

    pairs = []
    for i in range(len(info)):
        related = {}
        for j in grid.near(_box(info[i][0], info[i][1])):
            if j != i:
                value = relation(i, j)
                if value is not None:
                    related[j] = value
        for j, (side, gap, low, high) in related.items():
            if j < i or not MIN_THICKNESS - TOLERANCE <= gap <= reach or high - low < MIN_OVERLAP:
                continue
            # Another parallel line between them over their overlap would be the partner instead.
            if any(k != j and other[0] == side and TOLERANCE < other[1] < gap - TOLERANCE
                   and min(high, other[3]) - max(low, other[2]) > TOLERANCE for k, other in related.items()):
                continue
            pairs.append((i, j, side, gap, low, high))
    walls = []
    uses = {}  # piece -> [(side of the wall from the piece, low, high along the piece, wall index)]
    for i, j, side, gap, low, high in pairs:
        a, _b, d, n = info[i][:4]
        offset = side * gap / 2
        start = (a[0] + d[0] * low + n[0] * offset, a[1] + d[1] * low + n[1] * offset)
        end = (a[0] + d[0] * high + n[0] * offset, a[1] + d[1] * high + n[1] * offset)
        index = len(walls)
        walls.append(_Wall(start, end, round(gap, 4), {info[i][5], info[j][5]}, {info[i][6], info[j][6]}, "faces"))
        middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        for piece in (i, j):
            pa, _pb, pd, pn = info[piece][:4]
            s1, s2 = _dot(pd, _sub(start, pa)), _dot(pd, _sub(end, pa))
            uses.setdefault(piece, []).append((1 if _dot(pn, _sub(middle, pa)) > 0 else -1, min(s1, s2),
                                               max(s1, s2), index))
    for rows in uses.values():
        for first in range(len(rows)):
            for second in range(first + 1, len(rows)):
                one, two = rows[first], rows[second]
                if one[0] != two[0] and min(one[2], two[2]) - max(one[1], two[1]) > TOLERANCE:
                    walls[one[3]].flag = walls[two[3]].flag = "ambiguous_faces"
    paired = {info[piece][5] for piece in uses}
    return walls, paired


def _gap_filled(first, d, n, low, high, grid, walls, skip):
    """Whether a wall ends in the gap LOW..HIGH along FIRST (direction D, normal N) and is as wide as it: the gap is
    the T a wall drawn with faces leaves in the wall it meets."""
    width = high - low
    middle = _along(first.a, d, (low + high) / 2)
    for index in grid.near(_box(middle, middle, width + first.thickness)):
        other = walls[index]
        if index in skip or other.flag:
            continue
        e = other.direction()
        sine = abs(_cross(d, e))
        if sine < math.sin(GENTLE_BEND):
            continue
        if abs(width - other.thickness / sine) > 2 * TOLERANCE:
            continue
        for end in (other.a, other.b):
            along, across = _dot(d, _sub(end, first.a)), _dot(n, _sub(end, first.a))
            if abs(along - (low + high) / 2) <= 2 * TOLERANCE and abs(across) <= first.thickness / 2 + 2 * TOLERANCE:
                return True
    return False


def _merge_collinear(walls):
    """Joins pieces of one wall: collinear walls of one thickness that overlap or touch, or whose gap a wall ending
    in it fills (_gap_filled). Any other gap is an opening and stays. Pairs are found through a grid and joined by
    union-find, so this is near linear."""
    count = len(walls)
    if count < 2:
        return list(walls)
    widest = max(wall.thickness for wall in walls)
    margin = widest / math.sin(GENTLE_BEND) + 2 * TOLERANCE
    grid = _Grid(max(1.0, 4 * margin))
    for index, wall in enumerate(walls):
        grid.add(index, _box(wall.a, wall.b, margin))
    parent = list(range(count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, first in enumerate(walls):
        d = first.direction()
        n = (-d[1], d[0])
        for j in grid.near(_box(first.a, first.b, margin)):
            if j <= i:
                continue
            second = walls[j]
            if first.flag != second.flag or abs(first.thickness - second.thickness) > TOLERANCE:
                continue
            if not _parallel(d, second.direction()):
                continue
            if max(abs(_dot(n, _sub(second.a, first.a))), abs(_dot(n, _sub(second.b, first.a)))) > TOLERANCE:
                continue
            s = (0.0, first.length)
            t = sorted((_dot(d, _sub(second.a, first.a)), _dot(d, _sub(second.b, first.a))))
            gap = max(t[0] - s[1], s[0] - t[1])
            if gap > TOLERANCE:
                low, high = (s[1], t[0]) if t[0] >= s[1] else (t[1], s[0])
                if first.flag or not _gap_filled(first, d, n, low, high, grid, walls, {i, j}):
                    continue
            root_i, root_j = find(i), find(j)
            if root_i != root_j:
                parent[max(root_i, root_j)] = min(root_i, root_j)
    groups = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(index)
    merged = []
    for root in sorted(groups):
        members = [walls[index] for index in groups[root]]
        if len(members) == 1:
            merged.append(members[0])
            continue
        base = max(members, key=lambda wall: (wall.length, wall.a, wall.b))
        d = base.direction()
        ends = [_dot(d, _sub(point, base.a)) for wall in members for point in (wall.a, wall.b)]
        kinds = {wall.kind for wall in members}
        merged.append(_Wall(_along(base.a, d, min(ends)), _along(base.a, d, max(ends)), base.thickness,
                            set().union(*(wall.sources for wall in members)),
                            set().union(*(wall.layers for wall in members)),
                            kinds.pop() if len(kinds) == 1 else "mixed", base.flag))
    return merged


def _line_intersection(p, d, q, e):
    """Parameters (lambda, mu) with p + lambda d == q + mu e, or None for parallel lines."""
    denominator = _cross(d, e)
    if abs(denominator) < 1e-12:
        return None
    w = _sub(q, p)
    return _cross(w, e) / denominator, _cross(w, d) / denominator


def _join_ends(walls):
    """Closes junctions. L: two walls whose ends meet at a corner both reach past it by half the other's thickness,
    so the corner is filled. T: a wall end that stops short of another wall's centerline by no more than their half
    thicknesses is carried to it. Ambiguous walls are left as they are."""
    count = len(walls)
    if count < 2:
        return walls
    ends = [[wall.a, wall.b] for wall in walls]
    widest = max(wall.thickness for wall in walls)
    reach = widest + 2 * TOLERANCE
    grid = _Grid(max(1.0, 4 * reach))
    for index, wall in enumerate(walls):
        grid.add(index, _box(wall.a, wall.b, 2 * reach))

    def outward(index, which):
        a, b = walls[index].a, walls[index].b
        return _unit(b, a) if which == 0 else _unit(a, b)

    corners = []
    for i in range(count):
        if walls[i].flag:
            continue
        for wi in (0, 1):
            p = ends[i][wi]
            for j in grid.near(_box(p, p)):
                if j <= i or walls[j].flag:
                    continue
                angle = _turn(walls[i].direction(), walls[j].direction())
                if angle < GENTLE_BEND or angle > math.pi - GENTLE_BEND:
                    continue
                limit = max(walls[i].thickness, walls[j].thickness) + 2 * TOLERANCE
                for wj in (0, 1):
                    q = ends[j][wj]
                    if math.dist(p, q) > 2 * limit:
                        continue
                    hit = _line_intersection(p, outward(i, wi), q, outward(j, wj))
                    if hit is not None and abs(hit[0]) <= limit and abs(hit[1]) <= limit:
                        corners.append((abs(hit[0]) + abs(hit[1]), i, wi, j, wj, hit[0]))
    done = set()
    for _score, i, wi, j, wj, lam in sorted(corners):
        if (i, wi) in done or (j, wj) in done:
            continue
        di, dj = outward(i, wi), outward(j, wj)
        corner = _along(ends[i][wi], di, lam)
        ends[i][wi] = _along(corner, di, walls[j].thickness / 2)
        ends[j][wj] = _along(corner, dj, walls[i].thickness / 2)
        done.update({(i, wi), (j, wj)})
    for i in range(count):
        if walls[i].flag:
            continue
        for wi in (0, 1):
            if (i, wi) in done:
                continue
            p, di = ends[i][wi], outward(i, wi)
            best = None
            for j in grid.near(_box(p, p)):
                if j == i or walls[j].flag:
                    continue
                q, e = ends[j][0], _unit(ends[j][0], ends[j][1])
                if _turn(di, e) < GENTLE_BEND or _turn(di, e) > math.pi - GENTLE_BEND:
                    continue
                hit = _line_intersection(p, di, q, e)
                if hit is None:
                    continue
                lam, mu = hit
                limit = walls[i].thickness / 2 + walls[j].thickness / 2 + 2 * TOLERANCE
                if TOLERANCE < lam <= limit and -TOLERANCE <= mu <= math.dist(*ends[j]) + TOLERANCE:
                    if best is None or lam < best:
                        best = lam
            if best is not None:
                ends[i][wi] = _along(p, di, best)
    return [_Wall(ends[i][0], ends[i][1], wall.thickness, wall.sources, wall.layers, wall.kind, wall.flag,
                  wall.openings) for i, wall in enumerate(walls)]


def _flag_overlaps(walls):
    """Marks parallel walls that are not one wall but lie closer than their half thicknesses (a layer of faces given
    the centerline role draws each wall twice)."""
    if len(walls) < 2:
        return
    widest = max(wall.thickness for wall in walls)
    grid = _Grid(max(1.0, 4 * widest))
    for index, wall in enumerate(walls):
        grid.add(index, _box(wall.a, wall.b, widest))
    for i, first in enumerate(walls):
        d = first.direction()
        n = (-d[1], d[0])
        for j in grid.near(_box(first.a, first.b, widest)):
            second = walls[j]
            if j <= i or not _parallel(d, second.direction()):
                continue
            distance = abs(_dot(n, _sub(second.a, first.a)) + _dot(n, _sub(second.b, first.a))) / 2
            if distance > (first.thickness + second.thickness) / 2 - TOLERANCE:
                continue
            t = sorted((_dot(d, _sub(second.a, first.a)), _dot(d, _sub(second.b, first.a))))
            if min(first.length, t[1]) - max(0.0, t[0]) >= MIN_OVERLAP:
                for wall in (first, second):
                    wall.flag = wall.flag or "overlapping_walls"


def _wall_end(piece, walls, grid):
    """Whether an unpaired face line closes a wall's end (a jamb or an end cap)."""
    a, b = piece[0], piece[1]
    middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    d = _unit(a, b)
    for index in grid.near(_box(middle, middle)):
        wall = walls[index]
        if abs(_dot(d, wall.direction())) > 0.05:
            continue
        if min(math.dist(middle, wall.a), math.dist(middle, wall.b)) <= wall.thickness / 2 + 2 * TOLERANCE:
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------
# Doors.


def _swing(points):
    """A door swing: an open curve whose points (sampled on the true curve) lie on one circle and turn 60 to 120
    degrees about it. (hinge, radius, (first end, last end)) or None."""
    if len(points) < 3:
        return None
    a, m, b = points[0], points[len(points) // 2], points[-1]
    bx, bz, cx, cz = m[0] - a[0], m[1] - a[1], b[0] - a[0], b[1] - a[1]
    d = 2 * (bx * cz - bz * cx)
    if abs(d) < 1e-12:
        return None
    hinge = (a[0] + (cz * (bx * bx + bz * bz) - bz * (cx * cx + cz * cz)) / d,
             a[1] + (bx * (cx * cx + cz * cz) - cx * (bx * bx + bz * bz)) / d)
    radius = math.dist(hinge, a)
    if not MIN_DOOR_WIDTH / 2 - DOOR_SLACK <= radius <= MAX_DOOR_WIDTH + DOOR_SLACK:
        return None
    if any(abs(math.dist(hinge, point) - radius) > max(0.01, 0.01 * radius) for point in points):
        return None
    if not SWEEP_LIMITS[0] <= _turn(_unit(hinge, a), _unit(hinge, b)) <= SWEEP_LIMITS[1]:
        return None
    if _dot(_sub(m, hinge), _sub(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), hinge)) <= 0:
        return None  # the long way round: more than half a circle
    return hinge, radius, (a, b)


def _door_symbols(door_entities):
    """The door layers' swings and straight pieces (a leaf is one), as dicts with the entity they come from. Each
    curved stretch of an open polyline is tried as a swing and its straight runs are pieces, so a door drawn as one
    polyline (leaf and swing) reads like one drawn as a line and an arc."""
    swings, pieces = [], []

    def swing_of(points, entity_id, layer):
        fitted = _swing(points)
        if fitted is not None:
            swings.append({"hinge": fitted[0], "radius": fitted[1], "ends": fitted[2], "entity": entity_id,
                           "layer": layer})

    for entity, points in door_entities:
        entity_id, layer, closed = str(entity.get("id")), str(entity.get("layer")), bool(entity.get("closed"))
        if entity.get("type") not in STRAIGHT_TYPES:
            if not closed:  # an arc (or an ellipse or spline drawn as one)
                swing_of(points, entity_id, layer)
            continue
        stretch = []
        for a, b, curved in _straight_pieces(points, closed):
            if curved and not closed:
                stretch = stretch or [a]
                stretch.append(b)
                continue
            if len(stretch) >= 3:
                swing_of(stretch, entity_id, layer)
            stretch = []
            if not curved:
                pieces.append({"a": a, "b": b, "entity": entity_id, "layer": layer})
        if len(stretch) >= 3:
            swing_of(stretch, entity_id, layer)
    return swings, pieces


def _leaf(swing, pieces, grid):
    """The piece drawn from the swing's hinge to one of its ends (the door leaf), or None."""
    hinge, radius = swing["hinge"], swing["radius"]
    slack = max(DOOR_SLACK, 0.1 * radius)
    for index in sorted(grid.near(_box(hinge, hinge, slack))):
        a, b = pieces[index]["a"], pieces[index]["b"]
        for near, far in ((a, b), (b, a)):
            if math.dist(near, hinge) <= max(DOOR_SLACK, 0.05 * radius) and any(
                    math.dist(far, end) <= slack for end in swing["ends"]):
                return index
    return None


def _door_gaps(walls):
    """Breaks in a wall: two collinear pieces of one thickness whose facing ends lie MIN_DOOR_WIDTH to MAX_DOOR_WIDTH
    apart, the nearer one beyond the other's end along their line. [(i, p, j, q)]: end P of walls[i] faces end Q of
    walls[j]."""
    grid = _Grid(max(1.0, MAX_DOOR_WIDTH))
    for index, wall in enumerate(walls):
        if not wall.flag:
            grid.add(index, _box(wall.a, wall.b, MAX_DOOR_WIDTH))
    found = {}
    for i, first in enumerate(walls):
        if first.flag:
            continue
        d = first.direction()
        n = (-d[1], d[0])
        for p, out in ((first.a, (-d[0], -d[1])), (first.b, d)):
            best = None
            for j in grid.near(_box(p, p)):
                second = walls[j]
                if j == i or not _parallel(d, second.direction()):
                    continue
                if max(abs(_dot(n, _sub(second.a, p))), abs(_dot(n, _sub(second.b, p)))) > TOLERANCE:
                    continue
                near = min((_dot(out, _sub(point, p)), point) for point in (second.a, second.b))
                if near[0] > TOLERANCE and (best is None or near[0] < best[0]):
                    best = (near[0], j, near[1])
            if best is None or abs(walls[best[1]].thickness - first.thickness) > TOLERANCE:
                continue
            if MIN_DOOR_WIDTH - TOLERANCE <= best[0] <= MAX_DOOR_WIDTH + TOLERANCE:
                found.setdefault((min(i, best[1]), max(i, best[1])), (i, p, best[1], best[2]))
    return [found[key] for key in sorted(found)]


def _gap_fits(gap, walls, swings, grid):
    """The swings that fit a break: [(swing index, "single" or "half", the jamb it is hinged at: 0 at P, 1 at Q)]."""
    i, p, _j, q = gap
    thickness, width = walls[i].thickness, math.dist(p, q)
    e = _unit(p, q)
    n = (-e[1], e[0])
    fits = []
    for k in sorted(grid.near(_box(p, q, width))):
        hinge, radius, ends = swings[k]["hinge"], swings[k]["radius"], swings[k]["ends"]
        along, across = _dot(e, _sub(hinge, p)), _dot(n, _sub(hinge, p))
        if abs(across) > thickness / 2 + DOOR_SLACK:
            continue
        for side, at in ((0, 0.0), (1, width)):
            if abs(along - at) > max(DOOR_SLACK, 0.05 * width):
                continue
            for kind, leaf in (("single", width), ("half", width / 2)):
                slack = max(DOOR_SLACK, 0.1 * leaf)
                if abs(radius - leaf) > slack:
                    continue
                shut = at + leaf if side == 0 else at - leaf
                if any(abs(_dot(n, _sub(end, p))) <= thickness / 2 + DOOR_SLACK
                       and abs(_dot(e, _sub(end, p)) - shut) <= slack for end in ends):
                    fits.append((k, kind, side))
    return fits


def _wall_doors(walls, swings, pieces, excluded, import_id):
    """Doors in the breaks of walls (_door_gaps): one swing of the break's width hinged at one jamb and shut against
    the other, or two of half its width hinged at both jambs (a double door). Swings that disagree about a break, or a
    swing that fits more than one break, leave it unclear. Returns the doors (dicts; "join": the wall is joined across
    the break), and the swings and pieces they use."""
    gaps = _door_gaps(walls)
    swing_grid, piece_grid = _Grid(max(1.0, MAX_DOOR_WIDTH)), _Grid(2.0)
    for index, swing in enumerate(swings):
        swing_grid.add(index, _box(swing["hinge"], swing["hinge"]))
    for index, piece in enumerate(pieces):
        piece_grid.add(index, _box(piece["a"], piece["b"]))
    all_fits = [_gap_fits(gap, walls, swings, swing_grid) for gap in gaps]
    uses = {}
    for fits in all_fits:
        for k in {fit[0] for fit in fits}:
            uses[k] = uses.get(k, 0) + 1
    doors, used_swings, used_pieces = [], set(), set()
    for gap, fits in zip(gaps, all_fits):
        if not fits:
            continue
        i, p, j, q = gap
        # The jambs the swings are hinged at: full-width swings all at one jamb are one door (drawn on both sides
        # when it swings both ways), half-width ones at both jambs a double door; anything else disagrees.
        singles = {fit[2] for fit in fits if fit[1] == "single"}
        halves = {fit[2] for fit in fits if fit[1] == "half"}
        if any(uses[fit[0]] > 1 for fit in fits):
            kind = "unclear"
        elif len(singles) == 1 and not halves:
            kind = "single"
        elif halves == {0, 1} and not singles:
            kind = "double"
        else:
            kind = "unclear"
        chosen = sorted({fit[0] for fit in fits})
        used_swings.update(chosen)
        sources, layers = {swings[k]["entity"] for k in chosen}, {swings[k]["layer"] for k in chosen}
        for k in chosen:
            leaf = _leaf(swings[k], pieces, piece_grid)
            if leaf is not None:
                used_pieces.add(leaf)
                sources.add(pieces[leaf]["entity"])
                layers.add(pieces[leaf]["layer"])
        ends = sorted((_xz(p), _xz(q)), key=lambda point: (point["x"], point["z"]))
        door_id = "dr-fp-" + _digest(import_id, "door", ends)[:16]
        doors.append({"candidateId": door_id, "kind": kind, "widthMeters": _r(math.dist(p, q), 4),
                      "at": _xz(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)), "layers": sorted(layers),
                      "sources": sorted(sources)[:MAX_SOURCES], "gap": gap,
                      "join": kind != "unclear" and door_id not in excluded})
    return doors, used_swings, used_pieces


def _join_doors(walls, doors):
    """WALLS joined across the breaks of the DOORS that join them, each with its openings. Returns the walls and where
    each of the given walls went (index -> index)."""
    parent = list(range(len(walls)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for door in doors:
        i, _p, j, _q = door["gap"]
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[max(root_i, root_j)] = min(root_i, root_j)
    groups = {}
    for index in range(len(walls)):
        groups.setdefault(find(index), []).append(index)
    joined, place = [], {}
    for root in sorted(groups):
        members = groups[root]
        place.update({index: len(joined) for index in members})
        if len(members) == 1:
            joined.append(walls[members[0]])
            continue
        parts = [walls[index] for index in members]
        base = max(parts, key=lambda wall: (wall.length, wall.a, wall.b))
        d = base.direction()
        ends = [_dot(d, _sub(point, base.a)) for wall in parts for point in (wall.a, wall.b)]
        kinds = {wall.kind for wall in parts}
        openings = [(door["gap"][1], door["gap"][3]) for door in doors if find(door["gap"][0]) == root]
        joined.append(_Wall(_along(base.a, d, min(ends)), _along(base.a, d, max(ends)), base.thickness,
                            set().union(*(wall.sources for wall in parts)), set().union(*(wall.layers for wall in parts)),
                            kinds.pop() if len(kinds) == 1 else "mixed", None, openings))
    return joined, place


def _outline_doors(points, width, swings, pieces, free):
    """Doors in the outer walls along the outline POINTS (a closed ring): a swing hinged on an edge and shut along it,
    with its leaf drawn; two shut against each other are a double door. Returns ([(edge, start, end, kind, swing
    indexes, piece indexes)], the swings that fit an edge but have no leaf)."""
    piece_grid = _Grid(2.0)
    for index, piece in enumerate(pieces):
        piece_grid.add(index, _box(piece["a"], piece["b"]))
    leaves, leafless = {}, set()
    for k in free:
        swing = swings[k]
        hinge, radius = swing["hinge"], swing["radius"]
        slack = max(DOOR_SLACK, 0.1 * radius)
        fits = []
        for edge in range(len(points)):
            a, b = points[edge], points[(edge + 1) % len(points)]
            length, e = math.dist(a, b), _unit(a, b)
            n = (-e[1], e[0])
            along, across = _dot(e, _sub(hinge, a)), _dot(n, _sub(hinge, a))
            if abs(across) > width / 2 + DOOR_SLACK or not -DOOR_SLACK <= along <= length + DOOR_SLACK:
                continue
            for end in swing["ends"]:
                shut = _dot(e, _sub(end, a))
                if abs(_dot(n, _sub(end, a))) <= width / 2 + DOOR_SLACK and abs(abs(shut - along) - radius) <= slack:
                    low, high = sorted((along, shut))
                    if low >= -DOOR_SLACK and high <= length + DOOR_SLACK:
                        # Rounded as stored, and never past the edge's ends (the outer walls refuse that).
                        fits.append((edge, _r(max(0.0, low), 4), min(_r(high, 4), length)))
        if len(fits) != 1:
            continue
        leaf = _leaf(swing, pieces, piece_grid)
        if leaf is None:
            leafless.add(k)
            continue
        leaves[k] = (fits[0], leaf)
    found = []
    for k, ((edge, low, high), leaf) in sorted(leaves.items(), key=lambda item: item[1][0]):
        last = found[-1] if found else None
        if last and last[0] == edge and last[3] == "single" and abs(low - last[2]) <= DOOR_SLACK:
            found[-1] = (edge, last[1], high, "double", last[4] + [k], last[5] + [leaf])
        else:
            found.append((edge, low, high, "single", [k], [leaf]))
    return found, leafless


# ---------------------------------------------------------------------------------------------------------------
# Loops (rooms and the outline).


def _loop(points, closed):
    """A closed loop's distinct vertices without collinear middle points, or (None, reason)."""
    points = _dedupe(points, closed)
    if not closed:
        if len(points) > 3 and math.dist(points[0], points[-1]) <= CLOSE_GAP:
            points = points[:-1]
        else:
            return None, "open_outline"
    if len(points) < 3:
        return None, "too_small"
    kept = list(points)
    changed = True
    while changed and len(kept) > 3:
        changed = False
        for index in range(len(kept)):
            before, here, after = kept[index - 1], kept[index], kept[(index + 1) % len(kept)]
            direction = _unit(before, after)
            if direction != (0.0, 0.0) and abs(_cross(direction, _sub(here, before))) <= 1e-6 \
                    and _dot(_sub(here, before), _sub(after, here)) >= 0:
                del kept[index]
                changed = True
                break
    return kept, None


def _canonical_ring(points):
    """Counter-clockwise (x right, z up), starting at the lowest, then leftmost, vertex."""
    area = sum(points[i - 1][0] * points[i][1] - points[i][0] * points[i - 1][1] for i in range(len(points)))
    if area < 0:
        points = points[::-1]
    start = min(range(len(points)), key=lambda index: (points[index][1], points[index][0]))
    return points[start:] + points[:start]


def _rounded_polygon(ring):
    """(boundary, polygon) rounded to the layout's precision and then put in canonical order (so float noise from a
    turn never picks the first corner), or (boundary, None) if rounding broke it."""
    from shapely.geometry import Polygon
    pairs = _canonical_ring([(_r(x), _r(z)) for x, z in ring])
    boundary = [{"x": x, "z": z} for x, z in pairs]
    polygon = Polygon(pairs)
    if len(set(pairs)) != len(pairs) or not polygon.is_valid:
        return boundary, None
    return boundary, polygon


def _face_offset(outer, inner):
    """The wall thickness if INNER is OUTER moved inward by one distance everywhere (the two faces of the outer walls),
    else None."""
    if not outer.contains(inner):
        return None
    ring = (outer.length + inner.length) / 2
    thickness = (outer.area - inner.area) / ring if ring > 0 else 0
    if not MIN_THICKNESS - TOLERANCE <= thickness <= MAX_THICKNESS:
        return None
    moved = outer.buffer(-thickness, join_style="mitre")
    if moved.is_empty or moved.geom_type != "Polygon" or moved.hausdorff_distance(inner) > 2 * TOLERANCE:
        return None
    return round(thickness, 4)


# ---------------------------------------------------------------------------------------------------------------
# The conversion.


def _plan(layout):
    from .plan_settings import plan_settings_from_layout
    try:
        return plan_settings_from_layout(layout)
    except (ValueError, TypeError):
        return None


def _floor(layout) -> float:
    frame = layout.get("coordinateFrame") if isinstance(layout, dict) else None
    value = frame.get("floorElevation", 0) if isinstance(frame, dict) else 0
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _label(text) -> str | None:
    from .floor_plan_references import clean_label
    try:
        return clean_label(text, "label")
    except ValueError:
        return None


class _Unconverted:
    def __init__(self):
        self.rows, self.counts = [], {}

    def add(self, entity, reason):
        first = reason not in self.counts
        self.counts[reason] = self.counts.get(reason, 0) + 1
        # Past MAX_LISTED rows, each reason still keeps its first row, so every count has its message.
        if len(self.rows) < MAX_LISTED or first:
            self.rows.append({"entityId": str(entity.get("id")), "layerId": str(entity.get("layer")),
                              "reason": reason, "message": MESSAGES[reason]})

    def add_piece(self, entity_id, layer, reason):
        self.add({"id": entity_id, "layer": layer}, reason)


def _state(row, state, reason=None, message=None):
    row["state"] = state
    row["reason"] = reason
    row["message"] = message or (MESSAGES[reason] if reason else None)


def _compile_problem(error: ValueError) -> tuple[str, str]:
    text = str(error)
    if "outside the facility plan" in text:
        return "outside_plan", MESSAGES["outside_plan"]
    if "plan dimensions" in text:
        return "plan_size", MESSAGES["plan_size"]
    return "invalid", text[:200]


def convert(geometry: dict, reference: dict, layout: dict, settings: dict, *, import_id: str) -> dict:
    """The conversion of GEOMETRY (the stored drawing) placed by REFERENCE (the saved underlay: its alignment and layer
    roles) into LAYOUT, with SETTINGS (normalize_settings). Pure: reads nothing else and changes nothing."""
    from shapely.geometry import Point, Polygon, box as shapely_box
    from shapely.strtree import STRtree
    from .interior_walls import compile_interior_walls

    roles = {layer["layerId"]: layer["role"] for layer in reference.get("layers", [])}
    names = {layer.get("layerId"): layer.get("name") for layer in geometry.get("layers", [])}
    transform = _transformer(reference["alignment"], geometry.get("origin") or [0.0, 0.0])
    excluded = set(settings["excluded"])
    unconverted = _Unconverted()

    pieces = {role: [] for role in WALL_ROLES}
    loops = {role: [] for role in LOOP_ROLES}
    texts = []
    door_entities = []
    piece_count = loop_count = 0
    for entity in geometry.get("entities", []):
        role = roles.get(entity.get("layer"), "reference")
        if role in ("reference", "ignore"):
            continue
        if "text" in entity:
            if role in ("text", "room_boundary") and isinstance(entity.get("at"), list):
                texts.append((transform(entity["at"]), entity.get("text"), str(entity.get("id")),
                              str(entity.get("layer"))))
            continue
        points = entity.get("points")
        if not isinstance(points, list) or len(points) < 2 or role == "text":
            continue
        if role == "column":
            unconverted.add(entity, "later_phase")
            continue
        if role == "door":
            door_entities.append((entity, [transform(point) for point in points]))
            continue
        if entity.get("type") not in STRAIGHT_TYPES:
            unconverted.add(entity, "curve")
            continue
        drawn = [transform(point) for point in points]
        closed = bool(entity.get("closed"))
        if role in WALL_ROLES:
            runs = _straight_pieces(drawn, closed)
            if any(curved for _a, _b, curved in runs):
                unconverted.add(entity, "curve")
            for a, b, curved in runs:
                if not curved and math.dist(a, b) >= TOLERANCE:
                    piece_count += 1
                    pieces[role].append((a, b, str(entity.get("id")), str(entity.get("layer"))))
        else:
            loop_count += 1
            ring, reason = _loop(drawn, closed)
            if ring is None:
                unconverted.add(entity, reason)
            else:
                loops[role].append((ring, entity))
        if piece_count > MAX_PIECES or loop_count > MAX_LOOPS:
            raise ConversionSettingsError(
                f"The layers given wall, room or outline roles hold more than {MAX_PIECES:,} straight pieces or "
                f"{MAX_LOOPS:,} outlines, more than one conversion reads. Give those roles to fewer layers.")

    plan = _plan(layout)
    plan_box = shapely_box(0, 0, plan["widthMeters"], plan["depthMeters"]) if plan else None
    floor = _floor(layout)
    extensions = layout.get("extensions") if isinstance(layout.get("extensions"), dict) else {}
    interior = extensions.get("facilityInteriorWalls") if isinstance(
        extensions.get("facilityInteriorWalls"), dict) else {}
    existing_walls = [wall for wall in interior.get("walls", []) if isinstance(wall, dict)]
    walls_by_id = {wall.get("wallId"): wall for wall in existing_walls}
    existing_zones = [zone for zone in layout.get("zones", []) if isinstance(zone, dict)]
    zones_by_id = {zone.get("zoneId"): zone for zone in existing_zones}

    # Walls.
    wall_settings = settings["walls"]
    max_gap = wall_settings["maxThicknessMeters"] if wall_settings else DEFAULT_MAX_THICKNESS
    thickness = wall_settings["thicknessMeters"] if wall_settings else DEFAULT_THICKNESS
    raw = [_Wall(a, b, round(thickness, 4), {entity}, {layer}, "centerline")
           for a, b, entity, layer in pieces["wall_centerline"]]
    faced, paired = _face_walls(pieces["wall_faces"], max_gap)
    merged = _merge_collinear(raw + faced)
    _flag_overlaps(merged)
    ends_grid = _Grid(max(1.0, 4 * max((wall.thickness for wall in merged), default=1.0)))
    for index, wall in enumerate(merged):
        ends_grid.add(index, _box(wall.a, wall.b, wall.thickness))
    for a, b, entity, layer in pieces["wall_faces"]:
        if entity not in paired:
            unconverted.add_piece(entity, layer, "wall_end" if _wall_end((a, b), merged, ends_grid)
                                  else "no_matching_face")
    swings, door_pieces = _door_symbols(door_entities)
    gap_doors, used_swings, used_pieces = _wall_doors(merged, swings, door_pieces, excluded, import_id)
    joined, place = _join_doors(merged, [door for door in gap_doors if door["join"]])
    walls = _join_ends(joined)

    existing_grid = _Grid(4.0)
    existing_lines = []
    for wall in existing_walls:
        try:
            a = (float(wall["start"]["x"]), float(wall["start"]["z"]))
            b = (float(wall["end"]["x"]), float(wall["end"]["z"]))
            width = float(wall["thicknessMeters"])
        except (KeyError, TypeError, ValueError):
            continue
        existing_grid.add(len(existing_lines), _box(a, b, width))
        existing_lines.append((a, b, width, wall.get("wallId")))

    def wall_there(a, b, width, wall_id):
        d = _unit(a, b)
        n = (-d[1], d[0])
        for index in existing_grid.near(_box(a, b, width)):
            ea, eb, ewidth, eid = existing_lines[index]
            if eid == wall_id or not _parallel(d, _unit(ea, eb)):
                continue
            if abs(_dot(n, _sub(ea, a)) + _dot(n, _sub(eb, a))) / 2 > max(width, ewidth) / 2:
                continue
            t = sorted((_dot(d, _sub(ea, a)), _dot(d, _sub(eb, a))))
            if min(math.dist(a, b), t[1]) - max(0.0, t[0]) >= MIN_OVERLAP:
                return True
        return False

    wall_rows, seen = [], set()
    for index, wall in enumerate(walls):
        a, b = (wall.a, wall.b) if (wall.a[0], wall.a[1]) <= (wall.b[0], wall.b[1]) else (wall.b, wall.a)
        start, end = _xz(a), _xz(b)
        d = _unit(a, b)
        openings = sorted(({"startMeters": _r(min(s, t), 4), "endMeters": _r(max(s, t), 4)}
                           for s, t in ((_dot(d, _sub(p, a)), _dot(d, _sub(q, a))) for p, q in wall.openings)),
                          key=lambda item: item["startMeters"])
        # Ids come from the drawing and the geometry only, so converting again (by any version) finds a wall there.
        wall_id = "iw-fp-" + _digest(import_id, "wall", start, end, wall.thickness, openings)[:16]
        wall_rows.append({"candidateId": wall_id, "start": start, "end": end, "thicknessMeters": wall.thickness,
                          "lengthMeters": _r(math.dist(a, b), 4), "openings": openings, "from": wall.kind,
                          "flag": wall.flag, "index": index, "layers": sorted(wall.layers),
                          "sources": sorted(wall.sources)[:MAX_SOURCES]})
    wall_rows.sort(key=lambda row: (row["start"]["z"], row["start"]["x"], row["end"]["z"], row["end"]["x"],
                                    row["thicknessMeters"]))
    row_of = {}
    for number, row in enumerate(wall_rows, 1):
        flag = row.pop("flag")
        row_of[row.pop("index")] = row
        row["label"] = f"Drawing wall {number}"
        record = {"wallId": row["candidateId"], "label": row["label"], "start": row["start"], "end": row["end"],
                  "heightMeters": (wall_settings or {}).get("heightMeters"),
                  "thicknessMeters": row["thicknessMeters"], "baseElevation": floor, "color": WALL_COLOR,
                  "openings": row["openings"]}
        row["heightMeters"] = record["heightMeters"]
        row["record"] = record
        wall_id = row["candidateId"]
        if wall_id in walls_by_id:
            kept = walls_by_id[wall_id]
            same = all(kept.get(key) == record[key] for key in ("start", "end", "thicknessMeters", "openings"))
            _state(row, "there" if same else "edited", None if same else "edited")
        elif wall_id in seen:
            _state(row, "refused", "duplicate")
        elif flag:
            _state(row, "refused", flag)
        elif row["lengthMeters"] < MIN_WALL_METERS:
            _state(row, "refused", "too_short")
        elif not MIN_THICKNESS <= row["thicknessMeters"] <= MAX_THICKNESS:
            _state(row, "refused", "thickness")
        elif wall_id in excluded:
            _state(row, "excluded")
        elif wall_there((row["start"]["x"], row["start"]["z"]), (row["end"]["x"], row["end"]["z"]),
                        row["thicknessMeters"], wall_id):
            _state(row, "refused", "wall_there")
        elif wall_settings is None or wall_settings["heightMeters"] is None:
            _state(row, "waiting", "wall_settings")
        else:
            try:
                compile_interior_walls({"version": 1, "walls": [record]}, layout)
                _state(row, "new")
            except ValueError as exc:
                _state(row, "refused", *_compile_problem(exc))
        seen.add(wall_id)

    # Doors in the walls take the state of the wall they open.
    door_rows = []
    for door in gap_doors:
        row = {key: door[key] for key in ("candidateId", "kind", "widthMeters", "at", "layers", "sources")}
        row.update(wall=None, wallLabel=None, outline=None, edge=None)
        if door["kind"] == "unclear":
            _state(row, "refused", "door_ambiguous")
        elif door["candidateId"] in excluded:
            _state(row, "excluded")
        else:
            wall_row = row_of[place[door["gap"][0]]]
            row.update(wall=wall_row["candidateId"], wallLabel=wall_row["label"])
            if wall_row["state"] == "excluded":
                _state(row, "refused", "door_host_left_out")
            else:
                _state(row, wall_row["state"], wall_row["reason"], wall_row["message"])
        door_rows.append(row)

    # Rooms.
    room_settings = settings["rooms"]
    candidates = []
    for ring, entity in loops["room_boundary"]:
        polygon = Polygon(ring)
        if not polygon.is_valid:
            unconverted.add(entity, "crosses_itself")
            continue
        if polygon.area < MIN_ROOM_AREA:
            unconverted.add(entity, "too_small")
            continue
        if len(ring) > MAX_ZONE_VERTICES:
            unconverted.add(entity, "too_many_vertices")
            continue
        boundary, rounded = _rounded_polygon(ring)
        if rounded is None:
            unconverted.add(entity, "crosses_itself")
            continue
        candidates.append((boundary, rounded, entity))
    candidates.sort(key=lambda item: (item[0][0]["z"], item[0][0]["x"], -item[1].area, len(item[0])))
    room_ids = ["zn-fp-" + _digest(import_id, "room", boundary)[:16]
                for boundary, _polygon, _entity in candidates]
    polygons = [polygon for _boundary, polygon, _entity in candidates]
    room_tree = STRtree(polygons) if polygons else None
    text_tree = STRtree([Point(text[0]) for text in texts]) if texts else None
    zone_polygons, zone_ids = [], []
    for zone in existing_zones:
        try:
            shape = Polygon([(float(point["x"]), float(point["z"])) for point in zone["boundary"]])
        except (KeyError, TypeError, ValueError):
            continue
        if shape.is_valid and shape.area > 0:
            zone_polygons.append(shape)
            zone_ids.append(zone.get("zoneId"))
    zone_tree = STRtree(zone_polygons) if zone_polygons else None
    first_of = {}
    for index, room_id in enumerate(room_ids):
        first_of.setdefault(room_id, index)
    room_rows = []
    for index, (boundary, polygon, entity) in enumerate(candidates):
        room_id = room_ids[index]
        inside = [] if text_tree is None else sorted(int(i) for i in text_tree.query(polygon, predicate="contains"))
        named = [(label, texts[i]) for label, i in ((_label(texts[i][1]), i) for i in inside) if label]
        labels = [label for label, _text in named]
        number = len(room_rows) + 1
        # A room named by its one text keeps that text as a source too.
        sources = {str(entity.get("id"))} | ({named[0][1][2]} if len(named) == 1 else set())
        layers = {str(entity.get("layer"))} | ({named[0][1][3]} if len(named) == 1 else set())
        row = {"candidateId": room_id, "boundary": boundary, "areaSquareMeters": _r(polygon.area, 3),
               "label": labels[0] if len(labels) == 1 else f"Drawing room {number}",
               "labelFrom": "text" if len(labels) == 1 else ("several" if labels else "none"),
               "zoneType": None, "layers": sorted(layers), "sources": sorted(sources)}
        kind = (room_settings or {}).get("types", {}).get(room_id) or (room_settings or {}).get("zoneType")
        row["zoneType"] = kind
        row["record"] = {"zoneId": room_id, "zoneType": kind, "label": row["label"], "boundary": boundary,
                         "floorElevation": floor, "anchors": [], "evidence": []}
        holds = [] if room_tree is None else [
            int(j) for j in room_tree.query(polygon, predicate="covers")
            if int(j) != index and room_ids[int(j)] != room_id and room_ids[int(j)] not in excluded]
        same_zone = None
        if zone_tree is not None:
            for j in zone_tree.query(polygon, predicate="intersects"):
                other = zone_polygons[int(j)]
                union = polygon.union(other).area
                if union > 0 and polygon.intersection(other).area / union >= SAME_ZONE_OVERLAP \
                        and zone_ids[int(j)] != room_id:
                    same_zone = zone_ids[int(j)]
                    break
        if room_id in zones_by_id:
            kept = zones_by_id[room_id]
            same = kept.get("boundary") == boundary
            _state(row, "there" if same else "edited", None if same else "edited")
        elif first_of[room_id] != index:
            _state(row, "refused", "duplicate")
        elif room_id in excluded:
            _state(row, "excluded")
        elif holds:
            _state(row, "refused", "holds_rooms")
        elif plan_box is None:
            _state(row, "refused", "plan_size")
        elif not plan_box.buffer(1e-6).covers(polygon):
            _state(row, "refused", "outside_plan")
        elif same_zone is not None:
            _state(row, "refused", "zone_there")
        elif kind is None:
            _state(row, "waiting", "zone_type")
        else:
            _state(row, "new")
        room_rows.append(row)

    # The outline.
    outline_settings = settings["outline"]
    shapes = []
    for ring, entity in loops["perimeter"]:
        polygon = Polygon(ring)
        if not polygon.is_valid:
            unconverted.add(entity, "crosses_itself")
            continue
        if polygon.area < MIN_OUTLINE_AREA:
            unconverted.add(entity, "too_small")
            continue
        shapes.append((_canonical_ring(ring), polygon, entity))
    shapes.sort(key=lambda item: (-item[1].area, item[0][0][1], item[0][0][0]))
    outline_candidates = []
    if len(shapes) >= 2:
        (outer_ring, outer, outer_entity), (_inner_ring, inner, inner_entity) = shapes[0], shapes[1]
        faces = _face_offset(outer, inner)
        if faces is not None:
            middle = outer.buffer(-faces / 2, join_style="mitre")
            if middle.geom_type == "Polygon":
                ring = _canonical_ring([tuple(point) for point in list(middle.exterior.coords)[:-1]])
                outline_candidates.append((ring, "faces", faces, [outer_entity, inner_entity]))
                shapes = shapes[2:]
    for ring, _polygon, entity in shapes:
        outline_candidates.append((ring, "line", None, [entity]))
    current = extensions.get("facilityPerimeterWalls")
    outline_rows = []
    chosen = (outline_settings or {}).get("loop")
    door_height = (settings["doors"] or {}).get("heightMeters")
    free_swings = [k for k in range(len(swings)) if k not in used_swings]
    leafless = set()
    for ring, kind, faces, entities in outline_candidates:
        boundary, rounded = _rounded_polygon(ring)
        outline_id = "ol-fp-" + _digest(import_id, "outline", boundary)[:16]
        width = faces if faces is not None else (outline_settings or {}).get(
            "thicknessMeters", DEFAULT_OUTLINE_THICKNESS)
        row = {"candidateId": outline_id, "boundary": boundary, "thicknessMeters": width, "from": kind,
               "areaSquareMeters": _r(rounded.area, 3) if rounded is not None else None,
               "layers": sorted({str(entity.get("layer")) for entity in entities}),
               "sources": sorted(str(entity.get("id")) for entity in entities), "replaces": None}
        # Doors are looked for on the outline that can become the outer walls (the only one, or the one chosen).
        here = []
        if rounded is not None and (len(outline_candidates) == 1 or chosen == outline_id):
            points = [(point["x"], point["z"]) for point in boundary]
            found, missing = _outline_doors(points, width, swings, door_pieces, free_swings)
            leafless |= missing
            for edge, low, high, door_kind, ks, leaves in found:
                used_swings.update(ks)
                used_pieces.update(leaves)
                a, e = points[edge], _unit(points[edge], points[(edge + 1) % len(points)])
                ends = sorted((_xz(_along(a, e, low)), _xz(_along(a, e, high))), key=lambda p: (p["x"], p["z"]))
                here.append({"candidateId": "dr-fp-" + _digest(import_id, "door", ends)[:16], "kind": door_kind,
                             "widthMeters": _r(high - low, 4), "at": _xz(_along(a, e, (low + high) / 2)),
                             "layers": sorted({swings[k]["layer"] for k in ks} | {door_pieces[i]["layer"]
                                                                                  for i in leaves}),
                             "sources": sorted({swings[k]["entity"] for k in ks} | {door_pieces[i]["entity"]
                                                                                    for i in leaves}),
                             "wall": None, "wallLabel": None, "outline": outline_id, "edge": edge,
                             "opening": {"edge": edge, "startMeters": low, "endMeters": high}})
        kept_doors = [door for door in here if door["candidateId"] not in excluded]
        value = None
        if outline_settings is not None and outline_settings["heightMeters"] is not None:
            openings = [] if door_height is None else sorted(
                (dict(door["opening"], heightMeters=door_height) for door in kept_doors),
                key=lambda item: (item["edge"], item["startMeters"]))
            value = {"boundarySource": "polygon", "boundary": boundary,
                     "heightMeters": outline_settings["heightMeters"], "thicknessMeters": width, "openings": openings}
            settings_now = current.get("settings") if isinstance(current, dict) else None
            if isinstance(settings_now, dict) and "interiorColor" in settings_now:
                value["interiorColor"] = settings_now["interiorColor"]
        row["record"] = value
        if outline_id in excluded:
            _state(row, "excluded")
        elif rounded is None:
            _state(row, "refused", "invalid", "Rounded to the plan's precision, the outline crosses itself.")
        elif len(boundary) > MAX_OUTLINE_VERTICES:
            _state(row, "refused", "too_many_corners")
        elif len(outline_candidates) > 1 and chosen != outline_id:
            _state(row, "waiting" if not chosen else "refused", "choose_outline" if not chosen else "other_outline")
        elif plan_box is None:
            _state(row, "refused", "plan_size")
        elif not plan_box.buffer(1e-3).covers(rounded):
            _state(row, "refused", "outside_plan")
        elif outline_settings is None or outline_settings["heightMeters"] is None:
            _state(row, "waiting", "outline_settings")
        elif kept_doors and door_height is None:
            _state(row, "waiting", "door_settings")
        else:
            _outline_state(row, current, value, outline_settings, layout)
        outline_rows.append(row)
        for door in here:
            door.pop("opening")
            if door["candidateId"] in excluded:
                _state(door, "excluded")
            elif row["state"] == "excluded":
                _state(door, "refused", "door_host_left_out")
            else:
                _state(door, row["state"], row["reason"], row["message"])
            door_rows.append(door)

    # What is left on the door layers stays drawing, with the reason (once per entity and reason).
    listed = set()
    for index, swing in enumerate(swings):
        reason = "door_leaf_missing" if index in leafless else "door_unmatched"
        if index not in used_swings and (swing["entity"], reason) not in listed:
            listed.add((swing["entity"], reason))
            unconverted.add_piece(swing["entity"], swing["layer"], reason)
    kept = {swing["entity"] for swing in swings} | {door_pieces[index]["entity"] for index in used_pieces}
    for entity, _points in door_entities:
        if str(entity.get("id")) not in kept:
            unconverted.add(entity, "door_part")
    door_rows.sort(key=lambda row: (row["at"]["z"], row["at"]["x"], row["candidateId"]))
    for number, row in enumerate(door_rows, 1):
        row["label"] = f"Drawing door {number}"

    # Operations, in a fixed order: the outer walls, then walls, then zones.
    operations = []
    for row in outline_rows:
        if row["state"] == "new":
            operations.append({"op": "set_perimeter_walls", "wallSettings": row["record"]})
    new_walls = [row for row in wall_rows if row["state"] == "new"]
    operations.extend({"op": "upsert_interior_wall", "wall": row["record"]} for row in new_walls)
    operations.extend({"op": "add_zone", "zone": row["record"]} for row in room_rows if row["state"] == "new")
    blocked = None
    if len(existing_walls) + len(new_walls) > MAX_WALLS:
        blocked = {"code": "too_many_walls",
                   "message": f"{len(new_walls)} new walls and the {len(existing_walls)} already on the plan are more "
                              f"than the {MAX_WALLS} a plan holds. Leave some out, or give the wall roles to fewer "
                              f"layers."}
    elif len(operations) > MAX_OPERATIONS:
        blocked = {"code": "too_many_changes",
                   "message": f"{len(operations)} changes are more than one review holds ({MAX_OPERATIONS}). "
                              f"Convert fewer layers at a time."}
    elif not operations:
        blocked = {"code": "nothing_to_add", "message": "Nothing new to add."}

    def counts(rows):
        out = {}
        for row in rows:
            out[row["state"]] = out.get(row["state"], 0) + 1
        return dict(sorted(out.items()))

    def public(rows):
        return [{key: value for key, value in row.items() if key != "record"} for row in rows]

    # Every layer given a role is listed in the review, with the layers that gave or refused something.
    used_layers = {layer for layer, role in roles.items() if role not in ("reference", "ignore")}
    used_layers.update(row["layerId"] for row in unconverted.rows)
    for rows in (wall_rows, room_rows, outline_rows, door_rows):
        for row in rows:
            used_layers.update(row["layers"])
    return {
        "converterVersion": CONVERTER_VERSION,
        "importId": import_id,
        "referenceId": reference["referenceId"],
        "settings": settings,
        "walls": public(wall_rows),
        "rooms": public(room_rows),
        "outlines": public(outline_rows),
        "doors": public(door_rows),
        "unconverted": unconverted.rows,
        "unconvertedCounts": dict(sorted(unconverted.counts.items())),
        "layers": {layer: {"name": names.get(layer), "role": roles.get(layer, "reference")}
                   for layer in sorted(used_layers)},
        "summary": {"walls": counts(wall_rows), "rooms": counts(room_rows), "outlines": counts(outline_rows),
                    "doors": counts(door_rows),
                    "operations": len(operations), "wallsOnPlan": len(existing_walls), "wallLimit": MAX_WALLS,
                    "blocked": blocked},
        "operations": [] if blocked else operations,
    }


def _outline_state(row, current, value, outline_settings, layout):
    from .perimeter_walls import compile_perimeter_walls
    try:
        compiled = compile_perimeter_walls(value, layout)
    except ValueError as exc:
        _state(row, "refused", "invalid", str(exc)[:200])
        return
    if not isinstance(current, dict):
        _state(row, "new")
        return
    if current == compiled:
        _state(row, "there")
        return
    settings_now = current.get("settings") if isinstance(current.get("settings"), dict) else {}
    row["replaces"] = {"boundarySource": settings_now.get("boundarySource"),
                       "openings": len(settings_now.get("openings") or []),
                       "exteriorFinish": "exteriorFinish" in settings_now}
    if outline_settings.get("replace"):
        _state(row, "new")
        return
    lost = []
    if row["replaces"]["openings"]:
        count = row["replaces"]["openings"]
        lost.append(f"its {count} opening{'s' if count != 1 else ''}")
    if row["replaces"]["exteriorFinish"]:
        lost.append("its outside finish")
    _state(row, "waiting", "replace_needed", MESSAGES["replace_needed"]
           + (" Replacing drops " + " and ".join(lost) + "." if lost else ""))


def conversion_id(import_id: str, reference: dict, layout_id: str, base_revision: str, settings: dict) -> str:
    return "fpc-" + _digest(CONVERTER_VERSION, import_id, layout_id, base_revision, reference["alignment"],
                            reference["layers"], settings)[:32]


def origin_for(conversion: str, reference: dict, record: dict, settings: dict) -> dict:
    """What a staged conversion is bound to (operation_proposals): its source, alignment, layer roles, settings and
    converter. A change to any of them is a different proposal."""
    return {"kind": "floor-plan-conversion", "conversionId": conversion, "referenceId": reference["referenceId"],
            "importId": record["importId"], "sourceSha256": record["sourceSha256"],
            "geometrySha256": record["geometrySha256"], "alignmentSha256": _digest(reference["alignment"]),
            "layersSha256": _digest(reference["layers"]), "settingsSha256": _digest(settings),
            "converterVersion": CONVERTER_VERSION}
