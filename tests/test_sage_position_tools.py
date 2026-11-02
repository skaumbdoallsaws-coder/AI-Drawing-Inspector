"""Sage's plan_facility_position (docs/sage-ribbon-tools-plan.md, R3): the ribbon's Position tools (align,
distribute, offset, relative, distance, swap), planned on the server.

On the pattern fixture (tests/fixtures/facility_layout/pattern_parity/factory.json) with a stack of two crates and a
second workstation added: every mode against what the ribbon itself sends, run with Node here only
(tests/position_session_runner.js: the workspace's builders and the session's movePlacements, moveSelected,
duplicatePlacements and applyPattern); the summaries; the refusals; and the whole path on a test host (plan, stage
with preview_planned_design, Apply Directly, read back).
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime import pilot, progress
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import tool_specs as gateway_tool_specs
from ai_inspector.facility_layout import sage_patterns as sp
from ai_inspector.facility_layout import sage_positions as spos
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.layout_patterns import PatternError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/facility_layout/pattern_parity/factory.json"
RUNNER = ROOT / "tests/position_session_runner.js"
MILLS = [f"pl-mill-{index}" for index in range(1, 6)]
REVISION = "rev-a"
STACK = {"family": "vertical_stack", "stackId": "stack-crates", "count": 2, "gapMeters": 0, "itemHeightMeters": 0.9,
         "evidenceStatus": "unverified"}


def placed(catalog, placement_id, asset_id, x, z, label, y=0.0, relation=None, mode="manual"):
    revision = next(record["assetDefinitionRevision"] for record in catalog if record["assetId"] == asset_id)
    return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": revision,
            "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1},
            "positionMode": mode, "snapRelationship": relation, "metadata": {"instanceLabel": label}}


def fixture():
    data = json.loads(FIXTURE.read_bytes())
    layout, catalog = data["layout"], data["catalog"]
    for level in (0, 1):
        layout["placements"].append(placed(catalog, f"pl-crate-{level}", "asset-box", 34, 12, f"Crate {level}",
                                           y=0.9 * level, relation={**STACK, "level": level}))
    layout["placements"].append(placed(catalog, "pl-ws2-bench", "asset-bench", 27.5, 1.5, "Bench 2"))
    layout["zones"].append({"zoneId": "zn-ws-2", "label": "Workstation 2", "zoneType": "workcell", "floorElevation": 0,
                            "boundary": [{"x": 26, "z": 0}, {"x": 30, "z": 0}, {"x": 30, "z": 3}, {"x": 26, "z": 3}],
                            "anchors": [{"anchorId": "ws2-in", "position": {"x": 28, "y": 0, "z": 0},
                                         "facing": {"x": 0, "y": 0, "z": -1}}]})
    return layout, catalog


def plan(arguments, layout=None):
    saved, catalog = fixture()
    return spos.plan_position(layout or saved, catalog, arguments, revision=REVISION)


def by_id(layout, identifier):
    return next(placement for placement in layout["placements"] if placement["placementId"] == identifier)


# ---------------------------------------------------------------- the ribbon's own operations

EDGES = {value: key for key, value in spos.EDGES.items()}
AXES = {value: key for key, value in spos.AXES.items()}
MEASURES = {value: key for key, value in spos.MEASURES.items()}
SIDES_OF = {"minimum": {"east": "south", "west": "south", "north": "west", "south": "west"},
            "maximum": {"east": "north", "west": "north", "north": "east", "south": "east"}}

CASES = [  # the ribbon's dialog settings
    {"name": "align west", "mode": "align", "ids": MILLS, "alignMode": "left"},
    {"name": "align centre lines", "mode": "align", "ids": MILLS, "alignMode": "center-z", "anchorId": "pl-mill-3"},
    {"name": "align north, a stale revision", "mode": "align", "ids": ["pl-bench-1", "pl-stale-1", "pl-box-1"],
     "alignMode": "north", "anchorId": "pl-box-1"},
    {"name": "align an item on a support", "mode": "align", "ids": ["pl-mill-1", "pl-vise-1"], "alignMode": "right"},
    {"name": "align a support", "mode": "align", "ids": ["pl-mill-2", "pl-bench-1"], "alignMode": "south"},
    {"name": "align a stack", "mode": "align", "ids": ["pl-mill-1", "pl-crate-1"], "alignMode": "left"},
    {"name": "align east-west centres", "mode": "align", "ids": ["pl-lathe-1", "pl-box-1"], "alignMode": "center-x"},
    {"name": "distribute equal gaps", "mode": "distribute", "ids": MILLS, "axis": "x", "method": "equal-gap"},
    {"name": "distribute equal centres", "mode": "distribute", "ids": MILLS, "axis": "z", "method": "equal-center"},
    {"name": "distribute fixed gap", "mode": "distribute", "ids": MILLS, "axis": "x", "method": "fixed-gap", "gap": 2},
    {"name": "beside, centred", "mode": "relative", "ids": ["pl-box-1"], "referenceId": "pl-lathe-1",
     "relation": "east", "distance": 2, "alignment": "center"},
    {"name": "beside, a group", "mode": "relative", "ids": ["pl-mill-4", "pl-mill-5"], "referenceId": "pl-bench-1",
     "relation": "north", "distance": 1.5, "alignment": "minimum"},
    {"name": "beside, a support", "mode": "relative", "ids": ["pl-bench-1"], "referenceId": "pl-mill-1",
     "relation": "south", "distance": 0, "alignment": "maximum"},
    {"name": "beside, west", "mode": "relative", "ids": ["pl-crate-0"], "referenceId": "pl-box-1",
     "relation": "west", "distance": 3, "alignment": "maximum"},
    {"name": "east-west gap", "mode": "distance", "ids": ["pl-mill-2"], "referenceId": "pl-mill-1",
     "distanceMode": "horizontal-gap", "distance": 4},
    {"name": "north-south gap", "mode": "distance", "ids": ["pl-bench-1"], "referenceId": "pl-mill-1",
     "distanceMode": "vertical-gap", "distance": 2.5},
    {"name": "east-west centres", "mode": "distance", "ids": ["pl-box-1"], "referenceId": "pl-lathe-1",
     "distanceMode": "horizontal-center", "distance": 6},
    {"name": "north-south centres", "mode": "distance", "ids": ["pl-mill-4"], "referenceId": "pl-mill-3",
     "distanceMode": "vertical-center", "distance": 5},
    {"name": "centre to centre", "mode": "distance", "ids": ["pl-lathe-1"], "referenceId": "pl-mill-5",
     "distanceMode": "center-distance", "distance": 10},
    {"name": "offset a support", "mode": "offset", "ids": ["pl-bench-1"], "offset": {"x": 3, "z": -2}},
    {"name": "offset an item on a support", "mode": "offset", "ids": ["pl-vise-1"], "offset": {"x": 0.2, "z": 0}},
    {"name": "offset a stack", "mode": "offset", "ids": ["pl-crate-0"], "offset": {"x": -1, "z": 1}},
    {"name": "offset two", "mode": "offset", "ids": ["pl-mill-1", "pl-box-1"], "offset": {"x": 0, "z": -4.5}},
    {"name": "copy a support", "mode": "offset", "copy": True, "ids": ["pl-bench-1"], "offset": {"x": 0, "z": 4}},
    {"name": "copy a stack", "mode": "offset", "copy": True, "ids": ["pl-crate-1"], "offset": {"x": 2, "z": 0}},
    {"name": "copy two", "mode": "offset", "copy": True, "ids": ["pl-mill-1", "pl-box-1"], "offset": {"x": 5, "z": 5}},
    {"name": "swap two machines", "mode": "swap", "ids": ["pl-mill-1", "pl-lathe-1"]},
    {"name": "swap two cells", "mode": "swap", "ids": ["zn-ws-1", "zn-ws-2"]},
    {"name": "swap an item and a marking", "mode": "swap", "ids": ["pl-box-1", "mk-1"]},
]


def arguments_for(case):
    """The same request, as Sage gives it."""
    mode, ids = case["mode"], case["ids"]
    arguments = {"mode": mode, "itemIds": ids}
    if mode == "align":
        arguments["edge"] = EDGES[case["alignMode"]]
        if case.get("anchorId"):
            arguments["anchorId"] = case["anchorId"]
    elif mode == "distribute":
        arguments.update(axis=AXES[case["axis"]], method=case["method"])
        if "gap" in case:
            arguments["gap"] = case["gap"]
    elif mode == "relative":
        alignment = case["alignment"]
        edge = "center" if alignment == "center" else SIDES_OF[alignment][case["relation"]]
        arguments.update(referenceId=case["referenceId"], side=case["relation"], distance=case["distance"],
                         alignEdge=edge)
    elif mode == "distance":
        arguments.update(referenceId=case["referenceId"], measure=MEASURES[case["distanceMode"]],
                         distance=case["distance"])
    elif mode == "offset":
        arguments["offset"] = case["offset"]
        if case.get("copy"):
            arguments["copy"] = True
    return arguments


def ribbon(cases, layout=None, catalog=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    saved, records = fixture()
    payload = {"layout": layout or saved, "catalog": catalog or records, "operationIdNamespace": "unused",
               "cases": cases}
    flags = 0x08000000 if sys.platform == "win32" else 0  # no console window on the user's screen
    done = subprocess.run([node, str(RUNNER)], input=json.dumps(payload).encode("utf-8"), capture_output=True,
                          timeout=120, cwd=ROOT, creationflags=flags)
    return {item["name"]: item for item in json.loads(done.stdout)}


def same(ribbon_value, sage, path=""):
    if isinstance(ribbon_value, dict) and isinstance(sage, dict):
        if set(ribbon_value) == set(sage) == {"x", "y", "z", "w"}:
            sign = 1 if sum(ribbon_value[key] * sage[key] for key in "xyzw") >= 0 else -1
            assert all(abs(ribbon_value[key] - sign * sage[key]) < 1e-9 for key in "xyzw"), path
            return
        assert set(ribbon_value) == set(sage), f"{path}: ribbon {sorted(ribbon_value)} sage {sorted(sage)}"
        for key in ribbon_value:
            same(ribbon_value[key], sage[key], f"{path}.{key}")
    elif isinstance(ribbon_value, list) and isinstance(sage, list):
        assert len(ribbon_value) == len(sage), f"{path}: ribbon {len(ribbon_value)} sage {len(sage)}"
        for index, (left, right) in enumerate(zip(ribbon_value, sage)):
            same(left, right, f"{path}[{index}]")
    elif isinstance(ribbon_value, (int, float)) and not isinstance(ribbon_value, bool) \
            and isinstance(sage, (int, float)):
        assert abs(ribbon_value - sage) <= 1e-9, f"{path}: ribbon {ribbon_value} sage {sage}"
    else:
        assert ribbon_value == sage, f"{path}: ribbon {ribbon_value!r} sage {sage!r}"


def test_every_mode_sends_what_the_ribbon_sends():
    for case in CASES:
        case["namespace"] = sp._namespace(spos.TOOL, arguments_for(case), REVISION)
    results = ribbon(CASES)
    for case in CASES:
        result = results[case["name"]]
        assert result["ok"], result
        assert result["operations"], case["name"]
        same(result["operations"], plan(arguments_for(case))["operations"], case["name"])


def test_the_ribbon_and_sage_refuse_the_same_spans():
    """Equal clear gaps between items that already overlap along the axis: both refuse."""
    case = {"name": "overlap", "mode": "distribute", "ids": ["pl-bench-1", "pl-vise-1", "pl-mill-3"], "axis": "x",
            "method": "equal-gap"}
    assert not ribbon([case])["overlap"]["ok"]
    with pytest.raises(PatternError, match="already overlap"):
        plan(arguments_for(case))


# ---------------------------------------------------------------- what Sage is told

def test_align_says_the_anchor_and_what_moved():
    result = plan({"mode": "align", "itemIds": MILLS, "edge": "west"})
    assert result["anchor"] == "Mill 1 (pl-mill-1)" and result["movedCount"] == 4
    assert {row["item"] for row in result["moved"]} == {f"Mill {index} (pl-mill-{index})" for index in range(2, 6)}
    assert all(row["to"]["x"] - row["from"]["x"] == row["by"]["x"] for row in result["moved"])
    assert "carriedAlong" not in result


def test_an_anchor_outside_the_items_stays_put_and_lines_them_up():
    result = plan({"mode": "align", "itemIds": ["pl-mill-2"], "edge": "north", "anchorId": "pl-mill-1"})
    assert result["anchor"] == "Mill 1 (pl-mill-1)" and result["movedCount"] == 1
    move = result["operations"][0]
    assert move["placementId"] == "pl-mill-2" and abs(move["position"]["z"] - 20.35) < 1e-9  # 21.85 - 1.5: turned 90 degrees


def test_a_moved_support_carries_what_sits_on_it_and_says_so():
    result = plan({"mode": "relative", "itemIds": ["pl-bench-1"], "referenceId": "pl-mill-1", "side": "south",
                   "distance": 1})
    assert result["carriedAlong"] == ["Vise 1 (pl-vise-1)"]
    assert [operation["op"] for operation in result["operations"]] == ["move_placement", "move_placement",
                                                                        "set_snap_relationship"]


def test_a_stack_moves_whole():
    result = plan({"mode": "offset", "itemIds": ["pl-crate-1"], "offset": {"x": 1, "z": 0}})
    assert sorted(operation["placementId"] for operation in result["operations"]) == ["pl-crate-0", "pl-crate-1"]
    assert result["carriedAlong"] == ["Crate 0 (pl-crate-0)"]


def test_the_reference_named_among_the_items_stays_as_on_the_ribbon():
    result = plan({"mode": "relative", "itemIds": ["pl-box-1", "pl-lathe-1"], "referenceId": "pl-lathe-1",
                   "side": "east", "distance": 2})
    assert [operation["placementId"] for operation in result["operations"]] == ["pl-box-1"]


def test_distribute_and_distance_say_the_numbers():
    spread = plan({"mode": "distribute", "itemIds": MILLS, "axis": "east-west"})
    assert spread["method"] == "equal-gap" and spread["clearGap"] == 0.9  # (20 m span - 16.4 m of mills) / 4
    assert spread["order"][0] == "Mill 1 (pl-mill-1)" and spread["order"][-1] == "Mill 5 (pl-mill-5)"
    apart = plan({"mode": "distance", "itemIds": ["pl-mill-2"], "referenceId": "pl-mill-1",
                  "measure": "east-west-gap", "distance": 4})
    assert apart["before"] == 1.15 and apart["after"] == 4  # 4.65 (turned 90 degrees) - 3.5


def test_copies_bring_what_sits_on_them_and_say_how_many():
    result = plan({"mode": "offset", "itemIds": ["pl-bench-1"], "offset": {"x": 0, "z": 4}, "copy": True})
    assert result["newItems"] == 2 and result["copiedAlong"] == ["Vise 1 (pl-vise-1)"]
    bench, vise = result["operations"]
    assert vise["snapRelationship"]["supportPlacementId"] == bench["newPlacementId"]


def test_a_swap_trades_the_two_places_with_provenance():
    result = plan({"mode": "swap", "itemIds": ["pl-mill-1", "pl-lathe-1"]})
    assert result["swapped"] == ["Mill 1 (pl-mill-1)", "Lathe 1 (pl-lathe-1)"]
    moves = {operation["placementId"]: operation["position"] for operation in result["operations"]
             if operation["op"] == "move_placement"}
    assert moves == {"pl-mill-1": {"x": 30.0, "y": 0.0, "z": 30.0}, "pl-lathe-1": {"x": 2.0, "y": 0.0, "z": 20.0}}
    provenance = result["operations"][0]["layoutProvenance"]
    assert provenance["command"] == "swap" and provenance["seedEntityIds"] == ["pl-lathe-1", "pl-mill-1"]


@pytest.mark.parametrize("arguments, words", [
    ({"mode": "align", "itemIds": ["pl-mill-1", "pl-locked-1"], "edge": "north"}, "is locked. Ask the user to unlock it"),
    ({"mode": "align", "itemIds": ["pl-mill-1"], "edge": "north"}, "takes at least two items"),
    ({"mode": "align", "itemIds": ["pl-mill-1", "zn-ws-1"], "edge": "west"}, "is not a placed item"),
    ({"mode": "align", "itemIds": ["pl-mill-1", "pl-gone"], "edge": "west"}, "There is no pl-gone"),
    ({"mode": "align", "itemIds": ["pl-mill-1", "pl-mill-2"], "edge": "west", "gap": 2}, "gap is not for mode align"),
    ({"mode": "distribute", "itemIds": MILLS[:2], "axis": "east-west"}, "takes at least three items"),
    ({"mode": "distribute", "itemIds": MILLS, "axis": "east-west", "method": "fixed-gap"}, "fixed-gap needs a gap"),
    ({"mode": "distribute", "itemIds": MILLS, "axis": "east-west", "gap": 1}, "gap goes with method fixed-gap"),
    ({"mode": "relative", "itemIds": ["pl-box-1"], "referenceId": "pl-lathe-1", "side": "east", "distance": 1,
      "alignEdge": "east"}, "For side east, alignEdge is south, center, north"),
    ({"mode": "relative", "itemIds": ["pl-lathe-1"], "referenceId": "pl-lathe-1", "side": "east", "distance": 1},
     "besides the reference"),
    ({"mode": "distance", "itemIds": ["pl-box-1", "pl-mill-1"], "referenceId": "pl-lathe-1", "measure": "centers",
      "distance": 3}, "takes exactly one item"),
    ({"mode": "distance", "itemIds": ["pl-box-1"], "referenceId": "pl-box-1", "measure": "centers", "distance": 3},
     "its own reference"),
    ({"mode": "offset", "itemIds": ["pl-box-1"], "offset": {"x": 0, "z": 0}}, "The offset is zero"),
    ({"mode": "offset", "itemIds": ["pl-vise-1"], "offset": {"x": 1, "z": 0}, "copy": True}, "stand on nothing"),
    ({"mode": "swap", "itemIds": ["pl-mill-1"]}, "takes exactly two items"),
    ({"mode": "swap", "itemIds": ["zn-ws-1", "pl-ws-bench"]}, "overlap or share items"),
    ({"mode": "swap", "itemIds": ["pl-mill-1", "pl-locked-1"]}, "is locked. Ask the user to unlock it"),
    ({"mode": "swap", "itemIds": ["pl-vise-1", "pl-box-1"]}, "sits on Bench 1 (pl-bench-1), which would stay"),
    ({"mode": "swap", "itemIds": ["pl-bench-1", "pl-box-1"]}, "has Vise 1 (pl-vise-1) on it"),
    ({"mode": "swap", "itemIds": ["pl-crate-0", "pl-box-1"]}, "stack that would be split"),
    ({"mode": "align", "itemIds": ["pl-mill-1", "pl-mill-2"], "edge": "west", "anchorId": "pl-mill-1"}, None),
])
def test_what_cannot_be_done_says_why(arguments, words):
    if words is None:  # mill 2 is already 3.7 m wide round x 6.5: it moves; then nothing more to do
        layout = deepcopy(fixture()[0])
        planned = plan(arguments, layout)
        for operation in planned["operations"]:
            by_id(layout, operation["placementId"])["transform"]["position"] = operation["position"]
        with pytest.raises(PatternError, match="Nothing would move"):
            plan(arguments, layout)
        return
    with pytest.raises(PatternError, match=re.escape(words)):
        plan(arguments)


def test_a_locked_item_carried_along_is_named():
    layout = deepcopy(fixture()[0])
    by_id(layout, "pl-vise-1")["positionMode"] = "locked"
    with pytest.raises(PatternError, match=r"Vise 1 \(pl-vise-1\) is locked \(it would move along"):
        plan({"mode": "offset", "itemIds": ["pl-bench-1"], "offset": {"x": 1, "z": 0}}, layout)


# ---------------------------------------------------------------- registration

def test_the_tool_is_registered_with_a_closed_schema_a_label_and_a_rule():
    specs = {spec["name"]: spec for spec in gateway_tool_specs()}
    schema = specs[spos.TOOL]["input_schema"]
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    validator = Draft202012Validator(schema)
    for case in CASES:
        validator.validate(arguments_for(case))
    assert not validator.is_valid({"mode": "align", "itemIds": ["pl-mill-1", "pl-mill-1"], "edge": "west"})
    assert not validator.is_valid({"mode": "spin", "itemIds": ["pl-mill-1"]})
    assert "call plan_facility_position" in pilot.EDIT_INSTRUCTIONS
    layout, catalog = fixture()
    names = progress.LayoutNames(layout, catalog)
    describe = lambda arguments: progress.describe(spos.TOOL, arguments, names)  # noqa: E731
    assert describe({"mode": "align", "itemIds": ["pl-mill-1", "pl-mill-2"], "edge": "west"})["running"] == \
        "Planning the alignment of Mill 1 and Mill 2"
    assert describe({"mode": "relative", "itemIds": ["pl-box-1"], "referenceId": "pl-lathe-1", "side": "east",
                     "distance": 2})["done"] == "Planned a move of Box 1 east of Lathe 1"
    assert describe({"mode": "distance", "itemIds": ["pl-box-1"], "referenceId": "pl-lathe-1",
                     "measure": "east-west-gap", "distance": 1})["done"] == "Planned Box 1 1 m from Lathe 1"
    assert describe({"mode": "distance", "itemIds": ["pl-box-1"], "referenceId": "pl-lathe-1",
                     "distance": 2.5})["running"] == "Planning Box 1 2.5 m from Lathe 1"
    assert describe({"mode": "offset", "itemIds": MILLS, "offset": {"x": 1, "z": 0}, "copy": True})["failed"] == \
        "Couldn't plan copies of 5 items"
    assert describe({"mode": "swap", "itemIds": ["zn-ws-1", "zn-ws-2"]})["done"] == \
        "Planned a swap of Workstation 1 and Workstation 2"


# ---------------------------------------------------------------- the whole path

@pytest.fixture
def factory(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    catalog = list(host.agent_runtime.asset_catalog_provider(principal, LOCAL_SITE_ID))
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        {"op": "place_asset", "placement": placed(catalog, "pl-mill-a", "asset-cnc-mill", 5, 5, "Mill A")},
        {"op": "place_asset", "placement": placed(catalog, "pl-mill-b", "asset-cnc-mill", 12, 7, "Mill B")},
        {"op": "place_asset", "placement": placed(catalog, "pl-mill-c", "asset-cnc-mill", 22, 4, "Mill C")},
        {"op": "place_asset", "placement": placed(catalog, "pl-bench-a", "asset-workbench", 8, 16, "Bench A")}])
    try:
        yield host
    finally:
        host.close()


def run_in_apply_directly(host, arguments, turn):
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(host.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=turn)
    gateway.edit_mode = "direct"
    planned = asyncio.run(gateway.call(spos.TOOL, arguments))
    assert planned["ok"], planned
    assert host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved  # planning reads only
    staged = asyncio.run(gateway.call("preview_planned_design", {"packageId": planned["data"]["package"]["packageId"]}))
    assert staged["ok"], staged
    assert staged["data"]["approvalRequired"] is False, staged["data"]["directApplyPolicy"]
    proposal_id = staged["data"]["proposalId"]
    binding = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)[
        "alternative"]["transactionBinding"]
    approval = host.service.approve_layout_proposal(
        principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding, session_id="position-session",
        idempotency_key=f"position-{turn}", explicit_approval=False, authorization_mode="direct", direct_consent=True)
    host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"], binding,
                                       session_id="position-session", idempotency_key=f"position-{turn}")
    return planned["data"], host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]


def test_align_distribute_and_swap_are_staged_applied_directly_and_saved(factory):
    planned, layout = run_in_apply_directly(factory, {"mode": "align", "itemIds": ["pl-mill-a", "pl-mill-b",
                                                                                  "pl-mill-c"], "edge": "south"}, "a")
    assert planned["package"] == {"packageId": "position-1", "operations": 2}
    assert {round(by_id(layout, item)["transform"]["position"]["z"], 9) for item in ("pl-mill-b", "pl-mill-c")} == {5}
    _, layout = run_in_apply_directly(factory, {"mode": "distribute", "itemIds": ["pl-mill-a", "pl-mill-b",
                                                                                  "pl-mill-c"], "axis": "east-west",
                                                "method": "equal-center"}, "d")
    assert round(by_id(layout, "pl-mill-b")["transform"]["position"]["x"], 9) == 13.5
    planned, layout = run_in_apply_directly(factory, {"mode": "swap", "itemIds": ["pl-mill-a", "pl-bench-a"]}, "s")
    assert by_id(layout, "pl-mill-a")["transform"]["position"] == {"x": 8.0, "y": 0.0, "z": 16.0}
    assert by_id(layout, "pl-bench-a")["transform"]["position"] == {"x": 5.0, "y": 0.0, "z": 5.0}
    assert by_id(layout, "pl-mill-a")["metadata"]["layoutProvenance"]["command"] == "swap"


def test_a_copy_is_staged_applied_directly_and_saved(factory):
    planned, layout = run_in_apply_directly(factory, {"mode": "offset", "itemIds": ["pl-bench-a"], "copy": True,
                                                      "offset": {"x": 0, "z": 4}}, "c")
    benches = [placement for placement in layout["placements"] if placement["assetId"] == "asset-workbench"]
    assert planned["newItems"] == 1 and len(benches) == 2
    assert sorted(bench["transform"]["position"]["z"] for bench in benches) == [16, 20]


def test_a_refusal_reaches_sage_as_a_plain_reason(factory):
    principal = factory.principal()
    saved = factory.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(factory.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="refusal")
    refused = asyncio.run(gateway.call(spos.TOOL, {"mode": "distribute", "itemIds": ["pl-mill-a", "pl-mill-b"],
                                                   "axis": "east-west"}))
    assert refused["error"]["code"] == "layout_pattern_refused"
    assert "takes at least three items" in refused["error"]["message"]
    assert gateway.packages == {}
