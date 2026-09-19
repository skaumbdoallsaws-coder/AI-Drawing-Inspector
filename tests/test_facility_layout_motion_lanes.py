from __future__ import annotations

import pytest

from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.motion_lanes import derive_directional_lane


def _route() -> dict:
    return {
        "routeId": "route-main",
        "centerline": [
            {"x": 0.0, "y": 0.0, "z": 10.0},
            {"x": 100.0, "y": 0.0, "z": 10.0},
        ],
        "corridorWidth": 10.0,
    }


def _arrow(marking_id: str, x: float, z: float, rotation: float) -> dict:
    return {
        "markingId": marking_id,
        "markingType": "direction_arrow",
        "semanticRole": "material_flow",
        "transform": {
            "position": {"x": x, "y": 0.0, "z": z},
            "rotationDegrees": rotation,
        },
        "width": 1.0,
        "depth": 2.0,
    }


def test_directional_lane_uses_forward_and_reverse_arrow_rows() -> None:
    layout = {
        "floorMarkings": [
            _arrow("forward-a", 20.0, 13.0, 90.0),
            _arrow("forward-b", 80.0, 13.0, 90.0),
            _arrow("reverse-a", 20.0, 7.0, 270.0),
            _arrow("reverse-b", 80.0, 7.0, 270.0),
        ]
    }

    forward = derive_directional_lane(
        layout,
        _route(),
        travel_direction="forward",
    )
    reverse = derive_directional_lane(
        layout,
        _route(),
        travel_direction="reverse",
    )

    assert forward["status"] == "direction_markings"
    assert forward["sourceMarkingIds"] == ["forward-a", "forward-b"]
    assert forward["lateralOffsetMeters"] == 3.0
    assert [point["z"] for point in forward["laneCenterline"]] == [13.0, 13.0]
    assert reverse["sourceMarkingIds"] == ["reverse-a", "reverse-b"]
    assert reverse["laneCenterline"][0]["x"] == 100.0
    assert [point["z"] for point in reverse["laneCenterline"]] == [7.0, 7.0]


def test_directional_lane_retains_unmarked_centerline_without_claiming_lane() -> None:
    result = derive_directional_lane(
        {"floorMarkings": []},
        _route(),
        travel_direction="forward",
    )

    assert result["status"] == "centerline_unmarked"
    assert result["sourceMarkingIds"] == []
    assert result["lateralOffsetMeters"] == 0.0
    assert result["evidenceStatus"] == "unknown"
    assert result["laneCenterline"] == _route()["centerline"]


def test_directional_lane_refuses_two_same_direction_lanes() -> None:
    layout = {
        "floorMarkings": [
            _arrow("inner", 30.0, 12.0, 90.0),
            _arrow("outer", 70.0, 14.0, 90.0),
        ]
    }

    with pytest.raises(FacilityValidationError) as captured:
        derive_directional_lane(
            layout,
            _route(),
            travel_direction="forward",
        )

    assert captured.value.code == "facility_motion_lane_binding_ambiguous"
    assert captured.value.details["candidateLaneCount"] == 2


def test_directional_lane_ignores_arrows_outside_route_corridor() -> None:
    result = derive_directional_lane(
        {"floorMarkings": [_arrow("remote", 50.0, 30.0, 90.0)]},
        _route(),
        travel_direction="forward",
    )

    assert result["status"] == "centerline_unmarked"
