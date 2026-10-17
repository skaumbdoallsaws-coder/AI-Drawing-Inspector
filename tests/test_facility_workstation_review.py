import asyncio
from copy import deepcopy
import math

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.facility_layout import workstation_review as review
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.semantic_model import analyze_facility_asset_access
from ai_inspector.facility_layout.spatial import SpatialRecord
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from tests.test_facility_layout_semantic_model import _state
from tests.test_facility_operation_proposals import asset_host, current, propose, approve, apply, _place_review_assets
from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LOCAL_LAYOUT_ID


def codes(report):
    return {f["code"] for f in report["findings"]}


def authored(state, role="operator", side="east", status="authored"):
    state["assets"][0]["facilitySemantics"] = {
        "functionalSides": {role: {"side": side, "evidenceStatus": status}}}


def test_unknown_sides_are_not_guessed_from_labels_or_operator_positions():
    state = _state()
    before = deepcopy(state)
    report = review.review_workstations(state)
    assert "workstation_functional_sides_missing" in codes(report)
    assert "process_sequence_unverified" in codes(report)
    assert report["status"] == "needs_review" and not report["certified"]
    assert state == before
    assert all(not p["access"] for p in report["workstations"])


def test_gaps_are_measured_not_declared_safe():
    report = review.review_workstations(_state(), {"placementIds": ["pl-cnc"]})
    assert report["returnedCount"] == 1
    assert report["workstations"][0]["nearbyFootprintGaps"][0]["distanceMeters"] > 0
    assert not report["certified"]


def test_quaternion_rotates_local_side_and_preserves_legacy_angle():
    state = _state()
    authored(state)
    state["placements"][0]["transform"]["quaternion"] = {"x": 0, "y": math.sqrt(.5), "z": 0, "w": math.sqrt(.5)}
    measured = analyze_facility_asset_access(state, interface_role="operator", scope_ids=["pl-cnc"])["records"][0]
    assert measured["worldFacing"] == {"x": 0.0, "z": -1.0}
    del state["placements"][0]["transform"]["quaternion"]
    state["placements"][0]["transform"]["rotationDegrees"] = 90
    legacy = analyze_facility_asset_access(state, interface_role="operator", scope_ids=["pl-cnc"])["records"][0]
    assert legacy["worldFacing"] == measured["worldFacing"]


@pytest.mark.parametrize("status", ["inferred", "unknown", "unverified"])
def test_unverified_side_does_not_become_verified_geometry(status):
    state = _state()
    authored(state, status=status)
    report = review.review_workstations(state, {"placementIds": ["pl-cnc"]})
    assert "operator" not in report["workstations"][0]["access"]


def test_tilted_machine_is_not_treated_as_planar():
    state = _state()
    authored(state)
    state["placements"][0]["transform"]["quaternion"] = {"x": .7, "y": 0, "z": 0, "w": .7}
    result = analyze_facility_asset_access(state, interface_role="operator", scope_ids=["pl-cnc"])
    assert result["missingFunctionalSidePlacements"][0]["reason"] == "non_planar_orientation"


def test_wall_limits_access_even_without_equipment_collision():
    state = _state()
    authored(state)
    wall = SpatialRecord("wall", "wall-test", "", ((5.5, 2), (5.7, 2), (5.7, 6), (5.5, 6)), 0, 3)
    result = analyze_facility_asset_access(state, interface_role="operator", scope_ids=["pl-cnc"], shell_obstacles=[wall])
    record = result["records"][0]
    assert record["actualOutwardClearanceMeters"] == .5
    assert record["limitingGeometryKind"] == "shell_obstacle"
    assert record["nearestShellObstacle"]["shellFeatureId"] == "wall-test"


def operator(state, x=3):
    person = deepcopy(state["placements"][0])
    person.update(placementId="pl-person", assetId="asset-person", displayName="Operator", category="People",
                  metadata={"machinePlacementId": "pl-cnc"}, facilitySemantics={})
    person["transform"]["position"] = {"x": x, "y": 0, "z": 4}
    person["physicalGeometry"][0]["polygon"] = [{"x": x-.2, "z": 3.8}, {"x": x+.2, "z": 3.8},
                                               {"x": x+.2, "z": 4.2}, {"x": x-.2, "z": 4.2}]
    state["placements"].append(person)
    return person


def test_assigned_operator_on_wrong_side_is_actionable():
    state = _state()
    authored(state)
    operator(state)
    report = review.review_workstations(state, {"placementIds": ["pl-cnc"]})
    assert "operator_wrong_working_side" in codes(report)
    assert "operator_facing_unverified" in codes(report)
    assert all(f.get("nextAction") for f in report["findings"])


def test_authored_avatar_front_can_detect_facing_away():
    state = _state()
    authored(state)
    person = operator(state, x=6)
    person["facilitySemantics"] = {"functionalSides": {"front": {"side": "east", "evidenceStatus": "authored"}}}
    report = review.review_workstations(state, {"placementIds": ["pl-cnc"]})
    assert "operator_facing_away" in codes(report)
    assert "operator_facing_unverified" not in codes(report)


def test_review_checks_each_requested_process_leg():
    state = _state()
    state["routes"] = []
    report = review.review_workstations(state, {"processZoneIds": ["dept-machining", "dept-automation"]})
    assert "process_leg_disconnected" in codes(report)
    assert len(report["processFlow"]["legs"]) == 1


def test_unknown_ids_and_schema_limits():
    with pytest.raises(FacilityValidationError):
        review.review_workstations(_state(), {"placementIds": ["pl-does-not-exist"]})
    schema = review.tool_spec()["input_schema"]
    Draft202012Validator.check_schema(schema)
    for arguments in ({"pageSize": 0}, {"pageSize": 13}, {"path": "secret"}, {"processZoneIds": ["x"]}):
        assert list(Draft202012Validator(schema).iter_errors(arguments))


def test_partial_page_is_not_reported_as_complete():
    result = review.review_workstations(_state(), {"pageSize": 1})
    assert result["status"] == "partial_review" and result["nextOffset"] == 1


def test_cosmetic_changes_skip_second_pass():
    before = {"placements": [{"placementId": "pl-a", "assetId": "asset-a", "assetDefinitionRevision": "r",
               "transform": {"position": {"x": 0, "z": 0}}, "metadata": {}}],
               "extensions": {"facilityPerimeterWalls": {"settings": {"interiorColor": "#ffffff"}, "panels": []}}}
    after = deepcopy(before)
    after["extensions"]["facilityPerimeterWalls"]["settings"]["interiorColor"] = "#000000"
    after["placements"][0]["appearance"] = {"color": "#000000"}
    assert review.review_changed_workstations(None, None, None, before, after) is None


def test_real_gateway_preview_direct_policy_commit_and_undo(asset_host):
    context, placements = _place_review_assets(asset_host)
    initial = current(context)
    proposal = propose(context, operations=[{"op": "move_placement", "placementId": placements[0]["placementId"],
                        "position": {"x": 9, "y": 0, "z": 6}}], edit_mode="direct")
    report = proposal["alternative"]["validation"]["workstationReview"]
    assert report["reviewScope"] == "candidate_layout" and not report["certified"]
    assert proposal["alternative"]["directApplyPolicy"]["eligible"]
    assert current(context) == initial
    saved = apply(context, proposal, approve(context, proposal))
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
    gateway = FacilityEditGateway(asset_host.agent_runtime, asset_host.principal(), reference, turn_id="workstation-review")
    response = asyncio.run(gateway.call("review_facility_workstations", {}))
    assert response["ok"] and response["data"]["savedLayoutOnly"] and response["data"]["readOnly"]
    undo = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    restored = apply(context, undo, approve(context, undo, key="workstation-undo"), key="workstation-undo")
    expected = deepcopy(initial["layout"])
    expected["updatedAt"] = restored["layout"]["updatedAt"]
    assert restored["layout"] == expected
    stale = asyncio.run(gateway.call("review_facility_workstations", {}))
    assert stale["error"]["code"] == "codex_document_unavailable"
