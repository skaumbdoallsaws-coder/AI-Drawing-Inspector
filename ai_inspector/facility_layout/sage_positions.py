"""Sage's plan_facility_position (docs/sage-ribbon-tools-plan.md, R3): the ribbon's Position tools, planned on the
server like the patterns and cells (sage_patterns.py), returned as a package for preview_planned_design.

- align, distribute, relative and distance are the workspace's buildAlignmentUpdates, buildDistributionUpdates,
  buildRelativePositionUpdates and buildDistanceUpdate (static/facility_layout_workspace.js), with its footprints:
  the catalog's width and depth, swapped for a quarter turn, round the placement's position.
- Their moves are the session's movePlacements (static/facility_layout_session.js): a stack moves whole, an item on a
  support moves with it, and each attached item's snap relationship follows.
- offset is the ribbon's Offset: with copies off, the session's moveSelected (what sits on the items and the rest
  of their stacks move too); with copies on, its duplicatePlacements (they are copied too).
- swap is the patterns' buildSwap (static/facility_layout_patterns.js) through the session's applyPattern: two
  placements or cell zones (a zone brings what stands in it) trade places, provenance included.
- Not in the ribbon, refused before the preview instead: a swap that would split an item from its support, from
  what sits on it or from its stack (the ribbon moves only what it names); a copy of an item on a support without
  the support (the copy would stand on nothing); moving a locked item, carried ones included (the server refuses).
- The reference of mode relative is left out of the items, as the ribbon does. An anchorId of mode align that is
  not among them is added (it stays put); the ribbon's anchor is always one of the selection.
"""
from __future__ import annotations

from copy import deepcopy
import functools
import math
from typing import Any, Mapping, Sequence

from .asset_orientation import yaw_quaternion
from . import layout_patterns as lp
from .layout_patterns import PatternError
from . import sage_patterns as sp

TOOL = "plan_facility_position"
MODES = ("align", "distribute", "offset", "relative", "distance", "swap")
EDGES = {"west": "left", "center-x": "center-x", "east": "right", "north": "north", "center-z": "center-z",
         "south": "south"}
AXES = {"east-west": "x", "north-south": "z"}
METHODS = ("equal-gap", "equal-center", "fixed-gap")
MEASURES = {"east-west-gap": "horizontal-gap", "north-south-gap": "vertical-gap",
            "east-west-centers": "horizontal-center", "north-south-centers": "vertical-center",
            "centers": "center-distance"}
ALIGN_EDGES = {"east": {"south": "minimum", "center": "center", "north": "maximum"},
               "west": {"south": "minimum", "center": "center", "north": "maximum"},
               "north": {"west": "minimum", "center": "center", "east": "maximum"},
               "south": {"west": "minimum", "center": "center", "east": "maximum"}}
MODE_PARAMETERS = {"align": ("edge", "anchorId"), "distribute": ("axis", "method", "gap"),
                   "offset": ("offset", "copy"), "relative": ("referenceId", "side", "distance", "alignEdge"),
                   "distance": ("referenceId", "measure", "distance"), "swap": ()}
REQUIRED = {"align": ("edge",), "distribute": ("axis",), "offset": ("offset",),
            "relative": ("referenceId", "side", "distance"), "distance": ("referenceId", "measure", "distance"),
            "swap": ()}
COUNTS = {"align": (2, "at least two"), "distribute": (3, "at least three"), "offset": (1, "at least one"),
          "relative": (1, "at least one"), "distance": (1, "exactly one"), "swap": (2, "exactly two")}
LISTED = 40  # moves listed in the summary
MOVE_EPSILON = 1e-9


def tool_spec() -> dict:
    metres = {"type": "number", "minimum": 0, "maximum": 500}
    signed = {"type": "number", "minimum": -500, "maximum": 500}
    return {"name": TOOL, "description": (
        "Position items with the ribbon's Position tools, instead of writing coordinates. itemIds: the placements "
        "to position. mode align: line them up on one edge or centre line of anchorId (default: the first of "
        "itemIds), edge west, east, north, south, center-x (one north-south line) or center-z (one east-west "
        "line). mode distribute (three or more): space them along axis east-west or north-south; the two at the "
        "ends stay; method equal-gap (the default: the same clear space between neighbours), equal-center (the same "
        "centre to centre) or fixed-gap with gap (from the first, clear space in metres). mode offset: move them by "
        "offset {x, z} in metres (east +x, north +z); copy true leaves them and places copies there instead. mode "
        "relative: put them, as one group, on side north, east, south or west of referenceId, distance metres clear "
        "of it, lined up by alignEdge (center by default; for east or west: south, center or north; for north or "
        "south: west, center or east). mode distance: move the one item in itemIds so it stands distance metres "
        "from referenceId, measured as measure: east-west-gap or north-south-gap (clear space), east-west-centers or "
        "north-south-centers, or centers (straight centre to centre); it keeps its side. mode swap: two placements "
        "or cell zones trade places (a zone brings what stands in it). Items on a support move with it, and a stack "
        "moves whole. Locked items are refused. North is +z, up on the plan."),
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["mode", "itemIds"],
                         "properties": {
                             "mode": {"enum": list(MODES)},
                             "itemIds": {**sp._schema_ids(1, 240)},
                             "edge": {"enum": list(EDGES)}, "anchorId": sp.ID,
                             "axis": {"enum": list(AXES)}, "method": {"enum": list(METHODS)}, "gap": metres,
                             "offset": {"type": "object", "additionalProperties": False, "required": ["x", "z"],
                                        "properties": {"x": signed, "z": signed}},
                             "copy": {"type": "boolean"},
                             "referenceId": sp.ID, "side": {"enum": list(sp.COMPASS)}, "distance": metres,
                             "alignEdge": {"enum": ["center", "west", "east", "north", "south"]},
                             "measure": {"enum": list(MEASURES)}}}}


# ---------------------------------------------------------------- the workspace's footprints

def _obj(*values: Any) -> Mapping:
    """JS `a || b || {}` over objects."""
    return next((value for value in values if isinstance(value, Mapping)), {})


def _clean(value: Any) -> str:
    """cleanString(value, '')."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _first(*values: Any) -> Any:
    """JS `a || b || ...`."""
    return next((value for value in values if value), None)


def _definition(record: Mapping) -> Mapping:
    source = _obj(record.get("source"), record)
    return _obj(_first(record.get("definition"), record.get("assetDefinition"), source.get("definition"),
                       source.get("assetDefinition")))


def _record(catalog: Sequence[Mapping], placement: Mapping) -> Mapping | None:
    """catalogRecord over normalizeCatalog: the asset at the placement's revision (any revision when it names none)."""
    asset, revision = placement.get("assetId"), placement.get("assetDefinitionRevision")
    for record in catalog:
        if not isinstance(record, Mapping):
            continue
        definition = _definition(record)
        if _clean(_first(record.get("assetId"), definition.get("assetId"))) != asset:
            continue
        if not revision or _clean(_first(record.get("assetDefinitionRevision"),
                                         record.get("publishedAssetDefinitionRevision"),
                                         record.get("definitionRevision"),
                                         definition.get("assetDefinitionRevision"))) == revision:
            return record
    return None


def _size(record: Mapping) -> tuple[float, float]:
    """normalizeCatalog's width and depth."""
    definition = _definition(record)
    geometry = _obj(_first(definition.get("geometry"), record.get("geometry")))
    aabb = _obj(_first(geometry.get("aabb"), definition.get("aabb"), record.get("aabb")))
    minimum = _obj(_first(aabb.get("minimum"), aabb.get("min")))
    maximum = _obj(_first(aabb.get("maximum"), aabb.get("max")))
    dimensions = _obj(_first(record.get("dimensions"), definition.get("dimensions")))

    def measured(key, axis):
        given = lp._get(record, key)
        given = lp._get(dimensions, key) if given is lp.MISSING else given
        return lp.finite(given, lp.finite(lp._get(maximum, axis), math.nan) - lp.finite(lp._get(minimum, axis),
                                                                                         math.nan))

    return measured("width", "x"), measured("depth", "z")


def _yaw(quaternion: Any) -> float:
    """The workspace's quaternionYawDegrees: [0, 360), to 6 decimals."""
    q = _obj(quaternion)
    x, y = lp.finite(lp._get(q, "x"), 0), lp.finite(lp._get(q, "y"), 0)
    z, w = lp.finite(lp._get(q, "z"), 0), lp.finite(lp._get(q, "w"), 1)
    degrees = math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / math.pi
    if degrees < 0:
        degrees += 360
    return float(f"{degrees:.6f}")


def _session_yaw(quaternion: Any) -> float:
    """The session's quaternionYawDegrees: [0, 360), not rounded."""
    q = _obj(quaternion)
    x, y = lp.finite(lp._get(q, "x"), 0), lp.finite(lp._get(q, "y"), 0)
    z, w = lp.finite(lp._get(q, "z"), 0), lp.finite(lp._get(q, "w"), 1)
    result = math.fmod(math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + z * z)) * 180 / math.pi, 360)
    return result + 360 if result < 0 else result


def _bounds(index: Mapping, placement: Mapping, catalog: Sequence[Mapping]) -> dict:
    """placementBounds."""
    record = _record(catalog, placement)
    transform = _obj(placement.get("transform"))
    position = _obj(transform.get("position"))
    scale = max(0.0001, lp.finite(lp._get(transform, "scale"), 1))
    width, depth = _size(record) if record is not None else (1.2, 0.8)
    width, depth = width * scale, depth * scale
    if not (math.isfinite(width) and math.isfinite(depth)):
        raise PatternError(f"{sp._named(index, placement.get('placementId'))}: its size is not in the library.")
    if abs(lp.js_round(_yaw(transform.get("quaternion")) / 90) % 4) % 2 == 1:
        width, depth = depth, width
    x, z = lp.finite(lp._get(position, "x"), 0), lp.finite(lp._get(position, "z"), 0)
    return {"minX": x - width / 2, "maxX": x + width / 2, "minZ": z - depth / 2, "maxZ": z + depth / 2}


def _center(bounds: Mapping) -> dict:
    return {"x": (bounds["minX"] + bounds["maxX"]) / 2, "z": (bounds["minZ"] + bounds["maxZ"]) / 2}


def _union(values: Sequence[Mapping]) -> dict:
    return {"minX": min(value["minX"] for value in values), "minZ": min(value["minZ"] for value in values),
            "maxX": max(value["maxX"] for value in values), "maxZ": max(value["maxZ"] for value in values)}


def _placements(layout: Mapping, index: Mapping, ids: Sequence[str]) -> list:
    """precisionPlacements: placements only, each once."""
    found = []
    for identifier in ids:
        if identifier not in index:
            raise PatternError(f"There is no {identifier} in the saved layout.")
        collection, entity = index[identifier]
        if collection != "placements":
            raise PatternError(f"{sp._named(index, identifier)} is not a placed item; this positions placements.")
        found.append(entity)
    return found


def _update(index: Mapping, placement: Mapping, dx: float, dz: float) -> dict | None:
    """changedPlacementUpdate (placementUpdate's lock check included); None when it does not move."""
    if abs(dx) <= MOVE_EPSILON and abs(dz) <= MOVE_EPSILON:
        return None
    if placement.get("positionMode") == "locked":
        raise PatternError(f"{sp._named(index, placement['placementId'])} is locked. Ask the user to unlock it, or "
                           "leave it out.")
    position = _obj(_obj(placement.get("transform")).get("position"))
    return {"placementId": placement["placementId"],
            "position": {"x": lp.finite(lp._get(position, "x"), 0) + dx, "y": lp.finite(lp._get(position, "y"), 0),
                         "z": lp.finite(lp._get(position, "z"), 0) + dz}}


# ---------------------------------------------------------------- the workspace's builders

def build_alignment(layout: Mapping, catalog: Sequence[Mapping], ids: Sequence[str], mode: str,
                    anchor_id: str | None) -> dict:
    index = sp._index(layout)
    placements = _placements(layout, index, ids)
    anchor = next((placement for placement in placements if placement["placementId"] == anchor_id), placements[0])
    anchor_bounds = _bounds(index, anchor, catalog)
    anchor_center = _center(anchor_bounds)
    target = {"left": anchor_bounds["minX"], "center-x": anchor_center["x"], "right": anchor_bounds["maxX"],
              "north": anchor_bounds["maxZ"], "center-z": anchor_center["z"], "south": anchor_bounds["minZ"]}[mode]
    updates = []
    for placement in placements:
        if placement["placementId"] == anchor["placementId"]:
            continue
        bounds = _bounds(index, placement, catalog)
        center = _center(bounds)
        dx = dz = 0.0
        if mode == "left":
            dx = target - bounds["minX"]
        elif mode == "center-x":
            dx = target - center["x"]
        elif mode == "right":
            dx = target - bounds["maxX"]
        elif mode == "north":
            dz = target - bounds["maxZ"]
        elif mode == "center-z":
            dz = target - center["z"]
        else:
            dz = target - bounds["minZ"]
        update = _update(index, placement, dx, dz)
        if update:
            updates.append(update)
    return {"anchorPlacementId": anchor["placementId"], "updates": updates}


def build_distribution(layout: Mapping, catalog: Sequence[Mapping], ids: Sequence[str], axis: str, method: str,
                       gap: float | None) -> dict:
    index = sp._index(layout)
    records = []
    for placement in _placements(layout, index, ids):
        bounds = _bounds(index, placement, catalog)
        records.append({"placement": placement, "bounds": bounds, "center": _center(bounds),
                        "size": bounds["maxX"] - bounds["minX"] if axis == "x" else bounds["maxZ"] - bounds["minZ"]})

    def order(left, right):
        delta = left["center"][axis] - right["center"][axis]
        if abs(delta) > 1e-9:
            return -1 if delta < 0 else 1
        a, b = left["placement"]["placementId"], right["placement"]["placementId"]
        return (a > b) - (a < b)

    records.sort(key=functools.cmp_to_key(order))
    low, high = ("minX", "maxX") if axis == "x" else ("minZ", "maxZ")
    first, last = records[0], records[-1]
    centers, clear = {}, None
    if method == "equal-center":
        interval = (last["center"][axis] - first["center"][axis]) / (len(records) - 1)
        for number, record in enumerate(records):
            centers[record["placement"]["placementId"]] = first["center"][axis] + interval * number
    else:
        clear = float(gap) if method == "fixed-gap" else (
            (last["bounds"][high] - first["bounds"][low] - sum(record["size"] for record in records))
            / (len(records) - 1))
        if not math.isfinite(clear) or clear < 0:
            raise PatternError("They already overlap along that axis: the span between the two at the ends is too "
                               "small for equal clear gaps. Use fixed-gap with a gap, or equal-center.")
        cursor = first["bounds"][low]
        for record in records:
            centers[record["placement"]["placementId"]] = cursor + record["size"] / 2
            cursor += record["size"] + clear
    updates = []
    for record in records:
        delta = centers[record["placement"]["placementId"]] - record["center"][axis]
        update = _update(index, record["placement"], delta if axis == "x" else 0.0, delta if axis == "z" else 0.0)
        if update:
            updates.append(update)
    return {"clearGap": clear, "order": [record["placement"]["placementId"] for record in records],
            "updates": updates}


def build_relative(layout: Mapping, catalog: Sequence[Mapping], ids: Sequence[str], reference_id: str,
                   relation: str, distance: float, alignment: str) -> dict:
    index = sp._index(layout)
    moving = _placements(layout, index, ids)
    reference = _placements(layout, index, [reference_id])[0]
    if any(placement["placementId"] == reference_id for placement in moving):
        raise PatternError("The reference cannot also move: leave it out of itemIds.")
    reference_bounds = _bounds(index, reference, catalog)
    group = _union([_bounds(index, placement, catalog) for placement in moving])
    reference_center, group_center = _center(reference_bounds), _center(group)
    dx = dz = 0.0
    if relation == "east":
        dx = reference_bounds["maxX"] + distance - group["minX"]
    elif relation == "west":
        dx = reference_bounds["minX"] - distance - group["maxX"]
    elif relation == "north":
        dz = reference_bounds["maxZ"] + distance - group["minZ"]
    else:
        dz = reference_bounds["minZ"] - distance - group["maxZ"]
    if relation in ("east", "west"):
        dz = {"minimum": reference_bounds["minZ"] - group["minZ"], "center": reference_center["z"] - group_center["z"],
              "maximum": reference_bounds["maxZ"] - group["maxZ"]}[alignment]
    else:
        dx = {"minimum": reference_bounds["minX"] - group["minX"], "center": reference_center["x"] - group_center["x"],
              "maximum": reference_bounds["maxX"] - group["maxX"]}[alignment]
    return {"updates": [update for placement in moving if (update := _update(index, placement, dx, dz))]}


def measure(layout: Mapping, catalog: Sequence[Mapping], first_id: str, second_id: str, mode: str) -> float:
    """measurePlacementDistance."""
    index = sp._index(layout)
    first_placement, second_placement = _placements(layout, index, [first_id, second_id])
    first, second = _bounds(index, first_placement, catalog), _bounds(index, second_placement, catalog)
    first_center, second_center = _center(first), _center(second)
    gap_x = (second["minX"] - first["maxX"] if second["minX"] > first["maxX"]
             else first["minX"] - second["maxX"] if first["minX"] > second["maxX"] else 0)
    gap_z = (second["minZ"] - first["maxZ"] if second["minZ"] > first["maxZ"]
             else first["minZ"] - second["maxZ"] if first["minZ"] > second["maxZ"] else 0)
    return {"horizontal-gap": gap_x, "vertical-gap": gap_z,
            "horizontal-center": abs(second_center["x"] - first_center["x"]),
            "vertical-center": abs(second_center["z"] - first_center["z"]),
            "center-distance": math.hypot(second_center["x"] - first_center["x"],
                                          second_center["z"] - first_center["z"]),
            "shortest": math.hypot(gap_x, gap_z)}[mode]


def build_distance(layout: Mapping, catalog: Sequence[Mapping], reference_id: str, moving_id: str, mode: str,
                   distance: float) -> dict:
    index = sp._index(layout)
    if reference_id == moving_id:
        raise PatternError("The item cannot be its own reference.")
    reference, moving = _placements(layout, index, [reference_id, moving_id])
    reference_bounds, moving_bounds = _bounds(index, reference, catalog), _bounds(index, moving, catalog)
    reference_center, moving_center = _center(reference_bounds), _center(moving_bounds)
    dx = dz = 0.0
    if mode == "horizontal-gap":
        half = (moving_bounds["maxX"] - moving_bounds["minX"]) / 2
        target = (reference_bounds["maxX"] + distance + half if moving_center["x"] >= reference_center["x"]
                  else reference_bounds["minX"] - distance - half)
        dx = target - moving_center["x"]
    elif mode == "vertical-gap":
        half = (moving_bounds["maxZ"] - moving_bounds["minZ"]) / 2
        target = (reference_bounds["maxZ"] + distance + half if moving_center["z"] >= reference_center["z"]
                  else reference_bounds["minZ"] - distance - half)
        dz = target - moving_center["z"]
    elif mode == "horizontal-center":
        direction = 1 if moving_center["x"] >= reference_center["x"] else -1
        dx = reference_center["x"] + direction * distance - moving_center["x"]
    elif mode == "vertical-center":
        direction = 1 if moving_center["z"] >= reference_center["z"] else -1
        dz = reference_center["z"] + direction * distance - moving_center["z"]
    else:
        vector_x, vector_z = moving_center["x"] - reference_center["x"], moving_center["z"] - reference_center["z"]
        length = math.hypot(vector_x, vector_z)
        if length <= 1e-9:
            vector_x, vector_z = 1.0, 0.0
        else:
            vector_x, vector_z = vector_x / length, vector_z / length
        dx = reference_center["x"] + vector_x * distance - moving_center["x"]
        dz = reference_center["z"] + vector_z * distance - moving_center["z"]
    update = _update(index, moving, dx, dz)
    return {"updates": [update] if update else []}


# ---------------------------------------------------------------- the session's operations

def _stack(placement: Mapping | None) -> Mapping | None:
    relation = sp._relation(placement or {})
    return relation if relation.get("family") == "vertical_stack" and isinstance(relation.get("stackId"), str) \
        and relation.get("stackId") else None


def _surface(placement: Mapping | None) -> Mapping | None:
    relation = sp._relation(placement or {})
    return relation if relation.get("family") == "surface_attachment" \
        and isinstance(relation.get("supportPlacementId"), str) and relation.get("supportPlacementId") else None


def _xyz(value: Mapping) -> dict:
    return {"x": float(value["x"]), "y": float(value.get("y", 0) or 0), "z": float(value["z"])}


def _position_of(placement: Mapping) -> dict:
    return _xyz(_obj(_obj(placement.get("transform")).get("position")))


def move_operations(layout: Mapping, updates: Sequence[Mapping]) -> tuple[list, dict]:
    """The session's movePlacements: a stack moves whole and items on a moved support move with it; each attached
    item's snap relationship follows. Returns the operations and every placement's new position."""
    placements = [item for item in layout.get("placements") or [] if isinstance(item, Mapping)]
    by_id = {item.get("placementId"): item for item in placements}
    moved = {update["placementId"]: _xyz(update["position"]) for update in updates}
    for update in updates:
        relation = _stack(by_id[update["placementId"]])
        if not relation:
            continue
        current = _position_of(by_id[update["placementId"]])
        delta = {key: moved[update["placementId"]][key] - current[key] for key in "xyz"}
        for placement in placements:
            member = _stack(placement)
            if not member or member.get("stackId") != relation["stackId"] or placement["placementId"] in moved:
                continue
            position = _position_of(placement)
            moved[placement["placementId"]] = {key: position[key] + delta[key] for key in "xyz"}
    expanded = True
    while expanded:
        expanded = False
        for placement in placements:
            if placement["placementId"] in moved:
                continue
            relation = _surface(placement)
            if not relation or relation["supportPlacementId"] not in moved:
                continue
            support = by_id.get(relation["supportPlacementId"])
            if not support:
                continue
            support_new, support_old, position = (moved[relation["supportPlacementId"]], _position_of(support),
                                                  _position_of(placement))
            moved[placement["placementId"]] = {key: position[key] + support_new[key] - support_old[key]
                                               for key in "xyz"}
            expanded = True
    operations = [{"op": "move_placement", "placementId": identifier, "position": dict(position),
                   "movementKind": "user"} for identifier, position in moved.items()]
    for identifier, position in moved.items():
        placement = by_id[identifier]
        relation = _surface(placement)
        if not relation:
            continue
        support = by_id.get(relation["supportPlacementId"])
        if not support:
            raise PatternError(f"{identifier} sits on {relation['supportPlacementId']}, which is not in the layout.")
        support_new = moved.get(support["placementId"])
        support_position = support_new or _position_of(support)
        child_delta_y = position["y"] - _position_of(placement)["y"]
        support_delta_y = support_new["y"] - _position_of(support)["y"] if support_new else 0
        offset = lp.finite(relation.get("normalOffsetMeters") or 0, math.nan)
        if not math.isfinite(offset):
            raise PatternError(f"{identifier}'s surface offset is invalid.")
        relative = child_delta_y - support_delta_y
        next_offset = offset - relative if relation.get("side") == "below" else offset + relative
        if next_offset < -1e-9:
            raise PatternError(f"{identifier} would pass through its support's surface.")
        operations.append({"op": "set_snap_relationship", "placementId": identifier, "snapRelationship": {
            **deepcopy(dict(relation)),
            "localPosition": sp._rotate_floor_vector({"x": position["x"] - support_position["x"],
                                                      "z": position["z"] - support_position["z"]},
                                                     -_session_yaw(_obj(support.get("transform")).get("quaternion"))),
            "normalOffsetMeters": max(0, next_offset)}})
    return operations, moved


class _CopyIds:
    """The session's id sequences for duplicatePlacements, in one plan's namespace."""

    def __init__(self, namespace: str):
        self.namespace, self.placements, self.attachments, self.stacks = namespace, 0, 0, 0

    def placement(self) -> str:
        self.placements += 1
        return f"pl-surface-copy-{self.namespace}-{sp._base36(self.placements)}"

    def attachment(self, source: str) -> str:
        self.attachments += 1
        return f"{source or 'surface'}:copy:{self.namespace}:{sp._base36(self.attachments)}"

    def stack(self, source: str) -> str:
        self.stacks += 1
        return f"{source or 'stack'}:copy:{self.namespace}:{sp._base36(self.stacks)}"


def expanded(layout: Mapping, ids: Sequence[str]) -> list:
    """The session's expandedSurfaceAttachmentPlacementIds then expandedStackPlacementIds: the placements, what
    sits on them (and on that) and the rest of their stacks, in layout order."""
    placements = [item for item in layout.get("placements") or [] if isinstance(item, Mapping)]
    wanted = set(ids)
    changed = True
    while changed:
        changed = False
        for placement in placements:
            relation = _surface(placement)
            if relation and relation["supportPlacementId"] in wanted and placement["placementId"] not in wanted:
                wanted.add(placement["placementId"])
                changed = True
    stacks = {_stack(placement)["stackId"] for placement in placements
              if placement["placementId"] in wanted and _stack(placement)}
    wanted |= {placement["placementId"] for placement in placements
               if _stack(placement) and _stack(placement)["stackId"] in stacks}
    return [placement for placement in placements if placement["placementId"] in wanted]


def offset_operations(layout: Mapping, ids: Sequence[str], delta: Mapping) -> tuple[list, dict]:
    """The session's moveSelected for placements (the ribbon's Offset with copies off): the placements, what sits on
    them and the rest of their stacks move by delta; an item whose support stays gets its snap relationship
    re-anchored. Returns the operations and every placement's new position."""
    by_id = {item.get("placementId"): item for item in layout.get("placements") or [] if isinstance(item, Mapping)}
    moving = expanded(layout, ids)
    moving_ids = {placement["placementId"] for placement in moving}
    operations, moved = [], {}
    for placement in moving:
        current = _position_of(placement)
        position = {"x": current["x"] + float(delta["x"]), "y": current["y"], "z": current["z"] + float(delta["z"])}
        moved[placement["placementId"]] = position
        operations.append({"op": "move_placement", "placementId": placement["placementId"], "position": position,
                           "movementKind": "user"})
        relation = _surface(placement)
        if not relation or relation["supportPlacementId"] in moving_ids:
            continue
        support = by_id.get(relation["supportPlacementId"])
        if not support:
            raise PatternError(f"{placement['placementId']} sits on {relation['supportPlacementId']}, which is not in "
                               "the layout.")
        support_position = _position_of(support)
        offset = lp.finite(relation.get("normalOffsetMeters") or 0, math.nan)
        if not math.isfinite(offset):
            raise PatternError(f"{placement['placementId']}'s surface offset is invalid.")
        operations.append({"op": "set_snap_relationship", "placementId": placement["placementId"],
                           "snapRelationship": {**deepcopy(dict(relation)), "localPosition": sp._rotate_floor_vector(
                               {"x": position["x"] - support_position["x"], "z": position["z"] - support_position["z"]},
                               -_session_yaw(_obj(support.get("transform")).get("quaternion"))),
                               "normalOffsetMeters": max(0, offset)}})
    return operations, moved


def copy_operations(layout: Mapping, ids: Sequence[str], delta: Mapping, namespace: str) -> tuple[list, list]:
    """The session's duplicatePlacements: what sits on a copied support and the rest of a copied stack come along.
    Returns the operations and the copied placement ids, in order."""
    copied = expanded(layout, ids)
    sources = {placement["placementId"] for placement in copied}
    names = _CopyIds(namespace)
    group = any(_surface(placement) and _surface(placement)["supportPlacementId"] in sources for placement in copied)
    new_ids = {placement["placementId"]: names.placement() for placement in copied} if group else {}
    attachments, stack_ids, operations = {}, {}, []
    for placement in copied:
        position = _position_of(placement)
        operation = {"op": "duplicate_placement", "sourcePlacementId": placement["placementId"],
                     "position": {"x": position["x"] + float(delta["x"]), "y": position["y"],
                                  "z": position["z"] + float(delta["z"])}, "positionMode": "manual"}
        if placement["placementId"] in new_ids:
            operation["newPlacementId"] = new_ids[placement["placementId"]]
        relation = None
        stack = _stack(placement)
        surface = _surface(placement)
        if stack:  # copiedPlacementRelationship
            if stack["stackId"] not in stack_ids:
                stack_ids[stack["stackId"]] = names.stack(stack["stackId"])
            relation = {**deepcopy(dict(stack)), "stackId": stack_ids[stack["stackId"]]}
        elif surface and surface["supportPlacementId"] in new_ids:
            attachment = str(surface.get("attachmentId") or surface["supportPlacementId"] + ":surface")
            if attachment not in attachments:
                attachments[attachment] = names.attachment(attachment)
            relation = {**deepcopy(dict(surface)), "attachmentId": attachments[attachment],
                        "supportPlacementId": new_ids[surface["supportPlacementId"]]}
        if relation:
            operation["snapRelationship"] = relation
        operations.append(operation)
    return operations, [placement["placementId"] for placement in copied]


def build_swap(layout: Mapping, catalog: Sequence[Mapping], ids: Sequence[str]) -> dict:
    """The patterns' buildSwap."""
    index = sp._index(layout)
    zones = {zone.get("zoneId"): zone for zone in layout.get("zones") or [] if isinstance(zone, Mapping)}
    groups = []
    for identifier in ids:
        zone = zones.get(identifier)
        items = lp.collect_selection(layout, catalog, [identifier],
                                     {"expandZones": bool(zone), "includeZones": bool(zone)})
        if not items:
            raise PatternError(f"{sp._named(index, identifier)} cannot be swapped: swap placements or cell zones.")
        anchor = next((item for item in items if item["kind"] == "zone" and item["id"] == identifier), None) \
            if zone else items[0]
        groups.append({"id": identifier, "items": items, "anchor": deepcopy(anchor["position"])})
    seen = set()
    for group in groups:
        for item in group["items"]:
            if item["id"] in seen:
                raise PatternError("The two overlap or share items; swap two separate items or cell zones.")
            seen.add(item["id"])
            if item.get("positionMode") == "locked":
                raise PatternError(f"{sp._named(index, item['id'])} is locked. Ask the user to unlock it, or swap "
                                   "something else.")

    def translated(item, source, target):
        move = {"sourceId": item["id"], "kind": item["kind"],
                "position": {"x": item["position"]["x"] + target["x"] - source["x"], "y": item["position"]["y"],
                             "z": item["position"]["z"] + target["z"] - source["z"]},
                "rotationDegrees": item["rotationDegrees"], "sourceAnchor": deepcopy(source),
                "targetAnchor": deepcopy(target)}
        if item.get("boundary"):
            move["boundary"] = [lp.transform_point(point, source, target, 0) for point in item["boundary"]]
        return move

    moves = [translated(item, groups[0]["anchor"], groups[1]["anchor"]) for item in groups[0]["items"]]
    moves += [translated(item, groups[1]["anchor"], groups[0]["anchor"]) for item in groups[1]["items"]]
    return {"seedCount": len(moves), "count": 2, "moves": moves,
            "guide": {"kind": "swap", "start": deepcopy(groups[0]["anchor"]), "end": deepcopy(groups[1]["anchor"]),
                      "sourceIds": list(ids)}}


PATTERN_COMMANDS = {"swap": "swap", "vertical-stack": "vertical_stack", "surface-stack": "surface_stack"}


def apply_pattern(layout: Mapping, result: Mapping, namespace: str) -> list:
    """The session's applyPattern for a swap, a vertical stack or a surface stack: the copies (patternCopyOperation),
    the snap relationships, then the moves (patternMoveOperations), all with the pattern's provenance; the first
    operation also names the seeds."""
    index = sp._index(layout)
    copies, moves = result.get("copies") or [], result.get("moves") or []
    relationships = result.get("relationships") or []
    sources = sorted({item["sourceId"] for item in [*copies, *moves, *relationships] if item.get("sourceId")})
    support = (result.get("guide") or {}).get("supportPlacementId")
    if support and support not in sources:
        sources = sorted([*sources, support])
    provenance = sp._provenance(namespace, PATTERN_COMMANDS[result["mode"]], None, sources, result["count"],
                                result["seedCount"], result.get("guide") or {})
    operations = sp._copy_operations(layout, copies, provenance, sp._Ids(namespace)) if copies else []
    for relationship in relationships:
        if relationship.get("kind") != "placement":
            raise PatternError("pattern relationships currently support placements only")
        operations.append({"op": "set_snap_relationship", "placementId": relationship["sourceId"],
                           "snapRelationship": deepcopy(relationship["snapRelationship"]),
                           "layoutProvenance": deepcopy(provenance)})
    for move in moves:
        collection, entity = index[move["sourceId"]]
        position = _xyz(move["position"])
        if collection == "placements" and move["kind"] == "placement":
            operations.append({"op": "move_placement", "placementId": move["sourceId"], "position": position,
                               "movementKind": "user", "layoutProvenance": deepcopy(provenance)})
            operations.append({"op": "rotate_placement", "placementId": move["sourceId"],
                               "quaternion": yaw_quaternion(float(move["rotationDegrees"])), "movementKind": "user",
                               "layoutProvenance": deepcopy(provenance)})
        elif collection == "floorMarkings" and move["kind"] == "floor-marking":
            operations.append({"op": "edit_floor_marking", "markingId": move["sourceId"], "patch": {
                "transform": {"position": position, "rotationDegrees": float(move["rotationDegrees"])},
                "positionMode": "manual"}, "layoutProvenance": deepcopy(provenance)})
        elif collection == "zones" and move["kind"] == "zone":
            value = deepcopy(dict(entity))
            sp._transformed_cell_interfaces(value, move)
            patch = {"boundary": [sp._world_point(point) for point in move.get("boundary") or []],
                     "anchors": [sp._transformed_zone_anchor(anchor, move) for anchor in value.get("anchors") or []]}
            if "extensions" in value:
                patch["extensions"] = value["extensions"]
            operations.append({"op": "edit_zone", "zoneId": move["sourceId"], "patch": patch,
                               "layoutProvenance": deepcopy(provenance)})
        else:
            raise PatternError(f"pattern move source '{move['sourceId']}' does not exist")
    if not operations:
        raise PatternError("pattern result contains no changes")
    return sp._with_seed_provenance(operations, provenance, sources)


def swap_operations(layout: Mapping, swap: Mapping, namespace: str) -> list:
    """applyPattern for a swap."""
    return apply_pattern(layout, {**swap, "mode": "swap"}, namespace)


# ---------------------------------------------------------------- plan_facility_position

def _item_ids(arguments: Mapping) -> list:
    """itemIds, each once; align adds anchorId when it is not among them (it stays put either way)."""
    ids = list(dict.fromkeys(arguments.get("itemIds") or []))
    anchor = arguments.get("anchorId")
    if arguments.get("mode") == "align" and anchor and anchor not in ids:
        ids.insert(0, anchor)
    if arguments.get("mode") == "relative":
        ids = [identifier for identifier in ids if identifier != arguments.get("referenceId")]  # as the ribbon does
    return ids


def _check(arguments: Mapping) -> str:
    mode = arguments.get("mode")
    if mode not in MODES:
        raise PatternError(f"mode must be one of {', '.join(MODES)}.")
    stray = sorted(key for name, keys in MODE_PARAMETERS.items() if name != mode for key in keys
                   if key in arguments and key not in MODE_PARAMETERS[mode])
    if stray:
        raise PatternError(f"{', '.join(stray)} {'is' if len(stray) == 1 else 'are'} not for mode {mode}.")
    missing = [key for key in REQUIRED[mode] if key not in arguments]
    if missing:
        raise PatternError(f"mode {mode} needs {' and '.join(missing)}.")
    minimum, words = COUNTS[mode]
    count = len(_item_ids(arguments))
    if count < minimum or (mode in ("distance", "swap") and count != minimum):
        what = "besides the reference " if mode in ("relative", "distance") else ""
        raise PatternError(f"mode {mode} takes {words} item{'s' if minimum > 1 else ''} in itemIds {what}"
                           f"({count} given).")
    if mode == "distance" and arguments["itemIds"][0] == arguments["referenceId"]:
        raise PatternError("The item cannot be its own reference.")
    if mode == "distribute" and (arguments.get("method") == "fixed-gap") != ("gap" in arguments):
        raise PatternError("gap goes with method fixed-gap, and fixed-gap needs a gap.")
    if mode == "relative":
        edges = ALIGN_EDGES[arguments["side"]]
        if arguments.get("alignEdge", "center") not in edges:
            raise PatternError(f"For side {arguments['side']}, alignEdge is {', '.join(edges)}.")
    if mode == "offset" and not (abs(arguments["offset"]["x"]) > MOVE_EPSILON
                                 or abs(arguments["offset"]["z"]) > MOVE_EPSILON):
        raise PatternError("The offset is zero: give x or z in metres.")
    return mode


def _kept_together(layout: Mapping, index: Mapping, moving: set) -> None:
    """A swap moves only what it names (a zone: what stands in it). Refused when that would split an item from its
    support, from what sits on it, or from the rest of its stack."""
    placements = [item for item in layout.get("placements") or [] if isinstance(item, Mapping)]
    for placement in placements:
        identifier = placement["placementId"]
        if identifier not in moving:
            continue
        surface, stack = _surface(placement), _stack(placement)
        if surface and surface["supportPlacementId"] not in moving:
            raise PatternError(f"{sp._named(index, identifier)} sits on "
                               f"{sp._named(index, surface['supportPlacementId'])}, which would stay. Swap the "
                               "support, or the zone that holds both.")
        held = next((item for item in placements if (_surface(item) or {}).get("supportPlacementId") == identifier
                     and item["placementId"] not in moving), None)
        if held:
            raise PatternError(f"{sp._named(index, identifier)} has {sp._named(index, held['placementId'])} on it, "
                               "which would stay behind. Swap the zone that holds both, or move them with mode "
                               "offset.")
        if stack and any(_stack(item) and _stack(item)["stackId"] == stack["stackId"]
                         and item["placementId"] not in moving for item in placements):
            raise PatternError(f"{sp._named(index, identifier)} is part of a stack that would be split; swap does "
                               "not move stacks yet.")


def _unlocked(index: Mapping, moved: Mapping, named_ids: Sequence[str]) -> None:
    """The server refuses to move a locked placement: say so before the preview, carried items included."""
    for identifier in moved:
        placement = index[identifier][1]
        if placement.get("positionMode") == "locked":
            carried = "" if identifier in named_ids else " (it would move along with what you named)"
            raise PatternError(f"{sp._named(index, identifier)} is locked{carried}. Ask the user to unlock it, or "
                               "leave it out.")


def _moved_summary(index: Mapping, layout: Mapping, moved: Mapping, named_ids: Sequence[str]) -> dict:
    by_id = {item.get("placementId"): item for item in layout.get("placements") or [] if isinstance(item, Mapping)}
    rows, along = [], []
    for identifier, position in moved.items():
        before = _position_of(by_id[identifier])
        if identifier not in named_ids:
            along.append(sp._named(index, identifier))
        rows.append({"item": sp._named(index, identifier), "from": sp._point(before), "to": sp._point(position),
                     "by": {"x": sp._round(position["x"] - before["x"]), "z": sp._round(position["z"] - before["z"])}})
    stayed = [sp._named(index, identifier) for identifier in named_ids if identifier not in moved]
    return {"moved": rows[:LISTED], "movedCount": len(rows),
            **({"carriedAlong": along[:LISTED]} if along else {}), **({"unchanged": stayed[:LISTED]} if stayed else {})}


NOTHING = "Nothing would move: the items already stand where this puts them."


def plan_position(layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    mode = _check(arguments)
    catalog = list(catalog)
    index = sp._index(layout)
    ids = _item_ids(arguments)
    namespace = sp._namespace(TOOL, arguments, revision)
    summary: dict = {"available": True, "mode": mode}
    if mode == "swap":
        swap = build_swap(layout, catalog, ids)
        _kept_together(layout, index, {move["sourceId"] for move in swap["moves"] if move["kind"] == "placement"})
        operations = swap_operations(layout, swap, namespace)
        summary.update(swapped=[sp._named(index, identifier) for identifier in ids], movedCount=len(swap["moves"]),
                       moved=[{"item": sp._named(index, move["sourceId"]), "to": sp._point(move["position"])}
                              for move in swap["moves"]][:LISTED])
        return {**summary, "operations": operations}
    _placements(layout, index, ids)
    if mode == "offset" and arguments.get("copy") is True:
        copied = expanded(layout, ids)
        sources = {placement["placementId"] for placement in copied}
        for placement in copied:
            surface = _surface(placement)
            if surface and surface["supportPlacementId"] not in sources:
                raise PatternError(f"{sp._named(index, placement['placementId'])} sits on "
                                   f"{sp._named(index, surface['supportPlacementId'])}; a copy of it alone would "
                                   "stand on nothing. Copy the support with it.")
        operations, copied_ids = copy_operations(layout, ids, arguments["offset"], namespace)
        along = [sp._named(index, identifier) for identifier in copied_ids if identifier not in ids]
        summary.update(offset=sp._point(arguments["offset"]), newItems=len(copied_ids),
                       copied=[sp._named(index, identifier) for identifier in copied_ids][:LISTED],
                       **({"copiedAlong": along[:LISTED]} if along else {}))
        return {**summary, "operations": operations}
    if mode == "offset":
        operations, moved = offset_operations(layout, ids, arguments["offset"])
        _unlocked(index, moved, ids)
        summary["offset"] = sp._point(arguments["offset"])
        summary.update(_moved_summary(index, layout, moved, ids))
        return {**summary, "operations": operations}
    if mode == "align":
        result = build_alignment(layout, catalog, ids, EDGES[arguments["edge"]], arguments.get("anchorId"))
        updates = result["updates"]
        summary.update(edge=arguments["edge"], anchor=sp._named(index, result["anchorPlacementId"]))
    elif mode == "distribute":
        method = arguments.get("method", "equal-gap")
        result = build_distribution(layout, catalog, ids, AXES[arguments["axis"]], method, arguments.get("gap"))
        updates = result["updates"]
        summary.update(axis=arguments["axis"], method=method,
                       order=[sp._named(index, identifier) for identifier in result["order"]][:LISTED],
                       **({"clearGap": sp._round(result["clearGap"])} if result["clearGap"] is not None else {}))
    elif mode == "relative":
        alignment = ALIGN_EDGES[arguments["side"]][arguments.get("alignEdge", "center")]
        updates = build_relative(layout, catalog, ids, arguments["referenceId"], arguments["side"],
                                 float(arguments["distance"]), alignment)["updates"]
        summary.update(reference=sp._named(index, arguments["referenceId"]), side=arguments["side"],
                       distance=sp._round(arguments["distance"]), alignEdge=arguments.get("alignEdge", "center"))
    else:
        kind = MEASURES[arguments["measure"]]
        before = measure(layout, catalog, arguments["referenceId"], ids[0], kind)
        updates = build_distance(layout, catalog, arguments["referenceId"], ids[0], kind,
                                 float(arguments["distance"]))["updates"]
        summary.update(reference=sp._named(index, arguments["referenceId"]), measure=arguments["measure"],
                       before=sp._round(before), after=sp._round(arguments["distance"]))
    if not updates:
        raise PatternError(NOTHING)
    operations, moved = move_operations(layout, updates)
    _unlocked(index, moved, ids)
    summary.update(_moved_summary(index, layout, moved, ids))
    return {**summary, "operations": operations}
