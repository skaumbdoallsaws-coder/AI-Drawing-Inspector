"""attachTo and seatAt: items placed on a desk surface, and chairs seated at a desk, pass the real spatial checks."""
from __future__ import annotations

from copy import deepcopy
import math

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.assisted_tools import edit_tool_specs
from ai_inspector.facility_layout.asset_orientation import REGISTERED_ASSET_SEMANTICS
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.placement_intents import resolve_placement_intents
from ai_inspector.facility_layout.spatial import diagnose_layout
from tests.test_facility_layout_spatial import _box_asset, _codes, _placement, _yaw_quaternion, golden  # noqa: F401 (fixture)

REVISION = "a" * 64
HALF = 1.0818682226818055
CORNER = REGISTERED_ASSET_SEMANTICS["asset-import-cubicle-corner-workstation"][1]


def _surface(surface_id, x, z, half_x, half_z):
    diagonal = math.sqrt(0.5)
    return {"surfaceId": surface_id, "label": surface_id, "allowedSides": ["above"], "evidenceStatus": "derived",
            "localFrame": {"origin": {"x": x, "y": 0.7747, "z": z}, "xAxis": {"x": diagonal, "y": 0.0, "z": -diagonal},
                           "zAxis": {"x": diagonal, "y": 0.0, "z": diagonal}, "normal": {"x": 0.0, "y": 1.0, "z": 0.0}},
            "bounds": {"minimumX": -half_x, "maximumX": half_x, "minimumZ": -half_z, "maximumZ": half_z}}


def _cubicle():
    """The corner cubicle's footprint (an L along south and west) and its three accessory surfaces."""
    return {
        "assetId": "asset-cubicle", "category": "workstation",
        "coordinateFrame": {"allowedMountingSurfaces": ["floor"], "floorAnchor": {"x": 0, "y": 0, "z": 0}},
        "geometry": {"footprintPolygons": [
            [{"x": -0.2, "z": -HALF}, {"x": -0.2, "z": HALF}, {"x": -HALF, "z": HALF}, {"x": -HALF, "z": -HALF}],
            [{"x": HALF, "z": -HALF}, {"x": HALF, "z": -0.2}, {"x": -0.2, "z": -0.2}, {"x": -0.2, "z": -HALF}]],
            "heightInterval": {"minimumY": 0, "maximumY": 1.68}},
        "clearances": [],
        "supportSurfaces": [_surface("corner-monitor", -0.67, -0.67, 0.26, 0.105),
                            _surface("corner-keyboard", -0.43, -0.43, 0.23, 0.075),
                            _surface("corner-mouse", -0.17, -0.66, 0.049, 0.073)],
    }


def _assets():
    return [_cubicle(), _box_asset("asset-monitor", 0.49, 0.18, 0.39), _box_asset("asset-keyboard", 0.43, 0.12, 0.03),
            _box_asset("asset-mouse", 0.078, 0.121, 0.05), _box_asset("asset-chair", 0.587, 0.55, 0.83),
            _box_asset("asset-wide-monitor", 0.70, 0.20, 0.45)]


def _catalog():
    """Catalog records as the gateway sees them: the definition, plus reviewed semantics beside it."""
    semantics = {"asset-cubicle": CORNER,
                 "asset-chair": {"functionalSides": {"front": {"side": "north", "evidenceStatus": "inferred"}}}}
    return [{"assetId": asset["assetId"], "assetDefinitionRevision": REVISION, "displayName": asset["assetId"],
             "definition": asset, **({"facilitySemantics": semantics[asset["assetId"]]} if asset["assetId"] in semantics else {})}
            for asset in _assets()]


def _layout(golden, cubicle_yaw=0.0, *, cubicle=True):
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [_placement("pl-cubicle", "asset-cubicle", 2.0, 3.0, quaternion=_yaw_quaternion(cubicle_yaw))] if cubicle else []
    return layout


def _place(asset_id, placement_id, **intent):
    return {"op": "place_asset", "placementId": placement_id,
            "placement": {"assetId": asset_id, "assetDefinitionRevision": REVISION, "transform": {"scale": 1},
                          "positionMode": "manual", "snapRelationship": None, "metadata": {}}, **intent}


def _apply(layout, operations):
    resolved = resolve_placement_intents(operations, catalog=_catalog(), layout=layout)
    result = deepcopy(layout)
    for operation in resolved:
        result["placements"].append({"placementId": operation["placementId"], **operation["placement"]})
    return resolved, result


@pytest.mark.parametrize("yaw", [0.0, 90.0, 217.0])
def test_desk_accessories_attach_where_the_validator_expects_them(golden, yaw):
    attach = lambda surface: {"attachTo": {"supportPlacementId": "pl-cubicle", "surfaceId": surface}}
    resolved, layout = _apply(_layout(golden, yaw), [
        _place("asset-monitor", "pl-monitor", **attach("corner-monitor")),
        _place("asset-keyboard", "pl-keyboard", **attach("corner-keyboard")),
        _place("asset-mouse", "pl-mouse", **attach("corner-mouse")),
        _place("asset-chair", "pl-chair", seatAt={"deskPlacementId": "pl-cubicle"})])
    assert all("attachTo" not in op and "seatAt" not in op for op in resolved)
    monitor = resolved[0]["placement"]
    assert monitor["snapRelationship"]["surfaceSource"] == "asset_definition"
    assert monitor["transform"]["position"]["y"] == pytest.approx(0.7747)
    result = diagnose_layout(layout, _assets())
    assert "invalid_surface_attachment" not in _codes(result, "error")
    assert "placement_collision" not in _codes(result, "error")
    assert _codes(result, "unverified").count("surface_attachment_safety_unverified") == 3


def test_seat_turns_with_the_desk_and_faces_its_corner(golden):
    resolved, _ = _apply(_layout(golden, 90.0), [_place("asset-chair", "pl-chair", seatAt={"deskPlacementId": "pl-cubicle"})])
    transform = resolved[0]["placement"]["transform"]
    # The seat at (0.25, 0.25) in the desk's frame, turned 90 degrees with the desk: (0.25, -0.25).
    assert (transform["position"]["x"], transform["position"]["z"]) == (pytest.approx(2.25), pytest.approx(2.75))
    q = transform["quaternion"]
    heading = math.degrees(math.atan2(2 * (q["w"] * q["y"] + q["x"] * q["z"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))) % 360
    assert heading == pytest.approx((90 + 225) % 360)


def test_an_item_on_a_desk_placed_earlier_in_the_same_batch(golden):
    layout = _layout(golden, cubicle=False)
    desk = _place("asset-cubicle", "pl-new-desk")
    desk["placement"]["transform"] = {"position": {"x": 3.0, "y": 0.0, "z": 4.0}, "quaternion": _yaw_quaternion(180.0), "scale": 1}
    _, result = _apply(layout, [desk, _place("asset-keyboard", "pl-keyboard",
                                             attachTo={"supportPlacementId": "pl-new-desk", "surfaceId": "corner-keyboard"})])
    assert "invalid_surface_attachment" not in _codes(diagnose_layout(result, _assets()), "error")


@pytest.mark.parametrize("operation, code", [
    (_place("asset-monitor", "pl-x", attachTo={"supportPlacementId": "pl-cubicle", "surfaceId": "shelf"}), "attachment_surface_unknown"),
    (_place("asset-wide-monitor", "pl-x", attachTo={"supportPlacementId": "pl-cubicle", "surfaceId": "corner-monitor"}), "attachment_does_not_fit"),
    (_place("asset-monitor", "pl-x", attachTo={"supportPlacementId": "pl-missing", "surfaceId": "corner-monitor"}), "placement_intent_target_unknown"),
    (_place("asset-keyboard", "pl-x", seatAt={"deskPlacementId": "pl-cubicle"}), "asset_front_side_unknown"),
    (_place("asset-monitor", "pl-x", attachTo={"supportPlacementId": "pl-cubicle", "surfaceId": "corner-monitor"},
            orientation={"facing": "north"}), "placement_intent_conflict"),
])
def test_bad_intents_fail_with_a_clear_code(golden, operation, code):
    with pytest.raises(FacilityValidationError) as caught:
        resolve_placement_intents([operation], catalog=_catalog(), layout=_layout(golden))
    assert caught.value.code == code


def test_unknown_surface_lists_the_surfaces_that_exist(golden):
    operation = _place("asset-monitor", "pl-x", attachTo={"supportPlacementId": "pl-cubicle", "surfaceId": "shelf"})
    with pytest.raises(FacilityValidationError) as caught:
        resolve_placement_intents([operation], catalog=_catalog(), layout=_layout(golden))
    assert "corner-monitor, corner-keyboard, corner-mouse" in str(caught.value)


def test_place_asset_schema_accepts_intents_without_a_position():
    schema = next(s for s in edit_tool_specs() if s["name"] == "preview_facility_operations")["input_schema"]
    validator = Draft202012Validator({"$defs": schema.get("$defs", {}), **schema["properties"]["operations"]["items"]})
    placed = _place("asset-monitor", "pl-x")
    placed["placement"]["assetId"] = "asset-monitor"
    attached = {**placed, "attachTo": {"supportPlacementId": "pl-cubicle", "surfaceId": "corner-monitor"}}
    seated = {**placed, "seatAt": {"deskPlacementId": "pl-cubicle"}}
    assert validator.is_valid(attached) and validator.is_valid(seated)
    assert not validator.is_valid({**attached, "orientation": {"facing": "north"}})
    assert not validator.is_valid({**attached, "seatAt": {"deskPlacementId": "pl-cubicle"}})
    assert not validator.is_valid(placed)  # a plain placement still needs its position and turn
    plain = deepcopy(placed)
    plain["placement"]["transform"] = {"position": {"x": 1, "y": 0, "z": 1}, "scale": 1}
    assert validator.is_valid({**plain, "orientation": {"facing": "north"}})
    assert not validator.is_valid(plain)
