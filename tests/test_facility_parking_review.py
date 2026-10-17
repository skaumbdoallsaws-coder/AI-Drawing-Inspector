import asyncio
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.facility_layout import parking_review as review
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.facility_layout.errors import FacilityValidationError
from tests.test_facility_operation_proposals import context, current, propose, approve, apply


def zone():
    return {"zoneId":"zn-parking", "zoneType":"workcell", "label":"Visitor Parking",
        "boundary":[{"x":0,"z":0},{"x":30,"z":0},{"x":30,"z":20},{"x":0,"z":20}],
        "floorElevation":0, "anchors":[], "evidence":[]}


def bay(index):
    return {"markingId":f"fm-bay-{index}", "label":f"Bay {index}", "markingType":"parking_box", "semanticRole":"parking",
        "transform":{"position":{"x":2.5+index*2.5,"y":0,"z":2.5},"rotationDegrees":0},
        "width":2.5, "depth":5, "fillColor":"#ffffff", "strokeColor":"#ffffff", "opacity":1,
        "text":"", "positionMode":"manual", "metadata":{}, "evidence":[]}


def layout():
    return {"zones":[zone()], "floorMarkings":[bay(i) for i in range(10)], "routes":[], "placements":[]}


def route(kind="material", z=8, x1=-2, x2=32):
    return {"routeId":"rt-drive", "routeKind":kind, "label":"Drive aisle", "corridorWidth":6,
        "centerline":[{"x":x1,"y":0,"z":z},{"x":x2,"y":0,"z":z}]}


def result(value, count=10):
    return review.review_parking(value, ["zn-parking"], count)["reviews"][0]


def codes(value):
    return {f["code"] for f in value["findings"]}


def test_ten_spaces_without_aisles_are_not_complete_and_review_is_pure():
    value = layout()
    original = deepcopy(value)
    report = result(value)
    assert report["containedBays"] == 10
    assert report["status"] == "needs_review"
    assert "parking_vehicle_aisle_missing" in codes(report)
    assert "parking_maneuvering_unverified" in codes(report)
    assert value == original


@pytest.mark.parametrize("kind", ["direction_arrow", "floor_text", "solid_line"])
def test_arrows_labels_and_lines_do_not_prove_an_aisle(kind):
    value = layout()
    value["floorMarkings"].append(dict(bay(11), markingType=kind, semanticRole="forklift_lane"))
    assert "parking_vehicle_aisle_missing" in codes(result(value))


def test_pedestrian_route_is_not_vehicle_access():
    value = layout()
    value["routes"] = [route("operator")]
    assert "parking_vehicle_aisle_missing" in codes(result(value))


def test_connected_aisle_records_evidence_without_certifying_turns():
    value = layout()
    value["routes"] = [route()]
    report = result(value)
    assert report["boundaryConnectedComponents"] == 1
    assert report["aisleGeometryIds"] == ["rt-drive"]
    assert not codes(report) & {"parking_vehicle_aisle_missing", "parking_boundary_access_missing", "parking_bay_access_unverified"}
    assert "parking_maneuvering_unverified" in codes(report)
    assert review.review_parking(value, ["zn-parking"])["certified"] is False


def test_isolated_aisle_and_remote_aisle_are_not_access():
    value = layout()
    value["routes"] = [route(x1=1, x2=29)]
    assert "parking_boundary_access_missing" in codes(result(value))
    value["routes"] = [route(z=13)]
    assert "parking_bay_access_unverified" in codes(result(value))


def test_an_aisle_over_the_parking_spaces_is_not_valid_circulation():
    value = layout()
    value["routes"] = [route(z=2.5)]
    assert "parking_aisle_overlaps_bays" in codes(result(value))


def test_capacity_uses_actual_marked_bays_not_label_or_car_count():
    value = layout()
    value["zones"][0]["label"] = "Parking for 50"
    assert "parking_capacity_mismatch" in codes(result(value, 50))
    value["floorMarkings"] = []
    assert "parking_spaces_unrepresented" in codes(result(value))


def test_explicit_bay_geometry_counts_even_when_role_is_decorative():
    value = layout()
    for mark in value["floorMarkings"]:
        mark["semanticRole"] = "decorative"
    assert result(value)["containedBays"] == 10


def test_loose_lines_do_not_establish_bay_capacity():
    value = layout()
    for mark in value["floorMarkings"]:
        mark["markingType"] = "solid_line"
    assert "parking_spaces_unrepresented" in codes(result(value))


def test_removing_last_bay_from_unnamed_zone_still_triggers_review():
    before = layout()
    before["zones"][0]["label"] = "West area"
    after = deepcopy(before)
    after["floorMarkings"] = []
    report = review.review_changed_parking(before, after)
    assert "parking_spaces_unrepresented" in codes(report["reviews"][0])


def test_rotated_and_clipped_bays_use_actual_footprints():
    value = layout()
    value["floorMarkings"] = [bay(0)]
    value["floorMarkings"][0]["transform"]["position"]["x"] = 1.5
    value["floorMarkings"][0]["transform"]["rotationDegrees"] = 90
    report = result(value, 1)
    assert report["containedBays"] == 0
    assert "parking_bays_cross_zone_boundary" in codes(report)


def test_different_elevation_does_not_supply_access():
    value = layout()
    value["routes"] = [route()]
    for point in value["routes"][0]["centerline"]:
        point["y"] = 3
    assert "parking_vehicle_aisle_missing" in codes(result(value))


def test_unrelated_and_cosmetic_edits_do_not_trigger_parking_reviews():
    before, after = layout(), layout()
    after["displayName"] = "Renamed gym"
    after["zones"][0]["extensions"] = {"style":{"fillColor":"#35393E"}}
    assert review.review_changed_parking(before, after) is None
    after["floorMarkings"][0]["width"] = 3
    assert review.review_changed_parking(before, after)["reviews"]


def test_geometry_dependency_missing_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(review.routing, "Polygon", None)
    report = review.review_parking(layout(), ["zn-parking"])
    assert report["status"] == "not_checked" and not report["certified"]


def test_unknown_zone_rejected_and_tool_arguments_bounded():
    with pytest.raises(FacilityValidationError):
        review.review_parking(layout(), ["zn-missing"])
    schema = review.tool_spec()["input_schema"]
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors({"zoneIds":["zn-parking"],"requestedSpaces":0}))
    assert list(Draft202012Validator(schema).iter_errors({"zoneIds":["zn-parking"],"path":"secret"}))


def test_real_preview_reports_missing_aisle_before_approval_and_undo_restores(context):
    before = current(context)
    operations = [{"op":"add_zone","zone":zone()}, *[{"op":"add_floor_marking","floorMarking":bay(i)} for i in range(10)]]
    proposal = propose(context, operations=operations)
    report = proposal["alternative"]["validation"]["functionalDesign"]
    assert "parking_vehicle_aisle_missing" in codes(report["reviews"][0])
    assert current(context) == before and proposal["approvalRequired"]
    saved = apply(context, proposal, approve(context, proposal))
    undo = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    restored = apply(context, undo, approve(context, undo, key="parking-undo"), key="parking-undo")
    expected = deepcopy(before["layout"])
    expected["updatedAt"] = restored["layout"]["updatedAt"]
    assert restored["layout"] == expected


def test_gateway_reads_saved_parking_evidence_and_rejects_stale_scope(context):
    service, principal = context
    proposal = propose(context, operations=[{"op":"add_zone","zone":zone()}])
    saved = apply(context, proposal, approve(context, proposal))
    from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    runtime = type("Runtime", (), {"service":service})()
    ref = {"siteId":LOCAL_SITE_ID,"layoutId":LOCAL_LAYOUT_ID,"revision":saved["revision"]}
    gateway = FacilityEditGateway(runtime, principal, ref, turn_id="parking-read")
    reply = asyncio.run(gateway.call("review_facility_parking", {"zoneIds":["zn-parking"],"requestedSpaces":10}))
    assert reply["ok"] and reply["data"]["readOnly"]
    assert "parking_vehicle_aisle_missing" in codes(reply["data"]["reviews"][0])
    gateway.reference["revision"] = "0"*64
    reply = asyncio.run(gateway.call("review_facility_parking", {"zoneIds":["zn-parking"]}))
    assert reply["error"]["code"] == "codex_document_unavailable"
