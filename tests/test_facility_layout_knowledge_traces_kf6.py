from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
    FacilityKnowledgeContractError,
)
from ai_inspector.facility_layout.knowledge_traces import (
    compile_facility_trace_context,
    evaluate_held_out_command_families,
    load_facility_trace_evidence,
    validate_gold_trace_bundle,
    validate_held_out_case_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_existing_cases_remain_regression_visible_not_held_out() -> None:
    evidence = load_facility_trace_evidence(REPO_ROOT)
    assert evidence["regressionVisible"]["caseCount"] == 71
    assert evidence["regressionVisible"]["classification"] == (
        "regression_visible_not_held_out"
    )
    assert evidence["regressionVisible"]["heldOut"] is False


def test_gold_traces_cover_required_kinds_without_production_authority() -> None:
    traces = load_facility_trace_evidence(REPO_ROOT)["goldTraces"]
    assert {item["traceKind"] for item in traces["traces"]} == {
        "positive",
        "negative",
        "correction",
        "live_modification",
    }
    assert traces["sourceReference"]["placementCount"] == 827
    assert traces["sourceReference"]["coordinateContentCopied"] is False
    assert all(item["illustrative"] is True for item in traces["traces"])
    assert all(item["productionEvidence"] is False for item in traces["traces"])


def test_gold_trace_rejects_literal_world_geometry() -> None:
    traces = load_facility_trace_evidence(REPO_ROOT)["goldTraces"]
    tampered = deepcopy(traces)
    tampered["traces"][0]["semanticConstraints"]["x"] = 12.0
    from ai_inspector.facility_layout.knowledge_foundation import (
        canonical_facility_knowledge_bytes,
    )
    import hashlib

    tampered["traceContentSha256"] = hashlib.sha256(
        canonical_facility_knowledge_bytes(tampered["traces"])
    ).hexdigest()
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        validate_gold_trace_bundle(tampered)
    assert exc.value.code == "facility_trace_literal_geometry_forbidden"


def test_trace_and_held_out_content_hashes_fail_closed() -> None:
    evidence = load_facility_trace_evidence(REPO_ROOT)
    traces = deepcopy(evidence["goldTraces"])
    traces["traces"][0]["userIntent"] += " changed"
    with pytest.raises(FacilityKnowledgeContractError) as trace_exc:
        validate_gold_trace_bundle(traces)
    assert trace_exc.value.code == "facility_trace_hash_mismatch"

    held_out = deepcopy(evidence["heldOut"])
    held_out["cases"][0]["prompt"] += " changed"
    with pytest.raises(FacilityKnowledgeContractError) as held_exc:
        validate_held_out_case_bundle(held_out)
    assert held_exc.value.code == "facility_held_out_hash_mismatch"


def test_every_stage_retrieves_only_a_bounded_revision_bound_slice() -> None:
    for stage in FACILITY_GENERATION_STAGES:
        context = compile_facility_trace_context(REPO_ROOT, stage["stageId"])
        assert context["stageId"] == stage["stageId"]
        assert len(context["registryRevision"]) == 64
        assert len(context["traceContentSha256"]) == 64
        assert context["measurement"]["canonicalBytes"] <= 8_192
        assert context["measurement"]["estimatorId"] == "bytes4-v1"
        assert "placements" not in context


def test_g1_slice_contains_only_g1_eligible_examples() -> None:
    for stage_id in ("facility_envelope", "macro_departments", "review_and_save"):
        context = compile_facility_trace_context(
            REPO_ROOT,
            stage_id,
            g1_only=True,
        )
        assert context["traces"]
        assert all(item["g1Eligible"] is True for item in context["traces"])


def test_held_out_command_family_gate_is_above_95_percent() -> None:
    held_out = load_facility_trace_evidence(REPO_ROOT)["heldOut"]
    result = evaluate_held_out_command_families(held_out)
    assert result["caseCount"] == 20
    assert result["passPercent"] >= 95.0
    assert result["failedCount"] == 0


def test_trace_context_overflow_reports_stage_and_trace_ids() -> None:
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        compile_facility_trace_context(
            REPO_ROOT,
            "macro_departments",
            maximum_bytes=512,
        )
    assert exc.value.code == "facility_trace_context_too_large"
    assert exc.value.details["stageId"] == "macro_departments"
    assert exc.value.details["traceIds"]
