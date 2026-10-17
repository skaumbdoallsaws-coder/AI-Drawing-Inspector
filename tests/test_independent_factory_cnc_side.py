"""CAD-side checks must not confuse facing a center with facing an operating side."""
from copy import deepcopy
import math
import pytest

from tools.correct_independent_factory_cnc_side import (
    ASSET_ID, ASSET_REVISION, correction_operations, reviewed_side_check,
)
from tools.audit_independent_factory_layer2 import facing_quaternion, heading_error


def pair(yaw=0, x=0, z=3.5):
    machine = {"placementId": "machine", "assetId": ASSET_ID,
        "assetDefinitionRevision": ASSET_REVISION, "transform": {
            "position": {"x": 0, "y": 0, "z": 0},
            "quaternion": {"x": 0, "y": math.sin(yaw / 2), "z": 0, "w": math.cos(yaw / 2)}}}
    p = {"x": x, "y": 0, "z": z}
    operator = {"placementId": "person", "transform": {"position": p,
        "quaternion": facing_quaternion(p, machine["transform"]["position"])}}
    return machine, operator


def test_facing_center_from_rear_must_fail():
    m, p = pair()
    assert heading_error(p, m["transform"]["position"]) == pytest.approx(0)
    result = reviewed_side_check(m, p)
    assert result["operatorSideAlignment"] == -1
    assert not result["passed"]


@pytest.mark.parametrize("yaw,x,z", [(math.pi, 0, 3.5), (0, 0, -3.5),
                                      (math.pi/2, -3.5, 0), (-math.pi/2, 3.5, 0)])
def test_observed_work_side_transforms_with_machine(yaw, x, z):
    result = reviewed_side_check(*pair(yaw, x, z))
    assert result["passed"]
    assert result["evidenceStatus"] == "inferred"
    assert not result["approvedOperatingStation"]


def test_correct_side_but_facing_away_fails():
    m, p = pair(math.pi)
    p["transform"]["quaternion"] = {"x": 0, "y": 0, "z": 0, "w": 1}
    assert not reviewed_side_check(m, p)["passed"]


@pytest.mark.parametrize("key,value", [("assetId", "other-cnc"), ("assetDefinitionRevision", "new-revision")])
def test_visual_inference_never_migrates_to_other_model_or_revision(key, value):
    m, p = pair(math.pi)
    m[key] = value
    with pytest.raises(ValueError, match="No CAD-side review"):
        reviewed_side_check(m, p)


def test_coincident_operator_not_a_side_pass():
    m, p = pair()
    p["transform"]["position"] = deepcopy(m["transform"]["position"])
    with pytest.raises(ValueError, match="Coincident"):
        reviewed_side_check(m, p)


def test_original_layout_rejected():
    with pytest.raises(ValueError, match="refusing to overwrite"):
        correction_operations({"layoutId": "fl-reference-manual-20260812"})


def test_changed_revision_rejected(monkeypatch):
    import tools.correct_independent_factory_cnc_side as tool
    monkeypatch.setattr(tool, "layout_revision", lambda _doc: "changed")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        correction_operations({"layoutId": tool.LAYOUT_ID})
