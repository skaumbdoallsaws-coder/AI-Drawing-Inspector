"""The planned site's paint: its own review after the design is saved (site_paint.py, the user's option A)."""
from hashlib import sha256
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime.progress import SIMPLE
from ai_inspector.codex_runtime.site_tools import NAMES, read_site, tool_specs
from ai_inspector.facility_layout.errors import FacilityConflictError, FacilityValidationError
from ai_inspector.facility_layout.proposal_components import validate_proposal_components
from ai_inspector.facility_layout.site_interior import RACK_ASSET, RACK_FINISH
from ai_inspector.facility_layout.site_paint import PaintError, plan_paint
from ai_inspector.facility_layout.site_parking import CAR_ASSETS, PAINT_KEY, TRIM_KEY, paint_for
from ai_inspector.facility_layout.site_trucks import TRUCK_ASSET, TRUCK_FINISH

CAR = CAR_ASSETS[0]
ALL = {"trucks": {"cabColor": "blue", "containerColor": "white", "chassisColor": "dark grey"}, "racks": {"uprightColor": "deep blue", "beamColor": "orange"}, "cars": {}}  # the colours the planner used to choose by itself, now named in the prompt
RACK_KEYS = [row["key"] for row in RACK_FINISH["overrides"]]
SLOTS = {TRUCK_ASSET: [row["key"] for row in TRUCK_FINISH["overrides"]], CAR: [PAINT_KEY, TRIM_KEY, "p:world/APEX%20glass#0"],
         RACK_ASSET: RACK_KEYS[:-1]}  # this rack visual lacks the last planned part


def placement(placement_id, asset_id):
    return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": "r-" + asset_id}


def site_layout():
    return {"placements": [placement("pl-truck-court-receiving-1", TRUCK_ASSET), placement("pl-truck-court-shipping-1", TRUCK_ASSET),
                           placement("pl-car-park-001", CAR), placement("pl-car-park-002", CAR), placement("pl-car-park-003", CAR),
                           placement("pl-racks-01a-1", RACK_ASSET), placement("pl-racks-01a-2", RACK_ASSET),
                           placement("pl-forklift-1", "asset-forklift")]}


def fingerprint(asset_id):
    return sha256(asset_id.encode()).hexdigest()


def inventory_for(layout, calls):
    assets = {p["placementId"]: p["assetId"] for p in layout["placements"]}

    def inventory(placement_id, representation):
        calls.append((placement_id, representation))
        asset = assets[placement_id]
        return {"visualSha256": fingerprint(asset), "slots": [{"key": key} for key in SLOTS[asset]]}
    return inventory


def test_the_saved_trucks_pickups_and_racks_are_painted_with_each_visuals_fingerprint():
    layout, calls = site_layout(), []
    plan = plan_paint(layout, inventory_for(layout, calls), ALL)
    ops = {op["placementId"]: op for op in plan["operations"]}
    assert plan["available"] and plan["painted"] == {"trucks": 2, "cars": 3, "racks": 2}
    assert "pl-forklift-1" not in ops and len(calls) == 3  # each visual is inspected once
    assert all(op["op"] == "set_component_materials" for op in ops.values())
    assert ops["pl-truck-court-shipping-1"] == {"op": "set_component_materials", "placementId": "pl-truck-court-shipping-1",
                                                 "materials": TRUCK_FINISH, "visualSha256": fingerprint(TRUCK_ASSET)}
    cars = [ops[f"pl-car-park-00{n}"]["materials"] for n in (1, 2, 3)]
    assert cars == [paint_for(0), paint_for(1), paint_for(2)]  # the car park's order, everyday colours
    assert len({next(o["color"] for o in c["overrides"] if o["key"] == PAINT_KEY) for c in cars}) == 3
    assert all(next(o["color"] for o in c["overrides"] if o["key"] == TRIM_KEY) == "#b4b9be" for c in cars)
    rack = ops["pl-racks-01a-2"]["materials"]["overrides"]
    assert [row["key"] for row in rack] == RACK_KEYS[:-1]  # only parts this visual has


def test_painting_again_finds_nothing_and_kinds_limit_the_paint():
    layout = site_layout()
    for op in plan_paint(layout, inventory_for(layout, []), ALL)["operations"]:  # as if the review was approved
        next(p for p in layout["placements"] if p["placementId"] == op["placementId"])["componentMaterials"] = op["materials"]
    again = plan_paint(layout, inventory_for(layout, []), ALL)
    assert not again["available"] and again["operations"] == []
    assert again["alreadyPainted"] == {"trucks": 2, "cars": 3, "racks": 2} and "reason" in again
    fresh = site_layout()
    trucks = plan_paint(fresh, inventory_for(fresh, []), {"trucks": ALL["trucks"]})
    assert trucks["painted"] == {"trucks": 2} and len(trucks["operations"]) == 2


def test_sage_has_the_paint_tool():
    spec = next(item for item in tool_specs() if item["name"] == "plan_design_paint")
    assert "plan_design_paint" in NAMES and {"walls", "pavementLogo", "trucks", "racks", "cars"} == set(
        spec["input_schema"]["properties"])
    assert "plan_design_paint" in SIMPLE
    assert read_site(site_layout(), "plan_design_paint", {})["available"] is False  # no inventory, no paint


def test_part_colours_on_a_new_rack_row_need_a_saved_visual_like_any_new_placement():
    for op in ("place_asset", "place_asset_array"):
        with pytest.raises(FacilityValidationError, match="Place and save"):
            validate_proposal_components(SimpleNamespace(), None, "site-a", "fl-a", "rev-1",
                                         [{"op": op, "placement": {"componentMaterials": RACK_FINISH}}])


def test_each_distinct_visual_is_verified_once_and_every_edit_against_it():
    layout = site_layout()
    reference = {"siteId": "site-a", "layoutId": "fl-a", "revision": "rev-1"}
    calls = []

    def resolver(principal, binding, placement_id, representation):
        calls.append(placement_id)
        asset = next(p["assetId"] for p in layout["placements"] if p["placementId"] == placement_id)
        return {"identity": dict(binding), "placementId": placement_id, "assetId": asset,
                "assetDefinitionRevision": "r-" + asset, "representation": representation,
                "visualSha256": fingerprint(asset), "slots": [{"key": key} for key in SLOTS[asset]]}
    service = SimpleNamespace(get_layout=lambda *args: {"revision": "rev-1", "layout": layout},
                              component_inventory_resolver=resolver)
    ops = plan_paint(layout, inventory_for(layout, []), ALL)["operations"]
    proofs = validate_proposal_components(service, None, "site-a", "fl-a", "rev-1", ops)
    assert len(proofs) == 7 and len(calls) == 3 and reference["revision"] == "rev-1"
    wrong = [dict(ops[-1], visualSha256="0" * 64)] + ops[:-1]  # a stale fingerprint on one rack
    with pytest.raises(FacilityConflictError, match="visual bytes have changed"):
        validate_proposal_components(service, None, "site-a", "fl-a", "rev-1", ops[:-1] + wrong[:1])


def test_only_what_the_prompt_names_is_painted_in_its_colours():
    # The user (2026-10-24): "paint in our colors? I don't like that": no logo, band or yard mark unless asked.
    layout = site_layout()
    plan = plan_paint(layout, inventory_for(layout, []), {"trucks": {"cabColor": "red", "containerColor": "#123456",
                                                                     "chassisColor": "Dark Gray"}, "cars": {"colors": ["navy"]}})
    assert plan["painted"] == {"trucks": 2, "cars": 3} and "racks" not in plan["painted"]
    truck = next(op for op in plan["operations"] if op["placementId"] == "pl-truck-court-receiving-1")["materials"]
    assert {row["color"] for row in truck["overrides"]} == {"#b3261e", "#123456", "#2b2f33"}
    cars = [op["materials"] for op in plan["operations"] if op["placementId"].startswith("pl-car-park-")]
    assert all(next(o["color"] for o in c["overrides"] if o["key"] == PAINT_KEY) == "#1f3a6b" for c in cars)
    assert plan["look"] == {"trucks": "red cabs, #123456 containers, dark grey chassis", "cars": "navy"}
    with pytest.raises(PaintError, match="Unknown colour 'sunset'"):
        plan_paint(layout, inventory_for(layout, []), {"racks": {"uprightColor": "sunset", "beamColor": "orange"}})
    with pytest.raises(PaintError, match="Say what to paint"):
        plan_paint(layout, inventory_for(layout, []), {})
