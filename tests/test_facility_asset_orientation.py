"""Orientation intent: reviewed asset front sides and exact yaw quaternions."""
import asyncio
import math
import re

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway, edit_tool_specs
from ai_inspector.facility_layout import asset_orientation
from ai_inspector.facility_layout.asset_orientation import (
    COMPASS_HEADINGS, REGISTERED_ASSET_SEMANTICS, attach_registered_semantics,
    resolve_orientation_intents, yaw_quaternion)
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.host import LOCAL_ASSET_CATALOG, LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.validate import _quaternion

REVIEWED = "a" * 64
NORTH, EAST, SOUTH, WEST = (0, 1), (1, 0), (0, -1), (-1, 0)


def _turn(quaternion, vector):
    """Apply a yaw quaternion to a floor vector (x, z)."""
    angle = 2 * math.atan2(quaternion["y"], quaternion["w"])
    x, z = vector
    return (round(x * math.cos(angle) + z * math.sin(angle), 9) + 0.0,
            round(-x * math.sin(angle) + z * math.cos(angle), 9) + 0.0)


def _record(asset_id, front, revision=REVIEWED):
    return {"assetId": asset_id, "assetDefinitionRevision": revision,
            "facilitySemantics": {"functionalSides": {"front": {"side": front, "evidenceStatus": "inferred"}}}}


def _place(asset_id, orientation, revision=REVIEWED, **transform):
    return {"op": "place_asset", "orientation": orientation, "placement": {
        "assetId": asset_id, "assetDefinitionRevision": revision,
        "transform": {"position": {"x": 1, "y": 0, "z": 1}, "scale": 1, **transform}}}


CATALOG = [_record("asset-desk", "east"), _record("asset-chair", "north")]


@pytest.mark.parametrize("degrees, north_becomes", [
    (0, NORTH), (90, EAST), (180, SOUTH), (270, WEST), (-90, WEST), (450, EAST), (360, NORTH)])
def test_compass_turns_are_exact_canonical_unit_quaternions(degrees, north_becomes):
    quaternion = yaw_quaternion(degrees)
    assert _quaternion(quaternion, "transform.quaternion") == quaternion  # the layout kernel accepts it
    assert quaternion["x"] == quaternion["z"] == 0
    assert _turn(quaternion, NORTH) == north_becomes


def test_facing_turns_the_reviewed_front_to_the_requested_side():
    # A desk's front is its east side unrotated; a chair's is its north side.
    # The same raw rotation therefore points them 90 degrees apart.
    desk, chair = resolve_orientation_intents(
        [_place("asset-desk", {"facing": "north"}), _place("asset-chair", {"facing": "south"})],
        catalog=CATALOG, layout={"placements": []})
    assert "orientation" not in desk and "orientation" not in chair
    assert _turn(desk["placement"]["transform"]["quaternion"], EAST) == NORTH
    assert _turn(chair["placement"]["transform"]["quaternion"], NORTH) == SOUTH


def test_yaw_degrees_needs_no_reviewed_front():
    [placed] = resolve_orientation_intents([_place("asset-unreviewed", {"yawDegrees": 90})],
                                           catalog=[], layout={"placements": []})
    assert _turn(placed["placement"]["transform"]["quaternion"], NORTH) == EAST


def test_rotate_placement_uses_the_saved_placement_revision():
    layout = {"placements": [
        {"placementId": "pl-desk", "assetId": "asset-desk", "assetDefinitionRevision": REVIEWED},
        {"placementId": "pl-old-desk", "assetId": "asset-desk", "assetDefinitionRevision": "b" * 64}]}
    [rotated] = resolve_orientation_intents(
        [{"op": "rotate_placement", "placementId": "pl-desk", "orientation": {"facing": "west"}}],
        catalog=CATALOG, layout=layout)
    assert _turn(rotated["quaternion"], EAST) == WEST
    # A front reviewed on one model revision does not carry over to another.
    with pytest.raises(FacilityValidationError) as refused:
        resolve_orientation_intents(
            [{"op": "rotate_placement", "placementId": "pl-old-desk", "orientation": {"facing": "west"}}],
            catalog=CATALOG, layout=layout)
    assert refused.value.code == "asset_front_side_unknown"


def test_unreviewed_asset_cannot_use_facing():
    with pytest.raises(FacilityValidationError) as refused:
        resolve_orientation_intents([_place("asset-unreviewed", {"facing": "east"})],
                                    catalog=CATALOG, layout={"placements": []})
    assert refused.value.code == "asset_front_side_unknown"
    assert "yawDegrees" in str(refused.value)


@pytest.mark.parametrize("operation, code", [
    (_place("asset-desk", {"facing": "north", "yawDegrees": 90}), "orientation_intent_invalid"),
    (_place("asset-desk", {"facing": "up"}), "orientation_intent_invalid"),
    (_place("asset-desk", {"yawDegrees": True}), "orientation_intent_invalid"),
    (_place("asset-desk", {"yawDegrees": float("inf")}), "orientation_intent_invalid"),
    (_place("asset-desk", {"facing": "north"}, quaternion={"x": 0, "y": 0, "z": 0, "w": 1}),
     "orientation_intent_conflict"),
    ({"op": "rotate_placement", "placementId": "pl-new", "orientation": {"yawDegrees": 90}},
     "orientation_placement_not_saved"),
    ({"op": "move_placement", "placementId": "pl-desk", "orientation": {"yawDegrees": 90}},
     "orientation_intent_unsupported"),
])
def test_invalid_or_conflicting_intents_are_refused(operation, code):
    with pytest.raises(FacilityValidationError) as refused:
        resolve_orientation_intents([operation], catalog=CATALOG, layout={"placements": []})
    assert refused.value.code == code


def test_batches_without_intents_pass_through_untouched():
    operations = [{"op": "rename_layout", "displayName": "Plant"}]
    assert resolve_orientation_intents(operations, catalog=CATALOG, layout={}) is operations


def test_reviewed_sides_attach_only_to_the_reviewed_revision():
    asset_id, (revision, semantics) = next(iter(REGISTERED_ASSET_SEMANTICS.items()))
    definition = {"assetId": asset_id, "displayName": "Reviewed"}
    record = {"assetId": asset_id, "assetDefinitionRevision": revision, "definition": definition}
    attached = attach_registered_semantics(record)
    assert attached["facilitySemantics"] == semantics
    assert attached["definition"] == definition and "facilitySemantics" not in record
    assert "facilitySemantics" not in attach_registered_semantics(dict(record, assetDefinitionRevision="c" * 64))
    own = {"functionalSides": {}}
    assert attach_registered_semantics(dict(record, facilitySemantics=own))["facilitySemantics"] == own


def test_registry_names_compass_sides_for_exact_revisions():
    for asset_id, (revision, semantics) in REGISTERED_ASSET_SEMANTICS.items():
        assert re.fullmatch("[0-9a-f]{64}", revision), asset_id
        sides = semantics["functionalSides"]
        assert sides["front"]["side"] in COMPASS_HEADINGS, asset_id
        assert all(item["side"] in COMPASS_HEADINGS for item in sides.values()), asset_id


def test_agent_instructions_do_not_call_reviewed_fronts_unverified():
    # Reviewed fronts are marked inferred because no manufacturer drawing confirms
    # them. Without this explanation Sage called every facing orientation unverified.
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS
    assert {item["evidenceStatus"] for _, semantics in REGISTERED_ASSET_SEMANTICS.values()
            for item in semantics["functionalSides"].values()} == {"inferred"}
    text = " ".join(EDIT_INSTRUCTIONS.split())
    assert "evidenceStatus inferred only means no manufacturer drawing confirms it" in text
    assert "Do not call an orientation set with facing unverified." in text


def test_edit_schema_takes_orientation_in_place_of_a_quaternion():
    validator = Draft202012Validator(edit_tool_specs()[0]["input_schema"])
    placement = {"assetId": "asset-desk", "assetDefinitionRevision": REVIEWED, "positionMode": "manual",
                 "snapRelationship": None, "metadata": {},
                 "transform": {"position": {"x": 1, "y": 0, "z": 1}, "scale": 1}}
    quaternion = {"x": 0, "y": 0, "z": 0, "w": 1}
    with_quaternion = dict(placement, transform=dict(placement["transform"], quaternion=quaternion))

    def valid(operation):
        return validator.is_valid({"operations": [operation]})

    assert valid({"op": "place_asset", "placement": placement, "orientation": {"facing": "north"}})
    assert valid({"op": "place_asset", "placement": placement, "orientation": {"yawDegrees": -90}})
    assert valid({"op": "place_asset", "placement": with_quaternion})
    assert not valid({"op": "place_asset", "placement": placement})
    assert not valid({"op": "place_asset", "placement": with_quaternion, "orientation": {"facing": "north"}})
    assert valid({"op": "rotate_placement", "placementId": "pl-desk", "orientation": {"facing": "east"}})
    assert valid({"op": "rotate_placement", "placementId": "pl-desk", "quaternion": quaternion})
    assert not valid({"op": "rotate_placement", "placementId": "pl-desk"})
    assert not valid({"op": "rotate_placement", "placementId": "pl-desk", "quaternion": quaternion,
                      "orientation": {"facing": "east"}})


def test_agent_gateway_stages_a_facing_placement_as_an_exact_quaternion(tmp_path, monkeypatch):
    bench = next(item for item in LOCAL_ASSET_CATALOG if item["assetId"] == "asset-workbench")
    monkeypatch.setitem(asset_orientation.REGISTERED_ASSET_SEMANTICS, "asset-workbench",
                        (bench["assetDefinitionRevision"], asset_orientation._sides("east")))
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        host.ensure_bootstrap()
        principal = host.principal()
        revision = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"]
        gateway = FacilityEditGateway(host.agent_runtime, principal, {
            "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": revision}, turn_id="orientation-test")
        operation = {"op": "place_asset", "orientation": {"facing": "north"}, "placement": {
            "placementId": "pl-bench", "assetId": "asset-workbench",
            "assetDefinitionRevision": bench["assetDefinitionRevision"], "positionMode": "manual",
            "snapRelationship": None, "metadata": {},
            "transform": {"position": {"x": 6, "y": 0, "z": 6}, "scale": 1}}}
        result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [operation]}))
        assert result["ok"], result
        staged = host.service.get_layout_proposal_preview(
            principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, result["data"]["proposalId"])
        quaternion = staged["alternative"]["operations"][0]["placement"]["transform"]["quaternion"]
        assert _turn(quaternion, EAST) == NORTH

        # The agent learns the reviewed front from the asset it inspects.
        inspected = asyncio.run(gateway.call("inspect_facility_asset", {"assetId": "asset-workbench"}))
        assert inspected["data"]["definition"]["facilitySemantics"]["functionalSides"]["front"]["side"] == "east"
    finally:
        host.close()
