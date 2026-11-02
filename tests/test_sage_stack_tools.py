"""Sage's stacks and cell groups (docs/sage-ribbon-tools-plan.md, R4): plan_facility_stack (stack, surface) and
plan_facility_cell actions group and ungroup.

On the pattern fixture (tests/fixtures/facility_layout/pattern_parity/factory.json) with desks that publish a
worktop (square, and turned a quarter), a stack of crates and a manufacturing cell added: each against what the
ribbon itself sends, run with Node here only (tests/position_session_runner.js: the workspace's seed and builders,
then the session's applyPattern, createCellGroup and ungroupCell); the summaries; the refusals; and the whole path
on a test host (plan, stage with preview_planned_design, apply, read back).
"""
import asyncio
from copy import deepcopy
import json
import math
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
from ai_inspector.facility_layout import sage_stacks as ss
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.layout_patterns import PatternError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/facility_layout/pattern_parity/factory.json"
RUNNER = ROOT / "tests/position_session_runner.js"
REVISION = "rev-a"
WORKTOP = {"surfaceId": "worktop", "label": "Desk worktop", "localFrame": {
    "origin": {"x": 0.0, "y": 0.74, "z": 0.05}, "xAxis": {"x": 1, "y": 0, "z": 0}, "zAxis": {"x": 0, "y": 0, "z": 1},
    "normal": {"x": 0, "y": 1, "z": 0}}, "bounds": {"minimumX": -0.68, "maximumX": 0.68, "minimumZ": -0.33,
                                                    "maximumZ": 0.43}, "allowedSides": ["above"],
           "evidenceStatus": "derived"}
TURNED = {**WORKTOP, "surfaceId": "turned-top", "allowedSides": ["above", "below"], "localFrame": {
    **WORKTOP["localFrame"], "xAxis": {"x": 0, "y": 0, "z": -1}, "zAxis": {"x": 1, "y": 0, "z": 0}}}


def placed(placement_id, asset_id, revision, x, z, label, yaw=0.0, y=0.0, relation=None, mode="manual"):
    half = math.radians(yaw) / 2
    return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": revision,
            "transform": {"position": {"x": x, "y": y, "z": z},
                          "quaternion": {"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)}, "scale": 1},
            "positionMode": mode, "snapRelationship": relation, "metadata": {"instanceLabel": label}}


def fixture():
    data = json.loads(FIXTURE.read_bytes())
    layout, catalog = data["layout"], data["catalog"]

    def desk(asset_id, surfaces):
        return {"assetId": asset_id, "assetDefinitionRevision": "rev-" + asset_id, "displayName": asset_id,
                "definition": {"geometry": {"aabb": {"minimum": {"x": -0.7, "y": 0, "z": -0.4},
                                                     "maximum": {"x": 0.7, "y": 0.75, "z": 0.4}}}},
                "supportSurfaces": surfaces}

    catalog += [desk("asset-desk", [WORKTOP]), desk("asset-turned-desk", [TURNED])]
    stack = {"family": "vertical_stack", "stackId": "stack-crates", "count": 2, "gapMeters": 0,
             "itemHeightMeters": 0.9, "evidenceStatus": "unverified"}
    layout["placements"] += [
        placed("pl-desk-1", "asset-desk", "rev-asset-desk", 60, 5, "Desk 1"),
        placed("pl-desk-2", "asset-turned-desk", "rev-asset-turned-desk", 64, 5, "Desk 2", yaw=90),
        placed("pl-desk-4", "asset-desk", "rev-asset-desk", 72, 5, "Desk 4", yaw=30),
        placed("pl-tool-1", "asset-vise", "rev-vise", 61, 7, "Tool 1"),
        placed("pl-tool-2", "asset-vise", "rev-vise", 62, 7, "Tool 2", yaw=90),
        placed("pl-crate-0", "asset-box", "rev-box", 34, 12, "Crate 0", relation={**stack, "level": 0}),
        placed("pl-crate-1", "asset-box", "rev-box", 34, 12, "Crate 1", y=0.9, relation={**stack, "level": 1}),
        placed("pl-unknown", "asset-none", "rev-none", 80, 5, "Mystery")]
    layout["zones"].append({"zoneId": "zn-cell-1", "label": "Mill Cell M01", "zoneType": "workcell",
                            "floorElevation": 0, "anchors": [], "evidence": [],
                            "boundary": [{"x": 40, "z": 25}, {"x": 46, "z": 25}, {"x": 46, "z": 31},
                                         {"x": 40, "z": 31}],
                            "extensions": {"cellGroup": {"schemaVersion": 1, "groupKind": "manufacturing_cell",
                                                         "membership": "geometric", "envelopePadding": 1,
                                                         "autoNumber": {"seriesId": "s-1", "baseName": "Mill Cell",
                                                                        "prefix": "M", "start": 1, "padding": 2,
                                                                        "sequence": 1},
                                                         "functionalInterfaces": {}}}})
    return layout, catalog


def stack(arguments, layout=None):
    saved, catalog = fixture()
    return ss.plan_stack(layout or saved, catalog, arguments, revision=REVISION)


def cell(arguments, layout=None):
    saved, catalog = fixture()
    return sp.plan_cell(layout or saved, catalog, arguments, revision=REVISION)


# ---------------------------------------------------------------- the ribbon's own operations

def ribbon(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    layout, catalog = fixture()
    payload = {"layout": layout, "catalog": catalog, "operationIdNamespace": "unused", "cases": cases}
    flags = 0x08000000 if sys.platform == "win32" else 0  # no console window on the user's screen
    done = subprocess.run([node, str(RUNNER)], input=json.dumps(payload).encode("utf-8"), capture_output=True,
                          timeout=120, cwd=ROOT, creationflags=flags)
    return {item["name"]: item for item in json.loads(done.stdout)}


def same(ribbon_value, sage, path=""):
    if isinstance(ribbon_value, dict) and isinstance(sage, dict):
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


STACKS = [  # (Sage's arguments, the ribbon's selection and dialog settings)
    ({"mode": "stack", "placementId": "pl-box-1", "count": 3}, ["pl-box-1"], {"count": 3, "gap": 0}),
    ({"mode": "stack", "placementId": "pl-mill-2", "count": 2, "gap": 0.25}, ["pl-mill-2"], {"count": 2, "gap": 0.25}),
    ({"mode": "stack", "placementId": "pl-lathe-1", "count": 4, "gap": 0.1}, ["pl-lathe-1"], {"count": 4, "gap": 0.1}),
    ({"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-2", "pl-tool-1"]},
     ["pl-desk-1", "pl-tool-1", "pl-tool-2"],
     {"supportPlacementId": "pl-desk-1", "surfaceId": "worktop", "side": "above", "gap": 0, "itemGap": 0.05,
      "inset": 0.05}),
    ({"mode": "surface", "supportId": "pl-desk-2", "itemIds": ["pl-tool-1", "pl-tool-2"], "side": "bottom",
      "gap": 0.02}, ["pl-desk-2", "pl-tool-1", "pl-tool-2"],
     {"supportPlacementId": "pl-desk-2", "surfaceId": "turned-top", "side": "below", "gap": 0.02, "itemGap": 0.05,
      "inset": 0.05}),
    ({"mode": "surface", "supportId": "pl-desk-4", "itemIds": ["pl-tool-1", "pl-tool-2"], "itemGap": 0.2,
      "inset": 0.1}, ["pl-desk-4", "pl-tool-1", "pl-tool-2"],
     {"supportPlacementId": "pl-desk-4", "surfaceId": "worktop", "side": "above", "gap": 0, "itemGap": 0.2,
      "inset": 0.1}),
    ({"mode": "surface", "supportId": "pl-bench-1", "itemIds": ["pl-vise-1", "pl-tool-1"]},
     ["pl-bench-1", "pl-tool-1", "pl-vise-1"],
     {"supportPlacementId": "pl-bench-1", "surfaceId": "top", "side": "above", "gap": 0, "itemGap": 0.05,
      "inset": 0.05}),
]


def test_stacks_and_surfaces_send_what_the_ribbon_sends():
    cases = []
    for number, (arguments, ids, options) in enumerate(STACKS):
        cases.append({"name": str(number), "mode": arguments["mode"], "ids": ids, "options": options,
                      "namespace": sp._namespace(ss.TOOL, arguments, REVISION)})
    results = ribbon(cases)
    for number, (arguments, _, _) in enumerate(STACKS):
        result = results[str(number)]
        assert result["ok"], result
        same(result["operations"], stack(arguments)["operations"], f"case {number}")


GROUPS = [  # (Sage's arguments, the ribbon's selection)
    ({"action": "group", "itemIds": ["pl-mill-1", "pl-mill-2"], "name": "Machining", "prefix": "M", "number": 4},
     ["pl-mill-1", "pl-mill-2"]),
    ({"action": "group", "itemIds": ["zn-ws-1"], "name": "Workstation", "envelopePadding": 0.5}, ["zn-ws-1"]),
    ({"action": "group", "itemIds": ["pl-bench-1"]}, ["pl-bench-1"]),  # its vise comes too; the bounds are the same
]


def test_a_cell_group_and_an_ungroup_send_what_the_ribbon_sends():
    cases, planned = [], []
    for number, (arguments, ids) in enumerate(GROUPS):
        result = cell(arguments)
        auto = result["operations"][0]["zone"]["extensions"]["cellGroup"]["autoNumber"]
        planned.append(result)
        cases.append({"name": str(number), "mode": "group", "ids": ids,
                      "namespace": sp._namespace(sp.CELL_TOOL, arguments, REVISION), "cell": {
            "baseName": auto["baseName"], "prefix": auto["prefix"], "start": auto["start"], "numberPadding": 2,
            "envelopePadding": arguments.get("envelopePadding", 1), "color": ss.CELL_COLOR,
            "seriesId": auto["seriesId"]}})
    cases.append({"name": "ungroup", "mode": "ungroup", "zoneId": "zn-cell-1", "namespace": "0" * 40})
    results = ribbon(cases)
    for number, result in enumerate(planned):
        assert results[str(number)]["ok"], results[str(number)]
        same(results[str(number)]["operations"], result["operations"], f"group {number}")
    same(results["ungroup"]["operations"], cell({"action": "ungroup", "zoneId": "zn-cell-1"})["operations"])


# ---------------------------------------------------------------- what Sage is told

def test_a_stack_says_its_levels_and_heights():
    result = stack({"mode": "stack", "placementId": "pl-box-1", "count": 3, "gap": 0.1})
    assert result == {**result, "item": "Box 1 (pl-box-1)", "levels": 3, "newItems": 2, "itemHeight": 1.35,
                      "gap": 0.1, "totalHeight": 4.25}
    copies = [operation for operation in result["operations"] if operation["op"] == "duplicate_placement"]
    assert [round(operation["position"]["y"], 9) for operation in copies] == [1.45, 2.9]
    relation = next(operation for operation in result["operations"] if operation["op"] == "set_snap_relationship")
    assert relation["placementId"] == "pl-box-1" and relation["snapRelationship"]["level"] == 0
    assert result["operations"][0]["layoutProvenance"]["command"] == "vertical_stack"


def test_a_surface_says_where_each_item_went():
    result = stack({"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1", "pl-tool-2"]})
    assert result["support"] == "Desk 1 (pl-desk-1)" and result["surface"] == "worktop"
    assert result["surfaceLabel"] == "Desk worktop" and result["movedCount"] == 2
    assert [row["item"] for row in result["placed"]] == ["Tool 1 (pl-tool-1)", "Tool 2 (pl-tool-2)"]
    assert all(row["height"] == 0.74 for row in result["placed"])  # the worktop's height on the floor


def test_a_cell_takes_the_next_free_number_and_brings_what_sits_on_its_items():
    result = cell({"action": "group", "itemIds": ["pl-mill-3"], "name": "Mill Cell", "prefix": "M"})
    assert result["cell"] == "Mill Cell M02"  # Mill Cell M01 exists
    result = cell({"action": "group", "itemIds": ["pl-bench-1"]})
    assert result["cell"] == "Manufacturing Cell 01" and result["broughtAlong"] == ["Vise 1 (pl-vise-1)"]
    assert result["items"] == 2 and result["envelopePadding"] == 1
    zone = result["operations"][0]["zone"]
    assert zone["extensions"]["style"] == {"fillColor": "#2f80b9"} and "zoneId" not in zone


def test_an_ungroup_keeps_the_items():
    layout = deepcopy(fixture()[0])
    layout["placements"].append(placed("pl-in-cell", "asset-box", "rev-box", 43, 28, "Kit"))
    result = cell({"action": "ungroup", "zoneId": "zn-cell-1"}, layout)
    assert result["cell"] == "Mill Cell M01 (zn-cell-1)" and result["itemsStay"] == 1
    assert result["operations"] == [{"op": "delete_zone", "zoneId": "zn-cell-1"}]


@pytest.mark.parametrize("tool, arguments, words", [
    ("stack", {"mode": "stack", "placementId": "pl-locked-1"}, "is locked"),
    ("stack", {"mode": "stack", "placementId": "pl-crate-0"}, "is already part of a stack"),
    ("stack", {"mode": "stack", "placementId": "pl-vise-1"}, "sits on Bench 1 (pl-bench-1); a stack stands"),
    ("stack", {"mode": "stack", "placementId": "pl-bench-1"}, "has Vise 1 (pl-vise-1) on it"),
    ("stack", {"mode": "stack", "placementId": "pl-stale-1"}, "size at its revision is not in the library"),
    ("stack", {"mode": "stack", "placementId": "pl-unknown"}, "size at its revision is not in the library"),
    ("stack", {"mode": "stack", "placementId": "zn-ws-1"}, "is not a placed item"),
    ("stack", {"mode": "stack"}, "needs placementId"),
    ("stack", {"mode": "stack", "placementId": "pl-box-1", "count": 51}, "stack count must be between 2 and 50"),
    ("stack", {"mode": "stack", "placementId": "pl-box-1", "supportId": "pl-desk-1"}, "supportId is not for mode"),
    ("stack", {"mode": "surface", "supportId": "pl-mill-1", "itemIds": ["pl-tool-1"]}, "has no published surface"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1"], "surfaceId": "top"},
     "has no surface top; its surfaces: worktop"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1"], "side": "bottom"},
     "takes items on its top only"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-desk-1"]}, "cannot also be one"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-locked-1"]}, "is locked"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-crate-1"]}, "is part of a stack"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-vise-1"]}, "sits on Bench 1"),
    ("stack", {"mode": "surface", "supportId": "pl-bench-1", "itemIds": ["pl-box-1"]},
     "has Vise 1 (pl-vise-1) on it: include it in itemIds"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-mill-1"]}, "is bigger than Desk 1"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1", "pl-tool-2"], "itemGap": 1},
     "They do not all fit on Desk 1"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1"], "inset": 0.7},
     "too small for that inset"),
    ("stack", {"mode": "surface", "supportId": "pl-desk-1"}, "needs itemIds"),
    ("cell", {"action": "group", "itemIds": ["pl-mill-1"], "envelopePadding": 5},
     "The cell would also take in Mill 2 (pl-mill-2)"),
    ("cell", {"action": "group", "itemIds": ["pl-mill-3"], "name": "Mill Cell", "prefix": "M", "number": 1},
     "already a zone named Mill Cell M01"),
    ("cell", {"action": "group", "itemIds": ["pl-mill-3"], "strategy": "u"}, "strategy is not for action group"),
    ("cell", {"action": "group", "itemIds": ["pl-gone"]}, "There is no pl-gone"),
    ("cell", {"action": "group"}, "needs itemIds"),
    ("cell", {"strategy": "u", "placementIds": ["pl-mill-1", "pl-mill-2"], "name": "Cell"}, "name is for action group"),
    ("cell", {"action": "ungroup", "zoneId": "zn-ws-1"}, "is a zone, not a manufacturing cell"),
    ("cell", {"action": "ungroup", "zoneId": "zn-gone"}, "There is no zone zn-gone"),
    ("cell", {"action": "ungroup"}, "needs zoneId"),
    ("cell", {"action": "ungroup", "zoneId": "zn-cell-1", "itemIds": ["pl-mill-1"]}, "itemIds is not for action"),
])
def test_what_cannot_be_done_says_why(tool, arguments, words):
    with pytest.raises(PatternError, match=re.escape(words)):
        (stack if tool == "stack" else cell)(arguments)


# ---------------------------------------------------------------- registration

def test_the_tools_are_registered_with_closed_schemas_labels_and_rules():
    specs = {spec["name"]: spec for spec in gateway_tool_specs()}
    for name in (ss.TOOL, sp.CELL_TOOL):
        Draft202012Validator.check_schema(specs[name]["input_schema"])
        assert specs[name]["input_schema"]["additionalProperties"] is False
    for arguments, _, _ in STACKS:
        Draft202012Validator(specs[ss.TOOL]["input_schema"]).validate(arguments)
    for arguments, _ in GROUPS:
        Draft202012Validator(specs[sp.CELL_TOOL]["input_schema"]).validate(arguments)
    assert not Draft202012Validator(specs[sp.CELL_TOOL]["input_schema"]).is_valid(
        {"action": "group", "itemIds": ["pl-a"], "prefix": "A 1"})
    assert "call plan_facility_stack" in pilot.EDIT_INSTRUCTIONS
    assert "plan_facility_cell with action group or ungroup" in pilot.EDIT_INSTRUCTIONS
    layout, catalog = fixture()
    names = progress.LayoutNames(layout, catalog)
    describe = lambda tool, arguments: progress.describe(tool, arguments, names)  # noqa: E731
    assert describe(ss.TOOL, {"mode": "stack", "placementId": "pl-box-1", "count": 4})["running"] == \
        "Planning a stack of 4 from Box 1"
    assert describe(ss.TOOL, {"mode": "surface", "supportId": "pl-desk-1", "itemIds": ["pl-tool-1", "pl-tool-2"]})[
        "done"] == "Planned Tool 1 and Tool 2 on Desk 1"
    assert describe(sp.CELL_TOOL, {"action": "group", "itemIds": ["pl-mill-1", "pl-mill-2"]})["running"] == \
        "Planning a cell around Mill 1 and Mill 2"
    assert describe(sp.CELL_TOOL, {"action": "ungroup", "zoneId": "zn-cell-1"})["failed"] == \
        "Couldn't plan the ungrouping of Mill Cell M01"


# ---------------------------------------------------------------- the whole path

@pytest.fixture
def factory(tmp_path, monkeypatch):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    catalog = list(host.agent_runtime.asset_catalog_provider(principal, LOCAL_SITE_ID))
    revision = {record["assetId"]: record["assetDefinitionRevision"] for record in catalog}
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        {"op": "place_asset", "placement": placed(
            f"pl-{name}", asset, revision[asset], x, z, label)} for name, asset, x, z, label in (
            ("bench-a", "asset-workbench", 5, 5, "Bench A"), ("bench-b", "asset-workbench", 5, 12, "Bench B"),
            ("mill-a", "asset-cnc-mill", 20, 5, "Mill A"), ("mill-b", "asset-cnc-mill", 26, 5, "Mill B"),
            ("rack", "asset-pallet-rack", 5, 25, "Rack"))] + [
        # Once a layout has a zone, every item must stand in one: the shop floor holds them all.
        {"op": "add_zone", "zone": {"zoneType": "staging", "label": "Shop floor", "floorElevation": 0, "anchors": [],
                                    "evidence": [], "boundary": [{"x": 0, "z": 0}, {"x": 40, "z": 0},
                                                                 {"x": 40, "z": 40}, {"x": 0, "z": 40}]}}])
    try:
        yield host
    finally:
        host.close()


def run(host, tool, arguments, turn):
    """One Sage turn: plan, stage, and the user's approval in the review; returns the plan and the saved layout."""
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
    assert staged["data"]["validation"]["introduced"]["spatial"]["errorCount"] == 0, staged["data"]["validation"]
    proposal_id = staged["data"]["proposalId"]
    binding = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)[
        "alternative"]["transactionBinding"]
    direct = staged["data"]["approvalRequired"] is False
    approval = host.service.approve_layout_proposal(
        principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding, session_id="stack-session",
        idempotency_key=f"stack-turn-{turn}", explicit_approval=not direct,
        authorization_mode="direct" if direct else "explicit", direct_consent=direct)
    host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"], binding,
                                       session_id="stack-session", idempotency_key=f"stack-turn-{turn}")
    return planned["data"], staged["data"], host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)[
        "layout"]


def test_a_stack_a_cell_and_its_ungroup_are_staged_applied_and_saved(factory):
    planned, staged, layout = run(factory, ss.TOOL, {"mode": "stack", "placementId": "pl-bench-b", "count": 3}, "s")
    assert planned["package"] == {"packageId": "stack-1", "operations": 3}
    # Apply directly: a planned stack without findings applies without a review (live check, 2026-11-02).
    assert staged["approvalRequired"] is False, staged["directApplyPolicy"]
    stacked = [item for item in layout["placements"] if (item.get("snapRelationship") or {}).get("family")
               == "vertical_stack"]
    assert len(stacked) == 3 and sorted(item["snapRelationship"]["level"] for item in stacked) == [0, 1, 2]
    planned, staged, layout = run(factory, sp.CELL_TOOL, {"action": "group", "itemIds": ["pl-mill-a", "pl-mill-b"],
                                                          "name": "Machining", "prefix": "M"}, "g")
    assert staged["approvalRequired"] is False, staged["directApplyPolicy"]
    zone = next(item for item in layout["zones"] if item["label"] == "Machining M01")
    assert zone["extensions"]["cellGroup"]["autoNumber"]["sequence"] == 1
    planned, staged, layout = run(factory, sp.CELL_TOOL, {"action": "ungroup", "zoneId": zone["zoneId"]}, "u")
    assert staged["approvalRequired"] is False, staged["directApplyPolicy"]
    assert all(item["zoneId"] != zone["zoneId"] for item in layout["zones"])
    assert {"pl-mill-a", "pl-mill-b"} <= {item["placementId"] for item in layout["placements"]}


def test_items_put_on_a_published_surface_are_staged_applied_and_saved(factory):
    """The starter library publishes no surface: the host's pallet rack gets a shelf, as a published model has
    (the planner and the server's check both read it)."""
    shelf = [{**WORKTOP, "surfaceId": "shelf-1", "label": "First shelf",
              "localFrame": {**WORKTOP["localFrame"], "origin": {"x": 0, "y": 1.2, "z": 0}},
              "bounds": {"minimumX": -1.3, "maximumX": 1.3, "minimumZ": -0.5, "maximumZ": 0.5}}]
    entries = [factory._catalog["asset-pallet-rack"], *(entry for (asset, _), entry in factory._asset_versions.items()
                                                        if asset == "asset-pallet-rack")]
    for entry in entries:
        entry["supportSurfaces"] = deepcopy(shelf)
        entry["definition"]["supportSurfaces"] = deepcopy(shelf)
    planned, staged, layout = run(factory, ss.TOOL, {"mode": "surface", "supportId": "pl-rack",
                                                     "itemIds": ["pl-bench-b"]}, "surface")
    assert staged["approvalRequired"] is False, staged["directApplyPolicy"]
    assert planned["package"]["packageId"] == "stack-1" and planned["surface"] == "shelf-1"
    moved = next(item for item in layout["placements"] if item["placementId"] == "pl-bench-b")
    assert moved["snapRelationship"]["supportPlacementId"] == "pl-rack"
    assert moved["transform"]["position"]["y"] == pytest.approx(1.2)


def test_a_refusal_reaches_sage_as_a_plain_reason(factory):
    principal = factory.principal()
    saved = factory.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(factory.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="refusal")
    refused = asyncio.run(gateway.call(ss.TOOL, {"mode": "surface", "supportId": "pl-mill-a",
                                                 "itemIds": ["pl-bench-a"]}))
    assert refused["error"]["code"] == "layout_pattern_refused"
    assert "Mill A (pl-mill-a) has no published surface" in refused["error"]["message"]
    assert gateway.packages == {}
