from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.navigation_validation import (
    FacilityManualNavigationValidationError,
    validate_manual_navigation_path,
)


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"


def _rectangle(x0: float, z0: float, x1: float, z1: float):
    return [
        {"x": x0, "z": z0},
        {"x": x1, "z": z0},
        {"x": x1, "z": z1},
        {"x": x0, "z": z1},
    ]


def _shell():
    return {
        "features": [{
            "featureId": "floor-test",
            "featureKind": "floor_surface",
            "geometry": {"boundary": _rectangle(0, 0, 20, 12)},
        }],
    }


def _operator_asset():
    return {
        "assetId": "asset-operator",
        "geometry": {
            "footprintPolygons": [[
                {"x": -0.3, "z": -0.3},
                {"x": 0.3, "z": -0.3},
                {"x": 0.3, "z": 0.3},
                {"x": -0.3, "z": 0.3},
            ]],
        },
    }


def _vehicle_profile():
    fixture = json.loads(
        (FIXTURES / "routing" / "p7-routing-goldens.json").read_text(
            encoding="ascii"
        )
    )
    return deepcopy(fixture["vehicleProfile"])


def test_pedestrian_manual_path_reports_exact_blocked_segment():
    result = validate_manual_navigation_path(
        points=[
            {"x": 2, "z": 2},
            {"x": 5, "z": 2},
            {"x": 10, "z": 2},
        ],
        actor_class="pedestrian",
        actor_asset_definition=_operator_asset(),
        shell=_shell(),
        obstacles=[{
            "obstacleId": "machine-a",
            "boundary": _rectangle(7, 1, 8, 3),
        }],
    )
    assert result["valid"] is False
    assert result["invalidSegmentIndexes"] == [1]
    assert result["reviewStatus"] == "pending"
    assert "regulatory compliance" in result["qualification"]


def test_pedestrian_manual_path_is_byte_reproducible_and_does_not_mutate():
    points = [{"x": 2, "z": 2}, {"x": 10, "z": 2}]
    asset = _operator_asset()
    shell = _shell()
    before = deepcopy((points, asset, shell))
    first = validate_manual_navigation_path(
        points=points,
        actor_class="pedestrian",
        actor_asset_definition=asset,
        shell=shell,
        obstacles=[],
    )
    second = validate_manual_navigation_path(
        points=points,
        actor_class="pedestrian",
        actor_asset_definition=asset,
        shell=shell,
        obstacles=[],
    )
    assert first == second
    assert first["valid"] is True
    assert (points, asset, shell) == before


def test_vehicle_manual_path_uses_published_swept_volume_and_localizes_failure():
    result = validate_manual_navigation_path(
        points=[
            {"x": 2, "z": 5},
            {"x": 7, "z": 5},
            {"x": 12, "z": 5},
        ],
        actor_class="vehicle",
        actor_asset_definition=_operator_asset(),
        shell=_shell(),
        obstacles=[{
            "obstacleId": "blocked-lane",
            "boundary": _rectangle(9, 4, 10, 6),
        }],
        vehicle_profile=_vehicle_profile(),
    )
    assert result["valid"] is False
    assert result["validationMethod"] == "published_vehicle_swept_volume"
    assert result["invalidSegmentIndexes"] == [1]
    assert "route_swept_volume_collision" in {
        item["code"] for item in result["findings"]
    }


def test_vehicle_manual_path_fails_closed_without_profile():
    with pytest.raises(FacilityManualNavigationValidationError) as caught:
        validate_manual_navigation_path(
            points=[{"x": 2, "z": 5}, {"x": 12, "z": 5}],
            actor_class="vehicle",
            actor_asset_definition=_operator_asset(),
            shell=_shell(),
            obstacles=[],
        )
    assert caught.value.code == "facility_navigation_vehicle_profile_unavailable"
