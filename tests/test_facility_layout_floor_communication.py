from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.floor_communication import (
    FacilityFloorCommunicationError,
    compile_marking_array,
)


def _layout() -> dict:
    return {
        "zones": [
            {
                "zoneId": "zone-parking",
                "label": "Equipment Parking",
                "boundary": [
                    {"x": 0, "z": 0},
                    {"x": 30, "z": 0},
                    {"x": 30, "z": 20},
                    {"x": 0, "z": 20},
                ],
            }
        ],
        "routes": [
            {
                "routeId": "route-main",
                "label": "Main Spine",
                "centerline": [
                    {"x": 0, "y": 0, "z": 10},
                    {"x": 30, "y": 0, "z": 10},
                ],
            }
        ],
        "placements": [],
    }


def _parking_spec() -> dict:
    return {
        "communication_id": "parking-array-01",
        "marking_type": "parking_box",
        "label": "Equipment parking",
        "anchor_relationship": {
            "kind": "area",
            "target_area": "Equipment Parking",
        },
        "count": 12,
        "rows": 3,
        "columns": 4,
        "pitch": {"along": 5, "across": 5},
        "semantic_orientation": "east_west",
        "width": 4,
        "depth": 4,
        "source_unit": "m",
        "dimension_evidence_refs": ["user-authored-parking-template"],
    }


def test_area_marking_array_is_exact_and_deterministic() -> None:
    first = compile_marking_array(_layout(), _parking_spec())
    second = compile_marking_array(deepcopy(_layout()), deepcopy(_parking_spec()))
    assert first == second
    assert first["requestedCount"] == first["generatedCount"] == 12
    assert all(
        item["floorMarking"]["metadata"]["positionAuthority"]
        == "derived_from_relational_anchor"
        for item in first["operations"]
    )
    assert all(
        item["floorMarking"]["metadata"]["dimensionAuthority"]
        == "user_or_policy_authored"
        for item in first["operations"]
    )


def test_single_marking_does_not_constrain_unused_pitch_axes() -> None:
    specification = _parking_spec()
    specification.update(
        {
            "count": 1,
            "rows": 1,
            "columns": 1,
            "pitch": {"along": 1, "across": 1},
            "width": 6,
            "depth": 6,
        }
    )

    compiled = compile_marking_array(_layout(), specification)

    assert compiled["requestedCount"] == compiled["generatedCount"] == 1


def test_route_aligned_arrows_use_derived_route_geometry() -> None:
    spec = {
        "communication_id": "arrows-01",
        "marking_type": "direction_arrow",
        "label": "Flow direction",
        "anchor_relationship": {"kind": "route", "route_label": "Main Spine"},
        "count": 3,
        "rows": 1,
        "columns": 3,
        "pitch": {"along": 5, "across": 2},
        "semantic_orientation": "route_aligned",
        "width": 2,
        "depth": 1,
        "source_unit": "m",
        "dimension_evidence_refs": ["user-authored-arrow-template"],
    }
    result = compile_marking_array(_layout(), spec)
    positions = [item["floorMarking"]["transform"]["position"] for item in result["operations"]]
    assert [item["x"] for item in positions] == [10.0, 15.0, 20.0]
    assert all(item["z"] == 10.0 for item in positions)


def test_marking_dimensions_without_authority_fail_closed() -> None:
    spec = _parking_spec()
    spec["dimension_evidence_refs"] = []
    with pytest.raises(FacilityFloorCommunicationError) as exc:
        compile_marking_array(_layout(), spec)
    assert exc.value.code == "floor_communication_dimension_authority_missing"
