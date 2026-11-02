"""Sage's pattern and cell tools (docs/sage-ribbon-tools-plan.md, R1 and R2): plan_facility_pattern and
plan_facility_cell.

The planners on the shared fixture (tests/fixtures/facility_layout/pattern_parity/factory.json): rows (also given no
direction), grids, mirrors, circles, rings, where they fit (the seed moved inside its zone, or to origin), cells of
placed and new machines, operator-inside facing, removeIds and the refusals. Their
operations against the ribbon's own, run with Node here only: tools/compile_facility_construction_command.js for the
row and the cell, tests/pattern_session_runner.js (the session's applyPattern) for the mirror, circle and ring. And
the whole path on a test host: plan, stage with preview_planned_design, Apply Directly, then the provenance tools
read the result back.
"""
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime import pilot, progress
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import tool_specs as gateway_tool_specs
from ai_inspector.facility_layout import sage_patterns as sp
from ai_inspector.facility_layout.asset_orientation import COMPASS_HEADINGS, yaw_quaternion
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.operation_proposals import create as create_proposal, guard_operations
from ai_inspector.facility_layout.layout_patterns import (PatternError, facing_side_degrees, item_points,
                                                          normalize_degrees, normalized_item)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/facility_layout/pattern_parity/factory.json"
COMPILER = ROOT / "tools/compile_facility_construction_command.js"
MILLS = [f"pl-mill-{index}" for index in range(1, 6)]
NEW_MILLS = [{"assetId": "asset-mill", "count": 5}]
REVISION = "rev-a"


def fixture():
    data = json.loads(FIXTURE.read_bytes())
    return data["layout"], data["catalog"]


def pattern(arguments, layout=None, revision=REVISION):
    saved, catalog = fixture()
    return sp.plan_pattern(layout or saved, catalog, arguments, revision=revision)


def cell(arguments, layout=None, revision=REVISION):
    saved, catalog = fixture()
    return sp.plan_cell(layout or saved, catalog, arguments, revision=revision)


def without(*placement_ids):
    """The fixture's layout without those placements and what sits on them: room for copies that would stand
    there (a pattern is refused, or moves, where something stays in its way)."""
    layout = deepcopy(fixture()[0])
    gone = set(placement_ids)
    gone |= {placement["placementId"] for placement in layout["placements"]
             if (placement.get("snapRelationship") or {}).get("supportPlacementId") in gone}
    layout["placements"] = [placement for placement in layout["placements"] if placement["placementId"] not in gone]
    return layout


def facing_vector(heading):
    radians = math.radians(heading)
    return math.sin(radians), math.cos(radians)  # north is +z, east is +x


def operator_heading(machine):
    """The compass heading the mill's operator side (south in its own axes) faces after its yaw."""
    return (machine["yawDegrees"] + COMPASS_HEADINGS["south"]) % 360


def same_quaternion(left, right):
    sign = 1 if sum(left[key] * right[key] for key in "xyzw") >= 0 else -1
    return all(abs(left[key] - sign * right[key]) < 1e-9 for key in "xyzw")


# ---------------------------------------------------------------- registration

def test_the_tools_are_registered_with_closed_schemas_labels_and_rules():
    specs = {spec["name"]: spec for spec in gateway_tool_specs()}
    for name in sp.NAMES:
        Draft202012Validator.check_schema(specs[name]["input_schema"])
        assert specs[name]["input_schema"]["additionalProperties"] is False
        assert name in pilot.EDIT_INSTRUCTIONS
    layout, catalog = fixture()
    layout = deepcopy(layout)
    layout["zones"].append({"zoneId": "zn-a06", "label": "Assembly Cell A06", "boundary": []})
    names = progress.LayoutNames(layout, catalog)
    assert progress.describe(sp.CELL_TOOL, {"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-a06"},
                             names)["running"] == "Planning a U-shaped cell of 5 machines in Assembly Cell A06"
    assert progress.describe(sp.PATTERN_TOOL, {"seedIds": ["pl-bench-1"], "count": 6}, names)["done"] == \
        "Planned a row of 6 from Bench 1"
    assert progress.describe(sp.PATTERN_TOOL, {"seedIds": ["zn-ws-1"], "count": 3, "rows": 2}, names)["failed"] == \
        "Couldn't plan a 3 by 2 grid of Workstation 1"
    assert progress.failure_reason("layout_pattern_refused") == "not possible as asked"
    assert progress.describe(sp.PATTERN_TOOL, {"kind": "mirror", "seedIds": ["pl-bench-1"]}, names)["done"] == \
        "Planned a mirror image of Bench 1"
    assert progress.describe(sp.PATTERN_TOOL, {"kind": "circular", "seedIds": ["pl-mill-1"], "count": 6},
                             names)["running"] == "Planning a circle of 6 from Mill 1"
    assert progress.describe(sp.PATTERN_TOOL, {"kind": "circular", "seedIds": ["pl-mill-1"], "count": 3,
                                               "totalDegrees": 90}, names)["done"] == "Planned an arc of 3 from Mill 1"
    assert progress.describe(sp.PATTERN_TOOL, {"kind": "perimeter", "seedIds": ["pl-mill-1"]}, names)["failed"] == \
        "Couldn't plan a ring of copies of Mill 1"
    assert "kind mirror mirrors them across a line" in pilot.EDIT_INSTRUCTIONS
    schema = Draft202012Validator(specs[sp.PATTERN_TOOL]["input_schema"])
    for arguments in ({"kind": "mirror", "seedIds": ["pl-mill-1"], "linePoints": [{"x": 0, "z": 0}, {"x": 3, "z": 4}]},
                      {"kind": "circular", "seedIds": ["zn-ws-1"], "count": 6, "center": {"x": 1, "z": 2},
                       "totalDegrees": 180, "turnWithPattern": True},
                      {"kind": "perimeter", "seedIds": ["pl-mill-1"], "shape": "square", "widthCount": 3, "gap": 1}):
        schema.validate(arguments)
    assert not schema.is_valid({"kind": "circular", "seedIds": ["pl-mill-1"], "count": 4, "totalDegrees": 400})


# ---------------------------------------------------------------- plan_facility_pattern

def test_a_row_copies_an_item_and_what_sits_on_it_with_the_ribbons_ids():
    arguments = {"seedIds": ["pl-bench-1", "pl-vise-1"], "count": 6, "direction": "east", "gap": 2}
    result = pattern(arguments)
    operations = result["operations"]
    assert result["spacing"] == 3.8 and result["newItems"] == 10 and result["direction"] == "east"  # 1.8 m + 2 m
    assert [operation["op"] for operation in operations] == ["duplicate_placement"] * 10
    benches = [operation for operation in operations if operation["sourcePlacementId"] == "pl-bench-1"]
    vises = [operation for operation in operations if operation["sourcePlacementId"] == "pl-vise-1"]
    assert [round(operation["position"]["x"], 9) for operation in benches] == [13.8, 17.6, 21.4, 25.2, 29.0]
    for bench, vise in zip(benches, vises):  # each vise sits on its own bench copy
        assert vise["snapRelationship"]["supportPlacementId"] == bench["newPlacementId"]
        assert vise["snapRelationship"]["surfaceId"] == "top"
    assert len({vise["snapRelationship"]["attachmentId"] for vise in vises}) == 5
    provenance = operations[0]["layoutProvenance"]
    assert provenance["command"] == "linear_pattern" and provenance["seedEntityIds"] == ["pl-bench-1", "pl-vise-1"]
    assert provenance["parameters"]["count"] == 6 and abs(provenance["parameters"]["pitch"] - 3.8) < 1e-9
    assert operations[0]["layoutProvenanceSeedEntityIds"] == ["pl-bench-1", "pl-vise-1"]
    assert {operation["layoutProvenance"]["instanceIndex"] for operation in operations[1:]} == {1, 2, 3, 4, 5}
    # The same request on the same revision gives the same ids; another revision, new ones.
    assert pattern(arguments)["operations"] == operations
    assert pattern(arguments, revision="rev-b")["operations"][0]["newPlacementId"] != benches[0]["newPlacementId"]


def test_a_grid_repeats_the_row_across_it():
    alone = without(*MILLS[1:])  # mills 2 to 4 stand where the grid goes
    result = pattern({"seedIds": ["pl-mill-1"], "count": 3, "direction": "east", "spacing": 5, "rows": 2,
                      "rowDirection": "north", "rowGap": 1}, alone)
    assert result["newItems"] == 5 and result["rowSpacing"] == 4.7  # the mill is 3.7 m deep, plus the 1 m gap
    assert [instance["center"] for instance in result["instances"]] == [
        {"x": 2.0, "z": 20.0}, {"x": 7.0, "z": 20.0}, {"x": 12.0, "z": 20.0},
        {"x": 2.0, "z": 24.7}, {"x": 7.0, "z": 24.7}, {"x": 12.0, "z": 24.7}]
    operations = result["operations"]
    assert sorted(operation["layoutProvenance"].get("instanceIndex", 0) for operation in operations) == [0, 2, 3, 4, 5]
    assert operations[0]["layoutProvenance"]["parameters"]["rows"] == 2
    headed = pattern({"seedIds": ["pl-mill-1"], "count": 3, "headingDegrees": 90, "spacing": 5, "rows": 2,
                      "rowHeadingDegrees": 0, "rowGap": 1}, alone)
    assert headed["operations"] == pattern({"seedIds": ["pl-mill-1"], "count": 3, "headingDegrees": 90, "spacing": 5,
                                            "rows": 2, "rowHeadingDegrees": 0, "rowGap": 1}, alone)["operations"]
    assert [instance["center"] for instance in headed["instances"]] == [
        instance["center"] for instance in result["instances"]]


def test_a_zone_seed_copies_the_station_and_what_stands_in_it():
    result = pattern({"seedIds": ["zn-ws-1"], "count": 3, "direction": "east", "spacing": 6})
    kinds = sorted(operation["op"] for operation in result["operations"])
    assert kinds == ["add_floor_marking"] * 2 + ["add_zone"] * 2 + ["duplicate_placement"] * 4
    zones = [operation["zone"] for operation in result["operations"] if operation["op"] == "add_zone"]
    assert [zone["boundary"][0] for zone in zones] == [{"x": 26.0, "z": 0.0}, {"x": 32.0, "z": 0.0}]
    assert all("zoneId" not in zone and zone["extensions"]["layoutProvenance"]["command"] == "linear_pattern"
               for zone in zones)


def test_removed_items_go_first_with_what_is_attached_to_them():
    result = pattern({"seedIds": ["pl-mill-1"], "count": 2, "direction": "north", "spacing": 5,
                      "removeIds": ["pl-bench-1", "mk-1"]})
    operations = result["operations"]
    assert operations[:3] == [{"op": "delete_placement", "placementId": "pl-bench-1"},
                              {"op": "delete_floor_marking", "markingId": "mk-1"},
                              {"op": "delete_placement", "placementId": "pl-vise-1"}]  # the vise sat on the bench
    assert result["removed"] == ["Bench 1 (pl-bench-1)", "Arrow (mk-1)", "Vise 1 (pl-vise-1)"]
    assert operations[3]["op"] == "duplicate_placement" and operations[3]["layoutProvenanceSeedEntityIds"] == [
        "pl-mill-1"]


@pytest.mark.parametrize("arguments, words", [
    ({"seedIds": ["pl-locked-1"]}, "Locked mill (pl-locked-1) is locked"),
    ({"seedIds": ["pl-vise-1"]}, "sits on Bench 1 (pl-bench-1): include its support"),
    ({"seedIds": ["pl-bench-1"]}, "include every item attached to a support"),
    ({"seedIds": ["pl-none"]}, "There is no pl-none"),
    ({"seedIds": ["pl-stale-1"]}, "model revision or size is not in the library"),
    ({"seedIds": ["pl-mill-1"], "headingDegrees": 90}, "one of them"),
    ({"seedIds": ["pl-mill-1"], "spacing": None}, "spacing (centre to centre) or gap"),
    ({"seedIds": ["pl-mill-1"], "gap": 1}, "spacing (centre to centre) or gap"),
    ({"seedIds": ["pl-mill-1"], "rows": 2}, "Give the spacing between rows as rowSpacing (centre to centre) or rowGap"),
    ({"seedIds": ["pl-mill-1"], "rows": 2, "rowDirection": "west", "rowGap": 1}, "runs along the row"),
    ({"seedIds": MILLS, "count": 50}, "more than 240 new items"),
    ({"seedIds": ["pl-mill-1"]}, "The row does not fit (east: Mill 2 (pl-mill-2) stands in the way of copy 1). Give "
     "another direction, fewer copies, a smaller gap, origin or removeIds."),  # and no zone to move it in
    ({"seedIds": ["zn-ws-1"], "origin": {"x": 30, "z": 10}}, "Workstation 1 (zn-ws-1) is a zone: leave origin out"),
    ({"seedIds": ["pl-mill-1"], "removeIds": ["zn-ws-1"]}, "a zone stays"),
    ({"seedIds": ["pl-mill-1"], "removeIds": ["pl-mill-1"]}, "part of the plan"),
    ({"seedIds": ["pl-mill-1"], "removeIds": ["pl-locked-1"]}, "ask the user before removing it"),
    ({"seedIds": ["pl-mill-1"], "removeIds": ["pl-gone"]}, "There is no pl-gone to remove"),
])
def test_a_pattern_that_cannot_be_made_says_why(arguments, words):
    request = {"count": 3, "direction": "east", "spacing": 5, **arguments}
    request = {key: value for key, value in request.items() if value is not None}
    with pytest.raises(PatternError) as refused:
        pattern(request)
    assert words in str(refused.value)


# ---------------------------------------------------------------- a row given no direction

ROW = {"seedIds": ["pl-bench-1", "pl-vise-1"], "count": 3, "gap": 2}


def with_box(layout, placement_id, label, x, z, source="pl-box-1"):
    box = deepcopy(next(p for p in layout["placements"] if p["placementId"] == source))
    box.update(placementId=placement_id, metadata={"instanceLabel": label})
    box["transform"]["position"] = {"x": x, "y": 0, "z": z}
    layout["placements"].append(box)
    return layout


def test_a_row_given_no_direction_runs_along_the_seeds_length_the_way_it_fits():
    layout = deepcopy(fixture()[0])
    result = pattern(ROW)  # nothing in either way: the bench's own +x way
    assert (result["direction"], result["spacing"], result["gap"]) == ("east", 3.8, 2.0)
    assert result["picked"] == "direction east, along the length of Bench 1 (pl-bench-1)."
    blocked = with_box(deepcopy(layout), "pl-box-east", "Box east", 13.8, 5)  # where the first copy east goes
    result = pattern(ROW, blocked)
    assert result["picked"] == ("direction west, along the length of Bench 1 (pl-bench-1); east: Box east "
                                "(pl-box-east) stands in the way of copy 1.")
    benches = [op for op in result["operations"] if op["sourcePlacementId"] == "pl-bench-1"]
    assert [round(op["position"]["x"], 9) for op in benches] == [6.2, 2.4]
    assert pattern({**ROW, "removeIds": ["pl-box-east"]}, blocked)["direction"] == "east"  # it does not stay
    with pytest.raises(PatternError) as refused:  # a direction given is kept: no zone to move the bench in
        pattern({**ROW, "direction": "east"}, blocked)
    assert str(refused.value) == ("The row does not fit (east: Box east (pl-box-east) stands in the way of copy 1). "
                                  "Give another direction, fewer copies, a smaller gap, origin or removeIds.")
    near = with_box(deepcopy(layout), "pl-box-near", "Box near", 13.8, 6.35)  # 0.5 m beside the first copy east
    assert pattern(ROW, near)["picked"] == ("direction west, along the length of Bench 1 (pl-bench-1); east: "
                                            "less room (0.50 m clear).")
    both = with_box(deepcopy(blocked), "pl-box-west", "Box west", 6.2, 5)
    result = pattern(ROW, both)  # neither way along: across it
    assert result["picked"] == (
        "direction south, across the length of Bench 1 (pl-bench-1); east: Box east (pl-box-east) stands in the way "
        "of copy 1; west: Box west (pl-box-west) stands in the way of copy 1.")
    benches = [op for op in result["operations"] if op["sourcePlacementId"] == "pl-bench-1"]
    assert [(op["position"]["x"], round(op["position"]["z"], 9)) for op in benches] == [(10.0, 2.2), (10.0, -0.6)]
    boxed = with_box(with_box(both, "pl-box-south", "Box south", 10, 2.2), "pl-box-north", "Box north", 10, 7.8)
    with pytest.raises(PatternError) as refused:
        pattern(ROW, boxed)
    assert str(refused.value) == (
        "Neither along nor across the length of Bench 1 (pl-bench-1) does the row fit (east: Box east (pl-box-east) "
        "stands in the way of copy 1; west: Box west (pl-box-west) stands in the way of copy 1; south: Box south "
        "(pl-box-south) stands in the way of copy 1; north: Box north (pl-box-north) stands in the way of copy 1). "
        "Give fewer copies, a smaller gap, origin or removeIds.")


def test_a_row_given_no_direction_stays_in_the_seeds_zone_and_runs_along_a_turned_seed():
    layout = deepcopy(fixture()[0])
    layout["zones"].append({"zoneId": "zn-bay", "label": "Bay", "zoneType": "workcell", "floorElevation": 0,
                            "anchors": [], "evidence": [], "boundary": [
                                {"x": 0, "z": 0}, {"x": 14, "z": 0}, {"x": 14, "z": 10}, {"x": 0, "z": 10}]})
    assert pattern(ROW, layout)["picked"] == ("direction west, along the length of Bench 1 (pl-bench-1); east: "
                                              "copy 1 would be outside Bay (zn-bay).")  # it would cross x 14
    grid = pattern({**ROW, "rows": 2, "rowDirection": "north", "rowGap": 1})
    assert (grid["direction"], grid["rowDirection"], grid["newItems"]) == ("east", "north", 10)
    turned = deepcopy(fixture()[0])
    box = next(p for p in turned["placements"] if p["placementId"] == "pl-box-1")
    box["transform"]["quaternion"] = yaw_quaternion(90)  # its length now runs north-south
    result = pattern({"seedIds": ["pl-box-1"], "count": 3, "gap": 2}, turned)
    assert (result["direction"], result["spacing"], result["gap"]) == ("south", 3.5, 2.0)
    assert [(round(op["position"]["x"], 9), round(op["position"]["z"], 9)) for op in result["operations"]] == [
        (40.0, 1.5), (40.0, -2.0)]


def test_a_grid_given_no_side_puts_its_rows_where_they_fit_the_gap_apart():
    grid = pattern({**ROW, "direction": "east", "rows": 2})  # "2 m apart": the rows too
    assert (grid["rowDirection"], grid["rowGap"], grid["rowSpacing"], grid["newItems"]) == ("south", 2.0, 2.8, 10)
    assert grid["picked"] == "rows south."
    south = with_box(deepcopy(fixture()[0]), "pl-box-south", "Box south", 13.8, 2.2)  # where copy 4 goes south
    grid = pattern({**ROW, "direction": "east", "rows": 2}, south)
    assert grid["rowDirection"] == "north"
    assert grid["picked"] == "rows north; rows south: Box south (pl-box-south) stands in the way of copy 4."
    across = pattern({**ROW, "rows": 2, "rowDirection": "east", "rowGap": 1})  # rows east: the row runs across
    assert (across["direction"], across["rowDirection"], across["rowSpacing"]) == ("south", "east", 2.8)
    assert across["picked"] == "direction south (rows east), across the length of Bench 1 (pl-bench-1)."


def bay(layout, zone_id, label, x0, z0, x1, z1):
    layout["zones"].append({"zoneId": zone_id, "label": label, "zoneType": "workcell", "floorElevation": 0,
                            "anchors": [], "evidence": [], "boundary": [
                                {"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]})
    return layout


def boxed_in(zone):
    """Bench 1 at (10, 5) with a box in the way of the first copy each way along it, in ZONE (x0, z0, x1, z1)."""
    layout = with_box(with_box(deepcopy(fixture()[0]), "pl-box-east", "Box east", 13.8, 5), "pl-box-west",
                      "Box west", 6.2, 5)
    return bay(layout, "zn-bay", "Bay", *zone)


def test_a_row_that_does_not_fit_where_its_seed_stands_moves_the_seed_inside_its_zone_and_says_so():
    layout = boxed_in((0, 3, 40, 7))
    result = pattern(ROW, layout)
    assert result["direction"] == "east"
    assert result["picked"] == ("direction east, along the length of Bench 1 (pl-bench-1); west: Box west "
                                "(pl-box-west) stands in the way of copy 1.")
    assert result["seedMoved"] == {
        "items": ["Bench 1 (pl-bench-1)", "Vise 1 (pl-vise-1)"], "by": {"x": 7.5, "z": 0.0}, "meters": 7.5,
        "to": {"x": 17.5, "z": 5.0}, "why": (
            "from where Bench 1 (pl-bench-1) stands the row does not fit (Box east (pl-box-east) stands in the way "
            "of copy 1); this is the nearest place inside Bay (zn-bay) that keeps it 2.00 m clear of what stays")}
    operations = result["operations"]
    assert operations[:2] == [  # the seed moves first, the vise with its bench, then it is copied where it stands
        {"op": "move_placement", "placementId": "pl-bench-1", "position": {"x": 17.5, "y": 0.0, "z": 5.0},
         "movementKind": "user"},
        {"op": "move_placement", "placementId": "pl-vise-1", "position": {"x": 17.8, "y": 1.0, "z": 5.1},
         "movementKind": "user"}]
    benches = [op for op in operations if op.get("sourcePlacementId") == "pl-bench-1"]
    assert [round(op["position"]["x"], 9) for op in benches] == [21.3, 25.1]
    assert operations[2]["layoutProvenanceSeedEntityIds"] == ["pl-bench-1", "pl-vise-1"]
    assert result["extent"]["minX"] > 16 and result["closestGap"]["meters"] == 2.0
    given = pattern({**ROW, "direction": "east"}, layout)  # a direction given moves the seed the same way
    assert given["seedMoved"] == result["seedMoved"] and "picked" not in given
    assert [op.get("position") for op in given["operations"]] == [op.get("position") for op in operations]


def test_a_pattern_moves_its_seed_to_the_roomiest_place_or_to_origin_and_says_what_stays_close():
    tight = boxed_in((5, 3, 15, 7))  # 10 m: the row of three needs 9.4 m, and fits only beside the boxes
    result = pattern(ROW, tight)
    assert result["seedMoved"]["to"] == {"x": 6.5, "z": 3.5} and result["seedMoved"]["why"].endswith(
        "this is the place inside Bay (zn-bay) with the most room: 0.65 m clear of Box west (pl-box-west)")
    assert result["closestToWhatStays"] == {"meters": 0.65, "item": "Box west (pl-box-west)"}
    moved = pattern({**ROW, "direction": "east", "origin": {"x": 30, "z": 5}}, boxed_in((0, 3, 40, 7)))
    assert moved["seedMoved"] == {"items": ["Bench 1 (pl-bench-1)", "Vise 1 (pl-vise-1)"], "by": {"x": 20.0, "z": 0.0},
                                  "meters": 20.0, "to": {"x": 30.0, "z": 5.0}, "why": "origin"}
    assert moved["closestToWhatStays"] == {"meters": 0.75, "item": "Box 1 (pl-box-1)"}  # at (40, 5)
    assert moved["operations"][0]["position"] == {"x": 30.0, "y": 0.0, "z": 5.0}
    walled = bay(with_box(deepcopy(fixture()[0]), "pl-mill-9", "Mill 9", 13, 5, source="pl-mill-1"), "zn-bay", "Bay",
                 5, 3, 15, 7)  # the mill takes 3.7 m of the bay's 4 m, where every row of three would stand
    with pytest.raises(PatternError) as refused:
        pattern(ROW, walled)
    assert str(refused.value) == (
        "Neither along nor across the length of Bench 1 (pl-bench-1) does the row fit (east: Mill 9 (pl-mill-9) "
        "stands in the way of copy 1; west: copy 2 would be outside Bay (zn-bay); south and north: it needs 6.40 x "
        "1.80 m, more than Bay (zn-bay) has that way (4.00 x 10.00 m)), even moving Bench 1 (pl-bench-1) up to 4.3 "
        "m inside Bay (zn-bay). Give fewer copies, a smaller gap, origin or removeIds.")


def test_a_ring_or_a_circle_that_does_not_fit_moves_with_its_seed():
    hall = bay(deepcopy(fixture()[0]), "zn-hall", "Hall", 0, 0, 40, 14)
    ring = {"kind": "perimeter", "seedIds": ["pl-bench-1", "pl-vise-1"], "widthCount": 3, "depthCount": 2, "gap": 1}
    result = pattern(ring, with_box(deepcopy(hall), "pl-box-r", "Box r", 12.8, 5))  # where copy 1 goes
    assert result["seedMoved"]["by"] == {"x": 0.0, "z": -2.0} and result["seedMoved"]["why"] == (
        "from where Bench 1 (pl-bench-1) stands the ring does not fit (Box r (pl-box-r) stands in the way of copy "
        "1); this is the nearest place inside Hall (zn-hall) that keeps it 1.00 m clear of what stays")
    circle = {"kind": "circular", "seedIds": ["pl-bench-1", "pl-vise-1"], "count": 4, "center": {"x": 10, "z": 8}}
    free = pattern(circle, hall)
    result = pattern(circle, with_box(deepcopy(hall), "pl-box-c", "Box c", 13, 8))  # clockwise from the south: copy 3
    by = result["seedMoved"]["by"]
    assert "the circle does not fit (Box c (pl-box-c) stands in the way of copy 3)" in result["seedMoved"]["why"]
    assert [instance["center"] for instance in result["instances"]] == [  # the centre given moves with it
        {"x": round(instance["center"]["x"] + by["x"], 3), "z": round(instance["center"]["z"] + by["z"], 3)}
        for instance in free["instances"]]


def test_a_pattern_stays_in_the_smallest_zone_round_its_seed_that_it_fits():
    # Station bench at (21.2, 1.5) in Workstation 1 (x 20 to 24): a row of three is wider than the station.
    row = {"seedIds": ["pl-ws-bench"], "count": 3, "direction": "west", "gap": 1}
    result = pattern(row)
    assert "seedMoved" not in result  # no zone it fits: only what stays is in its way
    assert [round(op["position"]["x"], 9) for op in result["operations"]] == [19.4, 17.6]
    hall = bay(with_box(deepcopy(fixture()[0]), "pl-box-w", "Box w", 19.4, 1.5), "zn-hall", "Hall", 0, -10, 60, 40)
    assert "inside Hall (zn-hall)" in pattern(row, hall)["seedMoved"]["why"]


# ---------------------------------------------------------------- plan_facility_cell

def assert_operators_face_inside(result, *, at_center=False):
    """Every machine's operator side faces into the cell (square to its own side of the U, L or loop, so a corner
    machine's centre line passes beside the cell's centre), or right at the centre for a cluster."""
    center = result["cell"]["center"]
    for machine in result["machines"]:
        toward = (center["x"] - machine["position"]["x"], center["z"] - machine["position"]["z"])
        side = facing_vector(operator_heading(machine))
        cosine = (side[0] * toward[0] + side[1] * toward[1]) / math.hypot(*toward)
        limit = 1 - 1e-6 if at_center else 0.3  # the summary gives 3 decimals
        assert cosine > limit, (machine["label"], machine["yawDegrees"], toward)
        if not at_center:
            assert machine["yawDegrees"] % 90 == 0  # an unturned U, L or loop: square to the plan


def test_a_u_of_new_machines_faces_its_operators_inside():
    result = cell({"strategy": "u", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}})
    machines, operations = result["machines"], result["operations"]
    assert [machine["frontFaces"] for machine in machines] == ["east", "south", "south", "south", "west"]
    assert result["cell"]["opensTo"] == "south" and result["unverifiedFacing"] == []
    assert_operators_face_inside(result)
    assert result["closestGap"]["meters"] >= 1 and "note" not in result  # the 1 m gap holds
    # Seven mills are placed already (locked and stale ones included): the new ones are numbered on.
    assert [machine["label"] for machine in machines] == [f"CNC Mill {number}" for number in range(8, 13)]
    assert [operation["op"] for operation in operations] == ["place_asset"] * 5
    for machine, operation in zip(machines, operations):
        placement = operation["placement"]
        assert placement["placementId"] == machine["placementId"] and placement["placementId"].startswith("pl-cell-")
        assert placement["assetDefinitionRevision"] == "rev-mill"  # the exact library revision
        assert placement["transform"]["quaternion"] == yaw_quaternion(machine["yawDegrees"])
        assert placement["metadata"]["inputMethod"] == "sage-cell-layout"
        assert placement["metadata"]["instanceLabel"] == machine["label"]
        provenance = placement["metadata"]["layoutProvenance"]
        assert provenance["command"] == "cell_layout" and provenance["authoredStrategy"] == "u"
        assert provenance["seedEntityIds"] == sorted(item["placementId"] for item in machines)
        assert provenance["parameters"]["facing"] == "operator-inside"
        assert "layoutProvenanceSeedEntityIds" not in operation  # new ids are not seeds the layout has yet


def test_a_u_opens_where_asked_and_an_l_runs_up_west_and_along_north():
    turned = cell({"strategy": "u", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}, "openSide": "north"})
    assert turned["cell"]["opensTo"] == "north"
    assert [machine["frontFaces"] for machine in turned["machines"]] == ["west", "north", "north", "north", "east"]
    assert_operators_face_inside(turned)
    shaped = cell({"strategy": "l", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}})
    west = min(machine["position"]["x"] for machine in shaped["machines"])
    north = max(machine["position"]["z"] for machine in shaped["machines"])
    for machine in shaped["machines"]:
        on_west = abs(machine["position"]["x"] - west) < 1e-6
        assert on_west or abs(machine["position"]["z"] - north) < 1e-6
        assert machine["frontFaces"] == ("east" if on_west else "south")
    assert_operators_face_inside(shaped)
    assert_operators_face_inside(cell({"strategy": "loop", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}}))
    assert_operators_face_inside(cell({"strategy": "cluster", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}}),
                                 at_center=True)


def test_placed_machines_are_moved_and_turned_in_rows_toward_the_operator_side():
    result = cell({"strategy": "line", "placementIds": MILLS})
    operations = result["operations"]
    assert [operation["op"] for operation in operations] == ["move_placement", "rotate_placement"] * 5
    assert operations[0]["layoutProvenanceSeedEntityIds"] == MILLS
    assert all(operation["layoutProvenance"]["command"] == "cell_layout" for operation in operations)
    assert [machine["frontFaces"] for machine in result["machines"]] == ["south"] * 5  # right of the flow
    for machine, turn in zip(result["machines"], operations[1::2]):
        assert turn["placementId"] == machine["placementId"] and turn["quaternion"]["w"] >= 0
        assert turn["quaternion"] == yaw_quaternion(machine["yawDegrees"])
    north = cell({"strategy": "line", "placementIds": MILLS, "operatorSide": "north"})
    assert [machine["frontFaces"] for machine in north["machines"]] == ["north"] * 5
    kept = cell({"strategy": "line", "placementIds": MILLS, "facing": "preserve", "width": 30, "depth": 12})
    assert [machine["yawDegrees"] for machine in kept["machines"]] == [0, 90, 270, 200, 30]


def test_a_model_without_a_reviewed_operator_side_is_said_to_be_unverified():
    result = cell({"strategy": "line", "placementIds": ["pl-box-1", "pl-lathe-1", "pl-mill-1"]})
    reviewed = {machine["placementId"]: machine["frontReviewed"] for machine in result["machines"]}
    assert reviewed == {"pl-box-1": False, "pl-lathe-1": True, "pl-mill-1": True}
    assert result["unverifiedFacing"] == ["Box 1 (pl-box-1)"]
    lathe = next(machine for machine in result["machines"] if machine["placementId"] == "pl-lathe-1")
    assert lathe["frontFaces"] == "south"  # no operator side: its front faces the operator side of the row
    assert [machine.get("operatorFaces") for machine in result["machines"]] == [None, "south", "south"]
    assert result["operatorSides"] == ("Both operator sides face south. Box 1 (pl-box-1) has no reviewed operator "
                                       "side: facing unverified.")


def test_face_center_and_face_outward_turn_each_operator_side_and_the_summary_says_which_way():
    # The user's circle of 4 mills (2026-11-01): a loop with face-center turned each mill's +z, its back, to the
    # centre, and Sage said they faced it. Now the reviewed operator side faces it, for any strategy.
    arguments = {"strategy": "loop", "assets": [{"assetId": "asset-mill", "count": 4}], "center": {"x": 60, "z": 60}}
    inward = cell({**arguments, "facing": "face-center"})
    assert_operators_face_inside(inward, at_center=True)
    assert [machine["operatorFaces"] for machine in inward["machines"]][1::2] == [
        "south-east (the centre)", "north-west (the centre)"]
    assert inward["operatorSides"] == "All 4 operator sides face the centre."
    outward = cell({**arguments, "facing": "face-outward"})
    for machine in outward["machines"]:
        away = (machine["position"]["x"] - 60, machine["position"]["z"] - 60)
        side = facing_vector(operator_heading(machine))
        assert (side[0] * away[0] + side[1] * away[1]) / math.hypot(*away) > 1 - 1e-6
    assert outward["operatorSides"] == "All 4 operator sides face away from the centre."
    assert cell(arguments)["operatorSides"] == "All 4 operator sides face into the cell."  # operator-inside: square
    # A lathe's reviewed side is its front (north); a box has none: its north side, as the ribbon does, unverified.
    mixed = cell({"strategy": "cluster", "placementIds": ["pl-box-1", "pl-lathe-1", "pl-mill-1"],
                  "center": {"x": 60, "z": 60}, "facing": "face-center"})
    centre = mixed["cell"]["center"]
    for machine in mixed["machines"]:
        at = machine["position"]
        toward = math.degrees(math.atan2(centre["x"] - at["x"], centre["z"] - at["z"]))
        side = {"pl-box-1": 0, "pl-lathe-1": COMPASS_HEADINGS["north"], "pl-mill-1": COMPASS_HEADINGS["south"]}
        assert turn_apart(machine["yawDegrees"] + side[machine["placementId"]], toward) < 0.05, machine  # 1 mm
    assert mixed["unverifiedFacing"] == ["Box 1 (pl-box-1)"]
    assert mixed["operatorSides"] == ("Both operator sides face the centre. Box 1 (pl-box-1) has no reviewed "
                                      "operator side: facing unverified.")


def test_a_cell_in_a_zone_is_centred_in_it_and_must_fit():
    layout, catalog = fixture()
    layout = deepcopy(layout)
    layout["zones"].append({"zoneId": "zn-big", "label": "Cell A06", "zoneType": "workcell", "floorElevation": 0.25,
                            "boundary": [{"x": 0, "z": 40}, {"x": 30, "z": 40}, {"x": 30, "z": 60}, {"x": 0, "z": 60}]})
    result = cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-big"}, layout)
    assert result["cell"]["center"] == {"x": 15.0, "z": 50.0} and result["cell"]["zone"] == "Cell A06 (zn-big)"
    record = next(item for item in catalog if item["assetId"] == "asset-mill")
    for operation in result["operations"]:
        placement = operation["placement"]
        assert placement["transform"]["position"]["y"] == 0.25  # on the zone's floor
        item = normalized_item("placement", placement, [record], True)
        assert all(0 <= point["x"] <= 30 and 40 <= point["z"] <= 60 for point in item_points(item))
    with pytest.raises(PatternError, match="does not fit inside Cell A06"):
        cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-big", "width": 40, "depth": 12}, layout)
    with pytest.raises(PatternError, match="Workstation 1 .zn-ws-1. leaves about 4.0 x 3.0 m"):
        cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-ws-1"})


def with_column(y=0.0, *, x=12.0, z=51.3, zone=(0, 40, 24, 58)):
    """The fixture with a 24 x 18 m cell zone and a locked box (a column) where the U's middle machine would go."""
    layout, _ = fixture()
    layout = deepcopy(layout)
    x0, z0, x1, z1 = zone
    layout["zones"].append({"zoneId": "zn-col", "label": "Cell C", "zoneType": "workcell", "floorElevation": 0,
                            "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1},
                                         {"x": x0, "z": z1}]})
    layout["placements"].append({
        "placementId": "pl-column", "assetId": "asset-box", "assetDefinitionRevision": "rev-box",
        "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                      "scale": 1},
        "positionMode": "locked", "snapRelationship": None, "metadata": {"instanceLabel": "Column C-1"}})
    return layout


def clearance_to_column(result, layout):
    _, catalog = fixture()
    column = normalized_item("placement", layout["placements"][-1], catalog, True)
    record = [item for item in catalog if item["assetId"] == "asset-mill"]
    return min(sp._polygon_gap(item_points(normalized_item("placement", operation["placement"], record, True)),
                               item_points(column)) for operation in result["operations"])


def test_a_cell_in_a_zone_keeps_clear_of_what_stays_there():
    layout = with_column()
    sized = {"strategy": "u", "assets": NEW_MILLS, "center": {"x": 12, "z": 49}, "width": 15.51, "depth": 10.34}
    centred = cell(sized, layout)
    assert clearance_to_column(centred, layout) == 0  # the ribbon's U of that size, centred there, is on the column
    assert "Column C-1 (pl-column) stands in the way of" in centred["note"]
    grown = cell({key: value for key, value in sized.items() if key not in ("width", "depth")}, layout)
    assert clearance_to_column(grown, layout) >= 1 and "note" not in grown  # a default size grows past it
    result = cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-col"}, layout)
    assert "note" not in result and result["keptClearOf"] == ["Column C-1 (pl-column)"]
    assert result["shiftedFromZoneCenter"] != {"x": 0, "z": 0}
    assert clearance_to_column(result, layout) >= 1
    assert [machine["frontFaces"] for machine in result["machines"]] == ["east", "south", "south", "south", "west"]
    # A light hung overhead is not in a machine's way: nothing moves.
    overhead = with_column(6.0)
    assert "shiftedFromZoneCenter" not in cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-col"}, overhead)
    # No room to move: the summary says what is in the way.
    tight = with_column(zone=(4.245, 43.83, 19.755, 54.17))
    stuck = cell({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-col", "width": 15.51, "depth": 10.34}, tight)
    assert "Column C-1 (pl-column) stands in the way of CNC Mill" in stuck["note"]


def walked(*walks, handoffs=()):
    """The pattern fixture with saved walks: (programId, walker, [(anchorId, owner), ...]) each."""
    layout, _ = fixture()
    layout = deepcopy(layout)
    anchors = {}
    programs = []
    for program_id, walker, stops in walks:
        for anchor_id, owner in stops:
            anchors[anchor_id] = {"navigationAnchorId": anchor_id, "anchorKind": "station_operate",
                                  "ownerRef": {"ownerKind": "placement", "ownerId": owner}}
        programs.append({"movementProgramId": program_id, "actorPlacementId": walker,
                         "orderedStops": [{"stopId": f"nst-{program_id}-{n}", "navigationAnchorId": anchor_id}
                                          for n, (anchor_id, _) in enumerate(stops)],
                         "requiredAnchorIds": sorted({anchor_id for anchor_id, _ in stops})})
    layout["extensions"] = {"facilityNavigation": {
        "schemaVersion": 1, "anchors": list(anchors.values()), "movementPrograms": programs,
        "manualPathConstraints": [], "handoffPrograms": [
            {"handoffProgramId": handoff_id, "sourceMovementProgramId": source, "targetMovementProgramId": target}
            for handoff_id, source, target in handoffs]}}
    return layout


def walk_removal(result):
    return next((operation for operation in result["operations"] if operation["op"] == "delete_stranded_movements"),
                None)


def test_a_saved_walk_at_a_removed_item_goes_in_the_same_change_and_is_named():
    # The user (2026-11-01): "let sage remove the walk in the same change". Before, Sage refused.
    layout = walked(("nmp-1", "pl-box-1", [("na-bench", "pl-bench-1")]))
    result = cell({"strategy": "u", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}, "removeIds": ["pl-bench-1"]},
                  layout)
    assert result["removed"] == ["Bench 1 (pl-bench-1)", "Vise 1 (pl-vise-1)"]  # the vise goes with its bench
    assert result["alsoRemoves"] == "Also removes the Box 1's saved walk (1 stop)."
    assert [operation["op"] for operation in result["operations"][:3]] == [
        "delete_placement", "delete_placement", "delete_stranded_movements"]  # after the deletions it follows
    assert walk_removal(result) == {"op": "delete_stranded_movements", "movementProgramIds": ["nmp-1"],
                                    "navigationAnchorIds": ["na-bench"]}
    # The walker removed: its walk goes, with the stop only it used.
    walker = pattern({"seedIds": ["pl-mill-1"], "count": 2, "direction": "north", "spacing": 5,
                      "removeIds": ["pl-box-1"]}, layout)
    assert walker["alsoRemoves"] == "Also removes the Box 1's saved walk (1 stop)."
    assert walk_removal(walker)["navigationAnchorIds"] == ["na-bench"]
    # Nothing a walk stops at: no walk goes, and the summary says nothing about walks.
    lathe = pattern({"seedIds": ["pl-mill-1"], "count": 2, "direction": "north", "spacing": 5,
                     "removeIds": ["pl-lathe-1"]}, layout)
    assert lathe["removed"] == ["Lathe 1 (pl-lathe-1)"] and "alsoRemoves" not in lathe and not walk_removal(lathe)


def test_only_the_walks_that_stop_at_removed_items_go_and_a_shared_stop_stays_when_it_can():
    layout = walked(("nmp-a", "pl-box-1", [("na-home", "pl-box-1"), ("na-lathe", "pl-lathe-1"),
                                           ("na-mill", "pl-mill-1")]),
                    ("nmp-b", "pl-mill-2", [("na-mill", "pl-mill-1")]),
                    ("nmp-c", "pl-mill-3", [("na-mill-3", "pl-mill-3")]))
    arguments = {"strategy": "u", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}}
    # The lathe is A's alone: A goes with its own stops; the mill stop stays, as B uses it; B and C stay as they are.
    lathe = cell({**arguments, "removeIds": ["pl-lathe-1"]}, layout)
    assert lathe["alsoRemoves"] == "Also removes the Box 1's saved walk (3 stops)."
    assert walk_removal(lathe) == {"op": "delete_stranded_movements", "movementProgramIds": ["nmp-a"],
                                   "navigationAnchorIds": ["na-home", "na-lathe"]}
    # The shared stop's own item goes: both walks that stop there go, both named; C stays.
    mill = cell({**arguments, "removeIds": ["pl-mill-1"]}, layout)
    assert mill["alsoRemoves"] == ("Also removes the Box 1's saved walk (3 stops) and the Mill 2's saved walk "
                                   "(1 stop).")
    assert walk_removal(mill) == {"op": "delete_stranded_movements", "movementProgramIds": ["nmp-a", "nmp-b"],
                                  "navigationAnchorIds": ["na-home", "na-lathe", "na-mill"]}
    # A walk that hands work to a walk that stays: Sage cannot change the other walk, so it says so and stops.
    handed = walked(("nmp-a", "pl-box-1", [("na-lathe", "pl-lathe-1")]), ("nmp-b", "pl-mill-2", [("na-mill",
                                                                                                    "pl-mill-1")]),
                    handoffs=[("nhp-1", "nmp-a", "nmp-b")])
    with pytest.raises(PatternError) as refused:
        cell({**arguments, "removeIds": ["pl-lathe-1"]}, handed)
    assert str(refused.value) == (
        "Removing those items would also remove the Box 1's saved walk (1 stop), which hands work to the Mill 2's "
        "saved walk (1 stop). Sage cannot change the Mill 2's saved walk (1 stop): leave the items the Box 1's saved "
        "walk (1 stop) stops at out of removeIds, or ask the user.")


def test_new_machines_are_numbered_on_from_the_machines_that_stay():
    result = cell({"strategy": "u", "assets": NEW_MILLS, "center": {"x": 60, "z": 60}, "removeIds": MILLS[:3]})
    assert [machine["label"] for machine in result["machines"]] == [f"CNC Mill {number}" for number in range(5, 10)]
    assert [operation["op"] for operation in result["operations"]] == ["delete_placement"] * 3 + ["place_asset"] * 5


def cleared_cell():
    """The fixture with Cell C (x 0 to 24, z 40 to 58) furnished as Assembly Cell A05 is on Factory 02: a building
    column with a sign on it, a locked box, a box, a bench with a vise on it, a kit cart bay painted on the floor and
    a locked line; outside it, a mill and a marking that stay."""
    layout, catalog = fixture()
    layout, catalog = deepcopy(layout), deepcopy(catalog)
    box = next(record for record in catalog if record["assetId"] == "asset-box")
    catalog.append({**deepcopy(box), "assetId": "asset-column", "displayName": "Steel column",
                    "category": "Building Structures"})
    layout["zones"].append({"zoneId": "zn-c", "label": "Cell C", "zoneType": "workcell", "floorElevation": 0,
                            "boundary": [{"x": 0, "z": 40}, {"x": 24, "z": 40}, {"x": 24, "z": 58},
                                         {"x": 0, "z": 58}]})

    def place(placement_id, asset_id, x, z, label, mode="manual", on=None, y=0.0):
        record = next(item for item in catalog if item["assetId"] == asset_id)
        layout["placements"].append({
            "placementId": placement_id, "assetId": asset_id,
            "assetDefinitionRevision": record["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1},
            "positionMode": mode, "metadata": {"instanceLabel": label},
            "snapRelationship": {"family": "surface_attachment", "supportPlacementId": on} if on else None})

    def mark(marking_id, label, x, z, mode="manual"):
        layout["floorMarkings"].append({"markingId": marking_id, "type": "parking_box", "label": label, "width": 3,
                                        "depth": 3, "transform": {"position": {"x": x, "y": 0, "z": z},
                                                                  "rotationDegrees": 0}, "positionMode": mode})

    place("pl-c-column", "asset-column", 12, 51.3, "Column C-1")
    place("pl-c-locked", "asset-box", 2, 56, "Locked box C", mode="locked")
    place("pl-c-box", "asset-box", 20, 43, "Box C")
    place("pl-c-bench", "asset-bench", 5, 44, "Bench C")
    place("pl-c-vise", "asset-vise", 5.3, 44.1, "Vise C", on="pl-c-bench", y=1.0)
    place("pl-c-sign", "asset-box", 12.2, 51.3, "Sign C", on="pl-c-column", y=2.0)
    place("pl-c-outside", "asset-mill", 30, 50, "Mill outside")
    mark("fm-c-bay", "Kit cart bay", 14, 46)
    mark("fm-c-line", "Locked line", 22, 56, mode="locked")
    mark("fm-c-outside", "Outside bay", 30, 44)
    return layout, catalog


def test_a_cleared_zone_loses_what_stands_in_it_floor_markings_included_and_says_what_goes_and_stays():
    # The user (2026-11-02): clearZone "removes everything in the zone except building columns, floor markings
    # included", and names what it removes. Before, Sage named placements in removeIds: the A05 U kept its KIT CART bay.
    layout, catalog = cleared_cell()
    result = sp.plan_cell(layout, catalog, {"zoneId": "zn-c", "clearZone": True}, revision=REVISION)
    assert result["operations"] == [
        {"op": "delete_placement", "placementId": "pl-c-box"}, {"op": "delete_placement", "placementId": "pl-c-bench"},
        {"op": "delete_placement", "placementId": "pl-c-vise"}, {"op": "delete_floor_marking", "markingId": "fm-c-bay"}]
    assert result["cleared"] == (
        "Clears Cell C: removes Box C, Bench C, Vise C and Kit cart bay (floor marking). Keeps Column C-1 (building "
        "structure), Locked box C (locked), Sign C (on Column C-1, which stays) and Locked line (floor marking, "
        "locked).")
    assert result["removed"] == ["Box C (pl-c-box)", "Bench C (pl-c-bench)", "Vise C (pl-c-vise)",
                                 "Kit cart bay (fm-c-bay)"]
    assert "machines" not in result and "alsoRemoves" not in result
    # And laid out again in the same change: the clear first, then the cell, which keeps clear of what stays.
    built = sp.plan_cell(layout, catalog, {"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-c", "clearZone": True},
                         revision=REVISION)
    assert [operation["op"] for operation in built["operations"]] == [
        "delete_placement"] * 3 + ["delete_floor_marking"] + ["place_asset"] * 5
    assert built["cleared"] == result["cleared"] and len(built["machines"]) == 5
    # The machines a cell arranges stay, and are not named; removeIds still goes (here, from outside the zone).
    inside = deepcopy(layout)
    mill = deepcopy(next(item for item in inside["placements"] if item["placementId"] == "pl-c-outside"))
    inside["placements"].append({**mill, "placementId": "pl-c-mill", "metadata": {"instanceLabel": "Mill C"},
                                 "transform": {**mill["transform"], "position": {"x": 18, "y": 0, "z": 52}}})
    arranged = sp.plan_cell(inside, catalog, {"strategy": "line", "placementIds": ["pl-c-mill", "pl-mill-1"],
                                              "zoneId": "zn-c", "clearZone": True, "removeIds": ["pl-lathe-1"]},
                            revision=REVISION)
    gone = [operation.get("placementId") or operation.get("markingId") for operation in arranged["operations"]
            if operation["op"].startswith("delete_")]
    assert gone == ["pl-lathe-1", "pl-c-box", "pl-c-bench", "pl-c-vise", "fm-c-bay"]
    assert arranged["cleared"].startswith("Clears Cell C: removes Lathe 1, Box C, Bench C, Vise C and Kit cart bay")
    assert "Mill C" not in arranged["cleared"]
    # A saved walk that stops at an item the zone loses goes with it, named.
    layout["extensions"] = walked(("nmp-c", "pl-box-1", [("na-c-box", "pl-c-box")]))["extensions"]
    walk = sp.plan_cell(layout, catalog, {"zoneId": "zn-c", "clearZone": True}, revision=REVISION)
    assert walk["alsoRemoves"] == "Also removes the Box 1's saved walk (1 stop)."
    assert walk["operations"][-1] == {"op": "delete_stranded_movements", "movementProgramIds": ["nmp-c"],
                                      "navigationAnchorIds": ["na-c-box"]}


def test_a_cleared_zone_is_asked_for_in_one_call_and_says_why_when_it_cannot_be():
    specs = {spec["name"]: spec for spec in gateway_tool_specs()}
    schema = Draft202012Validator(specs[sp.CELL_TOOL]["input_schema"])
    schema.validate({"zoneId": "zn-c", "clearZone": True})  # only clearing: no strategy, no machines
    schema.validate({"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-c", "clearZone": True})
    assert not schema.is_valid({"zoneId": "zn-c", "clearZone": "yes"})
    assert "clearZone true with its zoneId" in pilot.EDIT_INSTRUCTIONS
    assert "Never look up a zone's items or review its workstations before plan_facility_cell" in (
        pilot.EDIT_INSTRUCTIONS)
    layout, catalog = cleared_cell()
    layout["zones"].append({"zoneId": "zn-a06", "label": "Assembly Cell A06", "boundary": []})
    names = progress.LayoutNames(layout, catalog)
    assert progress.describe(sp.CELL_TOOL, {"zoneId": "zn-a06", "clearZone": True}, names)["running"] == (
        "Planning the clearing of Assembly Cell A06")
    assert progress.describe(sp.CELL_TOOL, {"strategy": "u", "assets": NEW_MILLS, "zoneId": "zn-a06",
                                            "clearZone": True}, names)["done"] == (
        "Planned a U-shaped cell of 5 machines in Assembly Cell A06, cleared first")
    for arguments, words in (
            ({"clearZone": True}, "clearZone needs zoneId"),
            ({"strategy": "u", "zoneId": "zn-c", "clearZone": True}, "To only clear the zone, leave strategy out"),
            ({"zoneId": "zn-c"}, "or assets .new machines., one of them.$"),
            ({"placementIds": MILLS, "assets": NEW_MILLS, "zoneId": "zn-c", "clearZone": True},
             "or neither, to only clear the zone"),
            ({"assets": NEW_MILLS, "zoneId": "zn-c"}, "Give the cell's strategy"),
            ({"zoneId": "zn-none", "clearZone": True}, "There is no zone zn-none")):
        with pytest.raises(PatternError, match=words):
            sp.plan_cell(layout, catalog, arguments, revision=REVISION)
    with pytest.raises(PatternError) as refused:
        cell({"zoneId": "zn-col", "clearZone": True}, with_column())
    assert str(refused.value) == "There is nothing to clear in Cell C: Column C-1 (locked) stays."


@pytest.mark.parametrize("arguments, words", [
    ({"placementIds": MILLS, "assets": NEW_MILLS}, "one of them"),
    ({}, "one of them"),
    ({"assets": NEW_MILLS}, "need a place for the cell"),
    ({"assets": NEW_MILLS, "zoneId": "zn-ws-1", "center": {"x": 0, "z": 0}}, "zoneId or center"),
    ({"assets": NEW_MILLS, "zoneId": "zn-none"}, "There is no zone zn-none"),
    ({"placementIds": MILLS, "strategy": "l", "openSide": "east"}, "openSide is for a U"),
    ({"placementIds": MILLS, "openSide": "east", "turnDegrees": 90}, "openSide or turnDegrees"),
    ({"placementIds": MILLS, "rows": 6}, "more than the 5 machines"),
    ({"assets": [{"assetId": "asset-none", "count": 2}], "center": {"x": 0, "z": 0}}, "not in the library"),
    ({"placementIds": ["pl-mill-1", "pl-locked-1"]}, "is locked"),
    ({"placementIds": ["pl-bench-1", "pl-vise-1"]}, "attached to another item"),
    ({"placementIds": ["pl-mill-1", "zn-ws-1"]}, "a cell arranges placements"),
    ({"placementIds": MILLS, "width": 5, "depth": 5}, "needs more than"),
])
def test_a_cell_that_cannot_be_made_says_why(arguments, words):
    with pytest.raises(PatternError) as refused:
        cell({"strategy": "u", **arguments})
    assert words in str(refused.value)


# ---------------------------------------------------------------- the ribbon's own operations

def run_node(script, payload):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    flags = 0x08000000 if sys.platform == "win32" else 0  # no console window on the user's screen
    done = subprocess.run([node, str(script)], input=json.dumps(payload).encode("utf-8"), capture_output=True,
                          timeout=120, cwd=ROOT, creationflags=flags)
    output = json.loads(done.stdout)
    assert output["ok"], output
    return output["operations"]


def compiled(layout, catalog, namespace, command_id, arguments):
    return run_node(COMPILER, {"layout": layout, "catalog": catalog, "operationIdNamespace": namespace, "command": {
        "commandId": command_id, "arguments": arguments, "requestId": "parity-request",
        "expectedDraftRevision": "0" * 64}})


def same(ribbon, sage, path=""):
    if isinstance(ribbon, dict) and isinstance(sage, dict):
        if set(ribbon) == set(sage) == {"x", "y", "z", "w"}:
            assert same_quaternion(ribbon, sage), path
            return
        assert set(ribbon) == set(sage), f"{path}: ribbon {sorted(ribbon)} sage {sorted(sage)}"
        for key in ribbon:
            same(ribbon[key], sage[key], f"{path}.{key}")
    elif isinstance(ribbon, list) and isinstance(sage, list):
        assert len(ribbon) == len(sage), path
        for index, (left, right) in enumerate(zip(ribbon, sage)):
            same(left, right, f"{path}[{index}]")
    elif isinstance(ribbon, (int, float)) and not isinstance(ribbon, bool) and isinstance(sage, (int, float)):
        assert abs(ribbon - sage) <= 1e-9, f"{path}: ribbon {ribbon} sage {sage}"
    else:
        assert ribbon == sage, f"{path}: ribbon {ribbon!r} sage {sage!r}"


@pytest.mark.parametrize("seed, direction", [(["pl-bench-1", "pl-vise-1"], "east"), (["pl-lathe-1", "mk-1"], "north"),
                                             (["zn-ws-1"], "west"), (MILLS, "north")])
def test_a_row_sends_what_the_ribbon_sends(seed, direction):
    layout, catalog = fixture()
    arguments = {"seedIds": seed, "count": 4, "direction": direction, "spacing": 7.5}
    namespace = sp._namespace(sp.PATTERN_TOOL, arguments, REVISION)
    ribbon = compiled(layout, catalog, namespace, "linear-pattern", {**arguments, "sourceUnit": "m"})
    same(ribbon, pattern(arguments)["operations"])


@pytest.mark.parametrize("strategy, facing, turn", [
    ("u", "face-center", 30), ("l", "preserve", 0), ("serpentine", "follow-path", -45),
    ("cluster", "face-outward", 90)])
def test_a_cell_of_placed_machines_sends_what_the_ribbon_sends(strategy, facing, turn):
    layout, catalog = fixture()
    arguments = {"strategy": strategy, "placementIds": [*MILLS, "pl-lathe-1"], "width": 24, "depth": 16, "gap": 1.5,
                 "rows": 2, "facing": facing, "turnDegrees": turn}
    namespace = sp._namespace(sp.CELL_TOOL, arguments, REVISION)
    ribbon = compiled(layout, catalog, namespace, "cell-layout", {
        "selectionIds": arguments["placementIds"], "strategyId": strategy, "targetBounds": {"width": 24, "depth": 16},
        "sourceUnit": "m", "gap": 1.5, "rows": 2, "orientation": facing, "angleDegrees": turn, "invertU": False})
    same(ribbon, cell(arguments)["operations"])


# ---------------------------------------------------------------- R2: mirror, circle and ring

SESSION = ROOT / "tests/pattern_session_runner.js"
WITH_ZONES = {"expandZones": True, "includeZones": True, "strictGeometry": True}
CONTENTS_ONLY = {"expandZones": True, "includeZones": False, "strictGeometry": True}  # a ring copies a zone's contents
MILL_OPERATOR = COMPASS_HEADINGS["south"]  # the fixture's mill: operator side south in its own axes


def ribbon_session(builder, seed, options, namespace, collect=WITH_ZONES, layout=None):
    """What the ribbon's Mirror, Circular or Perimeter button sends: the workspace's builder, then the session's
    applyPattern (tests/pattern_session_runner.js)."""
    saved, catalog = fixture()
    return run_node(SESSION, {"layout": layout or saved, "catalog": catalog, "operationIdNamespace": namespace,
                              "ids": seed, "collect": collect, "builder": builder, "options": options})


def yaw_of(quaternion):
    """The turn of a yaw-only quaternion as a compass heading (a positive turn goes clockwise on the plan)."""
    return math.degrees(2 * math.atan2(quaternion["y"], quaternion["w"])) % 360


def turn_apart(first, second):
    return abs((first - second + 180) % 360 - 180)


def canonical(quaternion):
    """The sign the layout keeps: the first nonzero of w, x, y, z is positive."""
    return next(quaternion[key] for key in "wxyz" if quaternion[key] != 0) > 0


@pytest.mark.parametrize("seed, line, faces", [
    ("pl-mill-1", {"lineX": 10}, "south"), ("pl-mill-1", {"lineZ": 25}, "north"),
    ("pl-mill-2", {"lineX": 10}, "east")])
def test_a_mirrored_machine_faces_the_mirror_image_of_its_front(seed, line, faces):
    """Mill 1 faces south and Mill 2 west. Across a north-south line a south front stays south and a west front
    faces east; across an east-west line a south front faces north."""
    result = pattern({"kind": "mirror", "seedIds": [seed], **line})
    [copy] = result["copies"]
    assert copy["frontFaces"] == faces and copy["frontReviewed"] is True and result["unverifiedFacing"] == []
    [operation] = result["operations"]
    assert turn_apart(yaw_of(operation["quaternion"]) + MILL_OPERATOR, COMPASS_HEADINGS[faces]) < 1e-9
    assert operation["layoutProvenance"]["command"] == "mirror"


def test_a_mirror_by_side_leaves_the_gap_asked_and_says_what_it_cannot_check():
    result = pattern({"kind": "mirror", "seedIds": ["pl-bench-1", "pl-vise-1"], "side": "west", "gap": 1})
    # Bench 1 is 1.8 m wide at x 10: its west edge is at 9.1, so the line is at 8.6 and the copy 1 m clear.
    assert result["line"] == {"runs": "north-south", "from": {"x": 8.6, "z": 0.0}, "to": {"x": 8.6, "z": 30.0}}
    assert result["copySide"] == "west" and result["closestGap"]["meters"] == 1.0
    assert result["unverifiedFacing"] == ["Bench 1 (pl-bench-1)", "Vise 1 (pl-vise-1)"]
    bench, vise = result["operations"]
    assert vise["snapRelationship"]["supportPlacementId"] == bench["newPlacementId"]
    # By default the line runs just east of the seed, on the Plan's grid, as the ribbon draws it: 1 m past its edge
    # (10.9), rounded up to 12.
    assert pattern({"kind": "mirror", "seedIds": ["pl-bench-1", "pl-vise-1"]})["line"]["from"] == {"x": 12.0, "z": 0.0}


@pytest.mark.parametrize("seed, line", [
    (["pl-mill-1", "mk-1"], {"lineX": 10}), (["pl-mill-2", "pl-lathe-1"], {"lineZ": 25}),
    (["zn-ws-1"], {"side": "west", "gap": 1.5}), (["pl-bench-1", "pl-vise-1"], {}),
    (["pl-mill-3", "pl-box-1"], {"linePoints": [{"x": 0, "z": 0}, {"x": 30, "z": 40}]})])
def test_a_mirror_sends_what_the_ribbon_sends(seed, line):
    """The same copies, ids, turns, zones and markings as the ribbon's Mirror. Since 2026-11-01 both keep each
    machine's operator side (else its front, else its north side) as the mirror image: the copy turns to
    2 x the line's heading - its yaw - 2 x that side's heading. The ribbon used to keep the copy's own east side
    (- 180 in place of - 2 x side), which pointed a north or south front 180 degrees from the mirror image."""
    layout, catalog = fixture()
    arguments = {"kind": "mirror", "seedIds": seed, **line}
    items = sp._pattern_seed(layout, catalog, seed)
    start, end, _ = sp._mirror_line(layout, items, arguments)
    namespace = sp._namespace(sp.PATTERN_TOOL, arguments, REVISION)
    sage = pattern(arguments)["operations"]
    same(ribbon_session("mirror", seed, {"axisStart": start, "axisEnd": end}, namespace), sage)
    line_heading = math.degrees(math.atan2(end["x"] - start["x"], end["z"] - start["z"]))
    by_id = {item["id"]: item for item in items}
    machines = [operation for operation in sage if operation["op"] == "duplicate_placement"]
    assert machines
    for operation in machines:
        item = by_id[operation["sourcePlacementId"]]
        side = MILL_OPERATOR if item["id"].startswith("pl-mill") else 0  # the lathe's front is north
        turn = normalize_degrees(2 * line_heading - item["rotationDegrees"] - 2 * side)
        assert same_quaternion(operation["quaternion"], yaw_quaternion(turn))


def test_the_builders_read_a_models_reviewed_sides_as_the_ribbon_does():
    sides = {"functionalSides": {"front": {"side": "north"}, "operator": {"side": "south"}}}
    assert facing_side_degrees({"facilitySemantics": sides}) == 180  # the operator side first
    assert facing_side_degrees({"source": {"facilitySemantics": sides}}) == 180  # the workspace's catalog
    assert facing_side_degrees({"facilitySemantics": {"functionalSides": {"front": {"side": "west"}}}}) == 270
    assert facing_side_degrees({"facilitySemantics": {"functionalSides": {"front": "east"}}}) == 90
    assert facing_side_degrees({"facilitySemantics": {"functionalSides": {"front": {"side": "up"}}}}) is None
    assert facing_side_degrees({}) is None and facing_side_degrees(None) is None


@pytest.mark.parametrize("seed, arguments, options", [
    (["pl-mill-1"], {"count": 4, "center": {"x": 2, "z": 12}, "turnWithPattern": True},
     {"count": 4, "sweepDegrees": 360, "rotateWithPattern": True, "centerX": 2, "centerZ": 12}),
    (["pl-bench-1", "pl-vise-1"], {"count": 5, "totalDegrees": 120},
     {"count": 5, "sweepDegrees": 120, "rotateWithPattern": False}),
    (["zn-ws-1"], {"count": 3, "center": {"x": 30, "z": 10}, "totalDegrees": 180, "turnWithPattern": True},
     {"count": 3, "sweepDegrees": 180, "rotateWithPattern": True, "centerX": 30, "centerZ": 10}),
    (["pl-mill-3", "mk-1"], {"count": 6, "turnWithPattern": True},  # Mill 3's saved quaternion has w below zero
     {"count": 6, "sweepDegrees": 360, "rotateWithPattern": True})])
def test_a_circle_sends_what_the_ribbon_sends(seed, arguments, options):
    arguments = {"kind": "circular", "seedIds": seed, **arguments}
    namespace = sp._namespace(sp.PATTERN_TOOL, arguments, REVISION)
    sage = pattern(arguments)["operations"]
    same(ribbon_session("circular", seed, options, namespace), sage)
    assert all(canonical(operation["quaternion"]) for operation in sage if "quaternion" in operation)


@pytest.mark.parametrize("seed, arguments, clear", [  # clear: what stands where the ring goes
    (["pl-mill-1"], {"widthCount": 3, "depthCount": 2, "gap": 1}, ("pl-bench-1", "pl-mill-3", "pl-mill-4")),
    (["pl-bench-1", "pl-vise-1"], {"widthCount": 4, "depthCount": 1}, ()),
    (["zn-ws-1"], {"shape": "square", "widthCount": 2, "turnDegrees": 30}, ()),
    (["pl-mill-3"], {"widthCount": 2, "depthCount": 3, "turnDegrees": 315}, ("pl-mill-1", "pl-mill-2", "pl-mill-4")),
    (["pl-lathe-1", "mk-1"], {}, ())])
def test_a_ring_sends_what_the_ribbon_sends(seed, arguments, clear):
    layout = without(*clear)
    arguments = {"kind": "perimeter", "seedIds": seed, **arguments}
    namespace = sp._namespace(sp.PATTERN_TOOL, arguments, REVISION)
    options = {"shape": arguments.get("shape", "rectangle"), "widthCount": arguments.get("widthCount", 6),
               "depthCount": arguments.get("depthCount", 4), "clearGap": arguments.get("gap", 0),
               "angleDegrees": arguments.get("turnDegrees", 0)}
    sage = pattern(arguments, layout)["operations"]
    same(ribbon_session("perimeter", seed, options, namespace, CONTENTS_ONLY, layout), sage)
    assert all(canonical(operation["quaternion"]) for operation in sage if "quaternion" in operation)


def test_a_circle_that_turns_keeps_each_copy_facing_the_centre():
    arguments = {"kind": "circular", "seedIds": ["pl-mill-1"], "count": 4, "center": {"x": 2, "z": 12}}
    result = pattern({**arguments, "turnWithPattern": True})  # Mill 1 stands at (2, 20) facing south: the centre
    assert result["seedOperatorSides"] == [{"item": "Mill 1 (pl-mill-1)", "faces": "the centre"}]
    assert [instance["center"] for instance in result["instances"]] == [
        {"x": 2.0, "z": 20.0}, {"x": 10.0, "z": 12.0}, {"x": 2.0, "z": 4.0}, {"x": -6.0, "z": 12.0}]  # clockwise
    for operation in result["operations"]:
        toward = math.degrees(math.atan2(2 - operation["position"]["x"], 12 - operation["position"]["z"]))
        assert turn_apart(yaw_of(operation["quaternion"]) + MILL_OPERATOR, toward) < 1e-9
    still = pattern(arguments)
    assert all("quaternion" not in operation for operation in still["operations"])  # they keep the seed's heading
    assert "keep the seed's heading" in still["facing"]


def test_a_ring_faces_it_as_the_seed_does_and_says_when_that_is_along_it():
    result = pattern({"kind": "perimeter", "seedIds": ["pl-lathe-1"], "widthCount": 3, "depthCount": 2, "gap": 1})
    # Lathe 1 at (30, 30) is turned 90: 1.8 m east-west, 4.2 m north-south, its front facing east. A ring runs along
    # the seed's long side, so it runs south from the lathe and lies to the east: the lathe faces into it.
    assert result["turnedForSeed"] and result["seedSideRuns"] == "south" and result["ringLiesTo"] == "east"
    assert result["copiesPerSide"] == {"seedSide": 3, "oppositeSide": 3, "eachEnd": 2} and result["newItems"] == 9
    assert result["seedOperatorSides"] == [{"item": "Lathe 1 (pl-lathe-1)", "faces": "into the ring"}]
    assert "note" not in result
    positions = [operation["position"] for operation in result["operations"]] + [{"x": 30.0, "z": 30.0}]
    centre = {key: sum(point[key] for point in positions) / len(positions) for key in ("x", "z")}
    for operation in result["operations"]:
        front = facing_vector(yaw_of(operation["quaternion"]) if "quaternion" in operation else 90)
        inward = (centre["x"] - operation["position"]["x"], centre["z"] - operation["position"]["z"])
        assert front[0] * inward[0] + front[1] * inward[1] > 0  # every copy faces into the ring
    along = pattern({"kind": "perimeter", "seedIds": ["pl-mill-1"], "widthCount": 3, "depthCount": 2, "gap": 1},
                    without("pl-bench-1", "pl-mill-3", "pl-mill-4"))  # what stands where the ring goes
    assert along["seedOperatorSides"] == [{"item": "Mill 1 (pl-mill-1)", "faces": "along the ring"}]
    assert along["note"].startswith("Mill 1 (pl-mill-1) faces along the ring, as the seed does")
    assert "plan_facility_cell with strategy loop" in along["note"]


def test_overlapping_copies_are_named_and_touching_ones_are_not():
    crossing = pattern({"kind": "mirror", "seedIds": ["pl-mill-1"], "lineX": 2})
    assert crossing["closestGap"]["meters"] == 0
    assert crossing["note"].startswith("The mirror image overlaps the original")
    touching = pattern({"kind": "mirror", "seedIds": ["pl-mill-1"], "side": "east", "gap": 0})
    assert touching["closestGap"]["meters"] == 0 and "note" not in touching
    alone = without(*MILLS[1:])  # the other mills stand where these copies go
    tight = pattern({"kind": "circular", "seedIds": ["pl-mill-1"], "count": 8, "center": {"x": 2, "z": 17}}, alone)
    assert tight["note"].startswith("Copies overlap: give a centre further from the seed")
    assert pattern({"seedIds": ["pl-mill-1"], "count": 3, "direction": "east", "spacing": 3}, alone)["closestGap"] == {
        "meters": 0.0, "between": ["Mill 1 (pl-mill-1), the original", "Mill 1 (pl-mill-1), copy 1"]}


@pytest.mark.parametrize("arguments, words", [
    ({"kind": "spiral"}, "kind is linear, mirror, circular or perimeter, not spiral"),
    ({"kind": "mirror", "count": 3}, "count is not used by a mirror pattern; leave it out"),
    ({"kind": "mirror", "origin": {"x": 1, "z": 1}}, "origin is not used by a mirror pattern; leave it out"),
    ({"count": 3, "direction": "east", "spacing": 5, "turnWithPattern": True},
     "turnWithPattern is not used by a linear pattern"),
    ({"kind": "circular", "count": 4, "direction": "east", "spacing": 5}, "direction, spacing are not used"),
    ({"kind": "mirror", "lineX": 4, "side": "east"}, "Give the mirror line one way"),
    ({"kind": "mirror", "lineZ": 4, "gap": 1}, "gap goes with side"),
    ({"kind": "mirror", "linePoints": [{"x": 1, "z": 1}, {"x": 1, "z": 1}]}, "linePoints are the same point"),
    ({"kind": "circular"}, "Give count for a circular pattern"),
    ({"count": None}, "Give count for a linear pattern"),
    ({"kind": "perimeter", "shape": "square", "widthCount": 3, "depthCount": 4}, "A square has widthCount on every"),
    ({"kind": "perimeter", "seedIds": MILLS[:3], "widthCount": 50, "depthCount": 50}, "more than 240 new items"),
    ({"kind": "mirror", "seedIds": ["pl-vise-1"]}, "include its support"),
    ({"kind": "circular", "count": 3, "removeIds": ["pl-mill-1"]}, "part of the plan"),
])
def test_a_mirror_circle_or_ring_that_cannot_be_made_says_why(arguments, words):
    request = {key: value for key, value in {"seedIds": ["pl-mill-1"], **arguments}.items() if value is not None}
    with pytest.raises(PatternError) as refused:
        pattern(request)
    assert words in str(refused.value)


# ---------------------------------------------------------------- staged, applied and read back

@pytest.fixture
def factory(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    catalog = {item["assetId"]: item for item in host.agent_runtime.asset_catalog_provider(principal, LOCAL_SITE_ID)}

    def zone(zone_id, label, x0, z0, x1, z1):
        return {"op": "add_zone", "zone": {"zoneId": zone_id, "label": label, "zoneType": "workcell",
                                           "floorElevation": 0.0, "anchors": [], "evidence": [], "boundary": [
                                               {"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1},
                                               {"x": x0, "z": z1}]}}

    def place(placement_id, asset_id, x, z, label):
        return {"op": "place_asset", "placement": {
            "placementId": placement_id, "assetId": asset_id,
            "assetDefinitionRevision": catalog[asset_id]["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": 0, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": label}}}

    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        zone("zn-benches", "Bench line", 1, 1, 30, 6), zone("zn-a06", "Assembly Cell A06", 14, 8, 38, 26),
        place("pl-bench-a", "asset-workbench", 4, 3, "Bench A"),
        place("pl-old-1", "asset-cnc-mill", 20, 14, "Old mill 1"),
        place("pl-old-2", "asset-cnc-mill", 30, 20, "Old mill 2")])
    try:
        yield host
    finally:
        host.close()


def run_in_apply_directly(host, tool, arguments, turn, applied=None):
    """One Sage turn in Apply Directly mode: plan, stage the package, and the app's direct apply after the turn.
    APPLIED, a list, gets the apply's result (its receipt undoes the change)."""
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(host.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=turn)
    gateway.edit_mode = "direct"
    planned = asyncio.run(gateway.call(tool, arguments))
    assert planned["ok"], planned
    assert host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved  # planning reads only
    staged = asyncio.run(gateway.call("preview_planned_design", {"packageId": planned["data"]["package"]["packageId"]}))
    assert staged["ok"], staged
    assert staged["data"]["approvalRequired"] is False, staged["data"]["directApplyPolicy"]
    introduced = staged["data"]["validation"]["introduced"]
    assert introduced["spatial"]["errorCount"] == 0 and introduced["spatial"]["placementCollisions"] == 0
    proposal_id = staged["data"]["proposalId"]
    binding = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)[
        "alternative"]["transactionBinding"]
    approval = host.service.approve_layout_proposal(
        principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding, session_id="pattern-session",
        idempotency_key=f"pattern-{turn}", explicit_approval=False, authorization_mode="direct", direct_consent=True)
    result = host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                                                binding, session_id="pattern-session",
                                                idempotency_key=f"pattern-{turn}")
    if applied is not None:
        applied.append(result)
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    reader = FacilityEditGateway(host.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=turn + "-read")
    return planned["data"], saved["layout"], reader


def test_a_row_and_a_cell_are_staged_applied_directly_and_read_back(factory):
    planned, layout, reader = run_in_apply_directly(
        factory, sp.PATTERN_TOOL, {"seedIds": ["pl-bench-a"], "count": 6, "direction": "east", "gap": 2}, "row-turn")
    assert planned["package"] == {"packageId": "pattern-1", "operations": 5}
    assert sum(placement["assetId"] == "asset-workbench" for placement in layout["placements"]) == 6
    read = asyncio.run(reader.call("inspect_pattern_provenance", {}))
    record = next(item for item in read["data"]["records"] if item["command"] == "linear_pattern")
    assert record["seedEntityIds"] == ["pl-bench-a"] and record["memberCount"] == 6
    assert record["currentClassification"]["status"] == "consistent"

    planned, layout, reader = run_in_apply_directly(factory, sp.CELL_TOOL, {
        "strategy": "u", "assets": [{"assetId": "asset-cnc-mill", "count": 5}], "zoneId": "zn-a06",
        "removeIds": ["pl-old-1", "pl-old-2"]}, "cell-turn")
    mills = [placement for placement in layout["placements"] if placement["assetId"] == "asset-cnc-mill"]
    assert sorted(placement["placementId"] for placement in mills) == [
        machine["placementId"] for machine in planned["machines"]]
    assert planned["removed"] == ["Old mill 1 (pl-old-1)", "Old mill 2 (pl-old-2)"]
    # The starter mill has no reviewed sides: the reply must say its facing is unverified.
    assert len(planned["unverifiedFacing"]) == 5 and not any(m["frontReviewed"] for m in planned["machines"])
    read = asyncio.run(reader.call("inspect_cell_layout_provenance", {}))
    record = next(item for item in read["data"]["records"] if item["command"] == "cell_layout")
    assert record["authoredStrategy"] == "u" and record["memberCount"] == 5
    assert record["currentClassification"] == {**record["currentClassification"], "strategy": "u",
                                               "status": "consistent"}


def test_a_row_that_moves_its_seed_is_staged_applied_directly_and_read_back(factory):
    planned, layout, reader = run_in_apply_directly(  # west of Bench A at (4, 3) is outside Bench line (x 1 to 30)
        factory, sp.PATTERN_TOOL, {"seedIds": ["pl-bench-a"], "count": 4, "direction": "west", "gap": 2}, "move-turn")
    moved = planned["seedMoved"]
    assert moved["items"] == ["Bench A (pl-bench-a)"] and "inside Bench line (zn-benches)" in moved["why"]
    assert planned["package"] == {"packageId": "pattern-1", "operations": 4}  # the move and 3 copies
    bench = next(placement for placement in layout["placements"] if placement["placementId"] == "pl-bench-a")
    assert {key: bench["transform"]["position"][key] for key in ("x", "z")} == moved["to"]
    benches = sorted(placement["transform"]["position"]["x"] for placement in layout["placements"]
                     if placement["assetId"] == "asset-workbench")
    assert len(benches) == 4 and benches[0] > 1 and benches[-1] == moved["to"]["x"]
    read = asyncio.run(reader.call("inspect_pattern_provenance", {}))
    record = next(item for item in read["data"]["records"] if item["command"] == "linear_pattern")
    assert record["seedEntityIds"] == ["pl-bench-a"] and record["memberCount"] == 4
    assert record["currentClassification"]["status"] == "consistent"


def with_walks(host):
    """Two operators' saved walks in the staged-test layout, as the Plan saves them: Walker's goes home, to Old mill 1
    and to Bench A; Walker 2's from its home to Bench A (a stop the two share)."""
    principal = host.principal()
    catalog = {item["assetId"]: item for item in host.agent_runtime.asset_catalog_provider(principal, LOCAL_SITE_ID)}
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    revision = catalog["asset-workbench"]["assetDefinitionRevision"]
    walkers = [{"op": "place_asset", "placement": {
        "placementId": placement_id, "assetId": "asset-workbench", "assetDefinitionRevision": revision,
        "transform": {"position": {"x": x, "y": 0, "z": 3}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                      "scale": 1},
        "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": label}}}
        for placement_id, x, label in (("pl-walker", 12, "Walker"), ("pl-walker-2", 20, "Walker 2"))]  # Bench line
    owners = {"pl-walker": revision, "pl-walker-2": revision, "pl-bench-a": revision,
              "pl-old-1": catalog["asset-cnc-mill"]["assetDefinitionRevision"]}

    def anchor(anchor_id, owner, home=False):
        return {"navigationAnchorId": anchor_id, "anchorKind": "actor_home" if home else "station_operate",
                "ownerRef": {"ownerKind": "placement", "ownerId": owner}, "interactionKind": "none",
                "positionAuthority": "derived", "localPosition": None,
                "derivedPositionRef": {"sourceKind": "placement_transform" if home else "placement_access",
                                       "sourceId": owner, "sourceRevision": owners[owner]},
                "approachDirections": ["any"], "actorClasses": ["pedestrian"], "evidenceStatus": "derived",
                "evidence": ["evidence:deterministic-placement-access-v1"], "reviewStatus": "pending"}

    def walk(program_id, walker, stops):
        return {"movementProgramId": program_id, "actorPlacementId": walker, "actorClass": "pedestrian",
                "actorProfileRef": {"profileId": "pedestrian-profile:asset-workbench", "profileKind": "pedestrian",
                                    "profileRevision": revision},
                "orderedStops": [{"stopId": f"nst-{program_id}-{n}", "navigationAnchorId": stop,
                                  "interactionKind": "none", "required": True} for n, stop in enumerate(stops)],
                "loopMode": "task_cycle", "requiredRouteIds": [], "requiredAnchorIds": sorted(set(stops)),
                "forbiddenZoneIds": [], "forbiddenRouteIds": [], "manualPathConstraintIds": [], "handoffProgramIds": [],
                "sourceRevisions": {"actor_profile": revision, "layout": revision}, "evidenceStatus": "inferred",
                "evidence": ["evidence:walk-removal-test"], "reviewStatus": "pending"}

    navigation = {"schemaVersion": 1, "manualPathConstraints": [], "handoffPrograms": [], "anchors": [
        anchor("na-walker-home", "pl-walker", home=True), anchor("na-walker-2-home", "pl-walker-2", home=True),
        anchor("na-old-1", "pl-old-1"), anchor("na-bench-a", "pl-bench-a")], "movementPrograms": [
        walk("nmp-walker", "pl-walker", ["na-walker-home", "na-old-1", "na-walker-home", "na-bench-a"]),
        walk("nmp-walker-2", "pl-walker-2", ["na-walker-2-home", "na-bench-a"])]}
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        *walkers, {"op": "set_facility_navigation", "authoringSource": "plan_pointer",
                   "facilityNavigation": navigation}])
    return host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)


def test_the_kernel_removes_only_the_walks_that_deletions_earlier_in_the_change_strand(factory):
    saved = with_walks(factory)
    principal = factory.principal()
    navigation = saved["layout"]["extensions"]["facilityNavigation"]
    delete = {"op": "delete_placement", "placementId": "pl-old-1"}

    def walks(programs, anchors, **extra):
        return {"op": "delete_stranded_movements", "movementProgramIds": programs, "navigationAnchorIds": anchors,
                **extra}

    def refused(operations):
        with pytest.raises(FacilityLayoutError) as error:
            factory.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], operations)
        return error.value.code, error.value.details

    assert refused([delete])[0] == "facility_navigation_dangling_identity"  # as before: a stop would dangle
    own = ["na-old-1", "na-walker-home"]
    assert refused([walks(["nmp-walker"], own), delete])[0] == "facility_navigation_removal_not_stranded"
    code, details = refused([delete, walks(["nmp-walker", "nmp-walker-2"], own)])
    assert code == "facility_navigation_removal_not_stranded" and details["movementProgramIds"] == ["nmp-walker-2"]
    code, details = refused([delete, walks(["nmp-walker"], [*own, "na-bench-a"])])
    assert code == "facility_navigation_removal_in_use" and details["navigationAnchorIds"] == ["na-bench-a"]
    code, details = refused([delete, walks(["nmp-walker"], ["na-walker-home"])])
    assert code == "facility_navigation_removal_incomplete" and details["navigationAnchorIds"] == ["na-old-1"]
    code, details = refused([delete, walks([], ["na-old-1"])])
    assert code == "facility_navigation_removal_incomplete" and details["movementProgramIds"] == ["nmp-walker"]
    assert refused([delete, walks(["nmp-walker"], own, authoringSource="plan_pointer")])[0] == (
        "invalid_operation_field")
    done = factory.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
                                            [delete, walks(["nmp-walker"], own)])
    after = done["layout"]["extensions"]["facilityNavigation"]
    assert after["movementPrograms"] == navigation["movementPrograms"][1:]  # Walker 2's, exactly as it was
    assert [anchor["navigationAnchorId"] for anchor in after["anchors"]] == ["na-bench-a", "na-walker-2-home"]
    # Sage's own batches may not carry it; only a package from the server's planner may.
    with pytest.raises(FacilityLayoutError, match="not authorized"):
        guard_operations([delete, walks(["nmp-walker"], own)])
    guard_operations([delete, walks(["nmp-walker"], own)], 1000, 600_000, planned=True)


def test_a_cleared_cell_takes_its_walk_in_the_same_change_applied_directly_and_undo_brings_it_back(factory):
    before = with_walks(factory)["layout"]["extensions"]["facilityNavigation"]
    applied = []
    planned, layout, _ = run_in_apply_directly(factory, sp.CELL_TOOL, {
        "strategy": "u", "assets": [{"assetId": "asset-cnc-mill", "count": 5}], "zoneId": "zn-a06",
        "removeIds": ["pl-old-1", "pl-old-2"]}, "walk-turn", applied)
    assert planned["alsoRemoves"] == "Also removes the Walker's saved walk (3 stops)."
    navigation = layout["extensions"]["facilityNavigation"]
    assert navigation["movementPrograms"] == before["movementPrograms"][1:]  # Walker 2's stays byte-identical
    assert [anchor["navigationAnchorId"] for anchor in navigation["anchors"]] == ["na-bench-a", "na-walker-2-home"]
    assert sum(placement["assetId"] == "asset-cnc-mill" for placement in layout["placements"]) == 5
    # Undo brings the walk back, exactly.
    restored = undo_applied(factory, applied[0], "walk-undo")
    assert restored["layout"]["extensions"]["facilityNavigation"] == before


def undo_applied(host, applied, key):
    """The app's Undo of a commit (its receipt), approved and applied."""
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    undo = create_proposal(host.service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
                           undo_receipt_id=applied["receipt"]["receiptId"])
    binding = undo["alternative"]["transactionBinding"]
    approval = host.service.approve_layout_proposal(
        principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, undo["proposalId"], binding, session_id="pattern-session",
        idempotency_key=key, explicit_approval=True)
    return host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                                              binding, session_id="pattern-session", idempotency_key=key)


def test_a_cleared_zone_takes_its_floor_markings_applied_directly_and_undo_brings_them_back(factory):
    # Only clearing (no machines), as "Clear Assembly Cell A06" asks: one call, one review, Apply Directly, Undo.
    principal = factory.principal()
    saved = factory.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    factory.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        {"op": "add_floor_marking", "floorMarking": {
            "markingType": "parking_box", "label": "A06 kit cart bay", "semanticRole": "staging",
            "transform": {"position": {"x": 26, "y": 0.008, "z": 17}, "rotationDegrees": 0}, "width": 3, "depth": 3,
            "fillColor": "#facc15", "strokeColor": "#334155", "opacity": 1, "text": "KIT CART",
            "positionMode": "manual", "metadata": {}, "evidence": []}}])
    before = factory.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
    applied = []
    planned, layout, _ = run_in_apply_directly(factory, sp.CELL_TOOL, {"zoneId": "zn-a06", "clearZone": True},
                                               "clear-turn", applied)
    assert planned["cleared"] == ("Clears Assembly Cell A06: removes Old mill 1, Old mill 2 and A06 kit cart bay "
                                  "(floor marking).")
    assert planned["package"] == {"packageId": "cell-1", "operations": 3}
    assert {"pl-old-1", "pl-old-2"}.isdisjoint(placement["placementId"] for placement in layout["placements"])
    assert not any(marking.get("label") == "A06 kit cart bay" for marking in layout.get("floorMarkings") or [])
    restored = undo_applied(factory, applied[0], "clear-undo")["layout"]
    assert restored["placements"] == before["placements"]
    assert restored["floorMarkings"] == before["floorMarkings"]


def test_a_refusal_reaches_sage_as_a_plain_reason(factory):
    principal = factory.principal()
    saved = factory.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(factory.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="refusal")
    refused = asyncio.run(gateway.call(sp.CELL_TOOL, {"strategy": "u", "assets": [
        {"assetId": "asset-cnc-mill", "count": 30}], "zoneId": "zn-benches"}))
    assert refused["error"]["code"] == "layout_pattern_refused"
    assert "Bench line (zn-benches) leaves about" in refused["error"]["message"]
    assert gateway.packages == {}


def test_a_mirror_and_a_ring_are_staged_applied_directly_and_read_back(factory):
    planned, layout, reader = run_in_apply_directly(factory, sp.PATTERN_TOOL, {
        "kind": "mirror", "seedIds": ["pl-bench-a"], "side": "east", "gap": 2}, "mirror-turn")
    assert planned["package"] == {"packageId": "pattern-1", "operations": 1}
    benches = [placement["transform"]["position"]["x"] for placement in layout["placements"]
               if placement["assetId"] == "asset-workbench"]
    assert sorted(benches) == [4.0, 7.8]  # Bench A ends at x 4.9: the line is at 5.9 and the copy 2 m clear
    assert planned["unverifiedFacing"] == ["Bench A (pl-bench-a)"]  # the starter bench has no reviewed sides

    planned, layout, reader = run_in_apply_directly(factory, sp.PATTERN_TOOL, {
        "kind": "perimeter", "seedIds": ["pl-old-2"], "widthCount": 2, "depthCount": 1, "gap": 0.5}, "ring-turn")
    assert planned["newItems"] == 5 and planned["extent"]["maxX"] < 38 and planned["extent"]["maxZ"] < 26
    assert sum(placement["assetId"] == "asset-cnc-mill" for placement in layout["placements"]) == 7
    read = asyncio.run(reader.call("inspect_pattern_provenance", {}))
    records = {item["command"]: item for item in read["data"]["records"]}
    assert records["mirror"]["memberCount"] == 2 and records["perimeter"]["memberCount"] == 6
    for command in ("mirror", "perimeter"):
        assert records[command]["currentClassification"]["status"] == "consistent", records[command]


def test_a_circle_that_turns_is_staged_applied_directly_and_read_back(factory):
    planned, layout, reader = run_in_apply_directly(factory, sp.PATTERN_TOOL, {
        "kind": "circular", "seedIds": ["pl-old-1"], "count": 4, "center": {"x": 26, "z": 17}, "turnWithPattern": True,
        "removeIds": ["pl-old-2"]}, "circle-turn")
    mills = [placement for placement in layout["placements"] if placement["assetId"] == "asset-cnc-mill"]
    assert len(mills) == 4 and "pl-old-2" not in {placement["placementId"] for placement in mills}
    assert planned["removed"] == ["Old mill 2 (pl-old-2)"]

    def bearing(placement):  # how far round its south side is from the centre, as saved
        position = placement["transform"]["position"]
        toward = math.degrees(math.atan2(26 - position["x"], 17 - position["z"]))
        return yaw_of(placement["transform"]["quaternion"]) + MILL_OPERATOR - toward

    seed = next(placement for placement in mills if placement["placementId"] == "pl-old-1")
    assert all(turn_apart(bearing(placement), bearing(seed)) < 1e-5 for placement in mills)
    read = asyncio.run(reader.call("inspect_pattern_provenance", {}))
    record = next(item for item in read["data"]["records"] if item["command"] == "circular_pattern")
    assert record["memberCount"] == 4 and record["currentClassification"]["status"] == "consistent"
