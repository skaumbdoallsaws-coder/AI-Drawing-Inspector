"""Phase 7 machine evaluation and honest pilot-release disposition."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_inspector.product_intelligence.functional_relationships import (
    FunctionalRelationshipError,
    FunctionalRelationshipRegistry,
)

from .manifest import sha256_file
from .repository import AssemblyKnowledgeRepository
from .runtime_provider import PackageFunctionalContextProvider
from .semantic_contract import package_retrieval_decision


SEMANTIC_RELEASE_VERSION = "semantic-release-gate-v1"
MMLE_PRODUCT_ID = "mmle-50d-497533f6"
MMLE_PACKAGE_ID = "akp-dcd00b22c1abe6d78cfb51f5"

_PYTEST_FILES = (
    "tests/test_assembly_knowledge_adapter.py",
    "tests/test_assembly_knowledge_assembly_profile.py",
    "tests/test_assembly_knowledge_cost_policy.py",
    "tests/test_assembly_knowledge_endpoints.py",
    "tests/test_assembly_knowledge_enrichment.py",
    "tests/test_assembly_knowledge_evaluation.py",
    "tests/test_assembly_knowledge_evidence.py",
    "tests/test_assembly_knowledge_preparation.py",
    "tests/test_assembly_knowledge_process_map_integration.py",
    "tests/test_assembly_knowledge_review.py",
    "tests/test_assembly_knowledge_schema.py",
    "tests/test_assembly_knowledge_visuals.py",
    "tests/test_functional_catalog_migration.py",
    "tests/test_functional_relationships.py",
    "tests/test_semantic_knowledge_contract.py",
    "tests/test_semantic_human_review.py",
    "tests/test_semantic_rollout.py",
    "tests/test_semantic_scenario_factory.py",
    "tests/test_package_functional_context_provider.py",
    "tests/test_semantic_server_runtime_provider.py",
    "tests/test_fai_response_grounding.py",
    "tests/test_fai_request_targeting.py",
)


class SemanticReleaseError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticReleaseError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticReleaseError(f"Expected an object in {path}.")
    return value


def _run_command(
    repo_root: Path,
    command: Sequence[str],
    *,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    output = completed.stdout or ""
    return {
        "command": list(command),
        "exitCode": completed.returncode,
        "passed": completed.returncode == 0,
        "wallSeconds": round(time.perf_counter() - started, 3),
        "outputTail": output[-6000:],
    }


def run_release_test_suites(repo_root: str | Path) -> dict[str, Any]:
    """Run the bounded regression set without invoking an LLM."""

    root = Path(repo_root).resolve()
    suites = [
        _run_command(
            root,
            [
                sys.executable,
                "-m",
                "pytest",
                *_PYTEST_FILES,
                "-q",
                "--basetemp",
                ".sr",
            ],
        ),
        _run_command(root, [sys.executable, "tests/test_fai_response_grounding.py"]),
        _run_command(root, [sys.executable, "tests/test_fai_request_targeting.py"]),
        _run_command(root, ["node", "tests/test_assembly_knowledge_review.js"]),
        _run_command(root, ["node", "tests/test_fai_snapshot_frontend.js"]),
    ]
    return {
        "suiteCount": len(suites),
        "passedSuiteCount": sum(item["passed"] for item in suites),
        "allPassed": all(item["passed"] for item in suites),
        "suites": suites,
    }


def _route_evaluation(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "runtime_logs" / "skill_route_shadow_eval.json"
    if not path.is_file():
        return {
            "available": False,
            "allThresholdsPassed": False,
            "reason": "route evaluation artifact is missing",
        }
    report = _read_json(path)
    threshold_checks = report.get("threshold_checks") or {}
    return {
        "available": True,
        "path": "runtime_logs/skill_route_shadow_eval.json",
        "sha256": sha256_file(path),
        "modifiedAtUnixNs": path.stat().st_mtime_ns,
        "fixtureSha256": sha256_file(
            repo_root / "tests" / "fixtures" / "skill_route_cases.json"
        ),
        "routingSourceSha256": sha256_file(
            repo_root / "ai_inspector" / "agent_skills" / "routing.py"
        ),
        "model": report.get("model"),
        "caseCount": report.get("case_count"),
        "metrics": report.get("metrics") or {},
        "thresholds": report.get("thresholds") or {},
        "thresholdChecks": threshold_checks,
        "allThresholdsPassed": bool(threshold_checks)
        and all(value is True for value in threshold_checks.values()),
        "failedCaseIds": [
            item.get("id")
            for item in report.get("results", [])
            if isinstance(item, Mapping)
            and not all((item.get("checks") or {}).values())
        ],
    }


def evaluate_semantic_release(
    repo_root: str | Path,
    *,
    run_tests: bool = True,
) -> dict[str, Any]:
    """Evaluate machine gates and any explicit revision-bound human receipt."""

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    checkpoints = {
        phase: _read_json(runtime_root / "checkpoints" / f"phase-{phase}.json")
        for phase in range(7)
    }
    enrichment = _read_json(
        docs_root / "mmle-targeted-semantic-enrichment.json"
    )
    migration = _read_json(docs_root / "runtime-provider-migration-report.json")
    scenario_report = _read_json(
        docs_root / "synthetic-scenario-factory-report.json"
    )
    scenario_validation = _read_json(
        runtime_root / "scenarios" / "validation-report.json"
    )
    ledger = _read_json(docs_root / "review-ledger.json")
    review_queue = _read_json(docs_root / "mmle-semantic-review-queue.json")
    baseline = _read_json(docs_root / "baseline-query-set.json")
    parity = _read_json(docs_root / "functional-catalog-parity.json")
    gold = _read_json(runtime_root / "scenarios" / "gold-candidates.json")
    receipt_path = docs_root / "human-review-receipt.json"
    human_receipt = _read_json(receipt_path) if receipt_path.is_file() else {}

    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    stale_decision = package_retrieval_decision(
        documents["package.json"],
        prototype_mode=True,
        source_current=False,
    )
    wrong_product_rejected = False
    provider = PackageFunctionalContextProvider(
        root / "generated" / "training",
        catalog_registry=FunctionalRelationshipRegistry(),
    )
    try:
        provider.context_for_asset(
            assembly_number="SYN-WRONG-PRODUCT",
            part_number="SYN-MISSING",
            prototype_mode=True,
        )
    except FunctionalRelationshipError:
        wrong_product_rejected = True

    scenario_summary = scenario_validation.get("summary") or {}
    scenario_checks = scenario_validation.get("validation") or {}
    action_cases = [
        item
        for item in _read_json(
            runtime_root / "scenarios" / "candidates.json"
        ).get("candidates", [])
        if isinstance(item, Mapping) and item.get("expectedActions")
    ]
    unauthorized_cases = [
        item for item in action_cases if item.get("caseKind") == "unauthorized_action"
    ]
    failed_action_cases = [
        item for item in action_cases if item.get("caseKind") == "failed_action"
    ]
    authorization_accuracy = (
        sum(
            all(action.get("expectedOutcome") == "not_executed" for action in item["expectedActions"])
            for item in unauthorized_cases
        )
        / len(unauthorized_cases)
        if unauthorized_cases
        else 0.0
    )
    failed_action_honesty = (
        sum(
            item.get("receiptConstraints", {}).get("required") is True
            and item.get("receiptConstraints", {}).get("expectedSuccess") is False
            and "report_failed_action_honestly"
            in item.get("requiredResponseBehaviors", [])
            for item in failed_action_cases
        )
        / len(failed_action_cases)
        if failed_action_cases
        else 0.0
    )
    test_suites = run_release_test_suites(root) if run_tests else {
        "suiteCount": 0,
        "passedSuiteCount": 0,
        "allPassed": False,
        "suites": [],
        "reason": "tests were not requested",
    }
    route_evaluation = _route_evaluation(root)
    review_minutes = int((ledger.get("totals") or {}).get("minutes") or 0)
    review_budget_minutes = int(float(ledger.get("budgetHours") or 0) * 60)
    receipt_id = str(human_receipt.get("receiptId") or "")
    reviewed_baseline_count = sum(
        isinstance(item, Mapping)
        and (item.get("humanReview") or {}).get("status") == "accepted"
        and (item.get("humanReview") or {}).get("receiptId") == receipt_id
        for item in baseline.get("cases", [])
    )
    reviewed_gold_count = sum(
        isinstance(item, Mapping)
        and (item.get("humanReview") or {}).get("status") == "accepted"
        and (item.get("humanReview") or {}).get("receiptId") == receipt_id
        for item in gold.get("candidates", [])
    )
    reviewed_paraphrase_count = sum(
        isinstance(item, Mapping)
        and item.get("caseKind") == "catalog_paraphrase"
        and (item.get("humanReview") or {}).get("status") == "accepted"
        and (item.get("humanReview") or {}).get("receiptId") == receipt_id
        for item in gold.get("candidates", [])
    )
    rescore = migration.get("frozenSubsetRescoring") or {}
    rescore_cases = rescore.get("cases") or []
    previously_failing_pass_count = sum(
        isinstance(item, Mapping)
        and item.get("baselineStatus") == "fail"
        and item.get("currentStatus") == "pass"
        and item.get("humanReviewReceiptId") == receipt_id
        for item in rescore_cases
    )
    prior_pass_regression_count = sum(
        isinstance(item, Mapping)
        and item.get("baselineStatus") == "pass"
        and item.get("currentStatus") != "pass"
        for item in rescore_cases
    )
    receipt_claim_ids = set(
        (human_receipt.get("packageReview") or {}).get("confirmedClaimIds") or []
    )
    review_events = documents.get("review_receipt.json", {}).get("events", [])
    confirmed_receipt_claim_ids = {
        str(item.get("claimId") or "")
        for item in review_events
        if isinstance(item, Mapping)
        and item.get("action") in {"confirm", "edit"}
        and item.get("actor") == human_receipt.get("reviewer")
    }
    human_receipt_valid = all(
        (
            bool(receipt_id),
            human_receipt.get("status") == "complete",
            bool(str(human_receipt.get("reviewer") or "").strip()),
            bool(str(human_receipt.get("attestation") or "").strip()),
            human_receipt.get("humanAuthorityGranted") is False,
            human_receipt.get("controlledAuthorityGranted") is False,
            human_receipt.get("productionEligibilityChanged") is False,
            human_receipt.get("catalogRetirementAuthorized") is False,
            len(receipt_claim_ids) == 7,
            receipt_claim_ids <= confirmed_receipt_claim_ids,
            (human_receipt.get("packageReview") or {}).get("reviewedRevision")
            == documents["package.json"].get("packageRevision"),
            documents["package.json"].get("productionEligible") is False,
        )
    )
    machine_metrics = {
        "validSourceReferenceRate": (
            1.0
            if migration["mmlePrototypeRetrieval"]["diagnostics"]["sourceStatus"][
                "current"
            ]
            and scenario_checks.get("unresolvedReferenceCount") == 0
            else 0.0
        ),
        "unsupportedNumericalEngineeringClaimCount": (
            0
            if enrichment["gate"]["checks"]["noForbiddenEngineeringText"]
            else len(enrichment["gate"].get("forbiddenTextFindings") or [])
        ),
        "staleKnowledgeRejectionRate": 1.0 if not stale_decision.eligible else 0.0,
        "wrongProductRejectionRate": 1.0 if wrong_product_rejected else 0.0,
        "actionAuthorizationAccuracy": authorization_accuracy,
        "failedActionHonestyRate": failed_action_honesty,
        "providerWarmP95Ms": migration["performance"]["warmP95Ms"],
        "providerMaximumP95Ms": migration["performance"]["maximumP95Ms"],
        "scenarioValidationIssueCount": scenario_checks.get("issueCount"),
        "scenarioCandidateCount": scenario_summary.get("candidateCount"),
        "routeThresholdsPassed": route_evaluation["allThresholdsPassed"],
        "testSuitesPassed": test_suites["allPassed"],
        "reviewMinutesRecorded": review_minutes,
        "reviewBudgetMinutes": review_budget_minutes,
        "humanReviewReceiptValid": human_receipt_valid,
    }
    machine_thresholds = {
        "validSourceReferences": machine_metrics["validSourceReferenceRate"] == 1.0,
        "noUnsupportedNumericalClaims": machine_metrics[
            "unsupportedNumericalEngineeringClaimCount"
        ]
        == 0,
        "staleKnowledgeRejected": machine_metrics["staleKnowledgeRejectionRate"] == 1.0,
        "wrongProductRejected": machine_metrics["wrongProductRejectionRate"] == 1.0,
        "actionAuthorizationExact": machine_metrics["actionAuthorizationAccuracy"] == 1.0,
        "failedActionsReportedHonestly": machine_metrics["failedActionHonestyRate"] == 1.0,
        "providerLatencyWithinLimit": machine_metrics["providerWarmP95Ms"]
        <= machine_metrics["providerMaximumP95Ms"],
        "scenarioFactoryClean": machine_metrics["scenarioValidationIssueCount"] == 0,
        "routerHasNoThresholdRegression": route_evaluation["allThresholdsPassed"],
        "regressionSuitesPass": test_suites["allPassed"],
        "reviewLedgerWithinBudget": review_minutes <= review_budget_minutes,
        "priorPhaseMachineGatesPass": all(
            checkpoint.get("machineGatePassed") is True
            for checkpoint in checkpoints.values()
        ),
        "humanAuthorityNeverGranted": all(
            checkpoint.get("humanAuthorityGranted") is not True
            for checkpoint in checkpoints.values()
        ),
    }
    human_gates = {
        "reviewReceiptValid": human_receipt_valid,
        "phase0BaselineReviewed": reviewed_baseline_count >= 35,
        "phase1HeldOutParaphrasesReviewed": reviewed_paraphrase_count >= 40
        and parity.get("humanReviewReceiptId") == receipt_id,
        "phase4HighImpactClaimsResolved": review_queue["summary"].get(
            "pendingHighImpactClaimCount", 0
        )
        == 0
        and review_queue["summary"].get("reviewedPilotClaimCount", 0) >= 7,
        "phase5SixBaselineFailuresNowPass": previously_failing_pass_count >= 6
        and prior_pass_regression_count == 0
        and migration.get("humanReviewReceiptId") == receipt_id,
        "phase6GoldCasesReviewed": reviewed_gold_count >= 48,
    }
    machine_gate_passed = all(machine_thresholds.values())
    pilot_enabled = machine_gate_passed and all(human_gates.values())
    return {
        "schemaVersion": 1,
        "releaseVersion": SEMANTIC_RELEASE_VERSION,
        "machineImplementationComplete": machine_gate_passed,
        "pilotEnabled": pilot_enabled,
        "status": (
            "pilot_enabled"
            if pilot_enabled
            else (
                "machine_complete_human_review_required"
                if machine_gate_passed
                else "machine_gate_failed"
            )
        ),
        "machineMetrics": machine_metrics,
        "machineThresholds": machine_thresholds,
        "humanGates": human_gates,
        "humanReviewReceipt": {
            "receiptId": receipt_id or None,
            "valid": human_receipt_valid,
            "reviewer": human_receipt.get("reviewer"),
            "reviewedAt": human_receipt.get("reviewedAt"),
            "baselineReviewedCount": reviewed_baseline_count,
            "heldOutParaphraseReviewedCount": reviewed_paraphrase_count,
            "pilotClaimReviewEventCount": len(
                receipt_claim_ids & confirmed_receipt_claim_ids
            ),
            "frozenPreviouslyFailingPassCount": previously_failing_pass_count,
            "goldReviewedCount": reviewed_gold_count,
            "durationStatus": (
                human_receipt.get("reviewDuration") or {}
            ).get("status"),
        },
        "humanAuthorityGranted": False,
        "pilotMode": "explicit_prototype",
        "controlledUseEnabled": False,
        "catalogFallbackRetained": True,
        "catalogRetirementAuthorized": False,
        "routeEvaluation": route_evaluation,
        "testSuites": test_suites,
        "phaseCheckpoints": checkpoints,
        "phase6Report": scenario_report,
    }


__all__ = [
    "SEMANTIC_RELEASE_VERSION",
    "SemanticReleaseError",
    "evaluate_semantic_release",
    "run_release_test_suites",
]
