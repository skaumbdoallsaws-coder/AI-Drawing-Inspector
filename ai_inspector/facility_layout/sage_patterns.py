"""Sage's planning tools for the ribbon's patterns and cells (docs/sage-ribbon-tools-plan.md, R1 and R2).

plan_facility_pattern repeats items in a row or a grid (the ribbon's Linear Pattern), mirrors them across a line,
repeats them round a centre (Circular Pattern) or round a rectangle (Perimeter); plan_facility_cell arranges
placed machines or places new ones as a cell (the ribbon's Cell Layout, all ten shapes). Both are read-only: they
return a summary and the operations the ribbon would send, which the gateway keeps as a package for
preview_planned_design (one review, the usual validation, Apply directly respected).

- The math is the ribbon's (layout_patterns.py, a port of static/facility_layout_patterns.js).
- The guards are the command adapter's (static/facility_layout_command_adapter.js).
- The operations follow the session's (patternCopyOperation and patternMoveOperations in
  static/facility_layout_session.js), provenance included, so inspect_pattern_provenance reads Sage's patterns
  like the ribbon's.
- New: a grid (the row repeated in a second direction), new machines placed as a cell, a cell centred in a zone,
  removeIds, and operator-inside facing: each machine's reviewed operator side faces square into the cell.
- A mirror keeps each placement's reviewed operator side (else its front, else its north side) as the mirror image,
  as the ribbon's Mirror does since 2026-11-01: before, it kept each copy's east side, which pointed a north or
  south front 180 degrees from the mirror image.
- clearZone (2026-11-02): a cell clears its zone first, floor markings included, keeping the building's structure
  and locked items, and names both; with no machines it only clears the zone.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
import math
from typing import Any, Mapping, Sequence

from .asset_orientation import COMPASS_HEADINGS, yaw_quaternion
from . import layout_patterns as lp
from .layout_patterns import PatternError
from .navigation_contract import navigation_anchor_dangles, navigation_identity_index

PATTERN_TOOL = "plan_facility_pattern"
CELL_TOOL = "plan_facility_cell"
NAMES = (PATTERN_TOOL, CELL_TOOL)
COMPASS = ("north", "east", "south", "west")
FACINGS = ("operator-inside", *lp.CELL_ORIENTATIONS)
SHAPE_NAMES = {"line": "straight-line", "l": "L-shaped", "u": "U-shaped", "grid": "grid", "parallel": "parallel-row",
               "serpentine": "serpentine", "loop": "loop", "spine": "spine-and-branch",
               "herringbone": "herringbone", "cluster": "cluster"}
U_OPENS = 180  # an unturned U opens to the south: its base runs along the north side
LISTED = 60  # instances listed in a pattern's summary
GROWTH, GROWTH_STEPS = 0.1, 12  # a default-sized cell grows in 10% steps, up to 2.2 times, to keep the gap
SHIFT_STEP, SHIFT_LIMIT = 0.5, 400  # and shifts inside its zone in 0.5 m steps, the nearest 400 at most
NEAR = 3.0  # what stays within 3 m of a machine is named in the summary
# What a cleared zone keeps: the building (the library's Building Structures: columns, walls, roof members,
# sprinklers, light rows, doors). Locked items stay too, and what is mounted on an item that stays.
STRUCTURE = frozenset({"Building Structures"})
CLEARED_LISTED = 24  # items a cleared zone names, then "and N more"
KINDS = ("linear", "mirror", "circular", "perimeter")
COMMANDS = {"linear": "linear_pattern", "mirror": "mirror", "circular": "circular_pattern", "perimeter": "perimeter"}
KIND_PARAMETERS = {  # what each kind takes besides seedIds and removeIds
    "linear": ("count", "direction", "headingDegrees", "spacing", "gap", "rows", "rowDirection", "rowHeadingDegrees",
               "rowSpacing", "rowGap", "origin"),
    "mirror": ("side", "gap", "lineX", "lineZ", "linePoints"),
    "circular": ("count", "center", "totalDegrees", "turnWithPattern", "origin"),
    "perimeter": ("shape", "widthCount", "depthCount", "gap", "turnDegrees", "origin"),
}
PLAN_DEFAULTS = (40.0, 30.0, 1.0)  # the Plan's default width, depth and grid (static/facility_layout_workspace.js)
ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
IDS = {"type": "array", "items": ID, "uniqueItems": True}
METRES = {"type": "number", "exclusiveMinimum": 0, "maximum": 500}
POINT = {"type": "object", "additionalProperties": False, "required": ["x", "z"],
         "properties": {"x": {"type": "number"}, "z": {"type": "number"}}}


def _schema_ids(minimum, maximum):
    return {**IDS, "minItems": minimum, "maxItems": maximum}


def tool_specs() -> list[dict]:
    direction = {"enum": list(COMPASS)}
    heading = {"type": "number", "minimum": -360, "maximum": 360}
    return [{"name": PATTERN_TOOL, "description": (
        "Plan copies of items with the ribbon's pattern math, instead of writing coordinates. seedIds: the items to "
        "repeat: placements, floor markings, or a zone (it brings what stands inside it, such as a whole "
        "workstation). kind linear (the default): a straight row or a grid. count: how many in the row, the seed "
        "included (5 more is count 6). direction: north, east, south or west (north is +z, up on the plan; east is "
        "+x), or headingDegrees (0 north, 90 east); give neither and the row runs along the seed's length (else "
        "across it), the way it fits in the seed's zone clear of what stays (picked in the summary says which way "
        "and why: tell the user). spacing: centre to centre; gap: the clear space between neighbours along the row "
        "(2 m apart is gap 2, unless the user says centre to centre); give one. A grid: rows, with rowDirection (or "
        "rowHeadingDegrees; give neither and the rows go the side that fits) and rowSpacing or rowGap (default: "
        "gap). kind mirror: one mirrored copy across a line. side (north, east, south or west, default east) "
        "puts the copy on that side, with gap the clear space between the seed and its copy (default about 2 m); "
        "or give the line as lineX (a north-south line at that x), lineZ (an east-west line at that z) or "
        "linePoints (two points). Each machine's front is mirrored too. kind circular: count in all, the seed "
        "included, round center {x, z} (default: west of the seed by 1.5 times its larger side), clockwise on the "
        "plan, over totalDegrees (default 360; less makes an arc). turnWithPattern turns each copy as it goes "
        "round, so a seed that faces the centre keeps facing it; without it copies keep the seed's heading. kind "
        "perimeter: a ring of copies round a "
        "rectangle that starts at the seed and runs along its long side: widthCount on the seed's side and on the "
        "side opposite (default 6, the seed included), depthCount on each end (default 4), shape square (depthCount "
        "the same as widthCount), gap between neighbours (default 0); turnDegrees turns the ring clockwise. Each "
        "side's copies turn with the ring, so they face it as the seed does. A row, grid, circle or ring that does "
        "not fit where the seed stands moves with the seed to the nearest place in the seed's zone where it fits, "
        "in the same change: seedMoved in the summary says what moves where and why (tell the user; never ask the "
        "user to move the seed first). origin {x, z} moves the seed's main item there first. removeIds: "
        "placements or floor markings to delete in the same review; a saved walk that stops at one of them goes "
        "with it, and alsoRemoves in the summary names it: say it. "
        "Copies keep each item's finish, label and attached items. Read-only: stage the packageId with "
        "preview_planned_design."),
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["seedIds"],
            "properties": {
                "kind": {"enum": list(KINDS)}, "seedIds": _schema_ids(1, 240),
                "count": {"type": "integer", "minimum": 2, "maximum": 50},
                "direction": direction, "headingDegrees": heading,
                "spacing": METRES, "gap": {"type": "number", "minimum": 0, "maximum": 500},
                "rows": {"type": "integer", "minimum": 1, "maximum": 50},
                "rowDirection": direction, "rowHeadingDegrees": heading,
                "rowSpacing": METRES, "rowGap": {"type": "number", "minimum": 0, "maximum": 500},
                "side": direction, "lineX": {"type": "number"}, "lineZ": {"type": "number"},
                "linePoints": {"type": "array", "minItems": 2, "maxItems": 2, "items": POINT},
                "center": POINT, "origin": POINT,
                "totalDegrees": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
                "turnWithPattern": {"type": "boolean"},
                "shape": {"enum": ["rectangle", "square"]},
                "widthCount": {"type": "integer", "minimum": 1, "maximum": 50},
                "depthCount": {"type": "integer", "minimum": 1, "maximum": 50},
                "turnDegrees": heading,
                "removeIds": _schema_ids(0, 240)}}},
        {"name": CELL_TOOL, "description": (
        "Plan a manufacturing cell with the ribbon's Cell Layout math, instead of writing coordinates: arrange "
        "placed machines (placementIds, in flow order) or place new ones (assets: [{assetId, count}], in order) "
        "as strategy line, l, u, grid, parallel, serpentine, loop, spine, herringbone or cluster. zoneId centres "
        "the cell in that zone, and it must fit; center {x, z} centres it on a point; with neither, placed "
        "machines keep their centre. width and depth size the cell (default: from the largest machine and gap, "
        "1 m by default; gap is a preferred spacing, not an exact clearance); rows for grid, parallel and "
        "serpentine. turnDegrees turns the cell clockwise; openSide is the side a U opens to; an unturned L runs "
        "up its west side and along its north side. facing operator-inside (the default) turns each machine's "
        "reviewed operator side square into the cell: U, L and loop the inside, cluster the centre, spine the "
        "spine, rows toward operatorSide (default the right of the flow: south for an unturned row); face-center "
        "and face-outward turn it toward or away from the cell's centre, for any strategy (machines round a "
        "circle, all facing its centre: cluster, or loop with face-center). operatorSides in the summary says "
        "which way they face: tell the user that, not the facing you asked for. "
        "removeIds: placements or floor markings to delete in the same review, such as a zone's old machines. A "
        "saved walk that stops at one of them (or is walked by one) goes in the same change, with the stops only it "
        "uses; every other walk stays as it is. alsoRemoves in the summary names each walk that goes: say it, word "
        "for word. clearZone true (with zoneId) clears the zone first: it removes every item and floor marking "
        "standing there, except the building's columns and structure, locked items and what is mounted on them, and "
        "cleared in the summary names what goes and what stays: say it, word for word. Never look up the zone's "
        "items for it. With clearZone and no strategy or machines, the zone is only cleared. "
        "action group (not arrange, the default): make a manufacturing cell zone round itemIds (placements, floor "
        "markings, or a zone for what stands in it; what sits on them comes too), envelopePadding metres round them "
        "(default 1), named name, prefix and number: \"Assembly Cell A09\" is name Assembly Cell, prefix A, "
        "number 9 (default name Manufacturing Cell, no prefix, the next free number). Nothing moves; refused when the "
        "cell would take in items not named. action ungroup: remove the cell zoneId; its items stay. "
        "Read-only: stage the packageId with preview_planned_design."),
        "input_schema": {"type": "object", "additionalProperties": False,
            "properties": {
                "strategy": {"enum": list(lp.CELL_SHAPES)},
                "placementIds": _schema_ids(2, 50),
                "assets": {"type": "array", "minItems": 1, "maxItems": 10, "items": {
                    "type": "object", "additionalProperties": False, "required": ["assetId", "count"],
                    "properties": {"assetId": ID, "count": {"type": "integer", "minimum": 1, "maximum": 50}}}},
                "zoneId": ID,
                "center": {"type": "object", "additionalProperties": False, "required": ["x", "z"],
                           "properties": {"x": {"type": "number"}, "z": {"type": "number"}}},
                "width": METRES, "depth": METRES, "gap": {"type": "number", "minimum": 0, "maximum": 50},
                "rows": {"type": "integer", "minimum": 1, "maximum": 50},
                "turnDegrees": heading, "openSide": direction, "facing": {"enum": list(FACINGS)},
                "operatorSide": direction, "removeIds": _schema_ids(0, 240), "clearZone": {"type": "boolean"},
                "action": {"enum": ["arrange", "group", "ungroup"]}, "itemIds": _schema_ids(1, 240),
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "prefix": {"type": "string", "maxLength": 8, "pattern": "^[A-Za-z0-9-]*$"},
                "number": {"type": "integer", "minimum": 0, "maximum": 9999},
                "envelopePadding": {"type": "number", "minimum": 0, "maximum": 10}}}}]


# ---------------------------------------------------------------- reading the layout

def _index(layout: Mapping) -> dict:
    found = {}
    for collection, key in (("placements", "placementId"), ("zones", "zoneId"), ("floorMarkings", "markingId"),
                            ("routes", "routeId")):
        for item in layout.get(collection) or []:
            if isinstance(item, Mapping) and isinstance(item.get(key), str):
                found[item[key]] = (collection, item)
    return found


def _label(entity: Mapping, fallback: str) -> str:
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), Mapping) else {}
    text = metadata.get("instanceLabel") or entity.get("label") or entity.get("displayName")
    return f"{text} ({fallback})" if text else fallback


def _named(index: Mapping, identifier: str) -> str:
    return _label(index[identifier][1], identifier) if identifier in index else identifier


def _relation(placement: Mapping) -> Mapping:
    value = placement.get("snapRelationship")
    return value if isinstance(value, Mapping) else {}


def _attached(placement: Mapping) -> str | None:
    relation = _relation(placement)
    support = relation.get("supportPlacementId")
    return support if relation.get("family") == "surface_attachment" and isinstance(support, str) and support else None


def _namespace(tool: str, arguments: Mapping, revision: str) -> str:
    """Stable per plan: the same request on the same revision gives the same ids."""
    text = json.dumps({"tool": tool, "arguments": arguments, "revision": revision}, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _base36(number: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    text = ""
    while True:
        number, remainder = divmod(number, 36)
        text = digits[remainder] + text
        if not number:
            return text


def _builder_angle(arguments: Mapping, direction_key: str, heading_key: str, what: str) -> float:
    """A compass direction or heading as the builders' angle: 0 is +x (east) and 90 is -z (south)."""
    direction, heading = arguments.get(direction_key), arguments.get(heading_key)
    if (direction is None) == (heading is None):
        raise PatternError(f"Give {what} as {direction_key} (north, east, south or west) or {heading_key}, one of "
                           "them.")
    compass = COMPASS_HEADINGS[direction] if direction is not None else float(heading)
    return lp.normalize_degrees(compass - 90)


def _compass_name(heading: float) -> str:
    value = lp.normalize_degrees(heading) % 360
    for name, degrees in COMPASS_HEADINGS.items():
        if abs(value - degrees) < 1e-6 or abs(value - degrees - 360) < 1e-6:
            return name
    return f"{value:.0f} degrees"


BEARINGS = {"north": 0, "north-east": 45, "east": 90, "south-east": 135, "south": 180, "south-west": 225,
            "west": 270, "north-west": 315}


def _bearing(heading: float) -> str:
    value = lp.normalize_degrees(heading) % 360
    for name, degrees in BEARINGS.items():
        if abs(value - degrees) < 0.5 or abs(value - degrees - 360) < 0.5:
            return name
    return f"{value:.0f} degrees"


def _side_faces(heading: float, position: Mapping, center: Mapping | None) -> str:
    """Which way a side at compass HEADING faces: its bearing, and (round a cell's CENTER) toward or away from it."""
    if center is None or math.hypot(center["x"] - position["x"], center["z"] - position["z"]) < 1e-6:
        return _bearing(heading)
    toward = lp.tangent_heading({"x": center["x"] - position["x"], "z": center["z"] - position["z"]})
    apart = abs((heading - toward + 180) % 360 - 180)
    where = ("the centre" if apart < 1 else "into the cell" if apart < 89 else "along the cell" if apart <= 91
             else "out of the cell" if apart <= 179 else "away from the centre")
    return f"{_bearing(heading)} ({where})"


def _sides_said(machines: Sequence[Mapping]) -> str:
    """One sentence for Sage to repeat: which way the machines' reviewed operator sides face."""
    reviewed = [machine for machine in machines if "operatorFaces" in machine]
    missing = [machine["label"] for machine in machines if "operatorFaces" not in machine]
    if not reviewed:
        return "No machine has a reviewed operator side: their facing is unverified."
    tail = (f" {', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no reviewed operator side: facing "
            "unverified." if missing else "")
    places = [machine["operatorFaces"].partition(" (")[2].rstrip(")") or machine["operatorFaces"]
              for machine in reviewed]
    lead = {1: "The one reviewed operator side faces", 2: "Both operator sides face"}.get(
        len(reviewed), f"All {len(reviewed)} operator sides face")
    for together, said in ((("the centre",), "the centre"), (("the centre", "into the cell"), "into the cell"),
                           (("away from the centre",), "away from the centre"),
                           (("away from the centre", "out of the cell"), "out of the cell")):
        if all(place in together for place in places):
            return f"{lead} {said}.{tail}"
    if len(set(places)) == 1:
        return f"{lead} {places[0]}.{tail}"
    groups: dict[str, list] = {}
    for machine, place in zip(reviewed, places):
        groups.setdefault(place, []).append(machine["label"])
    listed = "; ".join(f"{place} ({', '.join(labels)})" for place, labels in groups.items())
    return f"Operator sides face {listed}.{tail}"


def _round(value: float) -> float:
    return round(value + 0.0, 3) + 0.0


def _point(value: Mapping) -> dict:
    return {"x": _round(value["x"]), "z": _round(value["z"])}


# ---------------------------------------------------------------- guards (the command adapter's)

def _check_seed(layout: Mapping, index: Mapping, seed: Sequence[Mapping]) -> None:
    selected = {item["id"] for item in seed}
    for item in seed:
        if item.get("positionMode") == "locked":
            raise PatternError(f"{_named(index, item['id'])} is locked. Ask the user to unlock it, or leave it out.")
        relation = item.get("snapRelationship") or {}
        if relation.get("family") == "vertical_stack":
            raise PatternError(f"{_named(index, item['id'])} is part of a stack; stacks cannot be patterned yet.")
        support = relation.get("supportPlacementId")
        if support and support not in selected:
            raise PatternError(f"{_named(index, item['id'])} sits on {_named(index, support)}: include its support.")
    for placement in layout.get("placements") or []:
        support = _relation(placement).get("supportPlacementId")
        if support in selected and placement.get("placementId") not in selected:
            raise PatternError(f"{_named(index, placement['placementId'])} sits on {_named(index, support)}: "
                               "include every item attached to a support.")


def _pattern_seed(layout: Mapping, catalog: list, ids: Sequence[str], include_zones: bool = True) -> list:
    index = _index(layout)
    for identifier in ids:
        if identifier not in index:
            raise PatternError(f"There is no {identifier} in the saved layout.")
        if index[identifier][0] == "routes":
            raise PatternError(f"{_named(index, identifier)} is a route; routes cannot be patterned.")
    for identifier in ids:
        if index[identifier][0] != "zones":
            continue
        zone = index[identifier][1]
        for other in layout.get("zones") or []:
            if other.get("zoneId") != identifier and (other.get("parentZoneId") == identifier or any(
                    lp.point_in_polygon(point, zone.get("boundary")) for point in other.get("boundary") or [])):
                raise PatternError(f"{_named(index, identifier)} has another zone inside or across it; a zone with "
                                   "zones inside cannot be patterned yet.")
    try:
        seed = lp.collect_selection(layout, catalog, list(ids),
                                    {"expandZones": True, "includeZones": include_zones, "strictGeometry": True})
    except PatternError as error:
        raise PatternError(f"{error}: an item's model revision or size is not in the library.") from error
    _check_seed(layout, index, seed)
    return seed


def _cell_seed(layout: Mapping, catalog: list, ids: Sequence[str]) -> list:
    index = _index(layout)
    for identifier in ids:
        if identifier not in index or index[identifier][0] != "placements":
            raise PatternError(f"{identifier} is not a placed item in the saved layout; a cell arranges placements.")
    try:
        seed = lp.collect_selection(layout, catalog, list(ids),
                                    {"expandZones": False, "includeZones": False, "strictGeometry": True})
    except PatternError as error:
        raise PatternError(f"{error}: a machine's model revision or size is not in the library.") from error
    _check_seed(layout, index, seed)
    attached = next((item for item in seed if item.get("snapRelationship")), None)
    if attached:
        raise PatternError(f"{_named(index, attached['id'])} is attached to another item; arrange the machines "
                           "before attaching anything to them.")
    return seed


def _removals(layout: Mapping, remove_ids: Sequence[str], kept: set) -> tuple[list, list, list]:
    """Delete operations for the items Sage names, and their attached items (as the ribbon's delete does), then the
    removal of the saved walks they strand; with the removed items' names and the walks' names."""
    index = _index(layout)
    wanted = list(dict.fromkeys(remove_ids))
    changed = True
    while changed:  # attached items go with their support
        changed = False
        for placement in layout.get("placements") or []:
            if placement.get("placementId") not in wanted and _attached(placement) in wanted:
                wanted.append(placement["placementId"])
                changed = True
    operations, labels = [], []
    for identifier in wanted:
        if identifier not in index:
            raise PatternError(f"There is no {identifier} to remove in the saved layout.")
        collection, entity = index[identifier]
        if identifier in kept:
            raise PatternError(f"{_named(index, identifier)} is part of the plan; it cannot also be removed.")
        if collection == "placements":
            if entity.get("positionMode") == "locked":
                raise PatternError(f"{_named(index, identifier)} is locked; ask the user before removing it.")
            operations.append({"op": "delete_placement", "placementId": identifier})
        elif collection == "floorMarkings":
            operations.append({"op": "delete_floor_marking", "markingId": identifier})
        else:
            raise PatternError(f"{_named(index, identifier)} is a {collection[:-1]}; removeIds takes placements and "
                               "floor markings (a zone stays).")
        labels.append(_named(index, identifier))
    walks, walk_removal = _walks_that_go(layout, index, operations)
    return [*operations, *([walk_removal] if walk_removal else [])], labels, walks


def _plain(index: Mapping, identifier: str, note: str | None = None) -> str:
    """An item's name as the user reads it (no id): 'A05 kit cart', 'A05 kit cart bay (floor marking)', with NOTE in
    the same brackets: 'Column C-5 (building structure)'."""
    collection, entity = index.get(identifier, ("", {}))
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), Mapping) else {}
    name = metadata.get("instanceLabel") or entity.get("label") or entity.get("displayName") or entity.get("text")
    notes = [*(["floor marking"] if collection == "floorMarkings" else []), *([note] if note else [])]
    return f"{name or identifier}" + (f" ({', '.join(notes)})" if notes else "")


def _listed(names: Sequence[str], limit: int = CLEARED_LISTED) -> str:
    shown = list(names[:limit])
    if len(names) > limit:
        shown.append(f"{len(names) - limit} more")
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _in_zone(entity: Mapping, boundary: Any) -> bool:
    """In the zone as the ribbon's zone selection reads it: its position inside the zone's outline."""
    transform = entity.get("transform")
    return lp.point_in_polygon(transform.get("position") if isinstance(transform, Mapping) else None, boundary)


def _clearing(layout: Mapping, catalog: list, index: Mapping, zone: Mapping, arranged: set,
              removing: set) -> tuple[list, list]:
    """clearZone: the placements and floor markings standing in ZONE that go, and what stays there, named with why:
    the building's structure, a locked item, an item mounted on one that stays. The machines the cell arranges stay
    and are not named (they are the cell); REMOVING (removeIds) goes anyway."""
    records = {record.get("assetId"): record for record in catalog if isinstance(record, Mapping)}
    boundary = zone.get("boundary")
    going, kept = [], []
    for placement in layout.get("placements") or []:
        identifier = placement.get("placementId") if isinstance(placement, Mapping) else None
        if not isinstance(identifier, str) or identifier in arranged or not _in_zone(placement, boundary):
            continue
        if (records.get(placement.get("assetId")) or {}).get("category") in STRUCTURE:
            kept.append(_plain(index, identifier, "building structure"))
        elif placement.get("positionMode") == "locked":
            kept.append(_plain(index, identifier, "locked"))
        else:
            going.append(identifier)
    while True:  # mounted on an item that stays (outside the zone, or kept): it stays with it
        staying = next((identifier for identifier in going if (support := _attached(index[identifier][1]))
                        and support not in going and support not in removing), None)
        if staying is None:
            break
        going.remove(staying)
        kept.append(_plain(index, staying, f"on {_plain(index, _attached(index[staying][1]))}, which stays"))
    for marking in layout.get("floorMarkings") or []:
        identifier = marking.get("markingId") if isinstance(marking, Mapping) else None
        if isinstance(identifier, str) and _in_zone(marking, boundary):
            if marking.get("positionMode") == "locked":
                kept.append(_plain(index, identifier, "locked"))
            else:
                going.append(identifier)
    return going, kept


def _cleared(index: Mapping, zone: Mapping, operations: Sequence[Mapping], kept: Sequence[str]) -> str:
    """The sentence Sage repeats: what the change removes and what stays in the zone."""
    gone = [_plain(index, operation.get("placementId") or operation.get("markingId")) for operation in operations
            if operation["op"] in ("delete_placement", "delete_floor_marking")]
    where = _plain(index, zone["zoneId"])
    text = f"Clears {where}: removes {_listed(gone)}." if gone else f"There was nothing to clear in {where}."
    return text + (f" Keeps {_listed(kept)}." if kept else "")


def _clear_only(layout: Mapping, catalog: list, index: Mapping, zone: Mapping, arguments: Mapping) -> dict:
    """clearZone with no machines: the zone is cleared, nothing is placed."""
    removing = list(arguments.get("removeIds") or [])
    clearing, kept = _clearing(layout, catalog, index, zone, set(), set(removing))
    removals, removed, walks = _removals(layout, [*removing, *clearing], set())
    if not removals:
        where = _plain(index, zone["zoneId"])
        raise PatternError(f"There is nothing to clear in {where}" + (f": {_listed(kept)} stays." if len(kept) == 1
                           else f": {_listed(kept)} stay." if kept else "."))
    return {"available": True, "cleared": _cleared(index, zone, removals, kept), "removed": removed,
            **({"alsoRemoves": _also_removes(walks)} if walks else {}), "operations": removals}


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _stops(program: Mapping) -> set:
    """Every navigation anchor a saved walk needs: its required anchors and its ordered stops."""
    return set(program.get("requiredAnchorIds") or []) | {
        stop.get("navigationAnchorId") for stop in program.get("orderedStops") or [] if isinstance(stop, Mapping)}


def _walk_name(index: Mapping, program: Mapping) -> str:
    """'the A05 operator's saved walk (4 stops)': its walker and the places it stops at."""
    walker = program.get("actorPlacementId")
    entity = index[walker][1] if walker in index else {}
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), Mapping) else {}
    who = metadata.get("instanceLabel") or entity.get("label")
    places = len({stop.get("navigationAnchorId") for stop in program.get("orderedStops") or []
                  if isinstance(stop, Mapping)})
    count = f"{places} stop{'' if places == 1 else 's'}"
    return f"the {who}'s saved walk ({count})" if who else f"saved walk {program.get('movementProgramId')} ({count})"


def _also_removes(walks: Sequence[str]) -> str:
    listed = walks[0] if len(walks) == 1 else ", ".join(walks[:-1]) + " and " + walks[-1]
    return f"Also removes {listed}."


def _walks_that_go(layout: Mapping, index: Mapping, deletions: Sequence[Mapping]) -> tuple[list, dict | None]:
    """The saved walks these deletions strand (a stop's item or the walker deleted), named, and the one operation
    that removes them with the stops only they use, for the same package (operations.py, delete_stranded_movements).
    The user (2026-11-01): "let sage remove the walk in the same change", naming every walk it removes. Every other
    walk stays as it is: a handoff to a walk that stays, or a stop that goes under a kept walk's drawn path, is
    refused here, in words."""
    navigation = (layout.get("extensions") or {}).get("facilityNavigation")
    if not isinstance(navigation, Mapping):
        return [], None
    deleted = {operation["placementId"] for operation in deletions if operation["op"] == "delete_placement"}
    erased = {operation["markingId"] for operation in deletions if operation["op"] == "delete_floor_marking"}
    remaining = {**layout,
                 "placements": [item for item in layout.get("placements") or []
                                if isinstance(item, Mapping) and item.get("placementId") not in deleted],
                 "floorMarkings": [item for item in layout.get("floorMarkings") or []
                                   if isinstance(item, Mapping) and item.get("markingId") not in erased]}
    identities = navigation_identity_index(remaining)
    anchors = [item for item in navigation.get("anchors") or [] if isinstance(item, Mapping)]
    gone = {item.get("navigationAnchorId") for item in anchors if navigation_anchor_dangles(item, identities)}
    programs = [item for item in navigation.get("movementPrograms") or [] if isinstance(item, Mapping)]
    stranded = [item for item in programs
                if item.get("actorPlacementId") not in identities.placement_ids or _stops(item) & gone]
    if not stranded and not gone:
        return [], None
    going = {item.get("movementProgramId") for item in stranded}
    names = {item.get("movementProgramId"): _walk_name(index, item) for item in programs}
    for item in navigation.get("handoffPrograms") or []:
        taking_part = ({item.get("sourceMovementProgramId"), item.get("targetMovementProgramId")}
                       if isinstance(item, Mapping) else set())
        if taking_part & going and taking_part - going:
            goes, stays = (names.get(min(ids)) for ids in (taking_part & going, taking_part - going))
            raise PatternError(f"Removing those items would also remove {goes}, which hands work to {stays}. Sage "
                               f"cannot change {stays}: leave the items {goes} stops at out of removeIds, or ask the "
                               "user.")
    in_use = set()
    for item in programs:
        if item.get("movementProgramId") not in going:
            in_use |= _stops(item)
    for item in navigation.get("manualPathConstraints") or []:
        if isinstance(item, Mapping) and item.get("movementProgramId") not in going:
            if any(isinstance(snap, Mapping) and snap.get("refKind") == "navigation_anchor"
                   and snap.get("refId") in gone for snap in item.get("snapRefs") or []):
                stays = names.get(item.get("movementProgramId"))
                raise PatternError(f"The path drawn for {stays} snaps to a stop at an item in removeIds. Sage cannot "
                                   "change that walk: leave the item out of removeIds, or ask the user.")
    walked = set()
    for item in stranded:
        walked |= _stops(item)
    stops = gone | (walked - in_use)
    return [names[item.get("movementProgramId")] for item in stranded], {
        "op": "delete_stranded_movements",
        "movementProgramIds": [item.get("movementProgramId") for item in stranded],
        "navigationAnchorIds": [item.get("navigationAnchorId") for item in anchors
                                if item.get("navigationAnchorId") in stops]}


# ---------------------------------------------------------------- operations (the session's)

def _world_position(value: Mapping) -> dict:
    return {"x": float(value["x"]), "y": float(value.get("y", 0) or 0), "z": float(value["z"])}


def _world_point(value: Mapping) -> dict:
    return {"x": float(value["x"]), "z": float(value["z"])}


def _rotate_floor_vector(value: Mapping, degrees: float) -> dict:
    radians = float(degrees) * math.pi / 180
    cosine, sine = math.cos(radians), math.sin(radians)
    result = {"x": float(value["x"]) * cosine + float(value["z"]) * sine,
              "z": -float(value["x"]) * sine + float(value["z"]) * cosine}
    for key in ("x", "z"):
        if abs(result[key]) < 1e-12:
            result[key] = 0
    return result


def _transform_floor_point(value: Mapping, source: Mapping, target: Mapping, degrees: float) -> dict:
    point, origin, goal = _world_point(value), _world_point(source), _world_point(target)
    rotated = _rotate_floor_vector({"x": point["x"] - origin["x"], "z": point["z"] - origin["z"]}, degrees)
    return {"x": goal["x"] + rotated["x"], "z": goal["z"] + rotated["z"]}


def _transformed_zone_anchor(anchor: Mapping, copy: Mapping) -> dict:
    result = deepcopy(dict(anchor))
    if copy.get("mirrored") is True and copy.get("mirrorAxis"):  # R2
        start, end = _world_point(copy["mirrorAxis"]["start"]), _world_point(copy["mirrorAxis"]["end"])
        dx, dz = end["x"] - start["x"], end["z"] - start["z"]
        length = math.hypot(dx, dz)
        if not length > 1e-9:
            raise PatternError("pattern mirror axis is invalid")
        unit = {"x": dx / length, "z": dz / length}
        if result.get("position"):
            point = _world_point(result["position"])
            offset = {"x": point["x"] - start["x"], "z": point["z"] - start["z"]}
            projection = offset["x"] * unit["x"] + offset["z"] * unit["z"]
            result["position"] = {**result["position"], "x": start["x"] + 2 * projection * unit["x"] - offset["x"],
                                  "z": start["z"] + 2 * projection * unit["z"] - offset["z"]}
        if result.get("facing"):
            facing = _world_point(result["facing"])
            projection = facing["x"] * unit["x"] + facing["z"] * unit["z"]
            result["facing"] = {**result["facing"], "x": 2 * projection * unit["x"] - facing["x"],
                                "z": 2 * projection * unit["z"] - facing["z"]}
        return result
    delta = copy.get("rotationDeltaDegrees") or 0
    if result.get("position"):
        result["position"] = {**result["position"], **_transform_floor_point(
            result["position"], copy["sourceAnchor"], copy["targetAnchor"], delta)}
    if result.get("facing"):
        result["facing"] = {**result["facing"], **_rotate_floor_vector(result["facing"], delta)}
    return result


def _cell_group(zone: Mapping) -> dict | None:
    extensions = zone.get("extensions") if isinstance(zone.get("extensions"), Mapping) else {}
    group = extensions.get("cellGroup")
    return group if isinstance(group, dict) and group.get("groupKind") == "manufacturing_cell" else None


def _js_number_or(value: Any, fallback: float) -> float:
    """Number(value) || fallback: NaN and 0 take the fallback."""
    number = lp.finite(value, math.nan)
    return fallback if not number or math.isnan(number) else number


def _cell_group_label(auto_number: Mapping) -> str:
    base = str(auto_number.get("baseName") or "Cell").strip() or "Cell"
    prefix = str(auto_number.get("prefix") or "").strip()
    sequence = max(0, lp.js_round(_js_number_or(auto_number.get("sequence"), 0)))
    padding = max(1, min(6, lp.js_round(_js_number_or(auto_number.get("padding"), 2))))
    suffix = prefix + str(sequence).rjust(padding, "0")
    return base + (" " + suffix if suffix else "")


def _transformed_cell_interfaces(zone: dict, copy: Mapping) -> None:
    group = _cell_group(zone)
    source = group.get("functionalInterfaces") if group else None
    if not isinstance(source, dict):
        return
    vectors = {"north": {"x": 0, "z": 1}, "east": {"x": 1, "z": 0}, "south": {"x": 0, "z": -1},
               "west": {"x": -1, "z": 0}}

    def cardinal(vector):
        if abs(vector["x"]) <= 1e-6:
            if abs(vector["z"] - 1) <= 1e-6:
                return "north"
            if abs(vector["z"] + 1) <= 1e-6:
                return "south"
        if abs(vector["z"]) <= 1e-6:
            if abs(vector["x"] - 1) <= 1e-6:
                return "east"
            if abs(vector["x"] + 1) <= 1e-6:
                return "west"
        return ""

    for record in source.values():
        if not isinstance(record, dict):
            continue
        if record.get("position"):
            record["position"] = _transformed_zone_anchor({"position": record["position"]}, copy)["position"]
        if isinstance(record.get("accessEnvelope"), list):
            record["accessEnvelope"] = [_transformed_zone_anchor({"position": point}, copy)["position"]
                                        for point in record["accessEnvelope"]]
            if copy.get("mirrored") is True:
                record["accessEnvelope"].reverse()
        facing = record.get("facing") or vectors.get(record.get("side"))
        if not facing:
            continue
        turned = _transformed_zone_anchor({"facing": {"x": facing["x"], "y": 0, "z": facing["z"]}}, copy)["facing"]
        side = cardinal(turned)
        if side:
            record["side"] = side
            record.pop("facing", None)
        else:
            record.pop("side", None)
            record["facing"] = {"x": turned["x"], "z": turned["z"]}
        record["evidenceStatus"] = "derived"


class _Ids:
    """The session's id sequences, in one plan's namespace."""

    def __init__(self, namespace: str):
        self.namespace, self.placements, self.attachments = namespace, 0, 0

    def placement(self) -> str:
        self.placements += 1
        return f"pl-surface-copy-{self.namespace}-{_base36(self.placements)}"

    def attachment(self, source: str) -> str:
        self.attachments += 1
        return f"{source or 'surface'}:copy:{self.namespace}:{_base36(self.attachments)}"


def _provenance(namespace: str, command: str, strategy: str | None, sources: Sequence[str], count: int,
                seed_count: int, guide: Mapping) -> dict:
    return {"schemaVersion": 1, "provenanceId": f"layout-pattern:{namespace}:1", "command": command,
            "authoredStrategy": strategy, "seedEntityIds": sorted(set(sources)),
            "parameters": {"count": count, "seedCount": seed_count, **deepcopy(dict(guide))},
            "manuallyEditedSinceCreation": False}


def _copy_operations(layout: Mapping, copies: Sequence[Mapping], provenance: Mapping, ids: _Ids) -> list:
    """patternCopyOperation for each copy: duplicates, floor markings and zones, as the ribbon sends them."""
    index = _index(layout)
    groups: dict[str, list] = {}
    for copy in copies:  # patternDuplicateContexts: one id map per instance, when it copies a support group
        if copy["kind"] != "placement" or copy["sourceId"] not in index:
            continue
        group = groups.setdefault(f"instance:{copy['instanceIndex']}", [])
        if copy["sourceId"] not in group:
            group.append(copy["sourceId"])
    contexts = {}
    for key, sources in groups.items():
        placed = {identifier: index[identifier][1] for identifier in sources}
        copies_group = any(_attached(placement) in placed for placement in placed.values())
        contexts[key] = {"placementIds": {identifier: ids.placement() for identifier in sources} if copies_group
                         else {}, "attachmentIds": {}}
    sequences: dict[str, int] = {}
    for zone in layout.get("zones") or []:
        auto = (_cell_group(zone) or {}).get("autoNumber")
        if isinstance(auto, Mapping) and auto.get("seriesId"):
            sequence = max(0, lp.js_round(_js_number_or(auto.get("sequence"), 0)))
            sequences[auto["seriesId"]] = max(sequences.get(auto["seriesId"], 0), sequence)
    operations = []
    for copy in copies:
        stamped = {**deepcopy(dict(provenance)), "instanceIndex": copy["instanceIndex"]}
        collection, source = index[copy["sourceId"]]
        if copy["kind"] == "placement" and collection == "placements":
            context = contexts.get(f"instance:{copy['instanceIndex']}")
            operation = {"op": "duplicate_placement", "sourcePlacementId": copy["sourceId"],
                         "position": _world_position(copy["position"]), "positionMode": "manual",
                         "layoutProvenance": stamped}
            if context and copy["sourceId"] in context["placementIds"]:
                operation["newPlacementId"] = context["placementIds"][copy["sourceId"]]
            relationship = None
            support = _attached(source)
            if context and support in context["placementIds"]:
                relation = _relation(source)
                attachment = str(relation.get("attachmentId") or support + ":surface")
                if attachment not in context["attachmentIds"]:
                    context["attachmentIds"][attachment] = ids.attachment(attachment)
                relationship = {**deepcopy(dict(relation)), "attachmentId": context["attachmentIds"][attachment],
                                "supportPlacementId": context["placementIds"][support]}
            if copy.get("snapRelationship") or relationship:
                operation["snapRelationship"] = deepcopy(copy.get("snapRelationship") or relationship)
            if copy.get("mirrored") is True:
                operation["quaternion"] = yaw_quaternion(copy["rotationDegrees"])
            elif abs(float(copy.get("rotationDeltaDegrees") or 0)) > 1e-9:  # circular and perimeter copies turn
                operation["quaternion"] = _turned(copy["rotationDeltaDegrees"],
                                                  (source.get("transform") or {}).get("quaternion"))
            operations.append(operation)
        elif copy["kind"] == "floor-marking" and collection == "floorMarkings":
            value = deepcopy(dict(source))
            value.pop("markingId", None)
            value["transform"] = {"position": _world_position(copy["position"]),
                                  "rotationDegrees": float(copy["rotationDegrees"])}
            value["positionMode"] = "manual"
            value["metadata"] = {**deepcopy(value.get("metadata") or {}), "layoutProvenance": stamped}
            operations.append({"op": "add_floor_marking", "floorMarking": value})
        elif copy["kind"] == "zone" and collection == "zones":
            value = deepcopy(dict(source))
            value.pop("zoneId", None)
            value["boundary"] = [_world_point(point) for point in copy.get("boundary") or []]
            value["anchors"] = [_transformed_zone_anchor(anchor, copy) for anchor in value.get("anchors") or []]
            auto = (_cell_group(value) or {}).get("autoNumber")
            if isinstance(auto, dict) and auto.get("seriesId"):
                sequences[auto["seriesId"]] = sequences.get(auto["seriesId"], 0) + 1
                auto["sequence"] = sequences[auto["seriesId"]]
                value["label"] = _cell_group_label(auto)
            _transformed_cell_interfaces(value, copy)
            value["extensions"] = {**deepcopy(value.get("extensions") or {}), "layoutProvenance": stamped}
            operations.append({"op": "add_zone", "zone": value})
        else:
            raise PatternError(f"pattern source '{copy['sourceId']}' does not match kind '{copy['kind']}'")
    return operations


def _session_quaternion(value: Mapping | None) -> dict:
    """The session's quaternion(): unit length, parts under 1e-12 set to zero."""
    source = value if isinstance(value, Mapping) else {"x": 0, "y": 0, "z": 0, "w": 1}
    parts = {key: float(source[key]) for key in "xyzw"}
    magnitude = math.hypot(*parts.values())
    if not magnitude:
        raise PatternError("quaternion cannot have zero length")
    unit = {key: part / magnitude for key, part in parts.items()}
    return {key: 0.0 if abs(part) < 1e-12 else part for key, part in unit.items()}


def _turned(degrees: float, value: Mapping | None) -> dict:
    """multiplyQuaternion(yawQuaternion(delta), the placement's quaternion), as the session turns a copy, with the
    sign the layout keeps (the first nonzero of w, x, y, z positive), as the server stores it."""
    angle = float(degrees) * math.pi / 180
    left = _session_quaternion({"x": 0, "y": math.sin(angle / 2), "z": 0, "w": math.cos(angle / 2)})
    right = _session_quaternion(value)
    product = _session_quaternion({
        "x": left["w"] * right["x"] + left["x"] * right["w"] + left["y"] * right["z"] - left["z"] * right["y"],
        "y": left["w"] * right["y"] - left["x"] * right["z"] + left["y"] * right["w"] + left["z"] * right["x"],
        "z": left["w"] * right["z"] + left["x"] * right["y"] - left["y"] * right["x"] + left["z"] * right["w"],
        "w": left["w"] * right["w"] - left["x"] * right["x"] - left["y"] * right["y"] - left["z"] * right["z"]})
    first = next((product[key] for key in "wxyz" if product[key] != 0), 0.0)
    sign = -1.0 if first < 0 else 1.0
    return {key: sign * product[key] + 0.0 for key in "xyzw"}


def _with_seed_provenance(operations: list, provenance: Mapping, seed_ids: Sequence[str]) -> list:
    """As the session does: the first operation carries the provenance and names the seeds."""
    if operations:
        operations[0]["layoutProvenance"] = deepcopy(dict(provenance))
        operations[0]["layoutProvenanceSeedEntityIds"] = list(seed_ids)
    return operations


# ---------------------------------------------------------------- plan_facility_pattern

def _pitch(items: Sequence[Mapping], angle: float, arguments: Mapping, spacing_key: str, gap_key: str,
           what: str) -> float:
    spacing, gap = arguments.get(spacing_key), arguments.get(gap_key)
    if (spacing is None) == (gap is None):
        raise PatternError(f"Give the {what} as {spacing_key} (centre to centre) or {gap_key} (clear space), one "
                           "of them.")
    if spacing is not None:
        return float(spacing)
    return lp.oriented_selection_bounds(items, angle)["width"] + float(gap)


def _moved_item(item: Mapping, copy: Mapping) -> dict:
    return {**item, "position": copy["position"], "rotationDegrees": copy["rotationDegrees"],
            **({"boundary": copy["boundary"]} if copy.get("boundary") is not None else {})}


def _check_kind(arguments: Mapping) -> str:
    kind = arguments.get("kind") or "linear"
    if kind not in KINDS:
        raise PatternError(f"kind is linear, mirror, circular or perimeter, not {kind}.")
    others = [key for key, value in arguments.items()
              if value is not None and key not in ("kind", "seedIds", "removeIds", *KIND_PARAMETERS[kind])]
    if others:
        one = len(others) == 1
        raise PatternError(f"{', '.join(others)} {'is' if one else 'are'} not used by a {kind} pattern; leave "
                           f"{'it' if one else 'them'} out.")
    if kind in ("linear", "circular") and arguments.get("count") is None:
        raise PatternError(f"Give count for a {kind} pattern: how many in all, the seed included.")
    return kind


def _check_capacity(seed: Sequence[Mapping], instances: int) -> None:
    if len(seed) * (instances - 1) > lp.MAX_PATTERN_OBJECTS:
        raise PatternError(f"{len(seed)} items x {instances} instances would make more than "
                           f"{lp.MAX_PATTERN_OBJECTS} new items; make the pattern smaller or pattern in steps.")


def _linear_at(seed: list, arguments: Mapping, count: int, rows: int, angle: float,
               row_angle: float | None) -> tuple:
    """The row (and grid) at the builders' ANGLE, its rows going ROW_ANGLE."""
    pitch = _pitch(seed, angle, arguments, "spacing", "gap", "row's spacing")
    row = lp.build_linear_pattern(seed, {"count": count, "pitch": pitch, "angleDegrees": angle})
    copies, guide = row["copies"], dict(row["guide"])
    center, direction = guide["start"], lp.rotate_vector({"x": 1, "z": 0}, angle)
    row_pitch, row_gap, across = None, None, {"x": 0, "z": 0}
    if rows > 1:
        first_row = [*seed, *(_moved_item(next(item for item in seed if item["id"] == copy["sourceId"]), copy)
                              for copy in copies)]
        apart = (arguments if arguments.get("rowSpacing") is not None or arguments.get("rowGap") is not None
                 or arguments.get("gap") is None else {"rowGap": arguments["gap"]})  # N m apart, both ways
        row_pitch = _pitch(first_row, row_angle, apart, "rowSpacing", "rowGap", "spacing between rows")
        row_gap = row_pitch - lp.oriented_selection_bounds(first_row, row_angle)["width"]
        across = lp.rotate_vector({"x": 1, "z": 0}, row_angle)
        for line in range(1, rows):
            for column in range(count):
                target = {"x": center["x"] + direction["x"] * pitch * column + across["x"] * row_pitch * line,
                          "z": center["z"] + direction["z"] * pitch * column + across["z"] * row_pitch * line}
                for item in seed:
                    copies.append(lp.transformed_copy(item, center, target, 0, line * count + column))
        guide.update({"rows": rows, "rowPitch": row_pitch, "rowEnd": {
            "x": guide["end"]["x"] + across["x"] * row_pitch * (rows - 1),
            "z": guide["end"]["z"] + across["z"] * row_pitch * (rows - 1)}})
    instances = []
    for line in range(rows):
        for column in range(count):
            instances.append({"index": line * count + column, "row": line, "column": column, "center": _point({
                "x": center["x"] + direction["x"] * pitch * column + across["x"] * (row_pitch or 0) * line,
                "z": center["z"] + direction["z"] * pitch * column + across["z"] * (row_pitch or 0) * line})})
    summary = {
        "count": count, "rows": rows, "instances": instances[:LISTED],
        **({"instancesNotListed": len(instances) - LISTED} if len(instances) > LISTED else {}),
        "direction": _compass_name(angle + 90), "spacing": _round(pitch),
        "gap": _round(pitch - lp.oriented_selection_bounds(seed, angle)["width"]),
        **({"rowDirection": _compass_name(row_angle + 90), "rowSpacing": _round(row_pitch),
            "rowGap": _round(row_gap)} if rows > 1 else {}),
    }
    return copies, guide, count, summary


def _plus(first: tuple, second: tuple) -> tuple:
    return first[0] + second[0], first[1] + second[1]


def _translated(seed: Sequence[Mapping], shift: tuple) -> list:
    """The seed moved by SHIFT (dx, dz) on the plan."""
    if not any(shift):
        return list(seed)
    return [{**item, "position": {**item["position"], "x": item["position"]["x"] + shift[0],
                                  "z": item["position"]["z"] + shift[1]}} for item in seed]


def _linear_ways(seed: list, arguments: Mapping, length: float, start: tuple) -> tuple[list, bool, bool]:
    """The ways a row or grid may go, by group of preference: the direction given, else along the seed's length
    (both ways), then across it; for a grid given no rowDirection, its rows on either side. And whether the tool
    chooses the direction, and the rows' side."""
    count, rows = int(arguments["count"]), int(arguments.get("rows") or 1)
    _check_capacity(seed, count * rows)
    given = arguments.get("direction") is not None or arguments.get("headingDegrees") is not None
    row_given = rows > 1 and (arguments.get("rowDirection") is not None
                              or arguments.get("rowHeadingDegrees") is not None)
    row_angle = (_builder_angle(arguments, "rowDirection", "rowHeadingDegrees", "the rows' direction") if row_given
                 else None)
    groups = ([[_builder_angle(arguments, "direction", "headingDegrees", "the row's direction")]] if given else
              [[length, lp.normalize_degrees(length + 180)],
               [lp.normalize_degrees(length + 90), lp.normalize_degrees(length - 90)]])
    ways = []
    for group, angles in enumerate(groups):
        for angle in angles:
            if row_angle is not None and abs(math.sin(math.radians(row_angle - angle))) < 1e-6:
                if given:
                    raise PatternError("rowDirection runs along the row; give a direction across it.")
                continue  # this way runs the way the rows go
            sides = ([None] if rows == 1 else [row_angle] if row_angle is not None
                     else [lp.normalize_degrees(angle + 90), lp.normalize_degrees(angle - 90)])
            for side in sides:
                ways.append({"group": group, "angle": angle, "rowAngle": side,
                             "build": lambda shift, a=angle, s=side: _linear_at(
                                 _translated(seed, _plus(start, shift)), arguments, count, rows, a, s)})
    return ways, not given, rows > 1 and not row_given


def _standing(index: Mapping, item: Mapping) -> bool:
    """A placement on the floor: not attached to a support (that stays within its support's footprint)."""
    return item["kind"] == "placement" and not (item["id"] in index and _attached(index[item["id"]][1]))


def _seed_length(index: Mapping, seed: Sequence[Mapping]) -> tuple[float, Mapping | None]:
    """The builders' angle along the seed's length, and the item it is read from: the largest placement standing on
    the floor, else the largest floor marking (its long side; its own +x for a square), else none (the seed's
    longer side on the plan)."""
    items = [item for item in seed if _standing(index, item)] or [item for item in seed if item["kind"] != "zone"]
    if not items:
        bounds = lp.selection_bounds(seed)
        return (0.0 if bounds["width"] >= bounds["depth"] else 90.0), None
    main = max(items, key=lambda item: item["width"] * item["depth"])
    return lp.normalize_degrees(main["rotationDegrees"] + (0.0 if main["width"] >= main["depth"] else 90.0)), main


def _area(points: Sequence[Mapping]) -> float:
    return abs(sum(a["x"] * b["z"] - b["x"] * a["z"] for a, b in zip(points, [*points[1:], *points[:1]]))) / 2


def _zones_round(layout: Mapping, seed: Sequence[Mapping], point: Mapping) -> list:
    """The zones round POINT that are not part of the seed, smallest first."""
    own = {item["id"] for item in seed if item["kind"] == "zone"}
    around = [zone for zone in layout.get("zones") or []
              if isinstance(zone, Mapping) and zone.get("zoneId") not in own
              and len(zone.get("boundary") or []) >= 3 and lp.point_in_polygon(point, zone["boundary"])]
    return sorted(around, key=lambda zone: _area(zone["boundary"]))


def _box(points: Sequence[Mapping]) -> tuple:
    xs, zs = [point["x"] for point in points], [point["z"] for point in points]
    return min(xs), max(xs), min(zs), max(zs)


def _ring(boundary: Any) -> list | None:
    """A zone's boundary as (x, z) pairs for _inside, or None when it needs lp.point_in_polygon (a value that is not
    a finite number)."""
    try:
        ring = [(point["x"], point["z"]) for point in boundary]
    except (TypeError, KeyError):
        return None
    numbers = all(type(value) in (int, float) and math.isfinite(value) for pair in ring for value in pair)
    return ring if numbers and len(ring) >= 3 else None


def _inside(x: float, z: float, ring: Sequence[tuple]) -> bool:
    """lp.point_in_polygon for a ring of finite numbers, without its checks: the same crossings, much faster."""
    inside, previous = False, len(ring) - 1
    for index in range(len(ring)):
        (ax, az), (bx, bz) = ring[index], ring[previous]
        previous = index
        if (az > z) != (bz > z) and x < (bx - ax) * (z - az) / (bz - az) + ax:
            inside = not inside
    return inside


def _within(point: Mapping, zone: Mapping, ring: Sequence[tuple] | None) -> bool:
    return _inside(point["x"], point["z"], ring) if ring else lp.point_in_polygon(point, zone["boundary"])


def _shape(item: Mapping, instance: int) -> dict:
    bottom = float(item["position"].get("y") or 0)
    points, center = lp.item_points(item), item["position"]
    inset = []  # each corner 1e-6 toward the centre: on the zone's own edge counts as inside (as in _fits)
    for point in points:
        dx, dz = center["x"] - point["x"], center["z"] - point["z"]
        length = math.hypot(dx, dz) or 1.0
        inset.append((point["x"] + dx / length * 1e-6, point["z"] + dz / length * 1e-6))
    return {"instance": instance, "points": points, "center": center, "box": _box(points), "inset": inset,
            "radius": math.hypot(item["width"], item["depth"]) / 2, "bottom": bottom,
            "top": bottom + float(item.get("height") or 0)}


def _instance_shapes(index: Mapping, seed: Sequence[Mapping], copies: Sequence[Mapping], with_seed: bool) -> list:
    """The footprints of the items of each instance that stand on the floor (the seed is instance 0), in order."""
    by_id = {item["id"]: item for item in seed}
    shapes = [_shape(item, 0) for item in seed if with_seed and _standing(index, item)]
    shapes += [_shape(_moved_item(by_id[copy["sourceId"]], copy), copy["instanceIndex"]) for copy in copies
               if _standing(index, by_id[copy["sourceId"]])]
    return sorted(shapes, key=lambda shape: shape["instance"])


def _blocked(shapes: Sequence[Mapping], shift: tuple, zone: Mapping | None, stays: Sequence[Mapping],
             enough: float) -> tuple[str | None, float, str | None]:
    """What keeps SHAPES, moved by SHIFT, from standing there (None: nothing): the first instance outside ZONE or
    with something that stays in its way (touching is not in the way; items above or below are not). And their
    clear space from what stays, up to ENOUGH, and the nearest item that stays."""
    dx, dz = shift
    best, nearest = enough, None
    ring = _ring(zone["boundary"]) if zone is not None else None
    for shape in shapes:
        name = f"copy {shape['instance']}" if shape["instance"] else "the original"
        if zone is not None and not all(_within({"x": x + dx, "z": z + dz}, zone, ring) for x, z in shape["inset"]):
            return f"{name} would be outside {_label(zone, zone['zoneId'])}", 0.0, None
        x0, x1, z0, z1 = shape["box"]
        x0, x1, z0, z1 = x0 + dx, x1 + dx, z0 + dz, z1 + dz
        points = None
        for other in stays:
            if other["bottom"] >= shape["top"] - 0.05 or other["top"] <= shape["bottom"] + 0.05:
                continue  # above or below it
            ox0, ox1, oz0, oz1 = other["box"]
            gx, gz = max(ox0 - x1, x0 - ox1, 0.0), max(oz0 - z1, z0 - oz1, 0.0)
            if gx * gx + gz * gz >= best * best:
                continue  # their boxes are apart by more than the room found so far
            if points is None:
                points = [{"x": point["x"] + dx, "z": point["z"] + dz} for point in shape["points"]]
            if not (gx or gz) and _overlap(points, other["points"], slack=1e-6):
                return f"{other['label']} stands in the way of {name}", 0.0, other["label"]
            gap = _polygon_gap(points, other["points"])
            if gap < best:
                best, nearest = gap, other["label"]
    return None, best, nearest


def _stays(layout: Mapping, catalog: list, zone: Mapping | None, ways: Sequence[Mapping], exclude: set) -> list:
    """What stays where the pattern may go: in and round its zone, else round its instances."""
    margin = max(way["enough"] for way in ways)
    if zone is not None:
        middle = lp.bounds_from_points(zone["boundary"])["center"]
        reach = max(math.hypot(point["x"] - middle["x"], point["z"] - middle["z"]) for point in zone["boundary"])
    else:
        shapes = [shape for way in ways for shape in way["shapes"]]
        if not shapes:
            return []
        middle = {"x": sum(shape["center"]["x"] for shape in shapes) / len(shapes),
                  "z": sum(shape["center"]["z"] for shape in shapes) / len(shapes)}
        reach = max(math.hypot(shape["center"]["x"] - middle["x"], shape["center"]["z"] - middle["z"])
                    + shape["radius"] for shape in shapes)
    return [{**item, "box": _box(item["points"])} for item in _obstacles(layout, catalog, middle, reach + margin,
                                                                          exclude)]


def _guide(shapes: Sequence[Mapping], angle: float) -> dict:
    """The rectangle round SHAPES in the pattern's own axes at ANGLE (centre, width along, depth across)."""
    axis_x, axis_z = lp.rotate_vector({"x": 1, "z": 0}, angle), lp.rotate_vector({"x": 0, "z": 1}, angle)
    points = [point for shape in shapes for point in shape["points"]]
    along = [point["x"] * axis_x["x"] + point["z"] * axis_x["z"] for point in points]
    across = [point["x"] * axis_z["x"] + point["z"] * axis_z["z"] for point in points]
    u, v = (min(along) + max(along)) / 2, (min(across) + max(across)) / 2
    return {"center": {"x": axis_x["x"] * u + axis_z["x"] * v, "z": axis_x["z"] * u + axis_z["z"] * v},
            "width": max(along) - min(along), "depth": max(across) - min(across)}


def _too_big(way: Mapping, zone: Mapping | None) -> str | None:
    """Why no move inside ZONE makes room for WAY: its instances (the seed included) are bigger than the zone
    that way."""
    shapes = way["all"]
    if zone is None or not shapes:
        return None
    guide = _guide(shapes, way["angle"])
    axis_x, axis_z = lp.rotate_vector({"x": 1, "z": 0}, way["angle"]), lp.rotate_vector({"x": 0, "z": 1}, way["angle"])
    along = [point["x"] * axis_x["x"] + point["z"] * axis_x["z"] for point in zone["boundary"]]
    across = [point["x"] * axis_z["x"] + point["z"] * axis_z["z"] for point in zone["boundary"]]
    room = (max(along) - min(along), max(across) - min(across))
    if guide["width"] <= room[0] + 1e-9 and guide["depth"] <= room[1] + 1e-9:
        return None
    return (f"it needs {guide['width']:.2f} x {guide['depth']:.2f} m, more than {_label(zone, zone['zoneId'])} has "
            f"that way ({room[0]:.2f} x {room[1]:.2f} m)")


def _moved_fit(index: Mapping, seed: Sequence[Mapping], ways: Sequence[Mapping], zone: Mapping,
               stays: Sequence[Mapping], nearest_enough: bool) -> tuple | None:
    """The pattern moved with its seed inside ZONE (0.5 m steps along its own axes) so that a way fits: with
    nearest_enough, the nearest move that keeps the way's enough clear of what stays; else the move with the most
    room, then the nearest. None, or (way, shift, room, the nearest item that stays)."""
    best = None
    for way in ways:
        shapes = way["moving"]
        if not shapes:
            continue
        budget = max(25, 400_000 // max(1, len(shapes) * max(1, len(stays))))  # bounds the work on large seeds
        for shift in _shifts(zone, _guide(shapes, way["angle"]), way["angle"])[:budget]:
            if not any(shift):
                continue
            distance = math.hypot(*shift)
            if nearest_enough and best is not None and distance > best[0][0] + 1e-9:
                break  # moves come nearest first
            way["tried"] = max(way.get("tried", 0.0), distance)
            if shift not in way["checked"]:
                way["checked"][shift] = _blocked(shapes, shift, zone, stays, way["enough"])
            problem, room, nearest = way["checked"][shift]
            if problem is not None or (nearest_enough and room < way["enough"] - 1e-9):
                continue
            key = (distance, way["order"]) if nearest_enough else (-room, distance, way["group"], way["order"])
            if best is None or key < best[0]:
                best = (key, way, shift, room, nearest)
            if nearest_enough:
                break  # the nearest for this way
    return best[1:] if best else None


def _why_not(way: Mapping, zone: Mapping | None, movable: bool) -> str:
    return (_too_big(way, zone) if movable else None) or way["problem"]


def _reasons(pairs: Sequence[tuple]) -> str:
    """'way: reason' for each (way, reason), the ways with the same reason together."""
    merged: dict[str, list] = {}
    for name, reason in pairs:
        merged.setdefault(reason, []).append(name)
    return "; ".join((" and ".join(names) + ": " if names[0] else "") + reason for reason, names in merged.items())


def _picked(chosen: Mapping, ways: Sequence[Mapping], what: str, direction: bool, moved: bool,
            zone: Mapping | None, movable: bool) -> str:
    """Which way the tool picked (a row given no direction, or a grid's rows given no side), and why not the
    others."""
    def name(way):  # a grid given its direction: its rows' side is all that was picked
        return way["name"] if direction else f"rows {way['built'][3]['rowDirection']}"

    head = (f"direction {chosen['name']}, {'along' if chosen['group'] == 0 else 'across'} the length of {what}"
            if direction else name(chosen))
    reasons = []
    for way in ways:
        if way is chosen or way["group"] > chosen["group"]:
            continue
        if way["problem"]:
            reasons.append((name(way), _why_not(way, zone, movable)))
        elif not moved and way["room"] < chosen["room"] - 1e-9:
            reasons.append((name(way), f"less room ({way['room']:.2f} m clear)"))
    return head + ("; " + _reasons(reasons) if reasons else "") + "."


def _where_it_fits(kind: str, layout: Mapping, catalog: list, seed: list, arguments: Mapping) -> tuple:
    """A row, grid, circle or ring where it fits: each instance inside the seed's zone (the smallest round it), with
    nothing that stays in its way. A row given no direction runs along the seed's length (else across it), the way
    with more room; a grid's rows given no side go the side that fits. When it does not fit from where the seed
    stands, it moves with the seed inside the zone: to the nearest place that keeps the row's gap (at least 1 m)
    clear of what stays, else the roomiest (along the seed's length before across it). origin moves the seed there
    first instead. picked and seedMoved in the summary say what the tool chose and why; nothing fitting is refused,
    naming what is in each way. Returns copies, guide, count, summary and the seed where the pattern has it."""
    index = _index(layout)
    length, main = _seed_length(index, seed)
    what = _named(index, main["id"]) if main else "the seed"
    in_seed = [item for item in seed if item["kind"] == "zone"]
    origin = arguments.get("origin")
    if origin is not None and in_seed:
        raise PatternError(f"origin moves placements and floor markings, and {_named(index, in_seed[0]['id'])} is a "
                           "zone: leave origin out.")
    anchor = main["position"] if main else lp.selection_bounds(seed)["center"]
    start = (0.0, 0.0) if origin is None else (float(origin["x"]) - anchor["x"], float(origin["z"]) - anchor["z"])
    direction = side = False
    if kind == "linear":
        ways, direction, side = _linear_ways(seed, arguments, length, start)
        noun = "grid" if int(arguments.get("rows") or 1) > 1 else "row"
    elif kind == "circular":
        def circle(shift):  # a centre given moves with the circle, not with origin
            moved = dict(arguments)
            if arguments.get("center") is not None:
                moved["center"] = {"x": float(arguments["center"]["x"]) + shift[0],
                                   "z": float(arguments["center"]["z"]) + shift[1]}
            return _circular(layout, catalog, _translated(seed, _plus(start, shift)), moved)
        ways, noun = [{"group": 0, "angle": 0.0, "rowAngle": None, "build": circle}], "circle"
    else:
        ways, noun = [{"group": 0, "angle": None, "rowAngle": None, "build": lambda shift: _perimeter(
            layout, catalog, _translated(seed, _plus(start, shift)), arguments)}], "ring"
    placed = _translated(seed, start)
    for order, way in enumerate(ways):
        way["order"], way["built"], way["checked"] = order, way["build"]((0.0, 0.0)), {}
        summary = way["built"][3]
        if way["angle"] is None:  # a ring's own axes
            way["angle"] = float(way["built"][1].get("angleDegrees") or 0)
        way["enough"] = max(1.0, float(summary.get("gap") or 0), float(summary.get("rowGap") or 0))
        way["name"] = (summary["direction"] + (f" (rows {summary['rowDirection']})" if way["rowAngle"] is not None
                                               else "")) if kind == "linear" else ""
        way["shapes"] = _instance_shapes(index, placed, way["built"][0], any(start))
        way["all"] = _instance_shapes(index, placed, way["built"][0], True)
    # The zone the pattern stays in: the smallest round the seed that it fits by size one way (a station's own
    # small zone is not where a row of stations goes); none, and only what stays is in its way.
    zone = next((zone for zone in _zones_round(layout, seed, {"x": anchor["x"] + start[0], "z": anchor["z"] + start[1]})
                 if any(_too_big(way, zone) is None for way in ways)), None)
    movable = origin is None and zone is not None and not in_seed
    for way in ways:
        way["moving"] = way["all"] if movable else []
    exclude = {item["id"] for item in seed} | set(arguments.get("removeIds") or [])
    stays = _stays(layout, catalog, zone, ways, exclude)
    for way in ways:
        way["problem"], way["room"], way["nearest"] = _blocked(way["shapes"], (0.0, 0.0), zone, stays,
                                                               way["enough"])
    chosen, shift, room, nearest = None, (0.0, 0.0), 0.0, None
    for group in sorted({way["group"] for way in ways}):  # along the seed's length, then across it
        members = [way for way in ways if way["group"] == group]
        fits = [way for way in members if way["problem"] is None]
        if fits:
            chosen = min(fits, key=lambda way: (-way["room"], way["order"]))
            room, nearest = chosen["room"], chosen["nearest"]
            break
        found = _moved_fit(index, placed, members, zone, stays, nearest_enough=True) if movable else None
        if found:
            chosen, shift, room, nearest = found
            break
    if chosen is None and movable:
        found = _moved_fit(index, placed, ways, zone, stays, nearest_enough=False)
        if found:
            chosen, shift, room, nearest = found
    if chosen is None:
        listed = _reasons([(way["name"], _why_not(way, zone, movable)) for way in ways])
        at = f" from origin ({float(origin['x']):g}, {float(origin['z']):g})" if origin is not None else ""
        lead = (f"Neither along nor across the length of {what} does the {noun} fit{at}" if direction
                else f"The {noun} does not fit{at}")
        tried = max(way.get("tried", 0.0) for way in ways)  # the nearest 400 places inside the zone, at most
        where = (f", even moving {what} up to {tried:.1f} m inside {_label(zone, zone['zoneId'])}"
                 if movable and tried else "")
        advice = {"linear": "fewer copies, a smaller gap, origin or removeIds",
                  "circular": "fewer copies, another center, origin or removeIds",
                  "perimeter": "fewer copies, a smaller gap, origin or removeIds"}[kind]
        if kind == "linear" and not direction:
            advice = "another direction, " + advice
        raise PatternError(f"{lead} ({listed}){where}. Give {advice}.")
    copies, guide, count, summary = chosen["build"](shift) if any(shift) else chosen["built"]
    if direction or side:
        summary["picked"] = _picked(chosen, ways, what, direction, any(shift), zone, movable)
    total = _plus(start, shift)
    if any(total):
        why = "origin" if origin is not None else (
            f"from where {what} stands the {noun} does not fit ({chosen['problem']}); "
            + (f"this is the nearest place inside {_label(zone, zone['zoneId'])} that keeps it "
               f"{chosen['enough']:.2f} m clear of what stays" if room >= chosen["enough"] - 1e-9 else
               f"this is the place inside {_label(zone, zone['zoneId'])} with the most room: {room:.2f} m clear of "
               f"{nearest}"))
        summary["seedMoved"] = {"items": [_named(index, item["id"]) for item in seed],
                                "by": _point({"x": total[0], "z": total[1]}), "meters": _round(math.hypot(*total)),
                                "to": _point({"x": anchor["x"] + total[0], "z": anchor["z"] + total[1]}),
                                "why": why}
    if nearest is not None and room < chosen["enough"] - 1e-9:
        summary["closestToWhatStays"] = {"meters": _round(room), "item": nearest}
    return copies, guide, count, summary, _translated(seed, total)


def _seed_moves(index: Mapping, seed: Sequence[Mapping], placed: Sequence[Mapping]) -> list:
    """Operations that move the seed's items where the pattern has them: placements with move_placement, one for
    each item (an item on a support gets its own: move_placement does not carry it along), floor markings with
    edit_floor_marking."""
    operations = []
    for item, moved in zip(seed, placed):
        dx, dz = moved["position"]["x"] - item["position"]["x"], moved["position"]["z"] - item["position"]["z"]
        if not (dx or dz):
            continue
        collection, entity = index[item["id"]]
        transform = entity.get("transform") if isinstance(entity.get("transform"), Mapping) else {}
        old = transform.get("position") if isinstance(transform.get("position"), Mapping) else item["position"]
        position = _world_position({**old, "x": float(old["x"]) + dx, "z": float(old["z"]) + dz})
        if collection == "placements":
            operations.append({"op": "move_placement", "placementId": item["id"], "position": position,
                               "movementKind": "user"})
        elif collection == "floorMarkings":
            operations.append({"op": "edit_floor_marking", "markingId": item["id"],
                               "patch": {"transform": {**deepcopy(dict(transform)), "position": position}}})
        else:
            raise PatternError(f"{_named(index, item['id'])} is a zone; a zone does not move with the seed.")
    return operations


def _clamp(value: Any, low: float, high: float, fallback: float) -> float:
    return max(low, min(high, lp.finite(value, fallback)))


def _plan_settings(layout: Mapping) -> tuple[float, float, float]:
    """The Plan's width, depth and grid, as planSettingsFromLayout reads them (static/facility_layout_workspace.js)."""
    stored = (layout.get("extensions") or {}).get("facilityPlan")
    stored = stored if isinstance(stored, Mapping) else {}
    width = _clamp(stored.get("widthMeters", lp.MISSING), 0.5, 10000, PLAN_DEFAULTS[0])
    depth = _clamp(stored.get("depthMeters", lp.MISSING), 0.5, 10000, PLAN_DEFAULTS[1])
    largest = max(width, depth)
    grid = _clamp(stored.get("gridSpacingMeters", lp.MISSING), 0.05, largest, min(largest, PLAN_DEFAULTS[2]))
    return width, depth, grid


def _mirror_line(layout: Mapping, seed: Sequence[Mapping], arguments: Mapping) -> tuple[dict, dict, str | None]:
    """The mirror line as the ribbon draws it: a north-south line across the whole Plan, an east-west one, or two
    points. By default it runs just past the seed on its east side: the ribbon's 1 m (or one grid step, if larger)
    rounded out to the Plan's grid."""
    given = [key for key in ("side", "lineX", "lineZ", "linePoints") if arguments.get(key) is not None]
    if len(given) > 1:
        raise PatternError("Give the mirror line one way: side (with gap), lineX, lineZ or linePoints.")
    if arguments.get("gap") is not None and given and given[0] != "side":
        raise PatternError("gap goes with side (the clear space between the seed and its mirror image); lineX, "
                           "lineZ and linePoints already fix the line.")
    width, depth, grid = _plan_settings(layout)
    if given == ["lineX"]:
        x = float(arguments["lineX"])
        return {"x": x, "z": 0.0}, {"x": x, "z": depth}, None
    if given == ["lineZ"]:
        z = float(arguments["lineZ"])
        return {"x": 0.0, "z": z}, {"x": width, "z": z}, None
    if given == ["linePoints"]:
        first, second = arguments["linePoints"]
        if math.hypot(float(first["x"]) - float(second["x"]), float(first["z"]) - float(second["z"])) < 1e-6:
            raise PatternError("linePoints are the same point; give two different points on the mirror line.")
        return ({"x": float(first["x"]), "z": float(first["z"])},
                {"x": float(second["x"]), "z": float(second["z"])}, None)
    side, gap = arguments.get("side") or "east", arguments.get("gap")
    bounds, step = lp.selection_bounds(seed), max(1.0, grid)
    if side == "east":
        x = bounds["maxX"] + gap / 2 if gap is not None else math.ceil((bounds["maxX"] + step) / grid) * grid
    elif side == "west":
        x = bounds["minX"] - gap / 2 if gap is not None else math.floor((bounds["minX"] - step) / grid) * grid
    elif side == "north":
        z = bounds["maxZ"] + gap / 2 if gap is not None else math.ceil((bounds["maxZ"] + step) / grid) * grid
    else:
        z = bounds["minZ"] - gap / 2 if gap is not None else math.floor((bounds["minZ"] - step) / grid) * grid
    if side in ("east", "west"):
        x = lp.to_fixed(x, 6)
        return {"x": x, "z": 0.0}, {"x": x, "z": depth}, side
    z = lp.to_fixed(z, 6)
    return {"x": 0.0, "z": z}, {"x": width, "z": z}, side


def _line_name(heading: float) -> str:
    value = lp.normalize_degrees(heading) % 180
    if min(value, 180 - value) < 1e-6:
        return "north-south"
    if abs(value - 90) < 1e-6:
        return "east-west"
    return f"{value:.0f} degrees from north"


def _front_of(layout: Mapping, catalog: list, item: Mapping) -> tuple[float | None, float | None]:
    if item["kind"] != "placement":
        return None, None
    return _sides(lp.catalog_record(catalog, _index(layout)[item["id"]][1]))


def _mirror(layout: Mapping, catalog: list, seed: list, arguments: Mapping) -> tuple:
    _check_capacity(seed, 2)
    start, end, side = _mirror_line(layout, seed, arguments)
    # The builder keeps each machine's operator side (else front, else north side) as the mirror image.
    result = lp.build_mirror(seed, {"axisStart": start, "axisEnd": end})
    line = lp.tangent_heading(lp.normalized_mirror_axis(start, end)["unit"])
    index, by_id = _index(layout), {item["id"]: item for item in seed}
    items, unverified = [], []
    for copy in result["copies"]:
        if copy["kind"] != "placement":
            continue
        item = by_id[copy["sourceId"]]
        operator, front = _front_of(layout, catalog, item)
        turn = copy["rotationDegrees"]
        label = _named(index, item["id"])
        if operator is None:
            unverified.append(label)
        items.append({"copyOf": label, "position": _point(copy["position"]), "yawDegrees": _round(turn),
                      "frontFaces": _compass_name(turn + (front if front is not None else 0)),
                      "frontReviewed": operator is not None})
    summary = {
        "line": {"runs": _line_name(line), "from": _point(start), "to": _point(end)},
        **({"copySide": side} if side else {}),
        "copies": items[:LISTED], **({"copiesNotListed": len(items) - LISTED} if len(items) > LISTED else {}),
        "facing": "mirrored: each copy's front is the mirror image of its original's",
        "unverifiedFacing": unverified[:LISTED],
    }
    return result["copies"], result["guide"], result["count"], summary


def _facing_relation(heading: float, toward: float) -> str:
    difference = abs((heading - toward + 180) % 360 - 180)
    return "toward" if difference < 45 else "away from" if difference > 135 else "across"


def _along_note(sides: Sequence[Mapping], along: str, advice: str) -> list:
    """A perimeter or circle keeps the seed's facing: say so when an operator side faces along it, and what helps."""
    labels = [side["item"] for side in sides if side["faces"] == along]
    if not labels:
        return []
    listed = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
    return [f"{listed} face{'' if len(labels) > 1 else 's'} {along}, as the seed does: {advice}"]


def _circular(layout: Mapping, catalog: list, seed: list, arguments: Mapping) -> tuple:
    count = int(arguments["count"])
    _check_capacity(seed, count)
    total = 360.0 if arguments.get("totalDegrees") is None else float(arguments["totalDegrees"])
    turn = arguments.get("turnWithPattern") is True
    options = {"count": count, "sweepDegrees": total, "rotateWithPattern": turn}
    if arguments.get("center") is not None:
        options.update(centerX=float(arguments["center"]["x"]), centerZ=float(arguments["center"]["z"]))
    result = lp.build_circular_pattern(seed, options)
    guide = result["guide"]
    bounds = lp.selection_bounds(seed)
    instances = [{"index": number, "center": _point(lp.transform_point(
        bounds["center"], guide["center"], guide["center"], guide["stepDegrees"] * number)),
        "turnDegrees": _round(guide["stepDegrees"] * number)} for number in range(count)]
    sides = []
    index = _index(layout)
    for item in seed:
        operator, _ = _front_of(layout, catalog, item)
        if operator is None:
            continue
        toward = lp.tangent_heading({"x": guide["center"]["x"] - item["position"]["x"],
                                     "z": guide["center"]["z"] - item["position"]["z"]})
        relation = _facing_relation(lp.normalize_degrees(item["rotationDegrees"] + operator), toward)
        sides.append({"item": _named(index, item["id"]),
                      "faces": {"toward": "the centre", "away from": "away from the centre",
                                "across": "along the circle"}[relation]})
    summary = {
        "count": count, "center": _point(guide["center"]), "radius": _round(guide["radius"]),
        "totalDegrees": _round(total), "stepDegrees": _round(guide["stepDegrees"]), "goesRound": "clockwise",
        "turnWithPattern": turn, "instances": instances[:LISTED],
        **({"instancesNotListed": len(instances) - LISTED} if len(instances) > LISTED else {}),
        "facing": ("each copy turns as it goes round, so it faces the centre as the seed does" if turn else
                   "copies keep the seed's heading; they do not turn (turnWithPattern turns them)"),
        **({"seedOperatorSides": sides[:LISTED]} if sides else {}),
        "notes": _along_note(sides, "along the circle", "to face the centre, turn the seed first, then plan it "
                             "again.") if turn else [],
    }
    return result["copies"], guide, result["count"], summary


def _perimeter(layout: Mapping, catalog: list, seed: list, arguments: Mapping) -> tuple:
    shape = arguments.get("shape") or "rectangle"
    width_count = 6 if arguments.get("widthCount") is None else int(arguments["widthCount"])
    depth_count = 4 if arguments.get("depthCount") is None else int(arguments["depthCount"])
    if shape == "square":
        if arguments.get("depthCount") is not None and depth_count != width_count:
            raise PatternError("A square has widthCount on every side; leave out depthCount.")
        depth_count = width_count
    _check_capacity(seed, 2 * (width_count + depth_count))
    gap = float(arguments.get("gap") or 0)
    result = lp.build_rectangular_perimeter(seed, {
        "shape": shape, "widthCount": width_count, "depthCount": depth_count, "clearGap": gap,
        "angleDegrees": float(arguments.get("turnDegrees") or 0)})
    guide = result["guide"]
    inward_heading = lp.normalize_degrees(guide["angleDegrees"])  # from the seed's side across the ring
    sides = []
    index = _index(layout)
    for item in seed:
        operator, _ = _front_of(layout, catalog, item)
        if operator is None:
            continue
        relation = _facing_relation(lp.normalize_degrees(item["rotationDegrees"] + operator), inward_heading)
        sides.append({"item": _named(index, item["id"]),
                      "faces": {"toward": "into the ring", "away from": "out of the ring",
                                "across": "along the ring"}[relation]})
    turned = abs(guide["angleDegrees"] - guide["requestedAngleDegrees"]) > 1e-9
    summary = {
        "shape": result["shape"], "widthCount": width_count, "depthCount": depth_count, "gap": _round(gap),
        "turnDegrees": _round(lp.normalize_degrees(guide["angleDegrees"])),
        **({"turnedForSeed": "the seed is deeper than it is wide, so the ring turned 90 degrees to run along its "
                             "long side"} if turned else {}),
        "seedSideRuns": _compass_name(guide["angleDegrees"] + 90), "ringLiesTo": _compass_name(inward_heading),
        "copiesPerSide": {"seedSide": width_count, "oppositeSide": width_count, "eachEnd": depth_count},
        "facing": "each side's copies turn with the ring, so they face it as the seed does",
        **({"seedOperatorSides": sides[:LISTED]} if sides else {}),
        # The ribbon runs a ring along the seed's long side, so a side on a short face always faces along it.
        "notes": _along_note(sides, "along the ring", "a ring runs along the seed's long side. For machines set "
                             "round an area facing into it, use plan_facility_cell with strategy loop."),
    }
    return result["copies"], guide, result["count"], summary


def _instance_gap(seed: Sequence[Mapping], copies: Sequence[Mapping]) -> tuple:
    """The smallest clear space between placements of different instances (the seed is instance 0), and which."""
    by_id = {item["id"]: item for item in seed}
    shapes = []
    for number, item in [*((0, item) for item in seed),
                         *((copy["instanceIndex"], _moved_item(by_id[copy["sourceId"]], copy)) for copy in copies)]:
        if item["kind"] != "placement":
            continue
        bottom = float(item["position"].get("y") or 0)
        shapes.append({"instance": number, "id": item["id"], "points": lp.item_points(item),
                       "center": item["position"], "radius": math.hypot(item["width"], item["depth"]) / 2,
                       "bottom": bottom, "top": bottom + float(item.get("height") or 0)})
    best = (math.inf, None)
    for i, first in enumerate(shapes):
        for second in shapes[i + 1:]:
            if first["instance"] == second["instance"]:
                continue
            if second["bottom"] >= first["top"] - 0.05 or second["top"] <= first["bottom"] + 0.05:
                continue  # one is above the other
            span = math.hypot(first["center"]["x"] - second["center"]["x"],
                              first["center"]["z"] - second["center"]["z"]) - first["radius"] - second["radius"]
            if span >= best[0]:
                continue
            found = _polygon_gap(first["points"], second["points"])
            if found < best[0]:
                best = (found, (first, second))
    return best


OVERLAP_NOTES = {
    "linear": "Copies overlap: give a larger spacing or gap.",
    "mirror": "The mirror image overlaps the original: move the line away from it (a larger gap, or another side).",
    "circular": "Copies overlap: give a centre further from the seed, fewer copies or a larger totalDegrees.",
    "perimeter": "Copies overlap: give a gap.",
}


def plan_pattern(layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    kind = _check_kind(arguments)
    catalog = list(catalog)
    seed = _pattern_seed(layout, catalog, list(arguments["seedIds"]), include_zones=kind != "perimeter")
    removals, removed, walks = _removals(layout, arguments.get("removeIds") or [], {item["id"] for item in seed})
    if kind == "mirror":  # its copy goes where its line puts it
        copies, guide, count, summary = _mirror(layout, catalog, seed, arguments)
        placed = seed
    else:
        copies, guide, count, summary, placed = _where_it_fits(kind, layout, catalog, seed, arguments)
    notes = summary.pop("notes", [])
    namespace = _namespace(PATTERN_TOOL, arguments, revision)
    provenance = _provenance(namespace, COMMANDS[kind], None, [copy["sourceId"] for copy in copies], count,
                             len(seed), guide)
    operations = _with_seed_provenance(_copy_operations(layout, copies, provenance, _Ids(namespace)), provenance,
                                       provenance["seedEntityIds"])
    index = _index(layout)
    moves = _seed_moves(index, seed, placed)  # the seed moves first, then is copied where it stands
    by_id = {item["id"]: item for item in placed}
    extent = lp.selection_bounds([*placed, *(_moved_item(by_id[copy["sourceId"]], copy) for copy in copies)])
    gap = _instance_gap(placed, copies)
    if gap[1] and _overlap(gap[1][0]["points"], gap[1][1]["points"], slack=1e-6):
        notes = [OVERLAP_NOTES[kind], *notes]

    def named(shape):
        return f"{_named(index, shape['id'])}, " + ("the original" if not shape["instance"]
                                                     else f"copy {shape['instance']}")

    return {
        "available": True, "kind": kind, "seedItems": [_named(index, item["id"]) for item in seed], **summary,
        "newItems": len(copies),
        **({"closestGap": {"meters": _round(gap[0]), "between": [named(shape) for shape in gap[1]]}}
           if gap[1] else {}),
        **({"note": " ".join(notes)} if notes else {}),
        "removed": removed, **({"alsoRemoves": _also_removes(walks)} if walks else {}),
        "extent": {key: _round(extent[key]) for key in ("minX", "maxX", "minZ", "maxZ", "width", "depth")},
        "operations": [*removals, *moves, *operations],
    }


# ---------------------------------------------------------------- plan_facility_cell

def _sides(record: Mapping | None) -> tuple[float | None, float | None]:
    """The model's reviewed operator side (else its front) and front, as compass headings."""
    semantics = (record or {}).get("facilitySemantics")
    sides = semantics.get("functionalSides") if isinstance(semantics, Mapping) else None
    if not isinstance(sides, Mapping):
        return None, None

    def heading(role):
        value = sides.get(role)
        side = value.get("side") if isinstance(value, Mapping) else value
        return COMPASS_HEADINGS.get(side) if isinstance(side, str) else None

    front = heading("front")
    operator = heading("operator")
    return (operator if operator is not None else front), front


def _inside_heading(shape: str, move: Mapping, angle: float, operator_side: str | None) -> float:
    """Where a machine's operator side faces in the cell: square into it."""
    tangent, offset = move["pathTangent"], move["pathOffset"]
    if shape in ("u", "l", "loop"):
        normal = {"x": tangent["z"], "z": -tangent["x"]}  # the right of the flow, which is the inside
        if normal["x"] * -offset["x"] + normal["z"] * -offset["z"] < 0:
            normal = {"x": -normal["x"], "z": -normal["z"]}
        return lp.tangent_heading(normal)
    if shape == "cluster":
        return lp.tangent_heading({"x": -offset["x"], "z": -offset["z"]})
    if shape == "spine":
        return lp.normalize_degrees(angle + (180 if move["pathPoint"]["z"] > 0 else 0))
    if shape == "herringbone":
        return move["rotationDegrees"]
    if operator_side:
        return COMPASS_HEADINGS[operator_side]
    return lp.normalize_degrees(angle + 180)


def _new_machines(layout: Mapping, catalog: list, assets: Sequence[Mapping], center: Mapping,
                  removed: set) -> tuple[list, dict]:
    by_id = {record.get("assetId"): record for record in catalog if isinstance(record, Mapping)}
    items, records = [], {}
    existing: dict[str, int] = {}  # numbered on from the machines that stay
    for placement in layout.get("placements") or []:
        if placement.get("placementId") not in removed:
            existing[placement.get("assetId")] = existing.get(placement.get("assetId"), 0) + 1
    number = 0
    for entry in assets:
        record = by_id.get(entry["assetId"])
        if record is None or not record.get("assetDefinitionRevision"):
            raise PatternError(f"{entry['assetId']} is not in the library; find it with search_industrial_assets.")
        for _ in range(int(entry["count"])):
            number += 1
            existing[record["assetId"]] = existing.get(record["assetId"], 0) + 1
            identifier = f"new-{number}"
            placement = {"placementId": identifier, "assetId": record["assetId"],
                         "assetDefinitionRevision": record["assetDefinitionRevision"],
                         "transform": {"position": {"x": center["x"], "y": center.get("y", 0), "z": center["z"]},
                                       "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
                         "positionMode": "manual"}
            items.append(lp.normalized_item("placement", placement, catalog, True))
            records[identifier] = {"record": record, "number": existing[record["assetId"]]}
    return items, records


def _zone_half_extents(zone: Mapping, center: Mapping, angle: float) -> tuple[float, float]:
    axis_x = lp.rotate_vector({"x": 1, "z": 0}, angle)
    axis_z = lp.rotate_vector({"x": 0, "z": 1}, angle)
    along = [(point["x"] - center["x"]) * axis_x["x"] + (point["z"] - center["z"]) * axis_x["z"]
             for point in zone["boundary"]]
    across = [(point["x"] - center["x"]) * axis_z["x"] + (point["z"] - center["z"]) * axis_z["z"]
              for point in zone["boundary"]]
    return min(max(along), -min(along)), min(max(across), -min(across))


def _fits(zone: Mapping, center: Mapping, width: float, depth: float, angle: float) -> bool:
    inset = 1e-6  # corners on the zone's own edge count as inside
    ring = _ring(zone["boundary"])
    for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        corner = lp.rotate_vector({"x": sx * (width / 2 - inset), "z": sz * (depth / 2 - inset)}, angle)
        if not _within({"x": center["x"] + corner["x"], "z": center["z"] + corner["z"]}, zone, ring):
            return False
    return True


def _growth_sizes(base: tuple, zone: Mapping | None, center: Mapping, angle: float) -> list:
    """Bigger default sizes for a cell, the smallest area first, as far as the zone allows."""
    limit = _zone_half_extents(zone, center, angle) if zone is not None else None
    sizes = {}
    for grow_width, grow_depth in itertools.product(range(GROWTH_STEPS + 1), repeat=2):
        width, depth = base[0] * (1 + GROWTH * grow_width), base[1] * (1 + GROWTH * grow_depth)
        if limit:
            width, depth = min(width, 2 * limit[0]), min(depth, 2 * limit[1])
        key = (round(width, 9), round(depth, 9))
        if key != (round(base[0], 9), round(base[1], 9)) and key not in sizes:
            sizes[key] = (width * depth, abs(grow_width - grow_depth))
    return sorted(sizes, key=sizes.get)


def _footprints(seed: Sequence[Mapping], moves: Sequence[Mapping], turns: Sequence[float]) -> list:
    shapes = []
    for item, move, turn in zip(seed, moves, turns):
        floor = float(move["position"].get("y") or 0)
        shapes.append({"points": lp.item_points({**item, "position": move["position"], "rotationDegrees": turn}),
                       "center": move["position"], "radius": math.hypot(item["width"], item["depth"]) / 2,
                       "bottom": floor, "top": floor + float(item.get("height") or 0)})
    return shapes


def _obstacles(layout: Mapping, catalog: list, center: Mapping, reach: float, exclude: set) -> list:
    """What stays where the cell may go: placements within reach of its centre. An item on a bench is inside the
    bench's footprint, and a light hung overhead is above the machines (_obstacle_gap compares heights)."""
    found = []
    for placement in layout.get("placements") or []:
        if placement.get("placementId") in exclude or _attached(placement):
            continue
        try:
            item = lp.normalized_item("placement", placement, catalog, False)
        except (PatternError, TypeError, KeyError, AttributeError):
            continue
        radius = math.hypot(item["width"], item["depth"]) / 2
        span = math.hypot(item["position"]["x"] - center["x"], item["position"]["z"] - center["z"]) - radius
        if span > reach:
            continue
        bottom = item["position"]["y"]
        found.append({"id": placement["placementId"], "label": _label(placement, placement["placementId"]),
                      "points": lp.item_points(item), "center": item["position"], "radius": radius,
                      "bottom": bottom, "top": bottom + item["height"]})
    return found


def _shifts(zone: Mapping, guide: Mapping, angle: float) -> list:
    """Centre shifts that keep the cell inside its zone, in 0.5 m steps along the cell's own axes, nearest first."""
    axis_x, axis_z = lp.rotate_vector({"x": 1, "z": 0}, angle), lp.rotate_vector({"x": 0, "z": 1}, angle)
    center = guide["center"]
    along = [(p["x"] - center["x"]) * axis_x["x"] + (p["z"] - center["z"]) * axis_x["z"] for p in zone["boundary"]]
    across = [(p["x"] - center["x"]) * axis_z["x"] + (p["z"] - center["z"]) * axis_z["z"] for p in zone["boundary"]]

    def steps(low, high):
        first, last = math.ceil(low / SHIFT_STEP - 1e-9), math.floor(high / SHIFT_STEP + 1e-9)
        return [SHIFT_STEP * k for k in range(first, last + 1)]

    options = []
    for u in steps(min(along) + guide["width"] / 2, max(along) - guide["width"] / 2):
        for v in steps(min(across) + guide["depth"] / 2, max(across) - guide["depth"] / 2):
            world = {"x": axis_x["x"] * u + axis_z["x"] * v, "z": axis_x["z"] * u + axis_z["z"] * v}
            options.append((math.hypot(u, v), world["x"] + 0.0, world["z"] + 0.0))
    options.sort()
    shifted = []
    for _, dx, dz in options[:SHIFT_LIMIT]:
        if _fits(zone, {"x": center["x"] + dx, "z": center["z"] + dz}, guide["width"], guide["depth"], angle):
            shifted.append((dx, dz))
    return shifted or [(0.0, 0.0)]


def _obstacle_gap(shapes: Sequence[Mapping], shift: tuple, obstacles: Sequence[Mapping]) -> tuple:
    """The smallest clear space between a machine (shifted) and something that stays, and which (indexes)."""
    best = (math.inf, None)
    dx, dz = shift
    for j, other in enumerate(obstacles):
        for i, shape in enumerate(shapes):
            if other["bottom"] >= shape["top"] - 0.05 or other["top"] <= shape["bottom"] + 0.05:
                continue  # above or below the machine
            span = math.hypot(shape["center"]["x"] + dx - other["center"]["x"],
                              shape["center"]["z"] + dz - other["center"]["z"]) - shape["radius"] - other["radius"]
            if span >= best[0]:
                continue
            points = [{"x": p["x"] + dx, "z": p["z"] + dz} for p in shape["points"]]
            found = _polygon_gap(points, other["points"])
            if found < best[0]:
                best = (found, (i, j))
    return best


def _shifted(result: Mapping, shift: tuple) -> dict:
    dx, dz = shift
    moved = deepcopy(dict(result))
    for move in moved["moves"]:
        move["position"] = {**move["position"], "x": move["position"]["x"] + dx, "z": move["position"]["z"] + dz}
    moved["guide"]["center"] = {"x": moved["guide"]["center"]["x"] + dx, "z": moved["guide"]["center"]["z"] + dz}
    return moved


def _cell_notes(closest: tuple, blocked: tuple, gap: float, machines: Sequence[Mapping],
                stays: Sequence[Mapping]) -> list:
    notes = []
    if closest[1] and closest[0] < gap - 1e-6:
        notes.append(f"The closest machines are {closest[0]:.2f} m apart, under the {gap:g} m gap: give width and "
                     "depth for more room, or another strategy.")
    if blocked[1] and blocked[0] < gap - 1e-6:
        machine, other = machines[blocked[1][0]]["label"], stays[blocked[1][1]]["label"]
        where = "stands in the way of" if blocked[0] <= 0 else f"is {blocked[0]:.2f} m from"
        notes.append(f"{other} {where} {machine}, under the {gap:g} m gap: remove or move it (removeIds), give "
                     "width, depth or another strategy, or turn the cell.")
    return notes


def _overlap(first: Sequence[Mapping], second: Sequence[Mapping], slack: float = 0.0) -> bool:
    """Whether two footprints overlap by more than slack metres (touching is not overlapping)."""
    for shape in (first, second):
        for k in range(len(shape)):
            a, b = shape[k], shape[(k + 1) % len(shape)]
            nx, nz = b["z"] - a["z"], a["x"] - b["x"]
            ours = [p["x"] * nx + p["z"] * nz for p in first]
            theirs = [p["x"] * nx + p["z"] * nz for p in second]
            allowance = slack * math.hypot(nx, nz)
            if max(ours) <= min(theirs) + allowance or max(theirs) <= min(ours) + allowance:
                return False
    return True


def _segment_distance(point: Mapping, a: Mapping, b: Mapping) -> float:
    dx, dz = b["x"] - a["x"], b["z"] - a["z"]
    length = dx * dx + dz * dz
    t = 0.0 if not length else max(0.0, min(1.0, ((point["x"] - a["x"]) * dx + (point["z"] - a["z"]) * dz) / length))
    return math.hypot(point["x"] - a["x"] - t * dx, point["z"] - a["z"] - t * dz)


def _polygon_gap(first: Sequence[Mapping], second: Sequence[Mapping]) -> float:
    if _overlap(first, second):
        return 0.0
    return min(_segment_distance(point, shape[k], shape[(k + 1) % len(shape)])
               for shape, other in ((first, second), (second, first)) for point in other for k in range(len(shape)))


def _closest_gap(seed: Sequence[Mapping], moves: Sequence[Mapping], turns: Sequence[float]) -> tuple:
    """The smallest clear space between two machines' footprints, and which two (indexes)."""
    shapes = [lp.item_points({**item, "position": move["position"], "rotationDegrees": turn})
              for item, move, turn in zip(seed, moves, turns)]
    radii = [math.hypot(item["width"], item["depth"]) / 2 for item in seed]
    best = (math.inf, None)
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            a, b = moves[i]["position"], moves[j]["position"]
            if math.hypot(a["x"] - b["x"], a["z"] - b["z"]) - radii[i] - radii[j] >= best[0]:
                continue
            found = _polygon_gap(shapes[i], shapes[j])
            if found < best[0]:
                best = (found, (i, j))
    return best


GROUP_ONLY = ("itemIds", "name", "prefix", "number", "envelopePadding")


def plan_cell(layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    if arguments.get("action", "arrange") != "arrange":  # R4: Create Cell and Ungroup Cell (sage_stacks.py)
        from . import sage_stacks
        return sage_stacks.plan_cell_group(layout, catalog, arguments, revision=revision)
    stray = [key for key in GROUP_ONLY if key in arguments]
    if stray:
        raise PatternError(f"{', '.join(stray)} {'is' if len(stray) == 1 else 'are'} for action group.")
    catalog = list(catalog)
    shape = arguments.get("strategy")
    placement_ids, assets = arguments.get("placementIds"), arguments.get("assets")
    clear = arguments.get("clearZone") is True
    clear_only = clear and not placement_ids and not assets
    if not clear_only and bool(placement_ids) == bool(assets):
        raise PatternError("Give placementIds (machines already placed) or assets (new machines), one of them"
                           + ("; or neither, to only clear the zone." if clear else "."))
    if clear and arguments.get("zoneId") is None:
        raise PatternError("clearZone needs zoneId: the zone to clear.")
    if clear_only and shape is not None:
        raise PatternError("A strategy needs the cell's machines: placementIds or assets. To only clear the zone, "
                           "leave strategy out.")
    if shape is None and not clear_only:
        raise PatternError("Give the cell's strategy: line, l, u, grid, parallel, serpentine, loop, spine, "
                           "herringbone or cluster.")
    index = _index(layout)
    zone = None
    if arguments.get("zoneId") is not None:
        found = index.get(arguments["zoneId"])
        if not found or found[0] != "zones":
            raise PatternError(f"There is no zone {arguments['zoneId']} in the saved layout.")
        zone = found[1]
        if arguments.get("center") is not None:
            raise PatternError("Give zoneId or center for the cell, one of them.")
    if clear_only:
        return _clear_only(layout, catalog, index, zone, arguments)
    removing = list(arguments.get("removeIds") or [])
    clearing, kept = (_clearing(layout, catalog, index, zone, set(placement_ids or []), set(removing)) if clear
                      else ([], []))
    center = None
    if zone is not None:
        bounds = lp.bounds_from_points(zone.get("boundary") or [])
        if not bounds:
            raise PatternError(f"{_named(index, zone['zoneId'])} has no usable outline.")
        center = {"x": bounds["center"]["x"], "y": lp.finite(zone.get("floorElevation", lp.MISSING), 0),
                  "z": bounds["center"]["z"]}
    elif arguments.get("center") is not None:
        center = {"x": float(arguments["center"]["x"]), "y": 0.0, "z": float(arguments["center"]["z"])}
    if assets and center is None:
        raise PatternError("New machines need a place for the cell: give zoneId or center.")
    if placement_ids:
        seed, new = _cell_seed(layout, catalog, placement_ids), {}
        removals, removed, walks = _removals(layout, [*removing, *clearing], set(placement_ids))
    else:
        removals, removed, walks = _removals(layout, [*removing, *clearing], set())
        gone = {operation["placementId"] for operation in removals if operation["op"] == "delete_placement"}
        seed, new = _new_machines(layout, catalog, assets, center, gone)
    if not 2 <= len(seed) <= 50:
        raise PatternError("A cell takes 2 to 50 machines.")
    if arguments.get("rows") is not None and arguments["rows"] > len(seed):
        raise PatternError(f"rows ({arguments['rows']}) is more than the {len(seed)} machines.")
    if arguments.get("openSide") is not None and shape != "u":
        raise PatternError("openSide is for a U; turn other shapes with turnDegrees.")
    if arguments.get("openSide") is not None and arguments.get("turnDegrees") is not None:
        raise PatternError("Give openSide or turnDegrees for the U, one of them.")
    angle = (lp.normalize_degrees(COMPASS_HEADINGS[arguments["openSide"]] - U_OPENS)
             if arguments.get("openSide") is not None else lp.finite(arguments.get("turnDegrees", lp.MISSING), 0))
    facing = arguments.get("facing") or "operator-inside"
    gap = float(arguments["gap"]) if arguments.get("gap") is not None else 1.0
    options = {"shape": shape, "gap": gap, "orientation": facing if facing in lp.CELL_ORIENTATIONS else "preserve",
               "angleDegrees": angle, "invertU": False}
    for key in ("width", "depth", "rows"):
        if arguments.get(key) is not None:
            options[key] = arguments[key]
    if center is not None:
        options["center"] = {"x": center["x"], "z": center["z"]}
        # The ribbon sizes a cell from the selection's spread; a cell put somewhere new starts from the machines.
        pitch = max(max(item["width"], item["depth"]) for item in seed) + max(0.0, gap)
        width, depth = pitch * max(2, math.ceil(len(seed) / 2)), pitch * 2
        if zone is not None:
            half_x, half_z = _zone_half_extents(zone, center, angle)
            width, depth = min(width, 2 * half_x), min(depth, 2 * half_z)
        options.setdefault("width", width)
        options.setdefault("depth", depth)
    sides_of = {item["id"]: _sides(new[item["id"]]["record"] if item["id"] in new
                                   else lp.catalog_record(catalog, index[item["id"]][1])) for item in seed}

    def arrange(settings):
        try:
            built = lp.build_cell_layout(seed, settings)
        except PatternError as error:
            if "must contain" not in str(error):
                raise
            need = 2 * (max(math.hypot(item["width"], item["depth"]) / 2 for item in seed) + max(0.0, gap) / 2)
            room = (f" {_named(index, zone['zoneId'])} leaves about {settings['width']:.1f} x "
                    f"{settings['depth']:.1f} m." if zone is not None else "")
            raise PatternError(f"The cell needs more than {need:.1f} x {need:.1f} m for these machines with a "
                               f"{gap:g} m gap.{room} Try a smaller gap, fewer machines, a bigger zone or another "
                               "strategy.") from error
        turns = []
        for item, move in zip(seed, built["moves"]):
            operator = sides_of[item["id"]][0]
            rotation = move["rotationDegrees"]
            if facing == "operator-inside":
                rotation = lp.normalize_degrees(_inside_heading(shape, move, angle, arguments.get("operatorSide"))
                                                - (operator if operator is not None else 0))
            turns.append(rotation)
        return built, turns

    result, turns = arrange(options)
    if zone is not None and not _fits(zone, result["guide"]["center"], result["guide"]["width"],
                                      result["guide"]["depth"], angle):
        guide = result["guide"]
        raise PatternError(f"The cell ({guide['width']:.1f} x {guide['depth']:.1f} m) does not fit inside "
                           f"{_named(index, zone['zoneId'])}; give a smaller width or depth, or turn it.")
    # The ribbon's default size is tight (its gap is only a preferred spacing), and it does not look at what else
    # stands where the cell goes. So a default-sized cell grows (width and depth apart: an L's corner needs one, a
    # row the other; the smallest area first), and in a zone it may shift inside the zone (the nearest shift first)
    # until neighbours, and what stays there, keep the gap. The positions are still the ribbon's for that size
    # and centre.
    base = (result["guide"]["width"], result["guide"]["depth"])
    explicit = arguments.get("width") is not None or arguments.get("depth") is not None
    sizes = [base] if explicit else [base, *_growth_sizes(base, zone, result["guide"]["center"], angle)]
    largest = max(sizes, key=lambda size: size[0] * size[1])
    middle = result["guide"]["center"]
    reach = (math.hypot(*largest) / 2 if zone is None else
             max(math.hypot(point["x"] - middle["x"], point["z"] - middle["z"]) for point in zone["boundary"]))
    stays = _obstacles(layout, catalog, middle, reach + gap,
                       {item["id"] for item in seed} | {operation["placementId"] for operation in removals
                                                         if operation["op"] == "delete_placement"})
    best = None
    for number, size in enumerate(sizes):
        built, built_turns = (result, turns) if number == 0 else arrange(
            {**options, "width": size[0], "depth": size[1]})
        own = _closest_gap(seed, built["moves"], built_turns)
        shapes = _footprints(seed, built["moves"], built_turns)
        shifts = (_shifts(zone, built["guide"], angle) if zone is not None and stays and own[0] >= gap - 1e-6
                  else [(0.0, 0.0)])
        for shift in shifts:
            blocked = _obstacle_gap(shapes, shift, stays)
            score = min(own[0], blocked[0])
            if best is None or score > best["score"] + 1e-9:
                best = {"score": score, "result": built, "turns": built_turns, "own": own, "blocked": blocked,
                        "shift": shift}
            if score >= gap - 1e-6:
                break
        if best["score"] >= gap - 1e-6:
            break
    result, turns = _shifted(best["result"], best["shift"]), best["turns"]
    closest, blocked = best["own"], best["blocked"]
    guide = result["guide"]
    final = _footprints(seed, result["moves"], turns)
    near = [item["label"] for item in stays if _obstacle_gap(final, (0.0, 0.0), [item])[0] < NEAR]
    if facing == "operator-inside":
        guide = {**guide, "facing": "operator-inside"}
    namespace = _namespace(CELL_TOOL, arguments, revision)
    machines, unverified, operations, new_ids = [], [], [], []
    round_it = guide["center"] if shape in ("u", "l", "loop", "cluster") or facing in (
        "face-center", "face-outward") else None  # a row's centre says nothing about which way it faces
    moves = []
    for item, move, rotation in zip(seed, result["moves"], turns):
        record = new[item["id"]]["record"] if item["id"] in new else None
        operator, front = sides_of[item["id"]]
        reviewed = operator is not None
        placement_id = (f"pl-cell-{namespace[:12]}-{len(new_ids) + 1}" if item["id"] in new else item["id"])
        if item["id"] in new:
            new_ids.append(placement_id)
            label = f"{record.get('displayName') or record['assetId']} {new[item['id']]['number']}"
        else:
            label = _named(index, item["id"])
        if not reviewed:
            unverified.append(label)
        machines.append({"label": label, "placementId": placement_id, "assetId": item["assetId"],
                         "new": item["id"] in new, "position": _point(move["position"]),
                         "yawDegrees": _round(rotation),
                         "frontFaces": _compass_name(rotation + (front if front is not None else 0)),
                         "frontReviewed": reviewed,
                         **({"operatorFaces": _side_faces(rotation + operator, move["position"], round_it)}
                            if reviewed else {})})
        moves.append((item, move, rotation, placement_id, label))
    sources = new_ids or [item["id"] for item in seed]
    provenance = _provenance(namespace, "cell_layout", shape, sources, len(seed), len(seed), guide)
    for item, move, rotation, placement_id, label in moves:  # label: the instanceLabel for a new machine
        if item["id"] in new:
            record = new[item["id"]]["record"]
            operations.append({"op": "place_asset", "placement": {
                "placementId": placement_id, "assetId": record["assetId"],
                "assetDefinitionRevision": record["assetDefinitionRevision"],
                "transform": {"position": _world_position(move["position"]), "quaternion": yaw_quaternion(rotation),
                              "scale": 1},
                "positionMode": "manual", "snapRelationship": None,
                "metadata": {"instanceLabel": label, "inputMethod": "sage-cell-layout",
                             "layoutProvenance": deepcopy(provenance)}}})
        else:
            operations.append({"op": "move_placement", "placementId": placement_id,
                               "position": _world_position(move["position"]), "movementKind": "user",
                               "layoutProvenance": deepcopy(provenance)})
            operations.append({"op": "rotate_placement", "placementId": placement_id,
                               "quaternion": yaw_quaternion(rotation), "movementKind": "user",
                               "layoutProvenance": deepcopy(provenance)})
    if not new:
        _with_seed_provenance(operations, provenance, provenance["seedEntityIds"])
    return {
        "available": True, "strategy": shape, "cellName": f"{SHAPE_NAMES[shape]} cell",
        "machines": machines,
        "cell": {"center": _point(guide["center"]), "width": _round(guide["width"]), "depth": _round(guide["depth"]),
                 "usableWidth": _round(guide["usableWidth"]), "usableDepth": _round(guide["usableDepth"]),
                 "turnDegrees": _round(angle), **({"opensTo": _compass_name(U_OPENS + angle)} if shape == "u" else {}),
                 **({"zone": _named(index, zone["zoneId"])} if zone is not None else {})},
        "facing": facing, "operatorSides": _sides_said(machines), "unverifiedFacing": unverified,
        "closestGap": ({"meters": _round(closest[0]), "between": [machines[i]["label"] for i in closest[1]]}
                       if closest[1] else None),
        **({"shiftedFromZoneCenter": _point({"x": best["shift"][0], "z": best["shift"][1]})}
           if any(best["shift"]) else {}),
        **({"keptClearOf": near} if near else {}),
        **({"note": " ".join(notes)} if (notes := _cell_notes(closest, blocked, gap, machines, stays)) else {}),
        **({"cleared": _cleared(index, zone, removals, kept)} if clear else {}),
        "removed": removed, **({"alsoRemoves": _also_removes(walks)} if walks else {}),
        "operations": [*removals, *operations],
    }


def plan(name: str, layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    if name == PATTERN_TOOL:
        return plan_pattern(layout, catalog, arguments, revision=revision)
    if name == CELL_TOOL:
        return plan_cell(layout, catalog, arguments, revision=revision)
    raise PatternError(f"unknown planning tool {name}")
