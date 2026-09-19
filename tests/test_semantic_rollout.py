from __future__ import annotations

from pathlib import Path

from ai_inspector.assembly_knowledge.repository import AssemblyKnowledgeRepository
from ai_inspector.assembly_knowledge.semantic_rollout import (
    MMLE_PACKAGE_ID,
    MMLE_PRODUCT_ID,
    authority_audit,
    remediate_synthetic_authority,
)
from ai_inspector.assembly_knowledge.semantic_pilot import (
    SEMANTIC_PILOT_VERSION,
    build_mmle_semantic_pilot_plan,
    select_mmle_pilot_occurrences,
)
from ai_inspector.assembly_knowledge.semantic_review import (
    build_semantic_pilot_review_queue,
)
from ai_inspector.assembly_knowledge.validation import (
    validate_assembly_knowledge_package,
)


ROOT = Path(__file__).resolve().parents[1]


def _current_documents() -> dict:
    repository = AssemblyKnowledgeRepository(ROOT / "generated" / "training")
    return repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)


def test_synthetic_authority_remediation_is_nonproduction_and_valid() -> None:
    source = _current_documents()
    corrected = remediate_synthetic_authority(source)
    audit = authority_audit(corrected)

    assert audit["syntheticClaimCount"] == 93
    assert audit["syntheticNonIllustrativeCount"] == 0
    assert audit["syntheticFalseConfirmationCount"] == 0
    assert audit["evidenceAuthorityCounts"]["illustrative"] == 7
    assert audit["evidenceAuthorityCounts"]["supporting"] >= 1
    assert audit["readiness"] == "structure_ready"
    assert audit["productionEligible"] is False
    assert not [
        item
        for item in validate_assembly_knowledge_package(corrected)
        if item["severity"] == "error"
    ]


def test_synthetic_authority_remediation_is_content_idempotent() -> None:
    first = remediate_synthetic_authority(_current_documents())
    second = remediate_synthetic_authority(first)
    assert second == first


def test_mmle_semantic_pilot_is_representative_and_economy_bounded() -> None:
    documents = _current_documents()
    selected = select_mmle_pilot_occurrences(documents)
    categories = {item["category"] for item in selected}
    assert len(selected) == 18
    assert {
        "lift_mechanism",
        "hydraulic_cylinder",
        "hydraulic_power_module",
        "swivel_caster",
        "battery_module",
        "charger",
    } <= categories

    planned, plan, authorization = build_mmle_semantic_pilot_plan(documents)
    assert planned == selected
    assert plan["taskMode"] == "semantic_pilot"
    assert plan["changedOccurrenceCount"] == 18
    assert plan["estimatedInputTokensPerCall"] <= 24_000
    assert plan["maximumOutputTokensPerCall"] <= 6_000
    assert plan["plannedCalls"] == 1
    assert plan["maximumCalls"] == 2
    assert plan["estimatedMaximumCostUsd"] <= 0.50
    assert authorization["authorized"] is True
    assert "api" not in str(authorization).lower()


def test_semantic_review_queue_is_bounded_without_authority_promotion() -> None:
    queue = build_semantic_pilot_review_queue(
        _current_documents(),
        prompt_version=SEMANTIC_PILOT_VERSION,
    )
    summary = queue["summary"]
    assert summary["totalPilotClaimCount"] == 7
    assert summary["pilotPendingClaimCount"] == 0
    assert summary["reviewedPilotClaimCount"] == 7
    assert summary["outsidePilotPendingClaimCount"] == 93
    assert summary["reviewCapPassed"] is True
    assert summary["humanAuthorityGranted"] is False
    assert summary["pendingHighImpactClaimCount"] == 0
    assert queue["items"] == []
