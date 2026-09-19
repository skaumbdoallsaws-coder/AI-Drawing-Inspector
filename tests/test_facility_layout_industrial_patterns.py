from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.industrial_patterns import (
    FacilityIndustrialPatternError,
    compile_industrial_pattern,
)


def _zone(width: float, depth: float, *, zone_id: str = "zone-a") -> dict:
    return {
        "zoneId": zone_id,
        "label": f"Area {zone_id}",
        "floorElevation": 0,
        "boundary": [
            {"x": 0, "z": 0},
            {"x": width, "z": 0},
            {"x": width, "z": depth},
            {"x": 0, "z": depth},
        ],
    }


def _asset(asset_id: str, width: float, depth: float) -> dict:
    return {
        "assetId": asset_id,
        "assetDefinitionRevision": "a" * 64,
        "displayName": asset_id,
        "definition": {
            "geometry": {
                "aabb": {
                    "minimum": {"x": -width / 2, "y": 0, "z": -depth / 2},
                    "maximum": {"x": width / 2, "y": 2, "z": depth / 2},
                }
            }
        },
    }


def test_closed_guard_run_preserves_38_panels_and_is_deterministic() -> None:
    zone = _zone(20, 20)
    panel = _asset("guard-panel", 0.05, 1.45)
    first = compile_industrial_pattern(
        zone,
        panel,
        batch_id="guards-a",
        quantity=38,
        pattern_id="guard_run_closed",
    )
    second = compile_industrial_pattern(
        deepcopy(zone),
        deepcopy(panel),
        batch_id="guards-a",
        quantity=38,
        pattern_id="guard_run_closed",
    )

    assert first == second
    assert first["placedQuantity"] == 38
    assert first["metrics"]["contactPolicy"] == "panel_abutment"
    assert first["metrics"]["openSide"] is False
    assert all(
        operation["placement"]["metadata"]["spacingAuthority"]
        == "panel_abutment_geometry"
        for operation in first["operations"]
    )


def test_grid_patterns_keep_exact_quantities_across_held_out_areas() -> None:
    rack = _asset("rack", 2.7, 1.1)
    cases = [(40, 25, 50), (32, 18, 24), (60, 30, 80)]
    for index, (width, depth, quantity) in enumerate(cases):
        result = compile_industrial_pattern(
            _zone(width, depth, zone_id=f"zone-{index}"),
            rack,
            batch_id=f"racks-{index}",
            quantity=quantity,
            pattern_id="rack_bank",
            semantic_orientation="long_side_east_west",
            authored_spacing_meters=0.5,
            spacing_evidence_ref="user-spacing-1",
        )
        assert result["requestedQuantity"] == quantity
        assert result["placedQuantity"] == quantity
        assert result["spacingMeters"] == 0.5
        assert result["spacingAuthority"] == "user_or_policy_authored"


def test_pattern_fails_without_mutation_instead_of_reducing_quantity() -> None:
    with pytest.raises(FacilityIndustrialPatternError) as exc:
        compile_industrial_pattern(
            _zone(5, 5),
            _asset("machine", 3, 4),
            batch_id="machines",
            quantity=10,
            pattern_id="machine_rows",
            semantic_orientation="long_side_east_west",
            authored_spacing_meters=1,
            spacing_evidence_ref="user-spacing-1",
        )
    assert exc.value.code == "industrial_pattern_unplaceable"


def test_authored_spacing_requires_traceable_authority() -> None:
    with pytest.raises(FacilityIndustrialPatternError) as exc:
        compile_industrial_pattern(
            _zone(20, 20),
            _asset("bench", 2, 1),
            batch_id="benches",
            quantity=4,
            pattern_id="assembly_bench_rows",
            authored_spacing_meters=1.5,
        )
    assert exc.value.code == "industrial_pattern_spacing_authority_invalid"
