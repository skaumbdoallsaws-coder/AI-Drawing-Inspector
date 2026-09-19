from __future__ import annotations

import json
import shutil
from pathlib import Path

from ai_inspector.assembly_knowledge.repository import AssemblyKnowledgeRepository
from ai_inspector.assembly_knowledge.semantic_human_review import (
    MMLE_PACKAGE_ID,
    MMLE_PRODUCT_ID,
    record_semantic_human_review,
)
from ai_inspector.assembly_knowledge.semantic_pilot import SEMANTIC_PILOT_VERSION
from ai_inspector.assembly_knowledge.semantic_review import (
    build_semantic_pilot_review_queue,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_review_fixture(target: Path) -> None:
    current_package = (
        REPO_ROOT
        / "generated"
        / "training"
        / MMLE_PRODUCT_ID
        / "assembly_knowledge"
        / MMLE_PACKAGE_ID
    )
    package_source = current_package / ".backups" / "rev-b1792b0f9303062e"
    package_target = (
        target
        / "generated"
        / "training"
        / MMLE_PRODUCT_ID
        / "assembly_knowledge"
        / MMLE_PACKAGE_ID
    )
    shutil.copytree(
        package_source,
        package_target,
    )

    docs_target = target / "docs" / "semantic-knowledge"
    docs_target.mkdir(parents=True)
    for name in (
        "baseline-query-set.json",
        "functional-catalog-parity.json",
        "mmle-semantic-review-queue.json",
        "runtime-provider-migration-report.json",
        "synthetic-scenario-factory-report.json",
        "review-ledger.json",
    ):
        shutil.copy2(REPO_ROOT / "docs" / "semantic-knowledge" / name, docs_target / name)

    runtime_source = REPO_ROOT / ".runtime" / "semantic-knowledge-rollout"
    runtime_target = target / ".runtime" / "semantic-knowledge-rollout"
    shutil.copytree(runtime_source / "scenarios", runtime_target / "scenarios")
    shutil.copytree(runtime_source / "checkpoints", runtime_target / "checkpoints")

    repository = AssemblyKnowledgeRepository(target / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    queue = build_semantic_pilot_review_queue(
        documents,
        prompt_version=SEMANTIC_PILOT_VERSION,
    )
    (docs_target / "mmle-semantic-review-queue.json").write_text(
        json.dumps(queue, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def test_explicit_review_closes_human_gates_without_authority_promotion(tmp_path: Path) -> None:
    _copy_review_fixture(tmp_path)
    result = record_semantic_human_review(
        tmp_path,
        reviewer="workspace_owner",
        attestation="Everything has been reviewed and looks good.",
        reviewed_at="2026-08-26T12:00:00Z",
    )

    assert result["status"] == "review_complete"
    assert result["reviewedCounts"] == {
        "baseline": 35,
        "claims": 7,
        "rescoring": 15,
        "gold": 48,
        "paraphrases": 40,
    }
    receipt = result["receipt"]
    assert receipt["humanAuthorityGranted"] is False
    assert receipt["controlledAuthorityGranted"] is False
    assert receipt["catalogRetirementAuthorized"] is False

    repository = AssemblyKnowledgeRepository(tmp_path / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    reviewed_claim_ids = set(receipt["packageReview"]["confirmedClaimIds"])
    claims = [
        claim
        for name in ("functional_context.json", "process_candidates.json")
        for claim in documents[name].get("claims", [])
        if claim.get("claimId") in reviewed_claim_ids
    ]
    assert len(claims) == 7
    assert {claim["reviewStatus"] for claim in claims} == {"confirmed"}
    assert {claim["knowledgeStatus"] for claim in claims} == {"inferred"}
    assert {claim["authority"] for claim in claims} == {"supporting"}
    assert documents["package.json"]["productionEligible"] is False

    queue = json.loads(
        (tmp_path / "docs" / "semantic-knowledge" / "mmle-semantic-review-queue.json").read_text(
            "ascii"
        )
    )
    assert queue["summary"]["pilotPendingClaimCount"] == 0
    assert queue["summary"]["reviewedPilotClaimCount"] == 7
    assert queue["summary"]["outsidePilotPendingClaimCount"] == 93

    gold = json.loads(
        (
            tmp_path
            / ".runtime"
            / "semantic-knowledge-rollout"
            / "scenarios"
            / "gold-candidates.json"
        ).read_text("ascii")
    )
    assert sum(
        item["humanReview"]["status"] == "accepted"
        for item in gold["candidates"]
    ) == 48
    assert gold["promotedFixtureCount"] == 0


def test_identical_review_recording_is_idempotent(tmp_path: Path) -> None:
    _copy_review_fixture(tmp_path)
    first = record_semantic_human_review(
        tmp_path,
        reviewer="workspace_owner",
        attestation="Everything has been reviewed and looks good.",
        reviewed_at="2026-08-26T12:00:00Z",
    )
    second = record_semantic_human_review(
        tmp_path,
        reviewer="workspace_owner",
        attestation="Everything has been reviewed and looks good.",
        reviewed_at="2026-08-26T12:05:00Z",
    )
    assert second["status"] == "already_recorded"
    assert second["receipt"]["receiptId"] == first["receipt"]["receiptId"]
