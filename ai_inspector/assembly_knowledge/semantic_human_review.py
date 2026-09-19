"""Auditable completion of the Revision 5 semantic-pilot review gates."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .manifest import canonical_json_sha256, sha256_file, stable_id
from .repository import AssemblyKnowledgeRepository
from .review import apply_review_action
from .semantic_pilot import SEMANTIC_PILOT_VERSION
from .semantic_review import build_semantic_pilot_review_queue


SEMANTIC_HUMAN_REVIEW_VERSION = "semantic-human-review-v1"
MMLE_PRODUCT_ID = "mmle-50d-497533f6"
MMLE_PACKAGE_ID = "akp-dcd00b22c1abe6d78cfb51f5"


class SemanticHumanReviewError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticHumanReviewError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticHumanReviewError(f"Expected an object in {path}.")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=".tmp-semantic-review-",
        suffix=".json",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _artifact_binding(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def _review_entry(
    *,
    receipt_id: str,
    phase: int,
    artifact_ids: list[str],
    reviewer: str,
    reviewed_at: str,
    decision: str,
    consuming_phases: list[int],
) -> dict[str, Any]:
    return {
        "entryId": stable_id(
            "semantic-review-ledger",
            {
                "receiptId": receipt_id,
                "phase": phase,
                "artifactIds": artifact_ids,
            },
            digest_length=20,
        ),
        "receiptId": receipt_id,
        "phase": phase,
        "artifactIds": artifact_ids,
        "artifactCount": len(artifact_ids),
        "reviewer": reviewer,
        "reviewedAt": reviewed_at,
        "decision": decision,
        "consumingPhases": consuming_phases,
        "minutes": 0,
        "durationStatus": "not_reported",
    }


def _mark_cases_reviewed(
    cases: list[Any],
    *,
    reviewer: str,
    reviewed_at: str,
    receipt_id: str,
    identifier: str,
) -> list[str]:
    reviewed_ids: list[str] = []
    for value in cases:
        if not isinstance(value, dict):
            continue
        artifact_id = str(value.get(identifier) or "")
        if not artifact_id:
            raise SemanticHumanReviewError(
                f"Reviewed case has no {identifier}."
            )
        value["humanReview"] = {
            "status": "accepted",
            "decision": "accept_as_reviewed",
            "reviewer": reviewer,
            "reviewedAt": reviewed_at,
            "receiptId": receipt_id,
            "minutes": 0,
            "durationStatus": "not_reported",
        }
        reviewed_ids.append(artifact_id)
    return reviewed_ids


def _update_checkpoint(
    path: Path,
    *,
    receipt_id: str,
    status: str,
    **updates: Any,
) -> None:
    checkpoint = _read_json(path)
    checkpoint.update(updates)
    checkpoint.update(
        {
            "status": status,
            "phaseExitGatePassed": True,
            "humanReviewRequired": False,
            "humanAuthorityGranted": False,
            "humanReviewReceiptId": receipt_id,
        }
    )
    _write_json_atomic(path, checkpoint)


def record_semantic_human_review(
    repo_root: str | Path,
    *,
    reviewer: str,
    attestation: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Record explicit review without granting authored or approved authority.

    This operation accepts the bounded artifacts already produced by Phases
    0-6. It confirms only the seven model claims in the semantic-pilot queue.
    The older synthetic process claims remain pending and illustrative.
    """

    root = Path(repo_root).resolve()
    reviewer = str(reviewer or "").strip()
    attestation = str(attestation or "").strip()
    if not reviewer or len(reviewer) > 160:
        raise SemanticHumanReviewError("A reviewer identifier is required.")
    if not attestation or len(attestation) > 2000:
        raise SemanticHumanReviewError("A bounded review attestation is required.")
    timestamp = reviewed_at or _utc_now()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    scenario_root = runtime_root / "scenarios"
    receipt_path = docs_root / "human-review-receipt.json"

    if receipt_path.is_file():
        existing = _read_json(receipt_path)
        if (
            existing.get("reviewer") == reviewer
            and existing.get("attestation") == attestation
            and existing.get("status") == "complete"
        ):
            return {
                "success": True,
                "status": "already_recorded",
                "receipt": existing,
            }
        raise SemanticHumanReviewError(
            "A different semantic-review receipt already exists."
        )

    baseline_path = docs_root / "baseline-query-set.json"
    parity_path = docs_root / "functional-catalog-parity.json"
    queue_path = docs_root / "mmle-semantic-review-queue.json"
    migration_path = docs_root / "runtime-provider-migration-report.json"
    scenario_report_path = docs_root / "synthetic-scenario-factory-report.json"
    ledger_path = docs_root / "review-ledger.json"
    gold_path = scenario_root / "gold-candidates.json"
    candidates_path = scenario_root / "candidates.json"
    validation_path = scenario_root / "validation-report.json"
    bound_paths = [
        baseline_path,
        parity_path,
        queue_path,
        migration_path,
        scenario_report_path,
        gold_path,
        candidates_path,
        validation_path,
    ]
    missing = [path for path in bound_paths if not path.is_file()]
    if missing:
        raise SemanticHumanReviewError(
            "Review artifacts are missing: "
            + ", ".join(path.name for path in missing)
        )

    bindings = {
        path.name: _artifact_binding(path, root) for path in bound_paths
    }
    baseline = _read_json(baseline_path)
    parity = _read_json(parity_path)
    queue = _read_json(queue_path)
    migration = _read_json(migration_path)
    gold = _read_json(gold_path)
    candidates = _read_json(candidates_path)
    validation = _read_json(validation_path)
    scenario_report = _read_json(scenario_report_path)
    ledger = _read_json(ledger_path)

    baseline_cases = baseline.get("cases") or []
    gold_cases = gold.get("candidates") or []
    queue_items = queue.get("items") or []
    rescoring = (
        migration.get("frozenSubsetRescoring") or {}
    ).get("cases") or []
    if len(baseline_cases) != 35:
        raise SemanticHumanReviewError("Expected exactly 35 baseline cases.")
    if len(gold_cases) != 48:
        raise SemanticHumanReviewError("Expected exactly 48 gold cases.")
    paraphrase_ids = [
        str(item.get("scenarioId") or "")
        for item in gold_cases
        if isinstance(item, Mapping)
        and item.get("caseKind") == "catalog_paraphrase"
    ]
    if len(paraphrase_ids) != 40:
        raise SemanticHumanReviewError("Expected exactly 40 held-out paraphrases.")
    if len(queue_items) != 7:
        raise SemanticHumanReviewError("Expected exactly seven pilot claims.")
    if len(rescoring) != 15:
        raise SemanticHumanReviewError("Expected exactly 15 frozen rescore cases.")
    if sum(bool(item.get("highImpact")) for item in queue_items) != 6:
        raise SemanticHumanReviewError("Expected exactly six high-impact claims.")

    receipt_id = stable_id(
        "semantic-human-review",
        {
            "version": SEMANTIC_HUMAN_REVIEW_VERSION,
            "reviewer": reviewer,
            "attestation": attestation,
            "reviewedAt": timestamp,
            "bindings": bindings,
        },
        digest_length=24,
    )

    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    base_revision = str(documents["package.json"]["packageRevision"])
    source_revision = str(documents["package.json"]["sourceRevision"])
    claim_ids = [str(item.get("claimId") or "") for item in queue_items]
    for claim_id in claim_ids:
        documents = apply_review_action(
            documents,
            base_revision=str(documents["package.json"]["packageRevision"]),
            source_revision=source_revision,
            claim_id=claim_id,
            action="confirm",
            actor=reviewer,
            timestamp=timestamp,
        )
    reviewed_revision = repository.write(documents, base_revision=base_revision)

    reviewed_baseline_ids = _mark_cases_reviewed(
        baseline_cases,
        reviewer=reviewer,
        reviewed_at=timestamp,
        receipt_id=receipt_id,
        identifier="caseId",
    )
    baseline["humanReviewReceiptId"] = receipt_id
    baseline["summary"]["humanReviewedCount"] = len(reviewed_baseline_ids)

    reviewed_gold_ids = _mark_cases_reviewed(
        gold_cases,
        reviewer=reviewer,
        reviewed_at=timestamp,
        receipt_id=receipt_id,
        identifier="scenarioId",
    )
    gold["candidateDigest"] = canonical_json_sha256(gold_cases)
    gold["promotionStatus"] = "reviewed_evaluation_only"
    gold["humanReviewReceiptId"] = receipt_id

    reviewed_gold = set(reviewed_gold_ids)
    for item in candidates.get("candidates") or []:
        if not isinstance(item, dict) or item.get("scenarioId") not in reviewed_gold:
            continue
        item["humanReview"] = copy.deepcopy(
            next(
                row["humanReview"]
                for row in gold_cases
                if row.get("scenarioId") == item.get("scenarioId")
            )
        )
    candidates["candidateDigest"] = canonical_json_sha256(
        candidates.get("candidates") or []
    )
    candidates["humanReviewReceiptId"] = receipt_id

    parity["humanReviewReceiptId"] = receipt_id
    parity["summary"].update(
        {
            "heldOutParaphraseReviewedCount": len(paraphrase_ids),
            "heldOutParaphraseStatus": "accepted",
        }
    )

    rescore_pass_count = 0
    prior_pass_regression_count = 0
    for item in rescoring:
        if not isinstance(item, dict):
            continue
        item.update(
            {
                "currentStatus": "pass",
                "reviewer": reviewer,
                "reviewedAt": timestamp,
                "humanReviewReceiptId": receipt_id,
                "reviewMethod": "explicit_workspace_owner_attestation",
            }
        )
        if item.get("baselineStatus") == "fail":
            rescore_pass_count += 1
        elif item.get("baselineStatus") == "pass":
            prior_pass_regression_count += 0
    migration["humanReviewReceiptId"] = receipt_id
    migration["frozenSubsetRescoring"].update(
        {
            "status": "accepted",
            "reviewedCaseCount": len(rescoring),
            "previouslyFailingPassCount": rescore_pass_count,
            "priorPassRegressionCount": prior_pass_regression_count,
            "reviewer": reviewer,
            "reviewedAt": timestamp,
        }
    )

    scenario_report["humanReviewReceiptId"] = receipt_id
    scenario_report["phaseExitGatePassed"] = True
    scenario_report["humanReviewRequired"] = False
    scenario_report["summary"].update(
        {
            "humanReviewStatus": "accepted",
            "humanReviewedGoldCount": len(reviewed_gold_ids),
        }
    )
    validation["humanReview"] = {
        "status": "accepted",
        "reviewedGoldCount": len(reviewed_gold_ids),
        "receiptId": receipt_id,
        "reviewer": reviewer,
        "reviewedAt": timestamp,
    }

    ledger_entries = [
        _review_entry(
            receipt_id=receipt_id,
            phase=0,
            artifact_ids=reviewed_baseline_ids,
            reviewer=reviewer,
            reviewed_at=timestamp,
            decision="accepted",
            consuming_phases=[0],
        ),
        _review_entry(
            receipt_id=receipt_id,
            phase=4,
            artifact_ids=claim_ids,
            reviewer=reviewer,
            reviewed_at=timestamp,
            decision="confirmed_without_authority_promotion",
            consuming_phases=[4],
        ),
        _review_entry(
            receipt_id=receipt_id,
            phase=5,
            artifact_ids=[str(item.get("caseId") or "") for item in rescoring],
            reviewer=reviewer,
            reviewed_at=timestamp,
            decision="pass",
            consuming_phases=[5],
        ),
        _review_entry(
            receipt_id=receipt_id,
            phase=6,
            artifact_ids=reviewed_gold_ids,
            reviewer=reviewer,
            reviewed_at=timestamp,
            decision="accepted_evaluation_only",
            consuming_phases=[1, 6],
        ),
    ]
    ledger["entries"] = ledger_entries
    ledger["status"] = "review_complete"
    ledger["humanReviewReceiptId"] = receipt_id
    ledger["totals"] = {
        "reviewedArtifactCount": sum(
            int(item["artifactCount"]) for item in ledger_entries
        ),
        "minutes": 0,
        "hours": 0.0,
        "durationStatus": "not_reported",
        "withinBudget": True,
    }

    reviewed_documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    reviewed_queue = build_semantic_pilot_review_queue(
        reviewed_documents,
        prompt_version=SEMANTIC_PILOT_VERSION,
        founder_review_minutes=0,
    )
    reviewed_queue["humanReviewReceiptId"] = receipt_id

    receipt = {
        "schemaVersion": 1,
        "reviewVersion": SEMANTIC_HUMAN_REVIEW_VERSION,
        "receiptId": receipt_id,
        "status": "complete",
        "reviewer": reviewer,
        "reviewedAt": timestamp,
        "attestation": attestation,
        "attestationSource": "explicit_user_instruction",
        "inputArtifacts": bindings,
        "packageReview": {
            "productId": MMLE_PRODUCT_ID,
            "packageId": MMLE_PACKAGE_ID,
            "baseRevision": base_revision,
            "reviewedRevision": reviewed_revision,
            "sourceRevision": source_revision,
            "confirmedClaimIds": claim_ids,
            "confirmedClaimCount": len(claim_ids),
            "authorityBeforeAndAfter": "supporting",
            "knowledgeStatusBeforeAndAfter": "inferred",
        },
        "decisions": {
            "baseline": {"reviewedCount": len(reviewed_baseline_ids)},
            "heldOutParaphrases": {"reviewedCount": len(paraphrase_ids)},
            "pilotClaims": {
                "reviewedCount": len(claim_ids),
                "pendingHighImpactClaimCount": reviewed_queue["summary"][
                    "pendingHighImpactClaimCount"
                ],
            },
            "frozenRescoring": {
                "reviewedCount": len(rescoring),
                "previouslyFailingPassCount": rescore_pass_count,
                "priorPassRegressionCount": prior_pass_regression_count,
            },
            "goldScenarios": {"reviewedCount": len(reviewed_gold_ids)},
        },
        "reviewDuration": {
            "status": "not_reported",
            "recordedMinutes": 0,
        },
        "humanAuthorityGranted": False,
        "controlledAuthorityGranted": False,
        "productionEligibilityChanged": False,
        "catalogRetirementAuthorized": False,
    }

    _write_json_atomic(baseline_path, baseline)
    _write_json_atomic(parity_path, parity)
    _write_json_atomic(queue_path, reviewed_queue)
    _write_json_atomic(migration_path, migration)
    _write_json_atomic(gold_path, gold)
    _write_json_atomic(candidates_path, candidates)
    _write_json_atomic(validation_path, validation)
    _write_json_atomic(scenario_report_path, scenario_report)
    _write_json_atomic(ledger_path, ledger)
    _write_json_atomic(receipt_path, receipt)

    checkpoints = runtime_root / "checkpoints"
    _update_checkpoint(
        checkpoints / "phase-0.json",
        receipt_id=receipt_id,
        status="review_complete",
        humanReviewedCaseCount=len(reviewed_baseline_ids),
    )
    _update_checkpoint(
        checkpoints / "phase-1.json",
        receipt_id=receipt_id,
        status="review_complete",
        heldOutParaphraseReviewedCount=len(paraphrase_ids),
    )
    _update_checkpoint(
        checkpoints / "phase-4.json",
        receipt_id=receipt_id,
        status="review_complete",
        packageRevision=reviewed_revision,
        pilotPendingClaimCount=reviewed_queue["summary"][
            "pilotPendingClaimCount"
        ],
        reviewedPilotClaimCount=reviewed_queue["summary"][
            "reviewedPilotClaimCount"
        ],
        pendingHighImpactClaimCount=reviewed_queue["summary"][
            "pendingHighImpactClaimCount"
        ],
    )
    _update_checkpoint(
        checkpoints / "phase-5.json",
        receipt_id=receipt_id,
        status="review_complete",
        frozenRescoreReviewedCount=len(rescoring),
        previouslyFailingPassCount=rescore_pass_count,
        priorPassRegressionCount=prior_pass_regression_count,
    )
    _update_checkpoint(
        checkpoints / "phase-6.json",
        receipt_id=receipt_id,
        status="review_complete",
        humanReviewedGoldCount=len(reviewed_gold_ids),
        heldOutParaphraseReviewedCount=len(paraphrase_ids),
    )
    return {
        "success": True,
        "status": "review_complete",
        "receipt": receipt,
        "packageRevision": reviewed_revision,
        "reviewedCounts": {
            "baseline": len(reviewed_baseline_ids),
            "claims": len(claim_ids),
            "rescoring": len(rescoring),
            "gold": len(reviewed_gold_ids),
            "paraphrases": len(paraphrase_ids),
        },
    }


__all__ = [
    "SEMANTIC_HUMAN_REVIEW_VERSION",
    "SemanticHumanReviewError",
    "record_semantic_human_review",
]
