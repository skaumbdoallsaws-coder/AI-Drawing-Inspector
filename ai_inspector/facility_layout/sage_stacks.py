"""Sage's stacks and cell groups (docs/sage-ribbon-tools-plan.md, R4): the ribbon's Build tools Stack, On Surface,
Create Cell and Ungroup Cell, planned on the server like the patterns (sage_patterns.py) and returned as a package
for preview_planned_design.

- plan_facility_stack mode stack: the patterns' buildVerticalStack (static/facility_layout_patterns.js), ported in
  layout_patterns.py: copies of one item straight above it, count levels in all, gap between them.
- plan_facility_stack mode surface: buildSurfaceStack, as the command adapter runs it
  (static/facility_layout_command_adapter.js): items laid out in rows on a support's published surface. The
  adapter's guards: exact asset revisions, no locked or stacked item, an item on another support needs that support
  in the request, and what already sits on the support or the items comes along in the request.
- Both through the session's applyPattern (sage_positions.apply_pattern), with their layout provenance.
- plan_facility_cell action group: the session's createCellGroup, as the ribbon's Create Cell dialog sends it (its
  defaults: 1 m round the items, the dialog's colour), with the adapter's check that the cell takes in nothing that
  was not named. Action ungroup: the session's ungroupCell (delete_zone); the items stay.

Not in the ribbon (plain refusals before the preview): stacking an item that sits on a support or has things on it,
and a support with no published surface (the ribbon would derive one from the model's box). Items on a named item
and the rest of its stack come into a cell with it (membership is by position anyway). The default cell number is
the next free one for that name, where the ribbon's dialog starts at 1.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

from . import layout_patterns as lp
from .layout_patterns import PatternError
from . import sage_patterns as sp
from . import sage_positions as spos

TOOL = "plan_facility_stack"
MODES = ("stack", "surface")
SIDES = {"top": "above", "bottom": "below"}
MODE_KEYS = {"stack": {"mode", "placementId", "count", "gap"},
             "surface": {"mode", "supportId", "itemIds", "surfaceId", "side", "gap", "itemGap", "inset"}}
GROUP_KEYS = {"group": {"action", "itemIds", "name", "prefix", "number", "envelopePadding"},
              "ungroup": {"action", "zoneId"}}
CELL_COLOR = "#2f80b9"  # the Create Cell dialog's default colour (static/facility_layout_workspace.js)
CELL_PADDING = 1.0  # and its envelope padding, in metres
CELL_NAME = "Manufacturing Cell"
LISTED = 40


def tool_spec() -> dict:
    metres = {"type": "number", "minimum": 0, "maximum": 5}
    return {"name": TOOL, "description": (
        "Stack items, or put items on another item's surface, with the ribbon's Build tools, instead of writing "
        "coordinates. mode stack: copies of placementId straight above it, count levels in all (the original "
        "included: a stack of 3 is count 3), gap metres between levels (default 0); the item stays where it is. "
        "mode surface: put itemIds on supportId's published surface (surfaceId; default its first), laid out in "
        "rows from its corner, itemGap apart (default 0.05 m), inset from its edges (default 0.05 m), side top "
        "(the default) or bottom, gap above the surface (default 0); they move with the support afterwards. What "
        "already sits on the support is laid out again with them: include it in itemIds. Locked or stacked items are "
        "refused. Read-only: stage the packageId with preview_planned_design."),
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["mode"], "properties": {
            "mode": {"enum": list(MODES)}, "placementId": sp.ID,
            "count": {"type": "integer", "minimum": 2, "maximum": lp.MAX_PATTERN_COUNT}, "gap": metres,
            "supportId": sp.ID, "itemIds": sp._schema_ids(1, 239), "surfaceId": sp.ID,
            "side": {"enum": list(SIDES)}, "itemGap": metres, "inset": metres}}}


# ---------------------------------------------------------------- shared

def _keys(arguments: Mapping, allowed: set, what: str) -> None:
    stray = sorted(key for key in arguments if key not in allowed)
    if stray:
        raise PatternError(f"{', '.join(stray)} {'is' if len(stray) == 1 else 'are'} not for {what}.")


def _placement(index: Mapping, identifier: str) -> Mapping:
    if identifier not in index:
        raise PatternError(f"There is no {identifier} in the saved layout.")
    collection, entity = index[identifier]
    if collection != "placements":
        raise PatternError(f"{sp._named(index, identifier)} is not a placed item.")
    return entity


def _held(layout: Mapping, identifier: str) -> list:
    """What sits on the placement."""
    return [item for item in layout.get("placements") or [] if sp._attached(item) == identifier]


def _sized(layout: Mapping, catalog: Sequence[Mapping], index: Mapping, ids: Sequence[str]) -> list:
    """collectSelection with the command adapter's exact revisions, refused in plain words."""
    try:
        return lp.collect_selection(layout, catalog, list(ids), {"expandZones": False, "includeZones": False,
                                                                  "strictGeometry": True})
    except PatternError as error:
        for identifier in ids:
            try:
                lp.collect_selection(layout, catalog, [identifier], {"expandZones": False, "includeZones": False,
                                                                     "strictGeometry": True})
            except PatternError:
                raise PatternError(f"{sp._named(index, identifier)}: its model's size at its revision is not in "
                                   "the library, so it cannot be stacked or placed on a surface.") from error
        raise


# ---------------------------------------------------------------- plan_facility_stack

def plan_stack(layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    mode = arguments.get("mode")
    if mode not in MODES:
        raise PatternError("mode must be stack or surface.")
    _keys(arguments, MODE_KEYS[mode], f"mode {mode}")
    catalog = list(catalog)
    index = sp._index(layout)
    namespace = sp._namespace(TOOL, arguments, revision)
    return (_stack if mode == "stack" else _surface)(layout, catalog, index, arguments, namespace)


def _stack(layout, catalog, index, arguments, namespace) -> dict:
    if "placementId" not in arguments:
        raise PatternError("mode stack needs placementId: the item to stack.")
    identifier = arguments["placementId"]
    placement = _placement(index, identifier)
    name = sp._named(index, identifier)
    if placement.get("positionMode") == "locked":
        raise PatternError(f"{name} is locked. Ask the user to unlock it.")
    if spos._stack(placement):
        raise PatternError(f"{name} is already part of a stack.")
    support = sp._attached(placement)
    if support:
        raise PatternError(f"{name} sits on {sp._named(index, support)}; a stack stands on the floor. Move it off "
                           "first.")
    held = _held(layout, identifier)
    if held:
        raise PatternError(f"{name} has {sp._named(index, held[0]['placementId'])} on it; the level above would "
                           "stand in it.")
    seed = _sized(layout, catalog, index, [identifier])
    if not (isinstance(seed[0].get("height"), (int, float)) and seed[0]["height"] > 0):
        raise PatternError(f"{name}: its height is not in the library, so it cannot be stacked.")
    result = lp.build_vertical_stack(seed, {"count": arguments.get("count", 3), "gap": arguments.get("gap", 0)})
    operations = spos.apply_pattern(layout, result, namespace)
    guide = result["guide"]
    return {"available": True, "mode": "stack", "item": name, "levels": result["count"],
            "newItems": len(result["copies"]), "itemHeight": sp._round(guide["itemHeightMeters"]),
            "gap": sp._round(guide["gapMeters"]), "totalHeight": sp._round(guide["totalHeightMeters"]),
            "operations": operations}


def _surface_of(index: Mapping, support: Mapping, requested: str | None) -> Mapping:
    surfaces = [surface for surface in support.get("supportSurfaces") or [] if isinstance(surface, Mapping)
                and surface.get("surfaceId")]
    name = sp._named(index, support["id"])
    if not surfaces:
        raise PatternError(f"{name} has no published surface to put items on.")
    if requested is None:
        return surfaces[0]
    found = next((surface for surface in surfaces if surface["surfaceId"] == requested), None)
    if not found:
        raise PatternError(f"{name} has no surface {requested}; its surfaces: "
                           f"{', '.join(surface['surfaceId'] for surface in surfaces)}.")
    return found


def _surface(layout, catalog, index, arguments, namespace) -> dict:
    for key in ("supportId", "itemIds"):
        if key not in arguments:
            raise PatternError(f"mode surface needs {key}.")
    support_id, ids = arguments["supportId"], list(dict.fromkeys(arguments["itemIds"]))
    if support_id in ids:
        raise PatternError("The support cannot also be one of the itemIds.")
    for identifier in [support_id, *ids]:
        _placement(index, identifier)
    seed = _sized(layout, catalog, index, [support_id, *ids])
    selected = {item["id"] for item in seed}
    for item in seed:
        name = sp._named(index, item["id"])
        if item.get("positionMode") == "locked":
            raise PatternError(f"{name} is locked. Ask the user to unlock it, or leave it out.")
        if spos._stack(index[item["id"]][1]):
            raise PatternError(f"{name} is part of a stack; stacks cannot go on a surface or hold items yet.")
        support = sp._attached(index[item["id"]][1])
        if support and support not in selected:
            raise PatternError(f"{name} sits on {sp._named(index, support)}. Move it off first, or put it on its "
                               "own support's surface.")
    for placement in layout.get("placements") or []:
        holder = sp._attached(placement)
        if holder in selected and placement["placementId"] not in selected:
            raise PatternError(f"{sp._named(index, holder)} has {sp._named(index, placement['placementId'])} on it: "
                               "include it in itemIds (what is on the surface is laid out again).")
    support = next(item for item in seed if item["id"] == support_id)
    surface = _surface_of(index, support, arguments.get("surfaceId"))
    side = SIDES[arguments.get("side", "top")]
    if isinstance(surface.get("allowedSides"), list) and side not in surface["allowedSides"]:
        allowed = " or ".join(next(word for word, value in SIDES.items() if value == item)
                              for item in surface["allowedSides"] if item in SIDES.values())
        raise PatternError(f"{sp._named(index, support_id)}'s {surface['surfaceId']} takes items on its "
                           f"{allowed or 'other side'} only.")
    try:
        result = lp.build_surface_stack(seed, {
            "supportPlacementId": support_id, "surfaceId": surface["surfaceId"], "side": side,
            "gap": arguments.get("gap", 0), "itemGap": arguments.get("itemGap", 0.05),
            "inset": arguments.get("inset", 0.05)})
    except PatternError as error:
        text = str(error)
        match = re.match(r"^'(.+)' does not fit on the selected support surface$", text)
        if match:
            raise PatternError(f"{sp._named(index, match.group(1))} is bigger than "
                               f"{sp._named(index, support_id)}'s {surface['surfaceId']}.") from error
        if text.startswith("selected items do not fit"):
            raise PatternError(f"They do not all fit on {sp._named(index, support_id)}'s {surface['surfaceId']}: "
                               "put fewer items on it, or use a smaller itemGap or inset.") from error
        if text.startswith("support surface is too small"):
            raise PatternError(f"{sp._named(index, support_id)}'s {surface['surfaceId']} is too small for that "
                               "inset.") from error
        if text.startswith("support surface requires"):
            raise PatternError(f"{sp._named(index, support_id)}'s {surface['surfaceId']} is not level in its "
                               "library model, so nothing can be placed on it.") from error
        raise
    operations = spos.apply_pattern(layout, result, namespace)
    placed = [{"item": sp._named(index, relation["sourceId"]),
               "onSurfaceAt": sp._point(relation["snapRelationship"]["localPosition"]),
               "to": sp._point(move["position"]), "height": sp._round(move["position"]["y"])}
              for relation, move in zip(result["relationships"], result["moves"])]
    return {"available": True, "mode": "surface", "support": sp._named(index, support_id),
            "surface": surface["surfaceId"], **({"surfaceLabel": surface["label"]} if surface.get("label") else {}),
            "side": arguments.get("side", "top"), "placed": placed[:LISTED], "movedCount": len(placed),
            "operations": operations}


# ---------------------------------------------------------------- plan_facility_cell: group and ungroup

def _next_number(layout: Mapping, name: str, prefix: str) -> int:
    """One more than the highest number of a cell named NAME PREFIX<number>, by its numbering or its label."""
    highest = 0
    pattern = re.compile(re.escape(f"{name} {prefix}") + r"(\d+)$")
    for zone in layout.get("zones") or []:
        auto = (sp._cell_group(zone) or {}).get("autoNumber")
        if isinstance(auto, Mapping) and str(auto.get("baseName") or "").strip() == name \
                and str(auto.get("prefix") or "").strip() == prefix:
            highest = max(highest, lp.js_round(sp._js_number_or(auto.get("sequence"), 0)))
        match = pattern.match(str(zone.get("label") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def plan_cell_group(layout: Mapping, catalog: Sequence[Mapping], arguments: Mapping, *, revision: str) -> dict:
    action = arguments.get("action")
    if action not in GROUP_KEYS:
        raise PatternError("action must be arrange, group or ungroup.")
    _keys(arguments, GROUP_KEYS[action], f"action {action}")
    index = sp._index(layout)
    if action == "ungroup":
        return _ungroup(layout, catalog, index, arguments)
    return _group(layout, list(catalog), index, arguments, sp._namespace(sp.CELL_TOOL, arguments, revision))


def _ungroup(layout, catalog, index, arguments) -> dict:
    if "zoneId" not in arguments:
        raise PatternError("action ungroup needs zoneId: the cell to ungroup.")
    found = index.get(arguments["zoneId"])
    if not found or found[0] != "zones":
        raise PatternError(f"There is no zone {arguments['zoneId']} in the saved layout.")
    zone = found[1]
    name = sp._named(index, zone["zoneId"])
    if not sp._cell_group(zone):
        raise PatternError(f"{name} is a zone, not a manufacturing cell; ungroup takes a cell made with Create Cell.")
    members = [item["id"] for item in lp.collect_selection(layout, catalog, [zone["zoneId"]],
                                                           {"expandZones": True, "includeZones": False})]
    return {"available": True, "action": "ungroup", "cell": name, "itemsStay": len(members),
            "operations": [{"op": "delete_zone", "zoneId": zone["zoneId"]}]}


def _group(layout, catalog, index, arguments, namespace) -> dict:
    if not arguments.get("itemIds"):
        raise PatternError("action group needs itemIds: the items the cell goes round.")
    for identifier in arguments["itemIds"]:
        if identifier not in index:
            raise PatternError(f"There is no {identifier} in the saved layout.")
        if index[identifier][0] == "routes":
            raise PatternError(f"{sp._named(index, identifier)} is a route; a cell goes round items.")
    named = lp.collect_selection(layout, catalog, list(arguments["itemIds"]),
                                 {"expandZones": True, "includeZones": False})
    placements = [item["id"] for item in named if item["kind"] == "placement"]
    along = {placement["placementId"] for placement in spos.expanded(layout, placements)} - set(placements)
    try:
        seed = lp.collect_selection(layout, catalog, [item["id"] for item in named] + sorted(along),
                                    {"expandZones": False, "includeZones": False, "strictGeometry": True})
    except PatternError:
        _sized(layout, catalog, index, [item["id"] for item in named if item["kind"] == "placement"])
        raise
    if not seed:
        raise PatternError("Nothing to group: name placements, floor markings or a zone holding them.")
    selected = {item["id"] for item in seed}
    name = str(arguments.get("name") or CELL_NAME).strip() or CELL_NAME
    prefix = str(arguments.get("prefix") or "").strip()
    number = arguments["number"] if "number" in arguments else _next_number(layout, name, prefix)
    padding = max(0.0, float(arguments.get("envelopePadding", CELL_PADDING)))
    bounds = lp.selection_bounds(seed)
    min_x, min_z = bounds["minX"] - padding, bounds["minZ"] - padding
    width, depth = max(0.01, bounds["width"] + 2 * padding), max(0.01, bounds["depth"] + 2 * padding)
    boundary = [{"x": min_x, "z": min_z}, {"x": min_x + width, "z": min_z},
                {"x": min_x + width, "z": min_z + depth}, {"x": min_x, "z": min_z + depth}]
    candidate = {**layout, "zones": [{"zoneId": "__candidate_cell__", "boundary": boundary, "zoneType": "workcell"}]}
    caught = [item["id"] for item in lp.collect_selection(candidate, catalog, ["__candidate_cell__"],
                                                          {"expandZones": True})
              if item["kind"] != "zone" and item["id"] not in selected]
    if caught:
        listed = ", ".join(sp._named(index, identifier) for identifier in caught[:6])
        raise PatternError(f"The cell would also take in {listed}{' and more' if len(caught) > 6 else ''}: add "
                           f"{'it' if len(caught) == 1 else 'them'} to itemIds, or use a smaller envelopePadding "
                           f"(now {sp._round(padding)} m).")
    auto = {"seriesId": f"cell-series-sage-{namespace[:16]}", "baseName": name, "prefix": prefix, "start": number,
            "padding": 2, "sequence": number}
    label = sp._cell_group_label(auto)
    if any(str(zone.get("label") or "") == label for zone in layout.get("zones") or []):
        raise PatternError(f"There is already a zone named {label}: give another number or name.")
    zone = {"zoneType": "workcell", "label": label, "boundary": boundary, "floorElevation": 0, "anchors": [],
            "evidence": [], "extensions": {"style": {"fillColor": CELL_COLOR}, "cellGroup": {
                "schemaVersion": 1, "groupKind": "manufacturing_cell", "membership": "geometric",
                "envelopePadding": padding, "autoNumber": auto, "functionalInterfaces": {}}}}
    return {"available": True, "action": "group", "cell": label, "items": len(seed),
            **({"broughtAlong": [sp._named(index, identifier) for identifier in sorted(along)][:LISTED]}
               if along else {}),
            "size": {"width": sp._round(width), "depth": sp._round(depth)},
            "corner": {"x": sp._round(min_x), "z": sp._round(min_z)}, "envelopePadding": sp._round(padding),
            "operations": [{"op": "add_zone", "zone": zone}]}
