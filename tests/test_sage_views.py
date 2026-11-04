"""Sage shows the user an area in 3D (docs/sage-basic-shapes-plan.md, Part B): SV0's framing (sage_views.py) and the
live view of SV3b, as far as the server goes: show_facility_views in the gateway, its step label, the camera view the
done step hands to the app window, "the last change" from the window's receipts, and the pilot's rules.

The framing cases are a small hall: a 40 x 30 m roof deck at 8 m with a light row at 6 m (so the camera stays under
5.5 m inside), a 2 m machine with a 6 m rack 3 m south of it, and a machine outside.
"""
import asyncio
from copy import deepcopy
import math

import pytest

from ai_inspector.codex_runtime import pilot, progress
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import tool_specs as gateway_tool_specs
from ai_inspector.facility_layout import sage_views as sv
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost


def record(asset_id, low, high, tags=(), category="Equipment"):
    return {"assetId": asset_id, "assetDefinitionRevision": "r1", "category": category,
            "definition": {"tags": list(tags), "geometry": {"aabb": {
                "minimum": dict(zip("xyz", low)), "maximum": dict(zip("xyz", high))}}}}


CATALOG = [record("asset-machine", (-1, 0, -1), (1, 2, 1)),
           record("asset-rack", (-3, 0, -0.5), (3, 6, 0.5)),
           record("asset-roof", (-20, 7.9, -15), (20, 8.0, 15), ("roof", "building", "overhead", "roof-sheeting"),
                  "Building Structures"),
           record("asset-light-row", (-18, 6.0, -0.2), (18, 6.5, 0.2), ("overhead", "lighting"),
                  "Building Structures")]


def placed(placement_id, asset_id, x, z, label=None):
    return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": "r1",
            "transform": {"position": {"x": x, "y": 0, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1}, "metadata": {"instanceLabel": label or placement_id}}


def zone(zone_id, label, x0, z0, x1, z1):
    return {"zoneId": zone_id, "label": label, "zoneType": "workcell", "floorElevation": 0.0,
            "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]}


def hall(rack=True):
    placements = [placed("pl-roof", "asset-roof", 20, 15, "Roof deck"),
                  placed("pl-lights", "asset-light-row", 20, 22, "Light row"),
                  placed("pl-machine", "asset-machine", 20, 18, "Machine"),
                  placed("pl-outside", "asset-machine", 60, 15, "Yard machine")]
    if rack:
        placements.append(placed("pl-rack", "asset-rack", 20, 15, "Rack"))
    return {"placements": placements,
            "zones": [zone("zn-cell", "Assembly Cell A06", 5, 5, 35, 25), zone("zn-yard", "Yard", 50, 5, 70, 25)],
            "floorMarkings": [{"markingId": "fm-bay", "label": "Kit cart bay", "width": 2, "depth": 2,
                               "transform": {"position": {"x": 26, "y": 0, "z": 12}, "rotationDegrees": 0}}]}


def frame(ids, layout=None, **options):
    return sv.frame_views(layout or hall(), CATALOG, ids, **options)


def test_a_name_the_user_said_resolves_to_ids_whole_name_first_then_every_word_zones_first():
    layout = hall()
    assert sv.resolve_query(layout, "Assembly Cell A06") == (["zn-cell"], "name")
    assert sv.resolve_query(layout, "the  kit cart bay") == (["fm-bay"], "name")      # case, spacing, "the"
    assert sv.resolve_query(layout, "yard machine") == (["pl-outside"], "name")
    assert sv.resolve_query(layout, "A06") == (["zn-cell"], "words")                  # a zone brings its contents
    assert sv.resolve_query(layout, "cart bays") == (["fm-bay"], "words")             # plurals as singulars
    layout["zones"] += [zone("zn-d1", "Dock door S1", 0, 30, 4, 34), zone("zn-d2", "Dock door S2", 6, 30, 10, 34)]
    assert sv.resolve_query(layout, "the dock doors") == (["zn-d1", "zn-d2"], "words")
    for query, message in (("crane", "Nothing in the saved layout"), ("the", "Give the name")):
        with pytest.raises(ValueError, match=message):
            sv.resolve_query(layout, query)
    layout["placements"] += [placed(f"pl-bin-{index}", "asset-machine", 1, 1, f"Bin {index}") for index in range(241)]
    with pytest.raises(ValueError, match="241 items match"):
        sv.resolve_query(layout, "bin")


def test_a_view_looks_at_the_middle_a_third_of_the_way_up_from_the_south_under_the_roof():
    view, = frame(["pl-machine"], hall(rack=False))["views"]
    camera = view["camera"]
    assert view["label"] == "Assembly Cell A06"          # named after its zone
    assert camera["target"] == {"x": 20.0, "y": 0.67, "z": 18.0} and camera["fov"] == 50
    assert view["from"] == "south" and view["elevationDegrees"] == 30 and view["roofHidden"] is False
    position = camera["position"]
    assert position["x"] == 20.0 and position["z"] < 18 and position["y"] <= 5.5  # under the lights, less 0.5 m
    rise = math.degrees(math.atan2(position["y"] - 0.67, 18 - position["z"]))
    assert abs(rise - 30) < 0.1
    assert view["ids"] == ["pl-machine"] and view["highView"] is False


def test_a_view_blocked_by_something_taller_than_the_sight_line_is_taken_from_the_next_side():
    open_view, = frame(["pl-machine"], hall(rack=False))["views"]
    assert open_view["from"] == "south"
    view, = frame(["pl-machine"])["views"]
    # the rack (6 m tall, 6 m wide, 3 m south of the machine) is what the south view, and the south-east and
    # south-west ones beside it, would look through; the east one is clear
    assert view["from"] == "east" and view["roofHidden"] is False
    camera, target = view["camera"]["position"], view["camera"]["target"]
    assert camera["x"] > target["x"] and camera["z"] == target["z"] == 18.0


def test_a_view_whose_near_edge_hides_behind_something_lower_than_the_line_to_its_middle_is_taken_elsewhere():
    """2026-11-03, Factory 02's Packing P01: the line to the middle of the area cleared the hall's south wall, but the
    wall hid the near third of the shot. A 1.5 m wall 2 m south of the machine: under the line to the machine's
    middle (1.8 m there), over the lines to its near corners on the floor (0.9 m there)."""
    layout = hall(rack=False)
    layout["placements"].append(placed("pl-wall", "asset-low-wall", 20, 16, "Low wall"))
    catalog = CATALOG + [record("asset-low-wall", (-6, 0, -0.1), (6, 1.5, 0.1))]
    view, = sv.frame_views(layout, catalog, ["pl-machine"])["views"]
    assert view["from"] not in ("south", "south-east", "south-west") and view["highView"] is False
    assert view["roofHidden"] is False


def test_a_large_area_is_seen_down_through_the_roof_with_the_roof_hidden():
    view, = frame(["zn-cell"])["views"]
    assert view["roofHidden"] is True and view["camera"]["position"]["y"] > 5.5
    assert view["label"] == "Assembly Cell A06"
    assert set(view["ids"]) == {"zn-cell", "pl-machine", "pl-rack", "fm-bay"}  # what stands in it, not the roof
    assert view["size"] == {"width": 30.0, "depth": 20.0, "height": 6.0}


def test_outside_the_building_the_roof_stays_and_the_height_is_free():
    view, = frame(["pl-outside"])["views"]
    assert view["label"] == "Yard" and view["from"] == "south" and view["roofHidden"] is False


def test_items_far_apart_are_separate_views_largest_first_and_the_rest_are_named():
    result = frame(["pl-outside", "pl-machine", "fm-bay"])
    assert [view["label"] for view in result["views"]] == ["Assembly Cell A06", "Yard"]
    assert result["views"][0]["ids"] == ["fm-bay", "pl-machine"]   # 6 m apart: one view
    one = frame(["pl-outside", "pl-machine"], max_views=1)
    assert len(one["views"]) == 1 and one["notShown"] == ["Yard"]


def test_the_same_layout_and_ids_always_give_the_same_views():
    ids = ["pl-outside", "pl-machine", "zn-cell", "fm-bay"]
    assert frame(ids) == frame(list(reversed(ids))) == frame(ids + ids[:1])


def test_unknown_ids_are_listed_and_nothing_known_is_refused():
    result = frame(["pl-machine", "pl-gone"])
    assert result["notFound"] == ["pl-gone"] and len(result["views"]) == 1
    with pytest.raises(ValueError, match="None of those ids"):
        frame(["pl-gone", "rt-route"])


def test_the_last_change_is_what_its_receipt_made_or_changed_and_is_still_there():
    receipt = {"payload": {"operationResult": {"createdIds": ["pl-new", "pl-machine"],
                                               "affectedIds": ["pl-machine", "pl-removed"]}}}
    assert sv.changed_ids(receipt) == ["pl-new", "pl-machine", "pl-removed"]
    assert sv.shown_ids(hall(), sv.changed_ids(receipt)) == ["pl-machine"]


def test_sage_is_told_whether_the_view_moved():
    views = frame(["zn-cell"])["views"]
    moved = sv.live_view(views, True)
    assert moved["moves"] is True and moved["to"] == "Assembly Cell A06"
    assert "Back" in moved["say"] and "roof is hidden" in moved["say"]
    still = sv.live_view(views, False)
    assert still["moves"] is False and "nothing moved" in still["say"]


# ---------------------------------------------------------------- the gateway, the step and the pilot

def test_the_tool_is_registered_with_a_closed_schema_a_label_and_the_only_when_asked_rule():
    spec = next(item for item in gateway_tool_specs() if item["name"] == sv.TOOL)
    assert spec["input_schema"]["additionalProperties"] is False
    assert "only when the user asks" in spec["description"] and "never describe how they look" in spec["description"]
    names = progress.LayoutNames({"zones": [{"zoneId": "zn-a06", "label": "Assembly Cell A06"}]})
    assert progress.describe(sv.TOOL, {"targetIds": ["zn-a06"]}, names)["done"] == "Found a view of Assembly Cell A06"
    assert progress.describe(sv.TOOL, {"target": "last_change"})["running"] == "Finding a view of the last change"
    assert progress.describe(sv.TOOL, {"query": "R03 robot"})["done"] == 'Found a view of "R03 robot"'
    assert spec["input_schema"]["properties"]["query"]["maxLength"] == 120
    for text in (pilot.INSTRUCTIONS, pilot.EDIT_INSTRUCTIONS):
        assert "call show_facility_views" in text and "Never call it unasked" in text
        assert "query with what they named" in text and "Do not look it up first" in text
    assert pilot.app_window_open({"facility_layout_live_state": {"viewportMode": "plan", "dirty": False}})
    assert not pilot.app_window_open({}) and not pilot.app_window_open({"facility_layout_live_state": {}})


def test_sage_looks_at_its_shots_first_fixes_only_its_own_work_and_at_most_twice_sv4():
    """SV4 (docs/sage-basic-shapes-plan.md), built to option 1: Sage's edits are saved after its reply, so a fix
    spans turns: no second set of shots in the same turn (user to confirm)."""
    for text in (pilot.INSTRUCTIONS, pilot.EDIT_INSTRUCTIONS):
        assert "look at the contact sheet before you reply" in text
        for check in ("overlaps", "items facing the wrong way", "things in an aisle or walkway",
                      "duplicates of what was already there", "anything floating or buried"):
            assert check in text, check
    edit, read_only = pilot.EDIT_INSTRUCTIONS, pilot.INSTRUCTIONS
    assert "Your own changes from this conversation that look wrong: fix them in this turn with the edit tools" in edit
    assert "(they follow\n  the user's apply mode), and say what looked wrong and what you changed." in edit
    assert "Do not call show_facility_views again\n  this turn" in edit
    assert "take the shots again and look once more" in edit
    assert "At most two fix rounds for the same problem" in edit and "show the shots and ask" in edit
    assert "Anything you did not change in this conversation: report it and offer a fix; never change it unasked" \
        in edit
    assert "Report what\nlooks wrong and offer a fix; this pilot cannot make it." in read_only
    assert "fix them in this turn" not in read_only
    spec = next(item for item in gateway_tool_specs() if item["name"] == sv.TOOL)
    assert "The tool only reads: make any fix with the edit tools." in spec["description"]


def test_sage_may_remove_only_its_own_accidental_duplicate_unasked_and_says_so_sv4_review():
    """SV4 review: fixing a duplicate Sage added means deleting it, which the general rule forbids unasked. Both
    places name the same single exception, under the user's apply mode, and Sage must say so; anything else still
    needs a specific request. The read-only pilot deletes nothing."""
    edit = " ".join(pilot.EDIT_INSTRUCTIONS.split())
    read_only = " ".join(pilot.INSTRUCTIONS.split())
    duplicate = "an accidental duplicate you added yourself in this conversation"
    terms = "(it follows the user's apply mode); say in your reply that you removed it."
    assert edit.count(duplicate) == 2 and edit.count(terms) == 2, "the shots rules and the deletion rule agree"
    assert ("Removing " + duplicate + " is the one deletion you may stage without being asked " + terms) in edit
    assert ("Deletion must be specifically requested. The only exception: removing " + duplicate + " " + terms
            + " Anything else still needs a specific request. Summarize removals in the preview.") in edit
    assert "Anything you did not change in this conversation: report it and offer a fix; never change it unasked"         in edit
    assert duplicate not in read_only


@pytest.fixture
def host(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    catalog = {item["assetId"]: item for item in host.agent_runtime.asset_catalog_provider(principal, LOCAL_SITE_ID)}
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [
        {"op": "add_zone", "zone": {**zone("zn-a06", "Assembly Cell A06", 14, 8, 38, 26), "anchors": [],
                                    "evidence": []}},
        {"op": "place_asset", "placement": {
            **placed("pl-old-1", "asset-cnc-mill", 20, 14, "Old mill 1"),
            "assetDefinitionRevision": catalog["asset-cnc-mill"]["assetDefinitionRevision"],
            "positionMode": "manual", "snapRelationship": None}}])
    try:
        yield host
    finally:
        host.close()


def gateway_for(host, turn, *, window=True, receipts=()):
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(host.agent_runtime, principal, {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=turn)
    gateway.edit_mode = "direct"
    gateway.app_window, gateway.receipt_ids = window, list(receipts)
    return gateway, saved


def test_show_facility_views_frames_the_zone_and_the_done_step_moves_the_open_window(host):
    gateway, saved = gateway_for(host, "show-turn")
    result = asyncio.run(gateway.call(sv.TOOL, {"targetIds": ["zn-a06"]}))
    assert result["ok"], result
    data = result["data"]
    view = data["views"][0]
    assert view["label"] == "Assembly Cell A06" and "pl-old-1" in view["ids"]
    assert data["liveView"]["moves"] is True and data["readOnly"] is True and data["pictures"].startswith("None")
    show = progress.view_show(sv.TOOL, {"targetIds": ["zn-a06"]}, data)
    assert show == {"cameraView": {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID,
                                   "revision": saved["revision"], "label": "Assembly Cell A06",
                                   "camera": view["camera"], "from": view["from"],
                                   "roofHidden": view["roofHidden"]}}
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved  # it only reads

    closed, _ = gateway_for(host, "show-closed", window=False)
    data = asyncio.run(closed.call(sv.TOOL, {"targetIds": ["zn-a06"]}))["data"]
    assert data["liveView"]["moves"] is False and progress.view_show(sv.TOOL, {}, data) is None


def test_show_facility_views_takes_the_name_the_user_said(host):
    """"show me the R03 robot" took 7 steps live (look-ups, one refused); with query it is one call."""
    gateway, _ = gateway_for(host, "query-turn")
    result = asyncio.run(gateway.call(sv.TOOL, {"query": "old mill 1"}))
    assert result["ok"], result
    assert result["data"]["views"][0]["ids"] == ["pl-old-1"]
    assert result["data"]["query"] == {"text": "old mill 1", "matchedBy": "name", "idCount": 1}
    unknown = asyncio.run(gateway.call(sv.TOOL, {"query": "paint booth"}))
    assert unknown["error"]["code"] == "show_views_refused" and "Nothing in the saved layout" in unknown["error"][
        "message"]
    both = asyncio.run(gateway.call(sv.TOOL, {"query": "old mill 1", "targetIds": ["zn-a06"]}))
    assert both["error"]["code"] == "show_views_refused" and "one of" in both["error"]["message"]


def apply_directly(host, operations, turn):
    gateway, _ = gateway_for(host, turn)
    staged = asyncio.run(gateway.call("preview_facility_operations", {"operations": operations}))
    assert staged["ok"], staged
    service, principal = host.service, host.principal()
    proposal_id = staged["data"]["proposalId"]
    binding = service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)[
        "alternative"]["transactionBinding"]
    approval = service.approve_layout_proposal(
        principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding, session_id="views-session",
        idempotency_key=f"views-{turn}", explicit_approval=False, authorization_mode="direct", direct_consent=True)
    return service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                                         binding, session_id="views-session", idempotency_key=f"views-{turn}")


def test_the_last_change_shows_what_the_windows_last_saved_change_made(host):
    nothing, _ = gateway_for(host, "none-turn")
    refused = asyncio.run(nothing.call(sv.TOOL, {"target": "last_change"}))
    assert refused["error"]["code"] == "show_views_refused" and "no last change" in refused["error"]["message"]
    layout = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
    moved = deepcopy(next(item for item in layout["placements"] if item["placementId"] == "pl-old-1"))
    assert moved["transform"]["position"] == {"x": 20, "y": 0, "z": 14}
    applied = apply_directly(host, [{"op": "move_placement", "placementId": "pl-old-1",
                                     "position": {"x": 30, "y": 0, "z": 20}}], "move-turn")
    receipt = applied["receipt"]["receiptId"]
    assert sv.changed_ids(applied["receipt"]) == ["pl-old-1"]

    gateway, _ = gateway_for(host, "last-turn", receipts=["rcpt-older", receipt])
    result = asyncio.run(gateway.call(sv.TOOL, {"target": "last_change"}))
    assert result["ok"], result
    view = result["data"]["views"][0]
    assert view["ids"] == ["pl-old-1"] and result["data"]["lastChange"] is True
    assert view["camera"]["target"]["x"] == 30.0 and view["camera"]["target"]["z"] == 20.0
    both = asyncio.run(gateway.call(sv.TOOL, {"target": "last_change", "targetIds": ["zn-a06"]}))
    assert both["error"]["code"] == "show_views_refused"


def test_a_window_with_no_change_of_its_own_shows_the_layouts_newest_receipt(host):
    """After an app restart, or in a new window, "show me what you changed" uses the layout's last saved change on
    the server (main session's live check, 2026-11-02: it found nothing)."""
    principal = host.principal()
    first = apply_directly(host, [{"op": "move_placement", "placementId": "pl-old-1",
                                   "position": {"x": 30, "y": 0, "z": 20}}], "move-1")
    second = apply_directly(host, [{"op": "move_placement", "placementId": "pl-old-1",
                                    "position": {"x": 33, "y": 0, "z": 21}}], "move-2")
    assert first["receipt"]["receiptId"] != second["receipt"]["receiptId"]
    newest = host.service.latest_layout_receipt(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    assert newest["receiptId"] == second["receipt"]["receiptId"]

    restarted, _ = gateway_for(host, "restart-turn")  # no receipts from this window
    result = asyncio.run(restarted.call(sv.TOOL, {"target": "last_change"}))
    assert result["ok"], result
    view = result["data"]["views"][0]
    assert view["ids"] == ["pl-old-1"] and view["camera"]["target"]["x"] == 33.0

    # Bound to its own layout: another layout's target finds none of these.
    from ai_inspector.facility_layout.transaction_adapter import facility_transaction_target
    store = host.service.transaction_runtime.kernel.receipt_store
    other = facility_transaction_target(tenant_id=principal.tenant_id, site_id=LOCAL_SITE_ID, layout_id="fl-other")
    assert store.latest_receipt_for(other) is None
    own = facility_transaction_target(tenant_id=principal.tenant_id, site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID)
    assert store.latest_receipt_for(own).receipt_id == second["receipt"]["receiptId"]

    # The item it changed is gone since: nothing left to show, and Sage is told so.
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
                                  [{"op": "delete_placement", "placementId": "pl-old-1"}])
    gone = asyncio.run(gateway_for(host, "gone-turn")[0].call(sv.TOOL, {"target": "last_change"}))
    assert gone["error"]["code"] == "show_views_refused" and "nothing to show" in gone["error"]["message"]
