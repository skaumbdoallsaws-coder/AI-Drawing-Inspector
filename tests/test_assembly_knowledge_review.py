from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeReviewError,
    adapt_bridge_package,
    apply_review_action,
    authorize_enrichment_plan,
    build_review_queue,
    compile_deterministic_evidence,
    execute_economy_enrichment,
    plan_enrichment_request,
    validate_assembly_knowledge_package,
)
from ai_inspector.assembly_knowledge.enrichment import ENRICHMENT_PROMPT_VERSION
from ai_inspector.assembly_knowledge.provider import FixtureMultimodalProvider


PACKAGE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)
RESPONSE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "enrichment"
    / "economy_response.json"
)


def _base_documents(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    return compile_deterministic_evidence(
        adapt_bridge_package(
            PACKAGE_FIXTURE,
            source_root=source,
            root_assembly=root,
            product_id="tricycle",
        ).documents
    )


def _enriched_documents(tmp_path: Path):
    documents = _base_documents(tmp_path)
    documents["package.json"]["assetHashes"] = {
        "visuals/presentation/contact-sheet.png": "1" * 64,
    }
    documents["visual_manifest.json"]["contactSheets"] = [
        {
            "contactSheetId": "sheet-1",
            "assetPath": "visuals/presentation/contact-sheet.png",
            "assetHash": "1" * 64,
            "width": 1800,
            "height": 1300,
            "viewIds": [],
        }
    ]
    documents["visual_manifest.json"]["views"] = []
    plan = plan_enrichment_request(
        documents,
        provider="fixture",
        model="fixture-model-v1",
        prompt_version=ENRICHMENT_PROMPT_VERSION,
    )
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-review-enrichment-1",
        unknown_pricing_acknowledged=True,
    )
    response = json.loads(RESPONSE_FIXTURE.read_text(encoding="ascii"))
    return execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=FixtureMultimodalProvider([response]),
    )["documents"]


def _first_pending_claim(documents):
    return next(
        item
        for name in ("functional_context.json", "process_candidates.json")
        for item in documents[name]["claims"]
        if item["reviewStatus"] == "pending"
    )


def test_deterministic_package_has_no_cross_document_errors(tmp_path: Path) -> None:
    findings = validate_assembly_knowledge_package(_base_documents(tmp_path))
    assert not [item for item in findings if item["severity"] == "error"]


def test_enriched_package_is_valid_but_inferred_claims_are_reviewable(
    tmp_path: Path,
) -> None:
    documents = _enriched_documents(tmp_path)
    findings = validate_assembly_knowledge_package(documents)
    assert not [item for item in findings if item["severity"] == "error"]
    assert any(
        item["code"] == "inferred_claim_pending_review" for item in findings
    )
    queue = build_review_queue(documents)
    assert queue["summary"]["valid"] is True
    assert queue["summary"]["pendingClaimCount"] > 0
    assert queue["items"][0]["predicate"] in {
        "candidate_process_branch",
        "candidate_operation_family",
    }
    assert queue["items"][0]["actions"] == [
        "confirm",
        "edit",
        "reject",
        "mark_unknown",
        "defer",
    ]


def test_model_cannot_be_promoted_to_authoritative_by_mutating_json(
    tmp_path: Path,
) -> None:
    documents = _enriched_documents(tmp_path)
    claim = _first_pending_claim(documents)
    claim["authority"] = "approved"
    claim["knowledgeStatus"] = "authored"
    findings = validate_assembly_knowledge_package(documents)
    codes = {item["code"] for item in findings if item["severity"] == "error"}
    assert "model_claim_authority_violation" in codes
    assert "unsupported_authoritative_claim" in codes


def test_numeric_manufacturing_value_requires_exact_authority(
    tmp_path: Path,
) -> None:
    documents = _enriched_documents(tmp_path)
    claim = copy.deepcopy(_first_pending_claim(documents))
    claim["claimId"] = "claim-numeric-manufacturing"
    claim["predicate"] = "torque_setting"
    claim["value"] = {"newtonMeters": 8}
    documents["process_candidates.json"]["claims"].append(claim)
    findings = validate_assembly_knowledge_package(documents)
    assert any(
        item["code"] == "unsupported_numeric_manufacturing_value"
        for item in findings
    )


def test_operation_cycle_is_rejected(tmp_path: Path) -> None:
    documents = _enriched_documents(tmp_path)
    operations = documents["process_candidates.json"]["operationFamilies"]
    first = operations[0]
    duplicate = copy.deepcopy(first)
    duplicate["operationId"] = "operation-second"
    duplicate["claimId"] = "claim-operation-second"
    first["predecessorOperationIds"] = ["operation-second"]
    duplicate["predecessorOperationIds"] = [first["operationId"]]
    operations.append(duplicate)
    findings = validate_assembly_knowledge_package(documents)
    assert any(item["code"] == "process_candidate_cycle" for item in findings)


def test_confirm_is_auditable_without_promoting_authority(tmp_path: Path) -> None:
    documents = _enriched_documents(tmp_path)
    claim = _first_pending_claim(documents)
    reviewed = apply_review_action(
        documents,
        base_revision=documents["package.json"]["packageRevision"],
        source_revision=documents["package.json"]["sourceRevision"],
        claim_id=claim["claimId"],
        action="confirm",
        actor="fixture-reviewer",
        timestamp="2026-07-25T12:00:00Z",
    )
    updated = next(
        item
        for name in ("functional_context.json", "process_candidates.json")
        for item in reviewed[name]["claims"]
        if item["claimId"] == claim["claimId"]
    )
    assert updated["reviewStatus"] == "confirmed"
    assert updated["knowledgeStatus"] == "inferred"
    assert updated["authority"] == "supporting"
    event = reviewed["review_receipt.json"]["events"][-1]
    assert event["before"]["reviewStatus"] == "pending"
    assert event["after"]["reviewStatus"] == "confirmed"
    assert reviewed["package.json"]["packageRevision"] != documents["package.json"][
        "packageRevision"
    ]


def test_edit_syncs_structured_record_and_mark_unknown_clears_value(
    tmp_path: Path,
) -> None:
    documents = _enriched_documents(tmp_path)
    operation_claim = next(
        item
        for item in documents["process_candidates.json"]["claims"]
        if item["predicate"] == "candidate_operation_family"
    )
    edited_value = {
        **operation_claim["value"],
        "label": "Reviewed wheel installation",
    }
    edited = apply_review_action(
        documents,
        base_revision=documents["package.json"]["packageRevision"],
        source_revision=documents["package.json"]["sourceRevision"],
        claim_id=operation_claim["claimId"],
        action="edit",
        actor="fixture-reviewer",
        edited_value=edited_value,
        timestamp="2026-07-25T12:01:00Z",
    )
    operation = next(
        item
        for item in edited["process_candidates.json"]["operationFamilies"]
        if item["claimId"] == operation_claim["claimId"]
    )
    assert operation["label"] == "Reviewed wheel installation"
    assert operation["reviewStatus"] == "edited"

    next_claim = _first_pending_claim(edited)
    unknown = apply_review_action(
        edited,
        base_revision=edited["package.json"]["packageRevision"],
        source_revision=edited["package.json"]["sourceRevision"],
        claim_id=next_claim["claimId"],
        action="mark_unknown",
        actor="fixture-reviewer",
        timestamp="2026-07-25T12:02:00Z",
    )
    updated = next(
        item
        for name in ("functional_context.json", "process_candidates.json")
        for item in unknown[name]["claims"]
        if item["claimId"] == next_claim["claimId"]
    )
    assert updated["reviewStatus"] == "unknown"
    assert updated["knowledgeStatus"] == "unknown"
    assert updated["value"] is None


def test_stale_package_or_source_revision_blocks_review(tmp_path: Path) -> None:
    documents = _enriched_documents(tmp_path)
    claim = _first_pending_claim(documents)
    with pytest.raises(AssemblyKnowledgeReviewError) as stale_package:
        apply_review_action(
            documents,
            base_revision="f" * 64,
            source_revision=documents["package.json"]["sourceRevision"],
            claim_id=claim["claimId"],
            action="confirm",
            actor="fixture-reviewer",
        )
    assert stale_package.value.code == "stale_package_revision"
    with pytest.raises(AssemblyKnowledgeReviewError) as stale_source:
        apply_review_action(
            documents,
            base_revision=documents["package.json"]["packageRevision"],
            source_revision="f" * 64,
            claim_id=claim["claimId"],
            action="confirm",
            actor="fixture-reviewer",
        )
    assert stale_source.value.code == "stale_source_revision"
