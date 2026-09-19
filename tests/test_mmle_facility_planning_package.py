from __future__ import annotations

from pathlib import Path

import pytest

from ai_inspector.facility_layout.facility_planning import (
    analyze_facility_planning_impact,
    compile_facility_planning_package,
    facility_planning_model_summary,
)
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.program_execution import (
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)
from tools.build_mmle_facility_planning_package import (
    build_mmle_facility_planning_package,
)


ROOT = Path(__file__).resolve().parents[1]


def _base() -> dict:
    return create_layout_document(
        layout_id="fl-mmle-planning",
        display_name="Blank Facility",
        association={"siteId": "site-local", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "local-origin",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-local",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-local",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-29T21:00:00Z",
    )


def test_mmle_package_is_traceable_nonproduction_and_reference_scale() -> None:
    catalog = build_private_local_asset_catalog(ROOT)
    package = build_mmle_facility_planning_package(ROOT, asset_catalog=catalog)
    compiled = compile_facility_planning_package(package, catalog)
    summary = facility_planning_model_summary(compiled)

    assert package["authority"] == {
        "knowledgeStatus": "inferred",
        "authority": "illustrative",
        "reviewStatus": "pending",
        "productionEligible": False,
        "planningClaim": "illustrative_prototype",
        "reviewReceiptId": None,
    }
    assert len(package["processSteps"]) == 20
    assert len(package["departments"]) == 6
    assert sum(len(item["labels"]) for item in package["areaGroups"]) == 39
    assert len(package["routes"]) == 8
    assert compiled["blockingFindingCount"] == 0
    assert summary["status"] == "prototype_ready"
    assert summary["productionEligible"] is False
    assert all(item["authority"] != "controlled" for item in package["evidenceRegister"])


def test_mmle_package_compiles_to_45_zones_8_routes_827_assets_50_markings() -> None:
    catalog = build_private_local_asset_catalog(ROOT)
    package = build_mmle_facility_planning_package(ROOT, asset_catalog=catalog)
    compiled = compile_facility_planning_package(package, catalog)
    try:
        plan = compile_facility_program_operation_plan(
            compiled["facilityProgram"], _base(), catalog
        )
    except Exception as exc:
        pytest.fail(f"{type(exc).__name__}: {getattr(exc, 'details', {})}")

    assert plan["expectedCounts"] == {
        "zones": 45,
        "routes": 8,
        "placements": 827,
        "floorMarkings": 50,
    }
    try:
        result = execute_facility_program_operation_plan(_base(), plan)
    except Exception as exc:
        pytest.fail(f"{type(exc).__name__}: {getattr(exc, 'details', {})}")
    assert result["counts"] == plan["expectedCounts"]
    assert result["saved"] is False
    assert result["undoLayout"] == _base()


def test_mmle_process_change_invalidates_only_downstream_scopes() -> None:
    package = build_mmle_facility_planning_package(
        ROOT, asset_catalog=build_private_local_asset_catalog(ROOT)
    )
    impact = analyze_facility_planning_impact(package, ["op-build-hydraulic-cylinder"])

    assert "assembly-kitting" in impact["affectedDepartmentIds"]
    assert "receiving-raw-material" not in impact["affectedDepartmentIds"]
    assert "machining-hall" not in impact["affectedDepartmentIds"]
    assert "department_resources" in impact["affectedStageIds"]
