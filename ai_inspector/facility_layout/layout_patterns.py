"""The ribbon's pattern and cell math in Python: a port of static/facility_layout_patterns.js.

The ribbon runs these builders in the browser. Sage's planning tools (sage_patterns.py) run the same math on the
server, so a pattern Sage plans lands where the ribbon would put it. Each function follows its JS twin line for
line, in the same order of arithmetic, and tests/test_layout_patterns_parity.py runs both on shared fixtures.

R1 (docs/sage-ribbon-tools-plan.md): the selection, bounds, the linear pattern and the cell layouts. R2: the
mirror, the circular pattern and the rectangular perimeter. R4: the vertical stack and the surface stack (with
locale_key for the JS localeCompare order of ids). Two additions the JS does not have, both off unless
asked:
- build_cell_layout takes an optional `center` (a cell centred in a zone or at a point, not on the selection), and
  each move also carries its path sample (`pathPoint`, `pathTangent`, `pathOffset`) for operator-side facing.
- Errors are PatternError (a ValueError) with the JS message.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal
import functools
import math
from typing import Any, Iterable, Mapping, Sequence

API_VERSION = 1
EPSILON = 1e-9
MAX_PATTERN_COUNT = 50
MAX_PATTERN_OBJECTS = 240
PERIMETER_JOIN_TOLERANCE = 0.001
CELL_SHAPES = ("line", "l", "u", "grid", "parallel", "serpentine", "loop", "spine", "herringbone", "cluster")
CELL_ORIENTATIONS = ("preserve", "follow-path", "face-center", "face-outward")
MISSING = object()  # JS undefined: a missing field takes the fallback, while None (JS null) reads as 0
SIDE_HEADINGS = {"north": 0, "east": 90, "south": 180, "west": 270}


class PatternError(ValueError):
    """A pattern the builders refuse, with the JS builder's reason."""


def clone(value: Any) -> Any:
    return None if value is MISSING else deepcopy(value)


def _get(value: Any, key: str) -> Any:
    return value.get(key, MISSING) if isinstance(value, Mapping) else MISSING


def finite(value: Any, fallback: Any) -> Any:
    """JS finite(): Number(value) when it is finite, else the fallback."""
    if value is MISSING:
        return fallback
    if value is None:
        number = 0.0
    elif isinstance(value, bool):
        number = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            number = 0.0
        else:
            try:
                number = float(text) if "_" not in text else math.nan
            except ValueError:
                return fallback
    else:
        return fallback
    return number if math.isfinite(number) else fallback


def positive(value: Any, fallback: Any, label: str = "value") -> float:
    number = finite(value, fallback)
    if not number > 0:
        raise PatternError(f"{label} must be greater than zero")
    return number


def nonnegative(value: Any, fallback: Any, label: str = "value") -> float:
    number = finite(value, fallback)
    if not number >= 0:
        raise PatternError(f"{label} must not be negative")
    return number


def js_round(value: float) -> int:
    """Math.round: halves go up, toward +infinity."""
    return math.floor(value + 0.5)


def integer(value: Any, fallback: Any, minimum: int, maximum: int, label: str = "value") -> int:
    number = finite(value, fallback)
    number = js_round(number) if math.isfinite(number) else number
    if not (minimum <= number <= maximum):
        raise PatternError(f"{label} must be between {minimum} and {maximum}")
    return int(number)


def clean_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def to_fixed(value: float, digits: int) -> float:
    """Number(value.toFixed(digits)): the exact binary value, halves away from zero."""
    rounded = float(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    return rounded + 0.0


def normalize_degrees(value: Any) -> float:
    result = math.fmod(finite(value, 0), 360)
    if result < 0:
        result += 360
    return to_fixed(result, 6)


def yaw_degrees(quaternion: Any) -> float:
    q = quaternion if isinstance(quaternion, Mapping) else {}
    x, y = finite(_get(q, "x"), 0), finite(_get(q, "y"), 0)
    z, w = finite(_get(q, "z"), 0), finite(_get(q, "w"), 1)
    return normalize_degrees(math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / math.pi)


def rotate_vector(point: Any, angle_degrees: Any) -> dict:
    radians = finite(angle_degrees, 0) * math.pi / 180
    cosine, sine = math.cos(radians), math.sin(radians)
    x, z = finite(_get(point, "x"), 0), finite(_get(point, "z"), 0)
    return {"x": x * cosine + z * sine, "z": -x * sine + z * cosine}


def transform_point(point: Any, origin: Any, target: Any, angle_degrees: Any) -> dict:
    offset = rotate_vector({
        "x": finite(_get(point, "x"), 0) - finite(_get(origin, "x"), 0),
        "z": finite(_get(point, "z"), 0) - finite(_get(origin, "z"), 0),
    }, angle_degrees)
    return {"x": finite(_get(target, "x"), 0) + offset["x"], "z": finite(_get(target, "z"), 0) + offset["z"]}


def point_in_polygon(point: Any, boundary: Any) -> bool:
    if not point or not isinstance(boundary, list) or len(boundary) < 3:
        return False
    x, z = finite(_get(point, "x"), math.nan), finite(_get(point, "z"), math.nan)
    if not (math.isfinite(x) and math.isfinite(z)):
        return False
    inside = False
    previous = len(boundary) - 1
    for index in range(len(boundary)):
        a, b = boundary[index] or {}, boundary[previous] or {}
        ax, az = finite(_get(a, "x"), math.nan), finite(_get(a, "z"), math.nan)
        bx, bz = finite(_get(b, "x"), math.nan), finite(_get(b, "z"), math.nan)
        previous = index
        if not all(math.isfinite(value) for value in (ax, az, bx, bz)):
            continue
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            inside = not inside
    return inside


def bounds_from_points(points: Any) -> dict | None:
    values = points if isinstance(points, list) else []
    if not values:
        return None
    result = {"minX": math.inf, "maxX": -math.inf, "minZ": math.inf, "maxZ": -math.inf}
    for point in values:
        x, z = finite(_get(point, "x"), math.nan), finite(_get(point, "z"), math.nan)
        if not (math.isfinite(x) and math.isfinite(z)):
            continue
        result["minX"], result["maxX"] = min(result["minX"], x), max(result["maxX"], x)
        result["minZ"], result["maxZ"] = min(result["minZ"], z), max(result["maxZ"], z)
    if not math.isfinite(result["minX"]):
        return None
    result["width"] = result["maxX"] - result["minX"]
    result["depth"] = result["maxZ"] - result["minZ"]
    result["center"] = {"x": (result["minX"] + result["maxX"]) / 2, "z": (result["minZ"] + result["maxZ"]) / 2}
    return result


def catalog_record(catalog: Any, placement: Mapping[str, Any]) -> dict | None:
    values = catalog if isinstance(catalog, list) else []
    asset_id, revision = placement.get("assetId"), placement.get("assetDefinitionRevision")
    for record in values:
        if record and record.get("assetId") == asset_id and (
                not revision or not record.get("assetDefinitionRevision")
                or record.get("assetDefinitionRevision") == revision):
            return record
    return next((record for record in values if record and record.get("assetId") == asset_id), None)


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def catalog_dimensions(record: Any, strict: bool = False) -> dict:
    source = _mapping(record)
    dimensions = _mapping(source.get("dimensions"))
    width = finite(_get(source, "width"), finite(_get(dimensions, "width"), math.nan))
    depth = finite(_get(source, "depth"), finite(_get(dimensions, "depth"), math.nan))
    height = finite(_get(source, "height"), finite(_get(dimensions, "height"), math.nan))
    definition = source.get("definition") if isinstance(source.get("definition"), Mapping) else source
    geometry = _mapping(definition.get("geometry"))
    aabb = _mapping(geometry.get("aabb") or geometry.get("axisAlignedBoundingBox"))
    minimum, maximum = _mapping(aabb.get("minimum")), _mapping(aabb.get("maximum"))
    if not width > EPSILON:
        width = finite(_get(maximum, "x"), math.nan) - finite(_get(minimum, "x"), math.nan)
    if not depth > EPSILON:
        depth = finite(_get(maximum, "z"), math.nan) - finite(_get(minimum, "z"), math.nan)
    interval = _mapping(geometry.get("heightInterval"))
    if not height > EPSILON:
        height = finite(_get(interval, "maximumY"), math.nan) - finite(_get(interval, "minimumY"), math.nan)
    if not height > EPSILON:
        height = finite(_get(maximum, "y"), math.nan) - finite(_get(minimum, "y"), math.nan)
    if strict and (not width > EPSILON or not depth > EPSILON or not height > EPSILON
                   or not all(math.isfinite(value) for value in (width, depth, height))):
        raise PatternError("Published asset dimensions are unavailable")
    return {"width": width if width > EPSILON else 1.2, "depth": depth if depth > EPSILON else 0.8,
            "height": height if height > EPSILON else math.nan}


def normalized_item(kind: str, value: Mapping[str, Any], catalog: Any, strict: bool = False) -> dict:
    if kind == "placement":
        record = catalog_record(catalog, value) or {}
        if strict and (not value.get("assetDefinitionRevision")
                       or record.get("assetDefinitionRevision") != value.get("assetDefinitionRevision")):
            raise PatternError("Exact asset revision is unavailable")
        dimensions = catalog_dimensions(record, strict)
        transform = _mapping(value.get("transform"))
        position = _mapping(transform.get("position"))
        scale = max(EPSILON, finite(_get(transform, "scale"), 1))
        definition = _mapping(record.get("definition"))
        return {
            "id": value.get("placementId"), "kind": kind, "assetId": value.get("assetId"),
            "assetDefinitionRevision": value.get("assetDefinitionRevision"),
            "positionMode": value.get("positionMode") or "manual",
            "position": {"x": finite(_get(position, "x"), 0), "y": finite(_get(position, "y"), 0),
                         "z": finite(_get(position, "z"), 0)},
            "rotationDegrees": yaw_degrees(transform.get("quaternion")),
            "width": dimensions["width"] * scale, "depth": dimensions["depth"] * scale,
            "height": dimensions["height"] * scale,
            "snapRelationship": clone(value.get("snapRelationship") or None),
            "supportSurfaces": clone(record.get("supportSurfaces") or definition.get("supportSurfaces") or []),
            "facingSideDegrees": facing_side_degrees(record),
        }
    if kind == "floor-marking":
        transform = _mapping(value.get("transform"))
        position = _mapping(transform.get("position"))
        return {
            "id": value.get("markingId"), "kind": kind, "positionMode": value.get("positionMode") or "manual",
            "position": {"x": finite(_get(position, "x"), 0), "y": finite(_get(position, "y"), 0),
                         "z": finite(_get(position, "z"), 0)},
            "rotationDegrees": normalize_degrees(_get(transform, "rotationDegrees")),
            "width": positive(_get(value, "width"), 1, "floor marking width"),
            "depth": positive(_get(value, "depth"), 1, "floor marking depth"),
        }
    boundary = clone(value.get("boundary") or [])
    bounds = bounds_from_points(boundary)
    if not bounds:
        raise PatternError(f"zone '{value.get('zoneId')}' is invalid")
    return {
        "id": value.get("zoneId"), "kind": "zone", "positionMode": "manual",
        "position": {"x": bounds["center"]["x"], "y": finite(_get(value, "floorElevation"), 0),
                     "z": bounds["center"]["z"]},
        "rotationDegrees": 0, "width": max(EPSILON, bounds["width"]), "depth": max(EPSILON, bounds["depth"]),
        "boundary": boundary,
    }


def item_points(item: Mapping[str, Any]) -> list:
    if item["kind"] == "zone":
        return item["boundary"]
    half_width, half_depth = item["width"] / 2, item["depth"] / 2
    points = []
    for corner in ({"x": -half_width, "z": -half_depth}, {"x": half_width, "z": -half_depth},
                   {"x": half_width, "z": half_depth}, {"x": -half_width, "z": half_depth}):
        rotated = rotate_vector(corner, item["rotationDegrees"])
        points.append({"x": item["position"]["x"] + rotated["x"], "z": item["position"]["z"] + rotated["z"]})
    return points


def selection_bounds(items: Iterable[Mapping[str, Any]]) -> dict:
    points = [point for item in (items or []) for point in item_points(item)]
    result = bounds_from_points(points)
    if not result:
        raise PatternError("pattern seed must contain at least one item")
    return result


def oriented_selection_bounds(items: Sequence[Mapping[str, Any]], angle_degrees: Any) -> dict:
    if not items:
        raise PatternError("pattern seed must contain at least one item")
    axis_x = rotate_vector({"x": 1, "z": 0}, angle_degrees)
    axis_z = rotate_vector({"x": 0, "z": 1}, angle_degrees)
    projected = [{"x": point["x"] * axis_x["x"] + point["z"] * axis_x["z"],
                  "z": point["x"] * axis_z["x"] + point["z"] * axis_z["z"]}
                 for item in items for point in item_points(item)]
    bounds = bounds_from_points(projected)
    if not bounds:
        raise PatternError("pattern seed has no measurable footprint")
    return {
        "center": {"x": axis_x["x"] * bounds["center"]["x"] + axis_z["x"] * bounds["center"]["z"],
                   "z": axis_x["z"] * bounds["center"]["x"] + axis_z["z"] * bounds["center"]["z"]},
        "width": max(EPSILON, bounds["width"]), "depth": max(EPSILON, bounds["depth"]),
        "axisX": axis_x, "axisZ": axis_z,
    }


def collect_selection(layout: Any, catalog: Any, selected_ids: Any, options: Mapping[str, Any] | None = None) -> list:
    source = layout if isinstance(layout, Mapping) else {}
    selection = selected_ids if isinstance(selected_ids, list) else []
    settings = options or {}
    placements = {item.get("placementId"): item for item in source.get("placements") or []}
    markings = {item.get("markingId"): item for item in source.get("floorMarkings") or []}
    zones = {item.get("zoneId"): item for item in source.get("zones") or []}
    identifiers: list = []
    seen: set = set()

    def add(identifier):
        if not identifier or identifier in seen:
            return
        seen.add(identifier)
        identifiers.append(identifier)

    for identifier in selection:
        add(clean_id(identifier))
    if settings.get("expandZones") is not False:
        for identifier in selection:
            zone = zones.get(identifier) if isinstance(identifier, str) else None
            if not zone or not isinstance(zone.get("boundary"), list):
                continue
            for placement in placements.values():
                if point_in_polygon(_mapping(placement.get("transform")).get("position"), zone["boundary"]):
                    add(placement.get("placementId"))
            for marking in markings.values():
                if point_in_polygon(_mapping(marking.get("transform")).get("position"), zone["boundary"]):
                    add(marking.get("markingId"))
    result = []
    for identifier in identifiers:
        if identifier in placements:
            result.append(normalized_item("placement", placements[identifier], catalog,
                                          settings.get("strictGeometry") is True))
        elif identifier in markings:
            result.append(normalized_item("floor-marking", markings[identifier], catalog))
        elif identifier in zones and settings.get("includeZones") is not False:
            result.append(normalized_item("zone", zones[identifier], catalog))
    return result


def transformed_copy(item: Mapping[str, Any], source_anchor: Mapping, target_anchor: Mapping,
                     angle_degrees: float, index: int) -> dict:
    position = transform_point(item["position"], source_anchor, target_anchor, angle_degrees)
    copy = {
        "sourceId": item["id"], "kind": item["kind"], "instanceIndex": index,
        "position": {"x": position["x"], "y": item["position"]["y"], "z": position["z"]},
        "rotationDegrees": normalize_degrees(item["rotationDegrees"] + angle_degrees),
        "rotationDeltaDegrees": normalize_degrees(angle_degrees),
        "sourceAnchor": clone(source_anchor), "targetAnchor": clone(target_anchor),
    }
    if item.get("boundary") is not None:
        copy["boundary"] = [transform_point(point, source_anchor, target_anchor, angle_degrees)
                            for point in item["boundary"]]
    return copy


def assert_pattern_capacity(seed_count: int, instance_count: int) -> None:
    if seed_count * max(0, instance_count - 1) > MAX_PATTERN_OBJECTS:
        raise PatternError(f"pattern would create more than {MAX_PATTERN_OBJECTS} layout objects")


def build_linear_pattern(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = list(items) if isinstance(items, (list, tuple)) else []
    settings = options or {}
    count = integer(_get(settings, "count"), 3, 2, MAX_PATTERN_COUNT, "pattern count")
    pitch = positive(_get(settings, "pitch"), 3, "pattern pitch")
    assert_pattern_capacity(len(seed), count)
    bounds = selection_bounds(seed)
    angle = finite(_get(settings, "angleDegrees"), 0)
    direction = rotate_vector({"x": 1, "z": 0}, angle)
    copies = []
    for instance in range(1, count):
        target = {"x": bounds["center"]["x"] + direction["x"] * pitch * instance,
                  "z": bounds["center"]["z"] + direction["z"] * pitch * instance}
        for item in seed:
            copies.append(transformed_copy(item, bounds["center"], target, 0, instance))
    return {
        "mode": "linear", "seedCount": len(seed), "count": count, "copies": copies, "moves": [],
        "guide": {
            "kind": "linear", "start": clone(bounds["center"]),
            "end": {"x": bounds["center"]["x"] + direction["x"] * pitch * (count - 1),
                    "z": bounds["center"]["z"] + direction["z"] * pitch * (count - 1)},
            "pitch": pitch,
        },
    }


def normalized_mirror_axis(start: Any, end: Any) -> dict:
    axis_start = {"x": finite(_get(start, "x"), math.nan), "z": finite(_get(start, "z"), math.nan)}
    axis_end = {"x": finite(_get(end, "x"), math.nan), "z": finite(_get(end, "z"), math.nan)}
    if not all(math.isfinite(value) for value in (axis_start["x"], axis_start["z"], axis_end["x"], axis_end["z"])):
        raise PatternError("mirror axis requires two finite floor points")
    dx, dz = axis_end["x"] - axis_start["x"], axis_end["z"] - axis_start["z"]
    length = math.hypot(dx, dz)
    if not length > EPSILON:
        raise PatternError("mirror axis points must be different")
    return {"start": axis_start, "end": axis_end, "unit": {"x": dx / length, "z": dz / length}}


def mirror_vector(vector: Any, start: Any, end: Any) -> dict:
    axis = normalized_mirror_axis(start, end)
    x, z = finite(_get(vector, "x"), 0), finite(_get(vector, "z"), 0)
    projection = x * axis["unit"]["x"] + z * axis["unit"]["z"]
    return {"x": 2 * projection * axis["unit"]["x"] - x, "z": 2 * projection * axis["unit"]["z"] - z}


def mirror_point(point: Any, start: Any, end: Any) -> dict:
    axis = normalized_mirror_axis(start, end)
    offset = {"x": finite(_get(point, "x"), 0) - axis["start"]["x"],
              "z": finite(_get(point, "z"), 0) - axis["start"]["z"]}
    projection = offset["x"] * axis["unit"]["x"] + offset["z"] * axis["unit"]["z"]
    return {"x": axis["start"]["x"] + 2 * projection * axis["unit"]["x"] - offset["x"],
            "z": axis["start"]["z"] + 2 * projection * axis["unit"]["z"] - offset["z"]}


def mirror_rotation_degrees(rotation_degrees: Any, start: Any, end: Any, side_degrees: Any = MISSING) -> float:
    """The turn of a mirrored copy. A turn cannot mirror the model itself, so one of its sides is kept as the mirror
    image of the original's and the others follow: side_degrees, a heading in the model's own axes (north 0, east
    90; its east side when not given)."""
    side = finite(side_degrees, 90)
    facing = rotate_vector({"x": 0, "z": 1}, finite(rotation_degrees, 0) + side)
    reflected = mirror_vector(facing, start, end)
    return normalize_degrees(math.atan2(reflected["x"], reflected["z"]) * 180 / math.pi - side)


def facing_side_degrees(record: Any) -> int | None:
    """The side a model works from, as a heading in its own axes: its reviewed operator side, else its reviewed
    front, else None. The catalog holds the reviewed sides in the layout's model space (facilitySemantics
    .functionalSides); the workspace keeps the catalog record as source."""
    value = record if isinstance(record, Mapping) else {}
    source = value.get("source")
    semantics = (value.get("facilitySemantics")
                 or (source.get("facilitySemantics") if isinstance(source, Mapping) else None) or {})
    sides = (semantics.get("functionalSides") if isinstance(semantics, Mapping) else None) or {}
    for role in ("operator", "front"):
        entry = sides.get(role) if isinstance(sides, Mapping) else None
        side = entry.get("side") if isinstance(entry, Mapping) else entry
        if isinstance(side, str) and side in SIDE_HEADINGS:
            return SIDE_HEADINGS[side]
    return None


def mirror_side_degrees(item: Any) -> float:
    """The side a mirrored copy keeps as the mirror image of its original's: a placement's operator side, else its
    front, else its north side (+Z, the front of a model file); a marking or a zone, its east side, as before."""
    if not isinstance(item, Mapping) or item.get("kind") != "placement":
        return 90
    side = item.get("facingSideDegrees")
    finite_side = isinstance(side, (int, float)) and not isinstance(side, bool) and math.isfinite(side)
    return side if finite_side else 0


def cell_facing_side_degrees(item: Any) -> float:
    """The side a cell turns toward its centre (face-center) or away from it (face-outward): a placement's operator
    side, else its front, else its north side (+Z, the front of a model file); a marking, its north side, as
    before."""
    if not isinstance(item, Mapping) or item.get("kind") != "placement":
        return 0
    side = item.get("facingSideDegrees")
    finite_side = isinstance(side, (int, float)) and not isinstance(side, bool) and math.isfinite(side)
    return side if finite_side else 0


def build_circular_pattern(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = list(items) if isinstance(items, (list, tuple)) else []
    settings = options or {}
    count = integer(_get(settings, "count"), 4, 2, MAX_PATTERN_COUNT, "pattern count")
    sweep = positive(_get(settings, "sweepDegrees"), 360, "total angle")
    if sweep > 360 + EPSILON:
        raise PatternError("total angle must not exceed 360 degrees")
    assert_pattern_capacity(len(seed), count)
    bounds = selection_bounds(seed)
    center = {
        "x": finite(_get(settings, "centerX"),
                    bounds["center"]["x"] - max(bounds["width"], bounds["depth"], 1) * 1.5),
        "z": finite(_get(settings, "centerZ"), bounds["center"]["z"]),
    }
    full_circle = abs(sweep - 360) <= EPSILON
    step = sweep / (count if full_circle else count - 1)
    turn = _get(settings, "rotateWithPattern") is True
    copies = []
    for instance in range(1, count):
        angle = step * instance
        target = transform_point(bounds["center"], center, center, angle)
        for item in seed:
            copies.append(transformed_copy(item, bounds["center"], target, angle if turn else 0, instance))
    return {
        "mode": "circular", "seedCount": len(seed), "count": count, "copies": copies, "moves": [],
        "guide": {
            "kind": "circular", "center": center,
            "radius": math.hypot(bounds["center"]["x"] - center["x"], bounds["center"]["z"] - center["z"]),
            "sweepDegrees": sweep, "stepDegrees": step,
        },
    }


def build_rectangular_perimeter(items: Sequence[Mapping[str, Any]],
                                options: Mapping[str, Any] | None = None) -> dict:
    seed = list(items) if isinstance(items, (list, tuple)) else []
    if not seed:
        raise PatternError("perimeter seed must contain at least one item")
    settings = options or {}
    square = _get(settings, "shape") == "square"
    width_count = integer(_get(settings, "widthCount"), 6, 1, MAX_PATTERN_COUNT, "width-side count")
    depth_count = width_count if square else integer(_get(settings, "depthCount"), 4, 1, MAX_PATTERN_COUNT,
                                                     "depth-side count")
    clear_gap = nonnegative(_get(settings, "clearGap"), 0, "perimeter clear gap")
    effective_gap = clear_gap if clear_gap > 0 else PERIMETER_JOIN_TOLERANCE
    angle = finite(_get(settings, "angleDegrees"), 0)
    effective_angle = angle
    oriented = oriented_selection_bounds(seed, effective_angle)
    if oriented["depth"] > oriented["width"] + EPSILON:
        effective_angle += 90
        oriented = oriented_selection_bounds(seed, effective_angle)
    span, thickness = oriented["width"], oriented["depth"]
    width_pitch = span + effective_gap
    depth_pitch = span + effective_gap
    width = width_count * span + max(0, width_count - 1) * effective_gap
    depth = depth_count * span + max(0, depth_count - 1) * effective_gap
    instance_count = 2 * (width_count + depth_count)
    assert_pattern_capacity(len(seed), instance_count)

    def translated(point, along_x, along_z):
        return {"x": point["x"] + oriented["axisX"]["x"] * along_x + oriented["axisZ"]["x"] * along_z,
                "z": point["z"] + oriented["axisX"]["z"] * along_x + oriented["axisZ"]["z"] * along_z}

    anchor = oriented["center"]
    left_endpoint = translated(anchor, -span / 2, 0)
    right_endpoint = translated(left_endpoint, width, 0)
    targets = []
    instance_index = 0
    for index in range(width_count):
        targets.append({"anchor": translated(anchor, width_pitch * index, 0), "rotationDeltaDegrees": 0,
                        "instanceIndex": instance_index, "side": "south", "original": index == 0})
        instance_index += 1
    for index in range(depth_count):
        targets.append({"anchor": translated(right_endpoint, thickness / 2 + effective_gap,
                                             span / 2 + depth_pitch * index),
                        "rotationDeltaDegrees": -90, "instanceIndex": instance_index, "side": "east"})
        instance_index += 1
    for index in range(width_count):
        targets.append({"anchor": translated(right_endpoint, -span / 2 - width_pitch * index,
                                             depth + thickness / 2 + effective_gap),
                        "rotationDeltaDegrees": 180, "instanceIndex": instance_index, "side": "north"})
        instance_index += 1
    for index in range(depth_count):
        targets.append({"anchor": translated(left_endpoint, -thickness / 2 - effective_gap,
                                             depth - span / 2 - depth_pitch * index),
                        "rotationDeltaDegrees": 90, "instanceIndex": instance_index, "side": "west"})
        instance_index += 1
    copies = []
    for target in targets:
        if target.get("original") is True:
            continue
        for item in seed:
            copy = transformed_copy(item, anchor, target["anchor"], target["rotationDeltaDegrees"],
                                    target["instanceIndex"])
            copy["perimeterSide"] = target["side"]
            copies.append(copy)
    return {
        "mode": "perimeter", "shape": "square" if square else "rectangle", "seedCount": len(seed),
        "count": instance_count, "copies": copies, "moves": [],
        "guide": {
            "kind": "perimeter",
            "points": [clone(left_endpoint), clone(right_endpoint), translated(right_endpoint, 0, depth),
                       translated(left_endpoint, 0, depth)],
            "width": width, "depth": depth, "widthCount": width_count, "depthCount": depth_count,
            "clearGap": clear_gap, "effectiveClearGap": effective_gap, "angleDegrees": effective_angle,
            "requestedAngleDegrees": angle,
        },
    }


def build_mirror(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = list(items) if isinstance(items, (list, tuple)) else []
    if not seed:
        raise PatternError("mirror seed must contain at least one item")
    assert_pattern_capacity(len(seed), 2)
    settings = options or {}
    axis = normalized_mirror_axis(_get(settings, "axisStart"), _get(settings, "axisEnd"))
    copies = []
    for item in seed:
        position = mirror_point(item["position"], axis["start"], axis["end"])
        rotation = mirror_rotation_degrees(item["rotationDegrees"], axis["start"], axis["end"],
                                           mirror_side_degrees(item))
        copy = {
            "sourceId": item["id"], "kind": item["kind"], "instanceIndex": 1,
            "position": {"x": position["x"], "y": item["position"]["y"], "z": position["z"]},
            "rotationDegrees": rotation,
            "rotationDeltaDegrees": normalize_degrees(rotation - item["rotationDegrees"]),
            "mirrored": True, "mirrorAxis": {"start": clone(axis["start"]), "end": clone(axis["end"])},
        }
        if item.get("boundary") is not None:
            copy["boundary"] = [mirror_point(point, axis["start"], axis["end"]) for point in item["boundary"]][::-1]
        copies.append(copy)
    return {
        "mode": "mirror", "seedCount": len(seed), "count": 2, "copies": copies, "moves": [],
        "guide": {"kind": "mirror", "start": clone(axis["start"]), "end": clone(axis["end"])},
    }


PUNCTUATION = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"  # ICU root order of the ASCII punctuation and symbols


def locale_key(text: Any) -> tuple:
    """String.prototype.localeCompare's order (ICU root) for ASCII ids: punctuation and symbols, then digits, then
    letters ignoring case; then lower case before upper. Other characters sort by code point after them."""
    primary, tertiary = [], []
    for character in str(text):
        if character in PUNCTUATION:
            primary.append((0, PUNCTUATION.index(character)))
        elif character.isdigit() and character.isascii():
            primary.append((1, ord(character)))
        elif character.isalpha() and character.isascii():
            primary.append((2, ord(character.lower())))
        else:
            primary.append((3, ord(character)))
        tertiary.append(1 if character.isupper() else 0)
    return tuple(primary), tuple(tertiary)


def _js_fixed6(value: float) -> str:
    """value.toFixed(6) for a value that is not negative."""
    return format(Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def build_vertical_stack(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = list(items) if isinstance(items, (list, tuple)) else []
    if len(seed) != 1 or seed[0]["kind"] != "placement":
        raise PatternError("vertical stack requires exactly one equipment placement")
    source = seed[0]
    relation = source.get("snapRelationship")
    if relation and relation.get("family") == "vertical_stack":
        raise PatternError("selected equipment is already part of a stack")
    settings = options or {}
    count = integer(_get(settings, "count"), 3, 2, MAX_PATTERN_COUNT, "stack count")
    gap = max(0, finite(_get(settings, "gap"), 0))
    item_height = positive(source.get("height"), math.nan, "verified equipment height")
    assert_pattern_capacity(1, count)
    stack_id = str(settings.get("stackId") or f"stack:{source['id']}:{count}:{_js_fixed6(gap)}")

    def relationship(level):
        return {"family": "vertical_stack", "stackId": stack_id, "level": level, "count": count, "gapMeters": gap,
                "itemHeightMeters": item_height, "evidenceStatus": "unverified"}

    copies = []
    for level in range(1, count):
        point = {"x": source["position"]["x"], "z": source["position"]["z"]}
        copy = transformed_copy(source, point, dict(point), 0, level)
        copy["position"]["y"] = source["position"]["y"] + level * (item_height + gap)
        copy["snapRelationship"] = relationship(level)
        copies.append(copy)
    return {
        "mode": "vertical-stack", "seedCount": 1, "count": count, "copies": copies, "moves": [],
        "relationships": [{"sourceId": source["id"], "kind": "placement", "snapRelationship": relationship(0)}],
        "guide": {"kind": "vertical-stack", "position": clone(source["position"]), "count": count,
                  "itemHeightMeters": item_height, "gapMeters": gap,
                  "totalHeightMeters": item_height * count + gap * (count - 1)},
    }


def _or_object(*values: Any) -> Mapping:
    """JS `a && a.b || {}`: the first truthy value, or an empty object."""
    return next((value for value in values if value), {})


def build_surface_stack(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = [item for item in (items if isinstance(items, (list, tuple)) else []) if item
            and item.get("kind") == "placement"]
    if len(seed) < 2:
        raise PatternError("surface stack requires one support and at least one child placement")
    settings = options or {}
    requested = clean_id(settings.get("supportPlacementId"))
    if requested:
        support = next((item for item in seed if item["id"] == requested), None)
    else:
        def by_area(left, right):
            delta = right["width"] * right["depth"] - left["width"] * left["depth"]
            if abs(delta) > EPSILON:
                return -1 if delta < 0 else 1
            a, b = locale_key(left["id"]), locale_key(right["id"])
            return (a > b) - (a < b)
        support = sorted(seed, key=functools.cmp_to_key(by_area))[0]
    if not support:
        raise PatternError("selected surface support is unavailable")
    if support.get("positionMode") == "locked":
        raise PatternError("locked equipment cannot become a surface stack support")
    children = sorted((item for item in seed if item["id"] != support["id"]), key=lambda item: locale_key(item["id"]))
    if any(item.get("positionMode") == "locked" for item in children):
        raise PatternError("locked equipment cannot be moved onto a support surface")
    if any((item.get("snapRelationship") or {}).get("family") == "vertical_stack" for item in children):
        raise PatternError("vertical stack members cannot be surface-attached")
    side = "below" if settings.get("side") == "below" else "above"
    gap = nonnegative(_get(settings, "gap"), 0, "surface gap")
    item_gap = nonnegative(_get(settings, "itemGap"), 0.05, "item gap")
    inset = nonnegative(_get(settings, "inset"), 0.05, "surface inset")
    explicit = next((surface for surface in support.get("supportSurfaces") or []
                     if surface and surface.get("surfaceId", MISSING) == settings.get("surfaceId", MISSING)), None)
    if explicit and isinstance(explicit.get("allowedSides"), list) and side not in explicit["allowedSides"]:
        raise PatternError(f"support surface does not allow placement on its '{side}' side")
    frame = explicit.get("localFrame") if explicit else None
    surface_bounds = _or_object(explicit and explicit.get("bounds"))
    origin = _or_object(frame and frame.get("origin"))
    x_axis = (frame and frame.get("xAxis")) or {"x": 1, "y": 0, "z": 0}
    z_axis = (frame and frame.get("zAxis")) or {"x": 0, "y": 0, "z": 1}
    normal = (frame and frame.get("normal")) or {"x": 0, "y": 1, "z": 0}
    if explicit:
        nan = math.nan
        x_length = math.hypot(finite(_get(x_axis, "x"), nan), finite(_get(x_axis, "y"), nan),
                              finite(_get(x_axis, "z"), nan))
        z_length = math.hypot(finite(_get(z_axis, "x"), nan), finite(_get(z_axis, "y"), nan),
                              finite(_get(z_axis, "z"), nan))
        dot = (finite(_get(x_axis, "x"), nan) * finite(_get(z_axis, "x"), nan)
               + finite(_get(x_axis, "z"), nan) * finite(_get(z_axis, "z"), nan))
        upward = (finite(_get(z_axis, "z"), nan) * finite(_get(x_axis, "x"), nan)
                  - finite(_get(z_axis, "x"), nan) * finite(_get(x_axis, "z"), nan))
        if (abs(finite(_get(x_axis, "y"), nan)) > EPSILON or abs(finite(_get(z_axis, "y"), nan)) > EPSILON
                or abs(finite(_get(normal, "x"), nan)) > EPSILON or abs(finite(_get(normal, "z"), nan)) > EPSILON
                or finite(_get(normal, "y"), nan) < 1 - EPSILON or abs(x_length - 1) > EPSILON
                or abs(z_length - 1) > EPSILON or abs(dot) > EPSILON or upward < 1 - EPSILON):
            raise PatternError("support surface requires a horizontal orthonormal local frame")
    minimum_x = finite(_get(surface_bounds, "minimumX"), -support["width"] / 2)
    maximum_x = finite(_get(surface_bounds, "maximumX"), support["width"] / 2)
    minimum_z = finite(_get(surface_bounds, "minimumZ"), -support["depth"] / 2)
    maximum_z = finite(_get(surface_bounds, "maximumZ"), support["depth"] / 2)
    available_width = maximum_x - minimum_x - inset * 2
    available_depth = maximum_z - minimum_z - inset * 2
    if not available_width > EPSILON or not available_depth > EPSILON:
        raise PatternError("support surface is too small after edge inset")
    surface_id = (clean_id(settings.get("surfaceId")) or (explicit and clean_id(explicit.get("surfaceId")))
                  or "derived-top")
    surface_source = "asset_definition" if explicit else "derived_aabb"
    evidence = (explicit and clean_id(explicit.get("evidenceStatus"))) or "unverified"
    attachment_id = clean_id(settings.get("attachmentId")) or f"surface:{support['id']}:{surface_id}:{side}"
    cursor_x, cursor_z, row_depth = minimum_x + inset, minimum_z + inset, 0
    positions = []
    for child in children:
        width = positive(child.get("width"), math.nan, "child width")
        depth = positive(child.get("depth"), math.nan, "child depth")
        height = positive(child.get("height"), math.nan, "child height")
        if width > available_width + EPSILON or depth > available_depth + EPSILON:
            raise PatternError(f"'{child['id']}' does not fit on the selected support surface")
        if cursor_x + width > maximum_x - inset + EPSILON:
            cursor_x = minimum_x + inset
            cursor_z += row_depth + item_gap
            row_depth = 0
        if cursor_z + depth > maximum_z - inset + EPSILON:
            raise PatternError("selected items do not fit on the support surface; reduce the selection or spacing")
        local = {"x": cursor_x + width / 2, "z": cursor_z + depth / 2}
        positions.append({"child": child, "height": height, "local": {
            "x": finite(_get(origin, "x"), 0) + finite(_get(x_axis, "x"), 1) * local["x"]
            + finite(_get(z_axis, "x"), 0) * local["z"],
            "z": finite(_get(origin, "z"), 0) + finite(_get(x_axis, "z"), 0) * local["x"]
            + finite(_get(z_axis, "z"), 1) * local["z"]}})
        cursor_x += width + item_gap
        row_depth = max(row_depth, depth)
    elevation = (finite(_get(origin, "y"), support["height"]) if explicit
                 else positive(support["height"], math.nan, "support height"))
    plane = support["position"]["y"] + elevation
    turn = (normalize_degrees(math.atan2(-finite(_get(x_axis, "z"), 0), finite(_get(x_axis, "x"), 1)) * 180 / math.pi)
            if explicit else 0)
    moves, relationships = [], []
    for entry in positions:
        rotated = rotate_vector(entry["local"], support["rotationDegrees"])
        child_y = plane + gap if side == "above" else plane - gap - entry["height"]
        moves.append({"sourceId": entry["child"]["id"], "kind": "placement",
                      "position": {"x": support["position"]["x"] + rotated["x"], "y": child_y,
                                   "z": support["position"]["z"] + rotated["z"]},
                      "rotationDegrees": normalize_degrees(support["rotationDegrees"] + turn)})
        relationships.append({"sourceId": entry["child"]["id"], "kind": "placement", "snapRelationship": {
            "family": "surface_attachment", "attachmentId": attachment_id, "supportPlacementId": support["id"],
            "surfaceId": surface_id, "side": side, "localPosition": clone(entry["local"]),
            "localRotationDegrees": turn, "normalOffsetMeters": gap, "surfaceSource": surface_source,
            "evidenceStatus": evidence}})
    return {
        "mode": "surface-stack", "seedCount": len(seed), "count": len(children), "copies": [], "moves": moves,
        "relationships": relationships,
        "guide": {"kind": "surface-stack", "supportPlacementId": support["id"], "attachmentId": attachment_id,
                  "side": side, "surfaceId": surface_id, "itemCount": len(children),
                  "supportPosition": clone(support["position"]), "supportWidth": support["width"],
                  "supportDepth": support["depth"]},
    }


def path_length(points: Sequence[Mapping], closed: bool) -> float:
    total = 0.0
    for index in range(1, len(points)):
        total += math.hypot(points[index]["x"] - points[index - 1]["x"], points[index]["z"] - points[index - 1]["z"])
    if closed and len(points) > 1:
        total += math.hypot(points[0]["x"] - points[-1]["x"], points[0]["z"] - points[-1]["z"])
    return total


def point_at_path_distance(points: Sequence[Mapping], closed: bool, requested_distance: float) -> dict:
    segments = [(points[index - 1], points[index]) for index in range(1, len(points))]
    if closed and len(points) > 1:
        segments.append((points[-1], points[0]))
    remaining = max(0, requested_distance)
    for index, (start, end) in enumerate(segments):
        length = math.hypot(end["x"] - start["x"], end["z"] - start["z"])
        if remaining <= length or index == len(segments) - 1:
            ratio = min(1, remaining / length) if length > EPSILON else 0
            return {"point": {"x": start["x"] + (end["x"] - start["x"]) * ratio,
                              "z": start["z"] + (end["z"] - start["z"]) * ratio},
                    "tangent": {"x": end["x"] - start["x"], "z": end["z"] - start["z"]}}
        remaining -= length
    return {"point": clone(points[0] if points else {"x": 0, "z": 0}), "tangent": {"x": 1, "z": 0}}


def path_samples(points: Sequence[Mapping], count: int, closed: bool) -> list:
    if count == 1:
        return [{"point": clone(points[0] if points else {"x": 0, "z": 0}),
                 "tangent": ({"x": points[1]["x"] - points[0]["x"], "z": points[1]["z"] - points[0]["z"]}
                             if len(points) > 1 else {"x": 1, "z": 0})}]
    total = path_length(points, closed)
    divisor = count if closed else count - 1
    return [point_at_path_distance(points, closed, total * index / divisor) for index in range(count)]


def cell_path(shape: str, count: int, width: float, depth: float, rows: int) -> dict:
    half_width, half_depth = width / 2, depth / 2
    if shape in ("line", "herringbone"):
        return {"points": [{"x": -half_width, "z": 0}, {"x": half_width, "z": 0}], "closed": False}
    if shape == "l":
        return {"points": [{"x": -half_width, "z": -half_depth}, {"x": -half_width, "z": half_depth},
                           {"x": half_width, "z": half_depth}], "closed": False}
    if shape in ("u", "loop"):
        return {"points": [{"x": -half_width, "z": -half_depth}, {"x": -half_width, "z": half_depth},
                           {"x": half_width, "z": half_depth}, {"x": half_width, "z": -half_depth}],
                "closed": shape == "loop"}
    if shape == "cluster":
        sides = max(3, count)
        points = []
        for index in range(sides):
            angle = index * math.pi * 2 / sides
            points.append({"x": math.cos(angle) * half_width, "z": math.sin(angle) * half_depth})
        return {"points": points, "closed": True}
    if shape == "spine":
        points = []
        for index in range(count):
            ratio = index / (count - 1) if count > 1 else 0.5
            points.append({"x": -half_width + width * ratio, "z": half_depth if index % 2 else -half_depth})
        return {"direct": points}
    row_count = max(2, min(count, rows))
    column_count = math.ceil(count / row_count)
    points = []
    for row in range(row_count):
        z = half_depth - depth * row / (row_count - 1) if row_count > 1 else 0
        for column in range(column_count):
            logical_column = column_count - 1 - column if shape == "serpentine" and row % 2 else column
            x = -half_width + width * logical_column / (column_count - 1) if column_count > 1 else 0
            points.append({"x": x, "z": z})
            if len(points) == count:
                break
        if len(points) == count:
            break
    return {"direct": points}


def tangent_heading(tangent: Any) -> float:
    return normalize_degrees(math.atan2(finite(_get(tangent, "x"), 0), finite(_get(tangent, "z"), 1)) * 180 / math.pi)


def build_cell_layout(items: Sequence[Mapping[str, Any]], options: Mapping[str, Any] | None = None) -> dict:
    seed = [item for item in (items if isinstance(items, (list, tuple)) else []) if item["kind"] != "zone"]
    if len(seed) < 2:
        raise PatternError("select at least two cell items to arrange")
    locked = next((item for item in seed if item.get("positionMode") == "locked"), None)
    if locked:
        raise PatternError(f"unlock '{locked['id']}' before arranging the cell")
    settings = options or {}
    shape = settings.get("shape") if settings.get("shape") in CELL_SHAPES else "u"
    bounds = selection_bounds(seed)
    max_width = max(item["width"] for item in seed)
    max_depth = max(item["depth"] for item in seed)
    max_footprint_radius = max(math.hypot(item["width"], item["depth"]) / 2 for item in seed)
    gap = max(0, finite(_get(settings, "gap"), 1))
    pitch = max(max_width, max_depth) + gap
    width = positive(_get(settings, "width"), max(bounds["width"], pitch * max(2, math.ceil(len(seed) / 2))),
                     "cell width")
    depth = positive(_get(settings, "depth"), max(bounds["depth"], pitch * 2), "cell depth")
    rows = integer(_get(settings, "rows"),
                   2 if shape == "parallel" else max(2, js_round(math.sqrt(len(seed)))),
                   1, max(1, len(seed)), "row count")
    boundary_inset = max_footprint_radius + gap / 2
    usable_width = width - boundary_inset * 2
    usable_depth = depth - boundary_inset * 2
    if not usable_width > EPSILON or not usable_depth > EPSILON:
        raise PatternError("cell width and depth must contain the selected equipment footprints and preferred "
                           "clear gap")
    path = cell_path(shape, len(seed), usable_width, usable_depth, rows)
    if "direct" in path:
        direct = path["direct"]
        samples = []
        for index, point in enumerate(direct):
            previous = direct[max(0, index - 1)]
            following = direct[min(len(direct) - 1, index + 1)]
            samples.append({"point": point, "tangent": {"x": following["x"] - previous["x"],
                                                        "z": following["z"] - previous["z"]}})
    else:
        samples = path_samples(path["points"], len(seed), path["closed"])
    inverted = shape == "u" and settings.get("invertU") is True
    if inverted:
        samples = [{"point": {"x": sample["point"]["x"], "z": -sample["point"]["z"]},
                    "tangent": {"x": sample["tangent"]["x"], "z": -sample["tangent"]["z"]}} for sample in samples]
    layout_angle = finite(_get(settings, "angleDegrees"), 0)
    orientation = settings.get("orientation") if settings.get("orientation") in CELL_ORIENTATIONS else "preserve"
    center = settings.get("center") if isinstance(settings.get("center"), Mapping) else bounds["center"]
    moves = []
    for index, item in enumerate(seed):
        sample = samples[index]
        offset = rotate_vector(sample["point"], layout_angle)
        rotation = item["rotationDegrees"]
        if orientation == "follow-path":
            rotation = tangent_heading(rotate_vector(sample["tangent"], layout_angle))
        elif orientation in ("face-center", "face-outward"):
            rotation = tangent_heading({"x": -offset["x"], "z": -offset["z"]}) - cell_facing_side_degrees(item)
            if orientation == "face-outward":
                rotation += 180
        if shape == "herringbone":
            rotation = normalize_degrees(layout_angle + (-35 if index % 2 else 35))
        moves.append({
            "sourceId": item["id"], "kind": item["kind"],
            "position": {"x": center["x"] + offset["x"], "y": item["position"]["y"], "z": center["z"] + offset["z"]},
            "rotationDegrees": normalize_degrees(rotation),
            # Not in the JS: the path sample, for operator-side facing (sage_patterns.py).
            "pathPoint": clone(sample["point"]), "pathTangent": rotate_vector(sample["tangent"], layout_angle),
            "pathOffset": offset,
        })
    return {
        "mode": "cell-layout", "shape": shape, "inverted": inverted, "seedCount": len(seed), "count": len(seed),
        "copies": [], "moves": moves,
        "guide": {
            "kind": "cell-layout", "shape": shape, "center": clone(center), "width": width, "depth": depth,
            "boundaryInset": boundary_inset, "usableWidth": usable_width, "usableDepth": usable_depth,
            "angleDegrees": layout_angle, "inverted": inverted,
        },
    }
