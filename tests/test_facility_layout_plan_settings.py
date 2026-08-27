from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.plan_settings import (
    default_plan_settings,
    normalize_plan_settings,
    plan_settings_from_layout,
    plan_world_bounds,
    shell_with_plan_boundary,
)


SETTINGS = {
    "widthMeters": 55.0,
    "depthMeters": 36.0,
    "gridSpacingMeters": 2.0,
    "majorGridSpacingMeters": 10.0,
}


def test_defaults_and_world_bounds_use_corner_origin_world_coordinates() -> None:
    assert default_plan_settings() == {
        "widthMeters": 40.0,
        "depthMeters": 30.0,
        "gridSpacingMeters": 1.0,
        "majorGridSpacingMeters": 5.0,
    }
    assert plan_world_bounds(
        SETTINGS,
        minimum_x=4.0,
        minimum_z=-3.0,
        floor_y=1.25,
    ) == {
        "minX": 4.0,
        "minZ": -3.0,
        "maxX": 59.0,
        "maxZ": 33.0,
        "floorY": 1.25,
    }


def test_layout_settings_round_trip_without_mutating_the_document() -> None:
    layout = {"extensions": {"facilityPlan": deepcopy(SETTINGS)}}
    before = deepcopy(layout)

    assert plan_settings_from_layout(layout) == SETTINGS
    assert layout == before


def test_plan_boundary_replaces_only_the_authoritative_floor_geometry() -> None:
    shell = {
        "coordinateFrame": {"floorElevation": 0.25},
        "features": [{
            "featureId": "floor-existing",
            "featureKind": "floor_surface",
            "geometry": {
                "boundary": [
                    {"x": -1.0, "z": -1.0},
                    {"x": 1.0, "z": -1.0},
                    {"x": 1.0, "z": 1.0},
                ],
                "elevation": 0.0,
            },
            "evidence": [{"sourceType": "site_survey"}],
        }],
    }
    layout = {"extensions": {"facilityPlan": deepcopy(SETTINGS)}}
    original_shell = deepcopy(shell)

    result = shell_with_plan_boundary(shell, layout)

    assert result["features"][0]["geometry"] == {
        "boundary": [
            {"x": 0.0, "z": 0.0},
            {"x": 55.0, "z": 0.0},
            {"x": 55.0, "z": 36.0},
            {"x": 0.0, "z": 36.0},
        ],
        "elevation": 0.25,
    }
    assert result["features"][0]["evidence"] == [
        {"sourceType": "site_survey"}
    ]
    assert shell == original_shell


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {
            "widthMeters": 40,
            "depthMeters": 30,
            "gridSpacingMeters": 0,
            "majorGridSpacingMeters": 5,
        },
        {
            "widthMeters": 40,
            "depthMeters": 30,
            "gridSpacingMeters": 2,
            "majorGridSpacingMeters": 5,
        },
    ],
)
def test_invalid_settings_fail_closed(settings: dict) -> None:
    with pytest.raises(ValueError):
        normalize_plan_settings(settings)
