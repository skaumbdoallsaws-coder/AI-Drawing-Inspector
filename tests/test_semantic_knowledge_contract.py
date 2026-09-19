from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge.functional_catalog import (
    adapt_functional_catalog,
)
from ai_inspector.assembly_knowledge.semantic_contract import (
    SemanticContractError,
    bounded_retrieval_claims,
    enforce_claim_write_policy,
    package_retrieval_decision,
    translate_legacy_authority,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = (
    ROOT / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"
)


def _documents() -> dict:
    graph = json.loads(CATALOG_PATH.read_text(encoding="ascii"))
    return adapt_functional_catalog(graph, repo_root=ROOT)


def _claim(**updates) -> dict:
    claim = {
        "claimId": "claim-policy-fixture",
        "subjectRef": "occurrence-root",
        "predicate": "occurrence_role",
        "objectRefs": [],
        "value": {"role": "fixture"},
        "knowledgeStatus": "inferred",
        "authority": "supporting",
        "evidenceRefs": ["evidence-fixture"],
        "assumptionIds": [],
        "generatedBy": {
            "kind": "model",
            "generatorId": "provider-model",
            "version": "1",
        },
        "reviewStatus": "pending",
    }
    claim.update(updates)
    return claim


def test_legacy_authority_translation_is_explicit_and_excludes_continuity() -> None:
    assert translate_legacy_authority("cad_constraint") == ("derived", "supporting")
    assert translate_legacy_authority("curated_profile") == ("authored", "supporting")
    with pytest.raises(SemanticContractError) as exc_info:
        translate_legacy_authority("untrusted_continuity")
    assert exc_info.value.code == "continuity_authority_not_adapted"


def test_model_writer_cannot_promote_its_own_claim() -> None:
    result = enforce_claim_write_policy(
        _claim(authority="approved", reviewStatus="confirmed"),
        evidence_by_id={"evidence-fixture": {"authority": "approved"}},
        authenticated_actor=True,
        review_events=[
            {
                "claimId": "claim-policy-fixture",
                "action": "confirm",
                "actor": "reviewer-1",
            }
        ],
    )
    assert result["knowledgeStatus"] == "inferred"
    assert result["authority"] == "supporting"
    assert result["reviewStatus"] == "pending"


def test_synthetic_writer_is_forced_to_illustrative_pending() -> None:
    claim = _claim(
        authority="authored",
        knowledgeStatus="authored",
        reviewStatus="confirmed",
        generatedBy={
            "kind": "deterministic",
            "generatorId": "synthetic-process-fixture-builder",
            "version": "1",
        },
    )
    result = enforce_claim_write_policy(
        claim,
        evidence_by_id={"evidence-fixture": {"authority": "authored"}},
    )
    assert result["knowledgeStatus"] == "authored"
    assert result["authority"] == "illustrative"
    assert result["reviewStatus"] == "pending"


def test_human_authority_requires_actor_review_and_matching_evidence() -> None:
    user_claim = _claim(
        authority="authored",
        knowledgeStatus="authored",
        reviewStatus="confirmed",
        generatedBy={
            "kind": "user",
            "generatorId": "authenticated-reviewer",
            "version": "1",
        },
    )
    with pytest.raises(SemanticContractError) as exc_info:
        enforce_claim_write_policy(
            user_claim,
            evidence_by_id={"evidence-fixture": {"authority": "authored"}},
            authenticated_actor=False,
            review_events=[],
        )
    assert exc_info.value.code == "authority_promotion_requires_authenticated_user"

    result = enforce_claim_write_policy(
        user_claim,
        evidence_by_id={"evidence-fixture": {"authority": "authored"}},
        authenticated_actor=True,
        review_events=[
            {
                "claimId": "claim-policy-fixture",
                "action": "confirm",
                "actor": "reviewer-1",
            }
        ],
    )
    assert result["authority"] == "authored"
    assert result["reviewStatus"] == "confirmed"


def test_nonproduction_retrieval_requires_explicit_prototype_mode() -> None:
    documents = _documents()
    package = documents["package.json"]
    denied = package_retrieval_decision(
        package,
        prototype_mode=False,
        source_current=True,
    )
    allowed = package_retrieval_decision(
        package,
        prototype_mode=True,
        source_current=True,
    )
    controlled = package_retrieval_decision(
        package,
        prototype_mode=True,
        controlled_use=True,
        source_current=True,
    )
    assert (denied.eligible, denied.code) == (False, "prototype_mode_required")
    assert (allowed.eligible, allowed.code) == (True, "prototype_eligible")
    assert (controlled.eligible, controlled.code) == (
        False,
        "controlled_package_not_eligible",
    )


def test_bounded_retrieval_filters_and_reports_truncation() -> None:
    documents = _documents()
    selected, diagnostics = bounded_retrieval_claims(
        documents,
        prototype_mode=True,
        max_claims=3,
        max_rendered_characters=100_000,
    )
    assert len(selected) == 3
    assert diagnostics["eligible"] is True
    assert diagnostics["candidateCount"] > 3
    assert diagnostics["returnedCount"] == 3
    assert diagnostics["truncated"] is True

    rejected = copy.deepcopy(documents)
    rejected["functional_context.json"]["claims"][0]["reviewStatus"] = "rejected"
    filtered, filtered_diagnostics = bounded_retrieval_claims(
        rejected,
        prototype_mode=True,
        max_claims=200,
        max_rendered_characters=1_000_000,
    )
    assert len(filtered) == filtered_diagnostics["candidateCount"]
    assert all(item["reviewStatus"] != "rejected" for item in filtered)
