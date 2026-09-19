from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.industrial_patterns import INDUSTRIAL_PATTERN_IDS
from ai_inspector.facility_layout.reference_generation import (
    FacilityReferenceGenerationError,
    compile_reference_reproduction_plan,
    execute_reference_reproduction_plan,
    facility_program_from_reference_manifest,
    topologically_order_reference_placements,
)
from ai_inspector.facility_layout.reference_quality import approve_reference_manifest
from ai_inspector.facility_layout.operations import create_layout_document


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/facility_layout/reference_quality/reference-manifest-v1.json"
SOURCE_PATH = ROOT / ".runtime/facility-layout/layouts/local/site-local/layouts/fl-reference-manual-20260812.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pending_reference_review_cannot_compile_a_reproduction_program() -> None:
    manifest = _load(MANIFEST_PATH)
    source = _load(SOURCE_PATH)
    pending = {
        "schemaVersion": "facility-reference-review-receipt-v1",
        "manifestRevision": manifest["manifestRevision"],
        "reviewStatus": "pending",
        "approvalRequested": False,
        "approvalEligible": True,
        "unresolvedCount": 0,
        "reviewedAt": None,
    }
    with pytest.raises(FacilityReferenceGenerationError) as exc:
        facility_program_from_reference_manifest(manifest, pending, source)
    assert exc.value.code == "reference_review_required"


def test_reviewed_reference_is_losslessly_represented_without_coordinates() -> None:
    manifest = _load(MANIFEST_PATH)
    source = _load(SOURCE_PATH)
    receipt = approve_reference_manifest(
        manifest,
        approver="Shadrack",
        reviewed_at="2026-08-29T17:00:00Z",
    )
    program = facility_program_from_reference_manifest(manifest, receipt, source)

    assert sum(item["quantity"] for item in program["resource_batches"]) == 827
    assert len(program["resource_batches"]) == 153
    assert len(program["macro_departments"]) == 6
    assert len(program["area_hierarchy"]) == 39
    assert len(program["route_network"]["primary_routes"]) == 8
    assert len(program["floor_communication"]) == 50
    assert len(program["cell_recipes"]) == 7
    assert len(program["module_families"]) == 7
    assert program["authority_and_mode"]["production_eligible"] is False
    assert {
        item["placement_pattern"] for item in program["resource_batches"]
    } <= set(INDUSTRIAL_PATTERN_IDS)

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert not ({"x", "y", "z", "position", "transform", "boundary", "centerline"} & set(value))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(program)


def test_support_dependencies_are_topologically_ordered_and_cycles_fail() -> None:
    values = [
        {"placementId": "dependent", "snapRelationship": {"supportPlacementId": "support"}},
        {"placementId": "unrelated", "snapRelationship": None},
        {"placementId": "support", "snapRelationship": None},
    ]
    ordered = topologically_order_reference_placements(values)
    ids = [item["placementId"] for item in ordered]
    assert ids.index("support") < ids.index("dependent")

    cyclic = [
        {"placementId": "a", "snapRelationship": {"supportPlacementId": "b"}},
        {"placementId": "b", "snapRelationship": {"supportPlacementId": "a"}},
    ]
    with pytest.raises(FacilityReferenceGenerationError) as exc:
        topologically_order_reference_placements(cyclic)
    assert exc.value.code == "reference_support_cycle"


def test_reference_plan_builds_the_complete_unsaved_factory() -> None:
    manifest = _load(MANIFEST_PATH)
    source = _load(SOURCE_PATH)
    receipt = approve_reference_manifest(
        manifest,
        approver="Shadrack",
        reviewed_at="2026-08-29T17:00:00Z",
    )
    program = facility_program_from_reference_manifest(manifest, receipt, source)
    plan = compile_reference_reproduction_plan(program, manifest, receipt, source)
    resource_stage = next(
        item for item in plan["stages"] if item["stageId"] == "department_resources"
    )
    assert [item["plannedInstanceCount"] for item in resource_stage["batches"]] == [500, 327]
    assert all(item["operationCount"] <= 500 for item in resource_stage["batches"])

    base = create_layout_document(
        layout_id="fl-reference-rq-draft",
        display_name="Blank Facility",
        association=source["association"],
        coordinate_frame=source["coordinateFrame"],
        source_shell_ref=source["sourceShellRef"],
        policy_set_ref=source["policySetRef"],
        created_at="2026-08-29T17:00:00Z",
    )
    result = execute_reference_reproduction_plan(base, plan, source)

    assert result["status"] == "complete"
    assert result["saved"] is False
    assert result["undoLayout"] == base
    assert result["validation"]["status"] == "valid"
    assert len(result["draftLayout"]["zones"]) == 45
    assert len(result["draftLayout"]["routes"]) == 8
    assert len(result["draftLayout"]["placements"]) == 827
    assert len(result["draftLayout"]["floorMarkings"]) == 50
    assert len(result["receiptChain"]) == 11
