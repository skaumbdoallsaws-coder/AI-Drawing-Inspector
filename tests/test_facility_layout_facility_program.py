from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.cell_replication import (
    G6_MAXIMUM_COPIED_PLACEMENTS,
)
from ai_inspector.facility_layout.facility_program import (
    FACILITY_PROGRAM_MAX_TOTAL_ASSETS,
    FACILITY_PROGRAM_SCHEMA,
    FACILITY_PROGRAM_STAGE_SLICE_BYTES,
    FACILITY_PROGRAM_TOOL_RESPONSE_BYTES,
    FacilityProgramError,
    canonicalize_facility_program,
    facility_program_from_full_factory,
    facility_program_model_summary,
    facility_program_stage_slice,
)
from ai_inspector.facility_layout.full_factory import (
    FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY,
    FacilityFullFactoryError,
    canonicalize_full_factory_request,
)
from ai_inspector.facility_layout.host import LOCAL_ASSET_CATALOG
from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)


def _asset_name() -> str:
    return str(LOCAL_ASSET_CATALOG[0]["displayName"])


def _full_factory_with_quantity(quantity: int) -> dict:
    requests = []
    remaining = quantity
    while remaining:
        current = min(50, remaining)
        requests.append(
            {
                "asset_name": _asset_name(),
                "quantity": current,
                "target_area": "Factory",
                "orientation_mode": "long_side_east_west",
                "facing_direction": None,
                "resource_role": "production",
                "access_requirement": "physical_only",
            }
        )
        remaining -= current
    return {
        "facility_envelope": {
            "width": 300,
            "depth": 200,
            "source_unit": "m",
            "display_name": "RQ Factory",
            "grid_size": 1,
        },
        "departments": {
            "count": 1,
            "labels": ["Factory"],
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [{"labels": ["Factory"], "proportion": None}],
        },
        "circulation": {"routes": [], "crossings": []},
        "subdivisions": [],
        "asset_placements": requests,
        "seed_cell": None,
        "cell_replication": None,
        "execution_mode": "authorized_draft_run",
    }


def test_reference_quality_asset_caps_are_reconciled_at_900() -> None:
    assert FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY == 900
    assert G6_MAXIMUM_COPIED_PLACEMENTS == 900
    assert FACILITY_PROGRAM_MAX_TOTAL_ASSETS == 900

    assert sum(
        item["quantity"]
        for item in canonicalize_full_factory_request(
            _full_factory_with_quantity(899)
        )["asset_placements"]
    ) == 899
    assert sum(
        item["quantity"]
        for item in canonicalize_full_factory_request(
            _full_factory_with_quantity(900)
        )["asset_placements"]
    ) == 900
    with pytest.raises(FacilityFullFactoryError) as exc:
        canonicalize_full_factory_request(_full_factory_with_quantity(901))
    assert exc.value.code == "full_factory_program_budget_exceeded"


def test_full_factory_adapter_is_compact_and_preserves_900_instances() -> None:
    program = facility_program_from_full_factory(
        _full_factory_with_quantity(900), list(LOCAL_ASSET_CATALOG)
    )

    assert program["schema_version"] == FACILITY_PROGRAM_SCHEMA
    assert len(program["resource_batches"]) == 1
    assert program["resource_batches"][0]["quantity"] == 900
    summary = facility_program_model_summary(program)
    assert summary["counts"]["requestedAssets"] == 900
    assert len(canonical_facility_knowledge_bytes(summary)) <= FACILITY_PROGRAM_TOOL_RESPONSE_BYTES
    resource_slice = facility_program_stage_slice(program, "department_resources")
    assert resource_slice["nextCursor"] is None
    assert len(canonical_facility_knowledge_bytes(resource_slice)) <= FACILITY_PROGRAM_STAGE_SLICE_BYTES


def test_full_factory_auto_orientation_maps_to_pattern_catalog_default() -> None:
    request = _full_factory_with_quantity(1)
    request["asset_placements"][0]["orientation_mode"] = "auto"

    program = facility_program_from_full_factory(
        request, list(LOCAL_ASSET_CATALOG)
    )

    assert program["resource_batches"][0]["semantic_orientation"] == "catalog_default"


def test_program_rejects_coordinates_and_unknown_fields() -> None:
    program = facility_program_from_full_factory(
        _full_factory_with_quantity(1), list(LOCAL_ASSET_CATALOG)
    )
    authored_geometry = deepcopy(program)
    authored_geometry["resource_batches"][0]["x"] = 20
    with pytest.raises(FacilityProgramError) as exc:
        canonicalize_facility_program(authored_geometry)
    assert exc.value.code == "facility_program_model_geometry_forbidden"

    unknown = deepcopy(program)
    unknown["unexpected"] = True
    with pytest.raises(FacilityProgramError) as exc:
        canonicalize_facility_program(unknown)
    assert exc.value.code == "facility_program_unknown_field"


def test_stage_slice_pages_without_silent_truncation() -> None:
    program = facility_program_from_full_factory(
        _full_factory_with_quantity(1), list(LOCAL_ASSET_CATALOG)
    )
    base = program["resource_batches"][0]
    program["resource_batches"] = []
    for index in range(80):
        item = deepcopy(base)
        item["batch_id"] = f"batch-{index:03d}"
        item["target_area"] = f"Area {index:03d}"
        program["resource_batches"].append(item)
    canonical = canonicalize_facility_program(program)

    cursor = 0
    seen = []
    while True:
        page = facility_program_stage_slice(
            canonical, "department_resources", cursor=cursor
        )
        assert len(canonical_facility_knowledge_bytes(page)) <= FACILITY_PROGRAM_STAGE_SLICE_BYTES
        seen.extend(item["value"]["batch_id"] for item in page["items"])
        if page["nextCursor"] is None:
            break
        assert page["nextCursor"] > cursor
        cursor = page["nextCursor"]
    assert seen == [f"batch-{index:03d}" for index in range(80)]
