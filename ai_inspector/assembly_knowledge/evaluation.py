"""Controlled-rollout metrics for Assembly Knowledge Packages."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, Mapping, Sequence

from .validation import validate_assembly_knowledge_package


ASSEMBLY_KNOWLEDGE_EVALUATION_VERSION = 1
MAX_REVIEW_ACTIONS_PER_OCCURRENCE = 0.25
ROLLOUT_FIXTURE_IDS = (
    "tricycle-native-cad",
    "four-cylinder-engine-functional",
    "synthetic-nested-assembly",
    "repeated-mirrored-occurrences",
    "suppressed-unresolved-references",
    "ambiguous-mates",
    "no-custom-properties",
    "conflicting-authored-inferred-claims",
    "changed-part-revision",
    "large-assembly-scaling",
)
_COMPLETED_REVIEW_ACTIONS = {
    "confirm",
    "edit",
    "reject",
    "mark_unknown",
}


def _check(
    *,
    passed: bool,
    observed: Any,
    target: Any,
    evidence: str,
) -> Dict[str, Any]:
    return {
        "passed": bool(passed),
        "observed": observed,
        "target": target,
        "evidence": evidence,
    }


def _claims(documents: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        item
        for name in ("functional_context.json", "process_candidates.json")
        for item in documents.get(name, {}).get("claims", [])
        if isinstance(item, Mapping)
    ]


def evaluate_assembly_knowledge_package(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    source_status: Mapping[str, Any] | None = None,
    runtime_guards: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Evaluate one package without modifying it or invoking a model."""

    package = documents["package.json"]
    structure = documents["product_structure.json"]
    occurrences = [
        item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping)
    ]
    occurrence_ids = [
        str(item.get("occurrenceId"))
        for item in occurrences
        if isinstance(item.get("occurrenceId"), str)
    ]
    sources = {
        str(item.get("sourceId")): item
        for item in documents["source_manifest.json"].get("sources", [])
        if isinstance(item, Mapping) and isinstance(item.get("sourceId"), str)
    }
    findings = validate_assembly_knowledge_package(documents)
    error_codes = Counter(
        str(item.get("code") or "unknown")
        for item in findings
        if item.get("severity") == "error"
    )

    occurrence_identity_errors = 0
    for item in occurrences:
        occurrence_id = item.get("occurrenceId")
        if (
            not isinstance(occurrence_id, str)
            or item.get("sourceOccurrenceId") != occurrence_id
            or item.get("sourceId") not in sources
            or item.get("sourceHash")
            != sources.get(str(item.get("sourceId")), {}).get("sha256")
        ):
            occurrence_identity_errors += 1
    occurrence_identity_errors += len(occurrence_ids) - len(set(occurrence_ids))

    repeated_groups: Dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in occurrences:
        if isinstance(item.get("itemId"), str):
            repeated_groups[str(item["itemId"])].append(item)
    repeated_groups = {
        key: rows for key, rows in repeated_groups.items() if len(rows) > 1
    }
    repeated_identity_errors = 0
    for rows in repeated_groups.values():
        ids = [str(item.get("occurrenceId")) for item in rows]
        paths = [
            str(
                (item.get("properties") or {}).get("sourceOccurrencePath")
                or item.get("name")
                or ""
            )
            for item in rows
        ]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            repeated_identity_errors += 1

    source_reference_errors = sum(
        1
        for item in occurrences
        if item.get("sourceId") not in sources
        or item.get("sourceHash")
        != sources.get(str(item.get("sourceId")), {}).get("sha256")
    )
    false_native_subassemblies = sum(
        1
        for item in occurrences
        if item.get("kind") in {"assembly", "subassembly"}
        and not str(item.get("sourcePath") or "").lower().endswith(".sldasm")
    )
    source_current = (
        bool(source_status.get("current"))
        if isinstance(source_status, Mapping)
        else None
    )
    guards = dict(runtime_guards or {})
    stale_guard = guards.get("stalePackageProposalBlocked")
    approval_guard = guards.get("unapprovedWriteBlocked")

    hard_metrics = {
        "occurrenceIdentityCorrectness": _check(
            passed=occurrence_identity_errors == 0,
            observed={
                "correct": len(occurrences) - occurrence_identity_errors,
                "total": len(occurrences),
                "errors": occurrence_identity_errors,
            },
            target="100%",
            evidence="canonical occurrence/source identity",
        ),
        "repeatedOccurrenceIdentityCorrectness": _check(
            passed=repeated_identity_errors == 0,
            observed={
                "repeatedItemGroups": len(repeated_groups),
                "errors": repeated_identity_errors,
            },
            target="100%",
            evidence="occurrence IDs and component paths remain distinct",
        ),
        "sourceReferenceResolution": _check(
            passed=source_reference_errors == 0 and source_current is not False,
            observed={
                "errors": source_reference_errors,
                "sourceCurrent": source_current,
            },
            target="100% before planning_ready",
            evidence="source manifest and optional bound-source preflight",
        ),
        "unknownEvidenceReferences": _check(
            passed=error_codes["unknown_evidence_reference"] == 0,
            observed=error_codes["unknown_evidence_reference"],
            target=0,
            evidence="deterministic package validator",
        ),
        "unsupportedAuthoritativeClaims": _check(
            passed=error_codes["unsupported_authoritative_claim"] == 0
            and error_codes["model_claim_authority_violation"] == 0
            and error_codes["manufacturing_sequence_from_cad_only"] == 0,
            observed=(
                error_codes["unsupported_authoritative_claim"]
                + error_codes["model_claim_authority_violation"]
                + error_codes["manufacturing_sequence_from_cad_only"]
            ),
            target=0,
            evidence="authority and CAD-sequence validators",
        ),
        "inventedNumericManufacturingValues": _check(
            passed=error_codes["unsupported_numeric_manufacturing_value"] == 0,
            observed=error_codes["unsupported_numeric_manufacturing_value"],
            target=0,
            evidence="numeric manufacturing-value validator",
        ),
        "falseNativeSubassemblies": _check(
            passed=false_native_subassemblies == 0,
            observed=false_native_subassemblies,
            target=0,
            evidence="assembly occurrence source extension",
        ),
        "stalePackageProposals": _check(
            passed=stale_guard is True,
            observed=stale_guard,
            target=True,
            evidence=str(
                guards.get("stalePackageProposalEvidence")
                or "runtime guard not supplied"
            ),
        ),
        "unapprovedProcessMapWrites": _check(
            passed=approval_guard is True,
            observed=approval_guard,
            target=True,
            evidence=str(
                guards.get("unapprovedWriteEvidence")
                or "runtime guard not supplied"
            ),
        ),
    }

    claims = _claims(documents)
    review_events = [
        item
        for item in documents["review_receipt.json"].get("events", [])
        if isinstance(item, Mapping)
    ]
    completed_review_actions = sum(
        1
        for item in review_events
        if item.get("action") in _COMPLETED_REVIEW_ACTIONS
    )
    review_rate = completed_review_actions / max(1, len(occurrences))

    def acceptance_rate(predicates: set[str]) -> float | None:
        relevant = [
            item for item in claims if item.get("predicate") in predicates
        ]
        reviewed = [
            item
            for item in relevant
            if item.get("reviewStatus")
            in {"confirmed", "edited", "rejected", "unknown"}
        ]
        if not reviewed:
            return None
        accepted = sum(
            1
            for item in reviewed
            if item.get("reviewStatus") in {"confirmed", "edited"}
        )
        return round(accepted / len(reviewed), 4)

    receipt = package.get("enrichmentReceipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    usage = receipt.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    quality_metrics = {
        "functionalRoleAcceptanceRate": acceptance_rate({"occurrence_role"}),
        "interfaceRelationshipAcceptanceRate": acceptance_rate(
            {"joint_archetype", "functional_relationship"}
        ),
        "processBranchAcceptanceRate": acceptance_rate(
            {"candidate_process_branch"}
        ),
        "processOperationAcceptanceRate": acceptance_rate(
            {"candidate_operation_family"}
        ),
        "unresolvedQuestionCount": len(
            documents["process_candidates.json"].get(
                "unresolvedQuestions", []
            )
        ),
        "pendingReviewClaimCount": sum(
            1 for item in claims if item.get("reviewStatus") == "pending"
        ),
        "completedReviewActionCount": completed_review_actions,
        "reviewActionsPerOccurrence": round(review_rate, 6),
        "reviewBurdenGatePassed": (
            review_rate <= MAX_REVIEW_ACTIONS_PER_OCCURRENCE
        ),
        "modelCalls": int(usage.get("providerAttempts", 0) or 0),
        "submittedImages": int(usage.get("imageCount", 0) or 0),
        "inputTokens": int(usage.get("inputTokens", 0) or 0),
        "outputTokens": int(usage.get("outputTokens", 0) or 0),
        "totalTokens": int(usage.get("totalTokens", 0) or 0),
        "estimatedMaximumCostUsd": receipt.get("estimatedMaximumCostUsd"),
        "pricingConfidence": receipt.get("pricingConfidence"),
        "cacheHit": bool(receipt.get("fromCache")) if receipt else None,
    }
    hard_pass = all(item["passed"] for item in hard_metrics.values())
    rollout_ready = (
        hard_pass
        and quality_metrics["reviewBurdenGatePassed"]
        and package.get("readiness")
        in {"planning_ready", "production_ready"}
    )
    return {
        "schemaVersion": ASSEMBLY_KNOWLEDGE_EVALUATION_VERSION,
        "identity": {
            "productId": package.get("productId"),
            "packageId": package.get("packageId"),
            "packageRevision": package.get("packageRevision"),
            "sourceRevision": package.get("sourceRevision"),
            "readiness": package.get("readiness"),
            "productionEligible": package.get("productionEligible"),
            "occurrenceCount": len(occurrences),
        },
        "summary": {
            "hardMetricsPassed": hard_pass,
            "reviewBurdenGatePassed": quality_metrics[
                "reviewBurdenGatePassed"
            ],
            "rolloutReady": rollout_ready,
            "validationErrorCount": sum(error_codes.values()),
        },
        "hardMetrics": hard_metrics,
        "qualityMetrics": quality_metrics,
        "validation": {
            "errorCodes": dict(sorted(error_codes.items())),
            "findingCount": len(findings),
        },
    }


def _as_fixture_rows(
    fixtures: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    rows = list(fixtures)
    seen: set[str] = set()
    for row in rows:
        fixture_id = row.get("fixtureId")
        if not isinstance(fixture_id, str) or not fixture_id:
            raise ValueError("Every rollout fixture requires fixtureId.")
        if fixture_id in seen:
            raise ValueError(f"Duplicate rollout fixture: {fixture_id}")
        seen.add(fixture_id)
        if not isinstance(row.get("report"), Mapping):
            raise ValueError(
                f"Rollout fixture {fixture_id} requires an evaluation report."
            )
        blocked = row.get("expectedBlockedMetrics", [])
        if (
            not isinstance(blocked, Sequence)
            or isinstance(blocked, (str, bytes))
            or any(not isinstance(item, str) for item in blocked)
        ):
            raise ValueError(
                f"Rollout fixture {fixture_id} has invalid blocked metrics."
            )
    return rows


def evaluate_assembly_knowledge_rollout(
    fixtures: Iterable[Mapping[str, Any]],
    *,
    feature_flag_guards: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Aggregate the required rollout scenarios into one explicit gate."""

    rows = _as_fixture_rows(fixtures)
    present_ids = {str(row["fixtureId"]) for row in rows}
    required_ids = set(ROLLOUT_FIXTURE_IDS)
    missing = sorted(required_ids - present_ids)
    scenario_results = []
    total_occurrences = 0
    total_review_actions = 0
    total_model_calls = 0
    total_images = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_cost = 0.0
    unknown_cost_fixture_ids: list[str] = []

    for row in sorted(rows, key=lambda item: str(item["fixtureId"])):
        fixture_id = str(row["fixtureId"])
        report = row["report"]
        hard_metrics = report.get("hardMetrics")
        hard_metrics = (
            hard_metrics if isinstance(hard_metrics, Mapping) else {}
        )
        expected_blocked = set(row.get("expectedBlockedMetrics", []))
        unknown_expected = sorted(expected_blocked - set(hard_metrics))
        mismatches = []
        for metric_name, metric in sorted(hard_metrics.items()):
            actual_pass = (
                bool(metric.get("passed"))
                if isinstance(metric, Mapping)
                else False
            )
            expected_pass = metric_name not in expected_blocked
            if actual_pass != expected_pass:
                mismatches.append(
                    {
                        "metric": metric_name,
                        "expectedPassed": expected_pass,
                        "observedPassed": actual_pass,
                    }
                )
        identity = report.get("identity")
        identity = identity if isinstance(identity, Mapping) else {}
        quality = report.get("qualityMetrics")
        quality = quality if isinstance(quality, Mapping) else {}
        occurrences = int(identity.get("occurrenceCount", 0) or 0)
        review_actions = int(
            quality.get("completedReviewActionCount", 0) or 0
        )
        model_calls = int(quality.get("modelCalls", 0) or 0)
        cost = quality.get("estimatedMaximumCostUsd")
        total_occurrences += occurrences
        total_review_actions += review_actions
        total_model_calls += model_calls
        total_images += int(quality.get("submittedImages", 0) or 0)
        total_input_tokens += int(quality.get("inputTokens", 0) or 0)
        total_output_tokens += int(quality.get("outputTokens", 0) or 0)
        total_tokens += int(quality.get("totalTokens", 0) or 0)
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            total_cost += float(cost)
        elif model_calls:
            unknown_cost_fixture_ids.append(fixture_id)
        scenario_results.append(
            {
                "fixtureId": fixture_id,
                "passed": not mismatches and not unknown_expected,
                "expectedBlockedMetrics": sorted(expected_blocked),
                "unknownExpectedMetrics": unknown_expected,
                "metricMismatches": mismatches,
                "occurrenceCount": occurrences,
                "reviewActionCount": review_actions,
                "readiness": identity.get("readiness"),
                "productionEligible": identity.get(
                    "productionEligible"
                ),
            }
        )

    review_rate = total_review_actions / max(1, total_occurrences)
    flags = dict(feature_flag_guards or {})
    flag_gate = (
        flags.get("preparationFlagRequired") is True
        and flags.get("aiEnrichmentFlagRequired") is True
    )
    scenario_gate = all(item["passed"] for item in scenario_results)
    coverage_gate = not missing
    review_gate = review_rate <= MAX_REVIEW_ACTIONS_PER_OCCURRENCE
    usage_gate = not unknown_cost_fixture_ids
    rollout_gate = (
        coverage_gate
        and scenario_gate
        and review_gate
        and usage_gate
        and flag_gate
    )
    return {
        "schemaVersion": ASSEMBLY_KNOWLEDGE_EVALUATION_VERSION,
        "summary": {
            "rolloutGatePassed": rollout_gate,
            "fixtureCoveragePassed": coverage_gate,
            "scenarioExpectationsPassed": scenario_gate,
            "reviewBurdenGatePassed": review_gate,
            "usageReportingPassed": usage_gate,
            "featureFlagGatePassed": flag_gate,
        },
        "fixtureCoverage": {
            "required": list(ROLLOUT_FIXTURE_IDS),
            "present": sorted(present_ids),
            "missing": missing,
        },
        "scenarioResults": scenario_results,
        "aggregateQuality": {
            "occurrenceCount": total_occurrences,
            "completedReviewActionCount": total_review_actions,
            "reviewActionsPerOccurrence": round(review_rate, 6),
            "maximumReviewActionsPerOccurrence": (
                MAX_REVIEW_ACTIONS_PER_OCCURRENCE
            ),
            "modelCalls": total_model_calls,
            "submittedImages": total_images,
            "inputTokens": total_input_tokens,
            "outputTokens": total_output_tokens,
            "totalTokens": total_tokens,
            "estimatedMaximumCostUsd": round(total_cost, 6),
            "unknownCostFixtureIds": sorted(unknown_cost_fixture_ids),
        },
        "featureFlagGuards": {
            "preparationFlagRequired": (
                flags.get("preparationFlagRequired") is True
            ),
            "aiEnrichmentFlagRequired": (
                flags.get("aiEnrichmentFlagRequired") is True
            ),
            "evidence": flags.get("evidence"),
        },
    }
