from __future__ import annotations

from copy import deepcopy
import random

import pytest

from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
    g1_department_semantic_type,
    validate_g1_department_result,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)


def _layout() -> dict:
    return create_layout_document(
        layout_id="fl-g1-test",
        display_name="Empty G1 Layout",
        association={"siteId": "site-a", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "origin-a",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-a",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-26T00:00:00Z",
    )


@pytest.mark.parametrize(
    ("width", "depth", "unit", "expected_width", "expected_depth"),
    [
        (100, 80, "m", 100.0, 80.0),
        (100_000, 80_000, "mm", 100.0, 80.0),
        (300, 200, "ft", 91.44, 60.96),
        (1200, 600, "in", 30.48, 15.24),
    ],
)
def test_envelope_normalizes_supported_units_without_saving(
    width: float,
    depth: float,
    unit: str,
    expected_width: float,
    expected_depth: float,
) -> None:
    layout = _layout()
    compiled = compile_g1_envelope_operations(
        layout,
        {
            "width": width,
            "depth": depth,
            "sourceUnit": unit,
            "displayName": "North Plant",
        },
    )
    result = apply_facility_layout_operations(layout, compiled["operations"])
    plan = result["document"]["extensions"]["facilityPlan"]
    assert plan["widthMeters"] == expected_width
    assert plan["depthMeters"] == expected_depth
    assert result["document"]["displayName"] == "North Plant"
    assert compiled["expectedSummary"]["saved"] is False


def test_randomized_partitions_cover_one_to_fifty_departments() -> None:
    random_source = random.Random(20260826)
    for count in range(1, 51):
        width = random_source.uniform(20.0, 500.0)
        depth = random_source.uniform(20.0, 500.0)
        labels = [f"Area {index + 1:02d}" for index in range(count)]
        weights = [random_source.uniform(0.1, 5.0) for _ in range(count)]
        layout = _layout()
        envelope = compile_g1_envelope_operations(
            layout,
            {
                "width": width,
                "depth": depth,
                "sourceUnit": "m",
                "displayName": f"Plant {count}",
            },
        )
        draft = apply_facility_layout_operations(
            layout, envelope["operations"]
        )["document"]
        departments = compile_g1_department_operations(
            draft,
            {
                "count": count,
                "labels": labels,
                "proportions": weights,
                "arrangement": "deterministic_grid",
                "orientation": "auto",
            },
        )
        assert len(departments["operations"]) <= 500
        result = apply_facility_layout_operations(
            draft, departments["operations"]
        )
        validation = validate_g1_department_result(
            result["document"], departments["expectedSummary"]
        )
        assert validation["status"] == "valid", (count, validation)
        assert validation["labels"] == labels
        assert validation["contained"] is True
        assert validation["overlaps"] == []
        assert validation["unexpectedZoneIds"] == []
        assert validation["coversFacilityArea"] is True


@pytest.mark.parametrize("arrangement", ["rows", "columns"])
def test_authored_proportions_are_exact_for_band_arrangements(
    arrangement: str,
) -> None:
    layout = _layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 60,
            "sourceUnit": "m",
            "displayName": "Band Plant",
        },
    )
    draft = apply_facility_layout_operations(
        layout, envelope["operations"]
    )["document"]
    departments = compile_g1_department_operations(
        draft,
        {
            "count": 3,
            "labels": ["Receiving", "Assembly", "Inspection"],
            "proportions": [2, 5, 3],
            "arrangement": arrangement,
            "orientation": "horizontal",
        },
    )
    result = apply_facility_layout_operations(
        draft, departments["operations"]
    )
    validation = validate_g1_department_result(
        result["document"], departments["expectedSummary"]
    )
    assert validation["status"] == "valid"
    assert validation["areaShares"] == pytest.approx([0.2, 0.5, 0.3])


def test_g1_never_invents_corridors_safety_separation_or_expansion() -> None:
    layout = _layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 50,
            "depth": 40,
            "sourceUnit": "m",
            "displayName": "No Extras",
        },
    )
    draft = apply_facility_layout_operations(
        layout, envelope["operations"]
    )["document"]
    departments = compile_g1_department_operations(
        draft,
        {"count": 4, "arrangement": "deterministic_grid"},
    )
    result = apply_facility_layout_operations(
        draft, departments["operations"]
    )["document"]
    assert len(result["zones"]) == 4
    assert result["routes"] == []
    assert result["floorMarkings"] == []
    assert result["placements"] == []
    assert departments["expectedSummary"]["inventedCorridor"] is False
    assert departments["expectedSummary"]["inventedSafetySeparation"] is False
    assert departments["expectedSummary"]["inventedExpansionReserve"] is False


def test_maintenance_department_remains_equipment_bearing() -> None:
    assert g1_department_semantic_type("Maintenance") == (
        "workcell",
        "maintenance",
    )
    assert g1_department_semantic_type("Maintenance Shop") == (
        "workcell",
        "maintenance_shop",
    )
    assert g1_department_semantic_type("Service Clearance") == (
        "service",
        "service_clearance",
    )


def test_authored_two_plus_three_rows_fill_the_envelope_with_equal_areas() -> None:
    layout = _layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 100,
            "depth": 80,
            "sourceUnit": "m",
            "displayName": "Row Plant",
        },
    )
    draft = apply_facility_layout_operations(
        layout, envelope["operations"]
    )["document"]
    request = {
        "count": 5,
        "labels": ["Receiving", "Machining", "Assembly", "Inspection", "Shipping"],
        "proportions": None,
        "arrangement": "row_stack",
        "orientation": "horizontal",
        "rows": [
            {"labels": ["Receiving", "Machining"], "proportion": None},
            {
                "labels": ["Assembly", "Inspection", "Shipping"],
                "proportion": None,
            },
        ],
    }
    compiled = compile_g1_department_operations(draft, request)
    result = apply_facility_layout_operations(
        draft, compiled["operations"]
    )["document"]
    validation = validate_g1_department_result(
        result, compiled["expectedSummary"]
    )

    assert validation["status"] == "valid"
    assert validation["rowOrder"] == "north_to_south"
    assert validation["areaShares"] == pytest.approx([0.2] * 5)
    assert validation["coversFacilityArea"] is True
    zones = {zone["label"]: zone for zone in result["zones"]}
    receiving = zones["Receiving"]["boundary"]
    assembly = zones["Assembly"]["boundary"]
    assert min(point["z"] for point in receiving) == pytest.approx(48.0)
    assert max(point["z"] for point in receiving) == pytest.approx(80.0)
    assert max(point["x"] for point in receiving) == pytest.approx(50.0)
    assert min(point["z"] for point in assembly) == pytest.approx(0.0)
    assert max(point["z"] for point in assembly) == pytest.approx(48.0)
    assert max(point["x"] for point in assembly) == pytest.approx(100 / 3)


def test_four_authored_rows_support_uneven_membership_and_unequal_areas() -> None:
    layout = _layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 160,
            "depth": 100,
            "sourceUnit": "m",
            "displayName": "Four Row Plant",
        },
    )
    draft = apply_facility_layout_operations(
        layout, envelope["operations"]
    )["document"]
    labels = [
        "Receiving",
        "Stores",
        "Machining",
        "Automation",
        "Assembly",
        "Inspection",
        "Packing",
        "Shipping",
    ]
    request = {
        "count": len(labels),
        "labels": labels,
        "proportions": [5, 10, 15, 20, 10, 10, 15, 15],
        "arrangement": "row_stack",
        "orientation": "horizontal",
        "rows": [
            {"labels": ["Receiving"], "proportion": None},
            {
                "labels": ["Stores", "Machining", "Automation"],
                "proportion": None,
            },
            {
                "labels": ["Assembly", "Inspection"],
                "proportion": None,
            },
            {
                "labels": ["Packing", "Shipping"],
                "proportion": None,
            },
        ],
    }

    compiled = compile_g1_department_operations(draft, request)
    result = apply_facility_layout_operations(
        draft, compiled["operations"]
    )["document"]
    validation = validate_g1_department_result(
        result, compiled["expectedSummary"]
    )

    assert validation["status"] == "valid"
    assert validation["areaShares"] == pytest.approx(
        [0.05, 0.10, 0.15, 0.20, 0.10, 0.10, 0.15, 0.15]
    )
    row_ranges = {
        (
            min(point["z"] for point in zone["boundary"]),
            max(point["z"] for point in zone["boundary"]),
        )
        for zone in result["zones"]
    }
    assert len(row_ranges) == 4
    assert validation["coversFacilityArea"] is True


def test_row_reorganization_preserves_semantic_zone_ids_and_unequal_areas() -> None:
    layout = _layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "Flexible Row Plant",
        },
    )
    draft = apply_facility_layout_operations(
        layout, envelope["operations"]
    )["document"]
    labels = ["Receiving", "Machining", "Assembly", "Inspection", "Shipping"]
    base_request = {
        "count": 5,
        "labels": labels,
        "proportions": [10, 20, 30, 15, 25],
        "arrangement": "row_stack",
        "rows": [
            {"labels": ["Receiving", "Machining"], "proportion": None},
            {
                "labels": ["Assembly", "Inspection", "Shipping"],
                "proportion": None,
            },
        ],
    }
    first = compile_g1_department_operations(draft, base_request)
    changed_request = deepcopy(base_request)
    changed_request["rows"] = [
        {
            "labels": ["Receiving", "Assembly", "Inspection"],
            "proportion": None,
        },
        {"labels": ["Machining", "Shipping"], "proportion": None},
    ]
    second = compile_g1_department_operations(draft, changed_request)

    assert first["expectedSummary"]["zoneIds"] == second["expectedSummary"]["zoneIds"]
    result = apply_facility_layout_operations(
        draft, first["operations"]
    )["document"]
    validation = validate_g1_department_result(
        result, first["expectedSummary"]
    )
    assert validation["status"] == "valid"
    assert validation["areaShares"] == pytest.approx(
        [0.1, 0.2, 0.3, 0.15, 0.25]
    )
