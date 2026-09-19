from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge.evidence import (
    build_process_map_evidence_context,
)
from ai_inspector.assembly_knowledge.validation import (
    validate_assembly_knowledge_package,
)
from ai_inspector.process_map.repository import load_named_process_map
from ai_inspector.process_map.semantic_plan import (
    SemanticProcessPlanError,
    build_semantic_process_plan_from_evidence,
    build_stage_detail_semantic_process_plan,
    compile_semantic_process_plan,
)
from tools.build_mmle_synthetic_process_knowledge import build_documents


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PATH = ROOT / "tests/fixtures/mmle_50d_synthetic_process_expected.json"
TRAINING_ROOT = ROOT / "generated/training"
PRODUCT_ID = "mmle-50d-497533f6"


def _expected() -> dict:
    return json.loads(EXPECTED_PATH.read_text(encoding="ascii"))


def _resolved(documents: dict) -> dict:
    context = build_process_map_evidence_context(documents)
    identity = context["identity"]
    return {
        "documents": documents,
        "context": context,
        "binding": {
            key: identity[key]
            for key in (
                "packageId",
                "packageRevision",
                "sourceRevision",
                "evidenceFingerprint",
                "contextFingerprint",
                "readiness",
                "productionEligible",
            )
        },
    }


def _blank_map(loaded: dict, map_id: str = "stage-detail-test") -> dict:
    process_map = copy.deepcopy(loaded["map"])
    process_map["mapId"] = map_id
    process_map["canvasNodes"] = []
    process_map["canvasEdges"] = []
    process_map["canvasGroups"] = []
    return process_map


def test_synthetic_package_is_complete_nonproduction_and_deterministic():
    first, summary = build_documents(ROOT)
    second, second_summary = build_documents(ROOT)
    expected = _expected()

    assert summary == second_summary
    assert first == second
    assert summary["leafOccurrenceCount"] == expected["leafOccurrenceCount"]
    assert summary["operationCount"] == expected["operationCount"]
    assert summary["stageDetailCount"] == expected["stageDetailCount"]
    assert summary["stageDetailOperationCount"] == expected[
        "stageDetailOperationCount"
    ]
    assert summary["unresolvedQuestionCount"] == expected["unresolvedQuestionCount"]
    assert summary["workInstructionBenchmarkStageCount"] == 1
    assert summary["workInstructionBenchmarkOperationCount"] == 5
    assert first["package.json"]["readiness"] == "planning_ready"
    assert first["package.json"]["productionEligible"] is False
    assert not [
        item
        for item in validate_assembly_knowledge_package(first)
        if item.get("severity") == "error"
    ]
    assert any(
        item.get("code") == "synthetic_demo_process_evidence"
        for item in first["unresolved.json"]["findings"]
    )
    benchmark = first["process_candidates.json"]["workInstructionBenchmarks"][0]
    assert benchmark["stageOperationId"] == "op-build-lift-mechanism"
    assert benchmark["authorization"] == {
        "status": "approved_for_synthetic_demonstration",
        "approvedForSyntheticDemonstration": True,
        "manufacturingApproval": False,
        "controlledReleaseAuthority": False,
        "scope": "Stage 03 scissor lift mechanism benchmark only",
        "limitation": (
            "Values in this source are synthetic demonstration requirements and "
            "are not approved MMLE-50D production requirements."
        ),
    }
    assert len(benchmark["operationPages"]) == 5
    assert len(benchmark["benchmarkHash"]) == 64
    assert benchmark["sourceRef"].endswith("work-instruction-stage-03.json")
    exit_operation = benchmark["operationPages"][-1]
    assert exit_operation["operationId"] == "wi-lift-03e"
    assert exit_operation["transitionGate"] == {
        "gateId": "SYN-GATE-WI-003E",
        "targetStageOperationId": "op-install-lift-and-platform",
        "requiredCheckIds": [
            "SYN-QC-03E-01",
            "SYN-QC-03E-02",
            "SYN-QC-03E-03",
        ],
        "requiredRecordId": "SYN-FRM-WI-003E",
        "satisfiedState": "eligible_for_main_integration",
        "failureState": "hold_for_engineering_review",
        "blocking": True,
    }
    assert any(
        row["path"].endswith("work-instruction-stage-03.json")
        and row["kind"] == "work_instruction"
        and len(row["sha256"]) == 64
        for row in first["source_manifest.json"]["sources"]
    )


def test_held_out_topology_matches_source_derived_candidates():
    documents, _ = build_documents(ROOT)
    process = documents["process_candidates.json"]
    expected = _expected()
    actual = [
        {
            "id": item["operationId"],
            "label": item["label"],
            "predecessors": item["predecessorOperationIds"],
        }
        for item in process["operationFamilies"]
    ]

    assert process["presentation"]["mode"] == expected["presentationMode"]
    assert len(process["branches"]) == expected["branchCount"]
    assert actual == expected["stages"]
    consumed = [
        occurrence_id
        for operation in process["operationFamilies"]
        for occurrence_id in operation["inputRefs"]
    ]
    assert len(consumed) == expected["leafOccurrenceCount"]
    assert len(consumed) == len(set(consumed))


def test_sage_context_preserves_process_candidates_and_synthetic_limits():
    documents, _ = build_documents(ROOT)
    context = build_process_map_evidence_context(documents)
    expected = _expected()

    assert context["identity"]["readiness"] == "planning_ready"
    assert context["identity"]["productionEligible"] is False
    assert context["processCandidates"]["presentation"]["mode"] == "high_level"
    assert len(context["occurrences"]) == 1
    assert context["scope"]["occurrenceCatalogMode"] == "high_level_inputs"
    assert context["scope"]["requiredOccurrenceCount"] == expected[
        "leafOccurrenceCount"
    ]
    assert len(context["processCandidates"]["operationFamilies"]) == expected[
        "operationCount"
    ]
    assert len(context["processCandidates"]["stageDetailIndex"]) == expected[
        "stageDetailCount"
    ]
    assert all(
        set(item)
        == {
            "stageOperationId",
            "detailMapLabel",
            "resultLabel",
            "suboperationCount",
            "stageDetailHash",
            "available",
        }
        for item in context["processCandidates"]["stageDetailIndex"]
    )
    assert "stageDetails" not in context["processCandidates"]
    assert context["truncated"]["occurrences"] is False
    assert context["truncated"]["processCandidates"] is False
    assert len(context["requirements"]) == 13
    assert len(context["resources"]) == 8
    assert any(
        item.get("code") == "synthetic_demo_process_evidence"
        for item in context["findings"]
    )


def test_high_level_preview_covers_every_leaf_without_leaf_card_explosion():
    documents, _ = build_documents(ROOT)
    resolved = _resolved(documents)
    context = resolved["context"]
    scope_id = context["scope"]["rootOccurrenceId"]
    plan = build_semantic_process_plan_from_evidence(
        context,
        scope_occurrence_id=scope_id,
    )
    loaded = load_named_process_map(TRAINING_ROOT, PRODUCT_ID, "default")
    compiled = compile_semantic_process_plan(
        plan,
        scope_occurrence_id=scope_id,
        base_revision=loaded["revision"],
        process_map=_blank_map(loaded, map_id="high-level-test"),
        product_structure=loaded["productStructure"],
        structure_revision=loaded["structureRevision"],
        assembly_knowledge=resolved,
    )

    assert plan["scope"]["presentationMode"] == "high_level"
    assert len(plan["requiredOccurrences"]) == 206
    occurrence_inputs = [
        item["ref"]
        for operation in plan["operations"]
        for item in operation["inputs"]
        if item["type"] == "occurrence"
    ]
    assert len(occurrence_inputs) == 206
    assert len(occurrence_inputs) == len(set(occurrence_inputs))
    assert compiled["summary"]["requiredOccurrenceCount"] == 206
    assert compiled["summary"]["operationCount"] == 14
    assert sum(
        item.get("op") == "place_occurrence" for item in compiled["operations"]
    ) == 1
    assert sum(
        item.get("op") == "add_process_step" for item in compiled["operations"]
    ) == 14
    assert len(compiled["createdIds"]["nodeIds"]) <= 24
    positioned = [
        item["position"]
        for item in compiled["operations"]
        if item.get("op") in {"add_process_step", "place_occurrence"}
    ]
    assert max(item["x"] for item in positioned) <= 2800
    assert max(item["y"] for item in positioned) <= 1800


def test_high_level_context_fails_closed_when_candidate_coverage_is_incomplete():
    documents, _ = build_documents(ROOT)
    context = build_process_map_evidence_context(documents)
    tampered = copy.deepcopy(context)
    tampered["processCandidates"]["operationFamilies"][0]["inputRefs"].pop()

    with pytest.raises(SemanticProcessPlanError) as error:
        build_semantic_process_plan_from_evidence(
            tampered,
            scope_occurrence_id=context["scope"]["rootOccurrenceId"],
        )

    assert error.value.code == "process_candidate_occurrence_catalog_invalid"


def test_every_high_level_stage_has_one_compact_revision_bound_detail_record():
    documents, _ = build_documents(ROOT)
    process = documents["process_candidates.json"]
    expected = _expected()
    high_level = {
        item["operationId"]: item for item in process["operationFamilies"]
    }
    stage_details = process["stageDetails"]

    assert len(stage_details) == expected["stageDetailCount"]
    assert {item["stageOperationId"] for item in stage_details} == set(high_level)
    assert sum(len(item["operationFamilies"]) for item in stage_details) == expected[
        "stageDetailOperationCount"
    ]
    assert all(
        high_level[item["stageOperationId"]]["stageDetailAvailable"] is True
        and high_level[item["stageOperationId"]]["stageDetailStepCount"]
        == len(item["operationFamilies"])
        and high_level[item["stageOperationId"]]["stageDetailHash"]
        == item["stageDetailHash"]
        for item in stage_details
    )
    assert all(
        len(item["stageDetailHash"]) == 64
        and set(item["stageDetailHash"]) <= set("0123456789abcdef")
        for item in stage_details
    )
    step_ids = [
        operation["operationId"]
        for item in stage_details
        for operation in item["operationFamilies"]
    ]
    assert len(step_ids) == len(set(step_ids))


def test_all_stage_details_compile_as_separate_compact_child_maps():
    documents, _ = build_documents(ROOT)
    resolved = _resolved(documents)
    loaded = load_named_process_map(TRAINING_ROOT, PRODUCT_ID, "default")
    scope_id = resolved["context"]["scope"]["rootOccurrenceId"]
    stage_details = documents["process_candidates.json"]["stageDetails"]

    for stage in stage_details:
        plan = build_stage_detail_semantic_process_plan(
            resolved,
            scope_occurrence_id=scope_id,
            stage_operation_id=stage["stageOperationId"],
        )
        compiled = compile_semantic_process_plan(
            plan,
            scope_occurrence_id=scope_id,
            base_revision=loaded["revision"],
            process_map=_blank_map(
                loaded,
                map_id=f"detail-{stage['stageOperationId']}",
            ),
            product_structure=loaded["productStructure"],
            structure_revision=loaded["structureRevision"],
            assembly_knowledge=resolved,
        )

        occurrence_inputs = [
            item["ref"]
            for operation in plan["operations"]
            for item in operation["inputs"]
            if item["type"] == "occurrence"
        ]
        assert plan["scope"]["presentationMode"] == "stage_detail"
        assert plan["scope"]["stageOperationId"] == stage["stageOperationId"]
        assert plan["scope"]["stageDetailHash"] == stage["stageDetailHash"]
        assert sorted(occurrence_inputs) == sorted(stage["requiredOccurrenceIds"])
        assert len(occurrence_inputs) == len(set(occurrence_inputs))
        assert compiled["summary"]["requiredOccurrenceCount"] == len(
            stage["requiredOccurrenceIds"]
        )
        assert compiled["summary"]["operationCount"] == len(
            stage["operationFamilies"]
        )
        assert sum(
            item.get("op") == "place_occurrence"
            for item in compiled["operations"]
        ) == 1
        assert sum(
            item.get("op") == "add_process_step"
            for item in compiled["operations"]
        ) == len(stage["operationFamilies"])
        result_card = next(
            item
            for item in compiled["operations"]
            if item.get("op") == "place_occurrence"
        )
        assert result_card["label"] == stage["resultLabel"]


@pytest.mark.parametrize(
    ("tamper", "finding_code"),
    [
        ("hash", "stage_detail_binding_mismatch"),
        ("label", "stage_detail_operation_content_mismatch"),
        ("occurrence", "required_occurrence_coverage_missing"),
    ],
)
def test_stage_detail_plans_reject_stale_or_modified_evidence(tamper, finding_code):
    documents, _ = build_documents(ROOT)
    resolved = _resolved(documents)
    loaded = load_named_process_map(TRAINING_ROOT, PRODUCT_ID, "default")
    scope_id = resolved["context"]["scope"]["rootOccurrenceId"]
    stage = documents["process_candidates.json"]["stageDetails"][0]
    plan = build_stage_detail_semantic_process_plan(
        resolved,
        scope_occurrence_id=scope_id,
        stage_operation_id=stage["stageOperationId"],
    )
    modified = copy.deepcopy(plan)
    if tamper == "hash":
        modified["scope"]["stageDetailHash"] = "0" * 64
    elif tamper == "label":
        modified["operations"][0]["label"] = "Untrusted replacement step"
    else:
        modified["requiredOccurrences"].pop()

    with pytest.raises(SemanticProcessPlanError) as error:
        compile_semantic_process_plan(
            modified,
            scope_occurrence_id=scope_id,
            base_revision=loaded["revision"],
            process_map=_blank_map(loaded),
            product_structure=loaded["productStructure"],
            structure_revision=loaded["structureRevision"],
            assembly_knowledge=resolved,
        )

    assert error.value.code == "semantic_plan_invalid"
    assert finding_code in {
        item["code"] for item in error.value.findings if item["severity"] == "error"
    }


def test_stage_detail_editor_contract_exposes_review_before_commit_navigation():
    editor_source = (ROOT / "static/process_map_editor.js").read_text(
        encoding="utf-8"
    )
    index_source = (ROOT / "static/index.html").read_text(encoding="utf-8")

    assert "onOpenStageDetail" in editor_source
    assert "openStageDetail" in editor_source
    assert "pm-stage-detail-action" in editor_source
    assert "Open details" in editor_source
    assert "openSelectedStageDetail" in editor_source
    assert "openStageDetail'" in editor_source
    assert "stageDetailOperationIds.has(semanticRef)" in editor_source
    assert "semanticRef.indexOf('op-')" not in editor_source
    assert "relation === 'stage_detail'" in editor_source
    assert "parentMapId" in editor_source
    assert "stage-detail-proposals" in index_source
    assert "_trainOpenProcessFlowStageDetail" in index_source
    assert "parentStageOperationId" in (ROOT / "server.py").read_text(
        encoding="utf-8-sig"
    )
