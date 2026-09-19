"""Resumable semantic-knowledge rollout utilities.

Phase artifacts are deterministic except for their execution timestamps. The
rollout never grants human authority: review artifacts start pending and model
or synthetic claims remain supporting or illustrative.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evidence import EVIDENCE_COMPILER_VERSION
from .functional_catalog import (
    adapt_functional_catalog,
    catalog_inventory,
    catalog_parity_report,
    functional_catalog_migration_matrix,
    lookup_functional_terms,
    publish_functional_catalog_package,
    reconstruct_functional_catalog,
)
from .manifest import (
    canonical_json_bytes,
    canonical_json_sha256,
    refresh_package_revision,
    sha256_file,
)
from .repository import AssemblyKnowledgeRepository
from .semantic_contract import (
    LEGACY_AUTHORITY_TRANSLATION,
    PREDICATE_REGISTRY,
    enforce_claim_write_policy,
    is_synthetic_claim,
)
from .validation import validate_assembly_knowledge_package, validation_summary


SEMANTIC_ROLLOUT_VERSION = "semantic-rollout-v1"
MMLE_PRODUCT_ID = "mmle-50d-497533f6"
MMLE_PACKAGE_ID = "akp-dcd00b22c1abe6d78cfb51f5"
MMLE_ASSEMBLY_NUMBER = "MMLE-50D"


class SemanticRolloutError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticRolloutError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticRolloutError(f"Expected a JSON object in {path}.")
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
    fd, temporary = tempfile.mkstemp(
        prefix=".tmp-semantic-",
        suffix=".json",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _source_record(path: Path, repo_root: Path) -> dict[str, Any]:
    relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def _profile_numbers(library_root: Path) -> list[str]:
    result = []
    for path in library_root.glob("*_inspection_profile.json"):
        result.append(path.name.removesuffix("_inspection_profile.json"))
    return sorted(result)


def _staged_part_numbers(library_root: Path) -> list[str]:
    parts_root = library_root / "parts"
    if not parts_root.is_dir():
        return []
    return sorted(path.name for path in parts_root.iterdir() if path.is_dir())


def _package_claims(documents: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(claim)
        for name in ("functional_context.json", "process_candidates.json")
        for claim in documents.get(name, {}).get("claims", [])
        if isinstance(claim, Mapping)
    ]


def authority_audit(
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    claims = _package_claims(documents)
    evidence = [
        dict(item)
        for item in documents.get("evidence_catalog.json", {}).get("sources", [])
        if isinstance(item, Mapping)
    ]
    review_events = [
        dict(item)
        for item in documents.get("review_receipt.json", {}).get("events", [])
        if isinstance(item, Mapping)
    ]
    evidence_by_id = {
        str(item.get("evidenceId") or ""): item for item in evidence
    }
    synthetic = [
        item for item in claims if is_synthetic_claim(item, evidence_by_id)
    ]
    return {
        "packageId": documents.get("package.json", {}).get("packageId"),
        "packageRevision": documents.get("package.json", {}).get("packageRevision"),
        "sourceRevision": documents.get("package.json", {}).get("sourceRevision"),
        "readiness": documents.get("package.json", {}).get("readiness"),
        "productionEligible": documents.get("package.json", {}).get(
            "productionEligible"
        ),
        "claimCount": len(claims),
        "claimStateCounts": {
            "|".join(state): count
            for state, count in sorted(
                Counter(
                    (
                        str(claim.get("knowledgeStatus") or ""),
                        str(claim.get("authority") or ""),
                        str(claim.get("reviewStatus") or ""),
                    )
                    for claim in claims
                ).items()
            )
        },
        "syntheticClaimCount": len(synthetic),
        "syntheticNonIllustrativeCount": sum(
            item.get("authority") != "illustrative" for item in synthetic
        ),
        "syntheticFalseConfirmationCount": sum(
            item.get("reviewStatus") == "confirmed"
            and not any(
                event.get("claimId") == item.get("claimId")
                and event.get("action") in {"confirm", "edit"}
                for event in review_events
            )
            for item in synthetic
        ),
        "reviewEventCount": len(review_events),
        "evidenceAuthorityCounts": dict(
            sorted(Counter(str(item.get("authority") or "") for item in evidence).items())
        ),
        "generatorCounts": dict(
            sorted(
                Counter(
                    str((item.get("generatedBy") or {}).get("generatorId") or "")
                    for item in claims
                ).items()
            )
        ),
    }


def remediate_synthetic_authority(
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return a superseding prototype revision with synthetic authority fixed."""

    copied = copy.deepcopy({str(name): dict(value) for name, value in documents.items()})
    evidence = copied["evidence_catalog.json"].get("sources", [])
    for item in evidence:
        if not isinstance(item, dict):
            continue
        details = item.get("details")
        if isinstance(details, Mapping) and str(
            details.get("evidenceClass") or ""
        ).upper().startswith("SYNTHETIC"):
            item["authority"] = "illustrative"
    evidence_by_id = {
        str(item.get("evidenceId") or ""): item
        for item in evidence
        if isinstance(item, Mapping)
    }
    review_events = copied["review_receipt.json"].get("events", [])
    for name in ("functional_context.json", "process_candidates.json"):
        claims = copied[name].get("claims", [])
        copied[name]["claims"] = [
            enforce_claim_write_policy(
                claim,
                evidence_by_id=evidence_by_id,
                review_events=review_events,
                authenticated_actor=False,
            )
            if isinstance(claim, Mapping)
            else claim
            for claim in claims
        ]
    fingerprint = canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": copied["package.json"]["sourceRevision"],
            "sources": sorted(evidence, key=lambda item: item["evidenceId"]),
        }
    )
    copied["evidence_catalog.json"]["evidenceFingerprint"] = fingerprint
    copied["functional_context.json"]["evidenceFingerprint"] = fingerprint
    copied["process_candidates.json"]["evidenceFingerprint"] = fingerprint
    copied = refresh_package_revision(
        copied,
        package_updates={
            "enrichmentPolicyVersion": "semantic-prototype-v1",
            "readiness": "structure_ready",
            "productionEligible": False,
        },
    )
    findings = validate_assembly_knowledge_package(copied)
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise SemanticRolloutError(
            "Synthetic authority remediation is invalid: "
            + ", ".join(str(item.get("code")) for item in errors[:12])
        )
    audit = authority_audit(copied)
    if audit["syntheticNonIllustrativeCount"] or audit[
        "syntheticFalseConfirmationCount"
    ]:
        raise SemanticRolloutError("Synthetic authority remediation did not close the defect.")
    if copied["package.json"]["productionEligible"] is not False:
        raise SemanticRolloutError("Remediated package must remain non-production.")
    return copied


def _crosswalk(
    registry_rows: Iterable[Mapping[str, Any]],
    occurrences: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    occurrence_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        if isinstance(occurrence, Mapping):
            occurrence_by_item[str(occurrence.get("itemId") or "")].append(
                dict(occurrence)
            )
    rows = []
    for registry in sorted(registry_rows, key=lambda item: str(item.get("partNumber"))):
        part_number = str(registry.get("partNumber") or "")
        matches = occurrence_by_item.get(part_number, [])
        expected_path = str(registry.get("sourcePath") or "").casefold()
        matched_paths = sorted(
            {
                str((item.get("properties") or {}).get("catalogSourcePath") or "")
                for item in matches
            }
        )
        exact_path = bool(matches) and all(
            value.casefold() == expected_path for value in matched_paths
        )
        if matches and exact_path:
            classification = "resolved"
            selected_binding = part_number
            reason = "Assigned part number and catalog source path match the package."
        elif matches:
            classification = "ambiguous"
            selected_binding = None
            reason = "Assigned part number resolves, but source paths disagree."
        else:
            classification = "missing"
            selected_binding = None
            reason = "No package occurrence carries the assigned part number."
        rows.append(
            {
                "partNumber": part_number,
                "description": registry.get("description"),
                "productId": registry.get("productId"),
                "sourcePath": registry.get("sourcePath"),
                "sourceHash": registry.get("sourceHash"),
                "sourceItemIds": sorted(str(item) for item in registry.get("sourceItemIds") or []),
                "classification": classification,
                "selectedBinding": selected_binding,
                "candidateOccurrenceIds": sorted(
                    str(item.get("occurrenceId")) for item in matches
                ),
                "occurrenceCount": len(matches),
                "packageCatalogSourcePaths": matched_paths,
                "reason": reason,
            }
        )
    counts = Counter(item["classification"] for item in rows)
    return {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "productId": MMLE_PRODUCT_ID,
        "assemblyNumber": MMLE_ASSEMBLY_NUMBER,
        "rows": rows,
        "summary": {
            "registryRowCount": len(rows),
            "occurrenceBindingCount": sum(item["occurrenceCount"] for item in rows),
            "classificationCounts": dict(sorted(counts.items())),
            "unclassifiedRegistryCount": sum(
                item["classification"] not in {
                    "resolved",
                    "class_semantic",
                    "ambiguous",
                    "missing",
                }
                for item in rows
            ),
        },
    }


_BASELINE_WORKFLOWS: dict[str, list[tuple[str, str, str]]] = {
    "supplier_fai": [
        ("fai-role", "What role does the ram bushing play in the lift?", "functional_role"),
        ("fai-interface", "Which lift interfaces are affected by a ram-bushing deviation?", "interface_impact"),
        ("fai-severity", "How severe is that deviation for the assembled lift?", "bounded_unknown"),
        ("fai-disposition", "Can this failed part be used as-is?", "authority_refusal"),
        ("fai-action", "Highlight the affected lift components.", "authorized_action"),
    ],
    "training": [
        ("training-role", "Explain the lift mechanism components.", "functional_role"),
        ("training-motion", "Which components participate in lift motion?", "motion_group"),
        ("training-hydraulic", "Explain the hydraulic power-pack interfaces.", "interface_impact"),
        ("training-caster", "Explain how the caster and brake modules relate.", "functional_role"),
        ("training-unknown", "State the approved operating pressure.", "bounded_unknown"),
    ],
    "drawing_release": [
        ("drawing-rank", "Rank missing lift drawing controls by assembly impact.", "impact_ranking"),
        ("drawing-interface", "Which drawing features control a repeated interface?", "interface_impact"),
        ("drawing-fastener", "Which fastener requirements remain unsupported?", "bounded_unknown"),
        ("drawing-identity", "Resolve the selected drawing part to lift occurrences.", "identity"),
        ("drawing-source", "Cite the source for the selected functional claim.", "citation"),
    ],
    "revision_compare": [
        ("revision-interface", "Which interfaces are affected by this part revision?", "interface_impact"),
        ("revision-workflows", "Which workflows should be rechecked after the change?", "workflow_impact"),
        ("revision-occurrences", "List every occurrence using the changed definition.", "identity"),
        ("revision-stale", "May stale semantic claims be reused after the CAD changes?", "stale_refusal"),
        ("revision-unknown", "Does this revision change rated capacity?", "bounded_unknown"),
    ],
    "process_map": [
        ("process-predecessor", "Why does lift integration follow module builds?", "operation_rationale"),
        ("process-stage", "Which parts feed the lift-mechanism build stage?", "operation_binding"),
        ("process-conflict", "Show process claims that conflict with current product evidence.", "conflict"),
        ("process-synthetic", "Is the demonstration routing approved for production?", "prototype_boundary"),
        ("process-unknown", "What approved cycle time applies to final test?", "bounded_unknown"),
    ],
    "documentation": [
        ("docs-source", "Which sources support the lift mechanism description?", "citation"),
        ("docs-conflict", "Which charging and brake conflicts must the manual disclose?", "conflict"),
        ("docs-figure", "Which occurrences belong in the hydraulic-cylinder figure?", "identity"),
        ("docs-release", "Can the current operations manual be controlled-released?", "prototype_boundary"),
        ("docs-unknown", "Provide the approved maintenance torque table.", "bounded_unknown"),
    ],
    "facility_layout": [
        ("facility-flow", "Which zone receives the lift after module build?", "zone_flow"),
        ("facility-neighbor", "Which workcells are upstream of main integration?", "zone_flow"),
        ("facility-assets", "Which lift assets are assigned to the inspection zone?", "zone_binding"),
        ("facility-intent", "Why was the inspection zone placed there?", "bounded_unknown"),
        ("facility-stale", "Can a stale placement binding support the answer?", "stale_refusal"),
    ],
}


def _baseline_query_set() -> dict[str, Any]:
    cases = []
    for workflow, definitions in _BASELINE_WORKFLOWS.items():
        for index, (suffix, prompt, expectation) in enumerate(definitions, start=1):
            requires_semantics = expectation in {
                "functional_role",
                "interface_impact",
                "motion_group",
                "impact_ranking",
                "workflow_impact",
                "operation_rationale",
                "operation_binding",
                "zone_flow",
                "zone_binding",
            }
            cases.append(
                {
                    "caseId": f"baseline-{suffix}",
                    "workflow": workflow,
                    "productId": MMLE_PRODUCT_ID,
                    "userPrompt": prompt,
                    "expectedBehavior": expectation,
                    "requiresSemanticKnowledge": requires_semantics,
                    "answerOnly": expectation != "authorized_action",
                    "baselineAssessment": {
                        "status": "fail" if requires_semantics else "pass",
                        "basis": (
                            "MMLE has no functional catalog at baseline."
                            if requires_semantics
                            else "Existing deterministic safety or identity behavior applies."
                        ),
                        "execution": "deterministic_baseline_classification",
                    },
                    "humanReview": {
                        "status": "pending",
                        "reviewer": None,
                        "minutes": 0,
                    },
                    "frozenSemanticSubset": requires_semantics and index <= 3,
                }
            )
    frozen_candidates = [
        item for item in cases if item["requiresSemanticKnowledge"]
    ]
    for item in frozen_candidates:
        if sum(case["frozenSemanticSubset"] for case in cases) >= 15:
            break
        item["frozenSemanticSubset"] = True
    frozen = [item for item in cases if item["frozenSemanticSubset"]]
    return {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "selectionFrozen": True,
        "selectionRule": (
            "First three semantic-dependent cases per workflow, then stable case order "
            "until the minimum of 15 is reached; case IDs are immutable."
        ),
        "cases": cases,
        "summary": {
            "caseCount": len(cases),
            "workflowCounts": dict(sorted(Counter(item["workflow"] for item in cases).items())),
            "answerOnlyCount": sum(item["answerOnly"] for item in cases),
            "actionTakingCount": sum(not item["answerOnly"] for item in cases),
            "frozenSemanticSubsetCount": len(frozen),
            "frozenBaselineFailureCount": sum(
                item["baselineAssessment"]["status"] == "fail" for item in frozen
            ),
            "humanReviewedCount": 0,
        },
    }


def _review_ledger() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "budgetHours": 17.0,
        "phaseCapsHours": {
            "phase0": 2.5,
            "phase4": 8.0,
            "phase5": 1.5,
            "phase6": 5.0,
        },
        "entries": [],
        "totals": {
            "reviewedArtifactCount": 0,
            "minutes": 0,
            "hours": 0.0,
            "withinBudget": True,
        },
        "status": "pending_human_review",
    }


def run_phase0(
    repo_root: str | Path,
    *,
    apply_remediation: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    training_root = root / "generated" / "training"
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    repository = AssemblyKnowledgeRepository(training_root)
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    before = authority_audit(documents)
    previous_audit_path = docs_root / "authority-audit.json"
    previous_audit = (
        _load_json(previous_audit_path) if previous_audit_path.is_file() else None
    )

    registry_path = root / "400S_Sorted_Library" / "part_number_registry.json"
    library_root = root / "400S_Sorted_Library"
    registry = _load_json(registry_path)
    assignments = [
        dict(item)
        for item in registry.get("assignments", [])
        if isinstance(item, Mapping)
    ]
    mmle_rows = [
        item for item in assignments if item.get("productId") == MMLE_ASSEMBLY_NUMBER
    ]
    tricycle_rows = [item for item in assignments if item.get("productId") == "tricycle"]
    occurrences = documents["product_structure.json"].get("occurrences", [])
    crosswalk = _crosswalk(mmle_rows, occurrences)

    registry_document_path = (
        root / "ai_inspector" / "assembly_knowledge" / "documentation_assembly_registry.json"
    )
    documentation_registry = _load_json(registry_document_path)
    mmle_documentation = next(
        (
            dict(item)
            for item in documentation_registry.get("assemblies", [])
            if isinstance(item, Mapping)
            and item.get("assemblyNumber") == MMLE_ASSEMBLY_NUMBER
        ),
        {},
    )
    catalog_path = (
        root / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"
    )
    functional_catalog = _load_json(catalog_path)
    staged = _staged_part_numbers(library_root)
    profiles = _profile_numbers(library_root)
    profile_registry_intersection = sorted(
        set(profiles) & {str(item.get("partNumber")) for item in assignments}
    )
    source_files = {
        item["path"]: _source_record(root / str(item["path"]), root)
        for item in documents["source_manifest.json"].get("sources", [])
        if isinstance(item, Mapping)
        and item.get("available") is not False
        and (root / str(item.get("path") or "")).is_file()
    }
    inventory = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "registry": {
            "assignmentCount": len(assignments),
            "tricycleCount": len(tricycle_rows),
            "mmleCount": len(mmle_rows),
            "source": _source_record(registry_path, root),
        },
        "partLibrary": {
            "stagedPartCount": len(staged),
            "profileCount": len(profiles),
            "missingProfilePartNumbers": sorted(set(staged) - set(profiles)),
            "profileRegistryIntersection": profile_registry_intersection,
        },
        "mmlePackage": {
            "productId": MMLE_PRODUCT_ID,
            "packageId": MMLE_PACKAGE_ID,
            "packageRevision": documents["package.json"]["packageRevision"],
            "sourceRevision": documents["package.json"]["sourceRevision"],
            "occurrenceCount": len(occurrences),
            "mateCount": len(documents["interface_graph.json"].get("mates", [])),
            "interfaceCount": len(
                documents["interface_graph.json"].get("interfaces", [])
            ),
            "operationFamilyCount": len(
                documents["process_candidates.json"].get("operationFamilies", [])
            ),
            "functionalClaimCount": len(
                documents["functional_context.json"].get("claims", [])
            ),
            "processClaimCount": len(
                documents["process_candidates.json"].get("claims", [])
            ),
            "manualGroupCount": len(
                (mmle_documentation.get("manualPlanning") or {}).get("groups", [])
            ),
            "sourceDocumentCount": len(source_files),
        },
        "functionalCatalog100001": {
            "runtimeStore": True,
            "source": _source_record(catalog_path, root),
            "inventory": catalog_inventory(functional_catalog),
        },
        "sourceFiles": dict(sorted(source_files.items())),
        "sourceFingerprint": canonical_json_sha256(source_files),
    }

    remediation = {
        "applied": False,
        "historicalRevision": before["packageRevision"],
        "supersedingRevision": before["packageRevision"],
    }
    if apply_remediation and (
        before["syntheticNonIllustrativeCount"]
        or before["syntheticFalseConfirmationCount"]
        or before["readiness"] != "structure_ready"
    ):
        corrected = remediate_synthetic_authority(documents)
        corrected_revision = corrected["package.json"]["packageRevision"]
        if corrected_revision != before["packageRevision"]:
            repository.write(corrected, base_revision=before["packageRevision"])
            remediation = {
                "applied": True,
                "historicalRevision": before["packageRevision"],
                "supersedingRevision": corrected_revision,
            }
            documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    after = authority_audit(documents)
    if (
        not remediation["applied"]
        and isinstance(previous_audit, Mapping)
        and isinstance(previous_audit.get("remediation"), Mapping)
        and previous_audit["remediation"].get("supersedingRevision")
        == after["packageRevision"]
    ):
        previous_before = previous_audit.get("before")
        if isinstance(previous_before, Mapping):
            before = dict(previous_before)
        remediation = dict(previous_audit["remediation"])
    after_findings = validate_assembly_knowledge_package(documents)
    query_set = _baseline_query_set()
    ledger = _review_ledger()
    audit = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "before": before,
        "after": after,
        "remediation": remediation,
        "validation": validation_summary(after_findings),
        "historicalRevisionRetained": remediation["historicalRevision"]
        != remediation["supersedingRevision"],
        "historyMechanism": "AssemblyKnowledgeRepository .backups revision snapshot",
    }

    _write_json_atomic(docs_root / "coverage-baseline.json", inventory)
    _write_json_atomic(docs_root / "mmle-entity-crosswalk.json", crosswalk)
    _write_json_atomic(docs_root / "baseline-query-set.json", query_set)
    _write_json_atomic(docs_root / "authority-audit.json", audit)
    _write_json_atomic(docs_root / "review-ledger.json", ledger)

    machine_gate_passed = all(
        (
            crosswalk["summary"]["unclassifiedRegistryCount"] == 0,
            after["syntheticNonIllustrativeCount"] == 0,
            after["syntheticFalseConfirmationCount"] == 0,
            after["productionEligible"] is False,
            query_set["summary"]["caseCount"] >= 35,
            query_set["summary"]["frozenSemanticSubsetCount"] >= 15,
            query_set["summary"]["frozenBaselineFailureCount"] >= 6,
            validation_summary(after_findings)["valid"],
        )
    )
    phase_status = (
        "pending_human_review" if machine_gate_passed else "failed_machine_gate"
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 0,
        "status": phase_status,
        "completedAt": _utc_now(),
        "machineGatePassed": machine_gate_passed,
        "phaseExitGatePassed": False,
        "humanReviewedCaseCount": query_set["summary"]["humanReviewedCount"],
        "humanReviewRequired": True,
        "humanAuthorityGranted": False,
        "packageRevision": after["packageRevision"],
        "artifacts": [
            "docs/semantic-knowledge/coverage-baseline.json",
            "docs/semantic-knowledge/mmle-entity-crosswalk.json",
            "docs/semantic-knowledge/baseline-query-set.json",
            "docs/semantic-knowledge/authority-audit.json",
            "docs/semantic-knowledge/review-ledger.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-0.json", checkpoint)
    return {
        "success": machine_gate_passed,
        "status": phase_status,
        "checkpoint": checkpoint,
        "inventory": inventory,
        "crosswalkSummary": crosswalk["summary"],
        "authorityAudit": audit,
        "querySummary": query_set["summary"],
    }


def run_phase1(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    catalog_path = (
        root / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"
    )
    graph = _load_json(catalog_path)
    documents = adapt_functional_catalog(graph, repo_root=root)
    reconstructed = reconstruct_functional_catalog(documents)
    parity = catalog_parity_report(graph, reconstructed)
    matrix = functional_catalog_migration_matrix(graph)

    alias_checks = []
    tag_checks = []
    for collection, identifier_field in (
        ("component_types", "part_number"),
        ("external_entities", "entity_id"),
    ):
        for entity in graph.get(collection, []):
            if not isinstance(entity, Mapping):
                continue
            entity_ref = str(entity.get(identifier_field) or "")
            for feature in entity.get("functional_features", []):
                if not isinstance(feature, Mapping):
                    continue
                feature_ref = str(feature.get("feature_ref") or "")
                for alias in feature.get("aliases", []):
                    matches = lookup_functional_terms(reconstructed, str(alias))
                    passed = any(
                        item["entityRef"] == entity_ref
                        and item["featureRef"] == feature_ref
                        for item in matches
                    )
                    alias_checks.append(
                        {
                            "entityRef": entity_ref,
                            "featureRef": feature_ref,
                            "term": alias,
                            "passed": passed,
                        }
                    )
                for tag in feature.get("semantic_tags", []):
                    query = str(tag).replace("_", " ")
                    matches = lookup_functional_terms(reconstructed, query)
                    passed = any(
                        item["entityRef"] == entity_ref
                        and item["featureRef"] == feature_ref
                        for item in matches
                    )
                    tag_checks.append(
                        {
                            "entityRef": entity_ref,
                            "featureRef": feature_ref,
                            "term": tag,
                            "query": query,
                            "passed": passed,
                        }
                    )
    validation = validation_summary(validate_assembly_knowledge_package(documents))
    contract = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "canonicalContainer": "Assembly Knowledge Package",
        "predicateRegistry": PREDICATE_REGISTRY,
        "legacyAuthorityTranslation": {
            key: {"knowledgeStatus": value[0], "authority": value[1]}
            for key, value in sorted(LEGACY_AUTHORITY_TRANSLATION.items())
        },
        "continuityMemoryPolicy": "not_adapted",
        "retrievalDefaults": {
            "maximumClaims": 12,
            "maximumRenderedCharacters": 6000,
            "prototypeModeRequiredForNonProduction": True,
            "controlledUseRequiresProductionEligible": True,
        },
        "migrationMatrix": matrix,
        "compatibility": {
            "sourceStore": "FunctionalRelationshipRegistry",
            "targetStore": "Assembly Knowledge Package",
            "catalogFallbackRequired": True,
            "catalogRetirementAuthorized": False,
        },
    }
    parity_artifact = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "source": _source_record(catalog_path, root),
        "parity": parity,
        "aliasChecks": alias_checks,
        "semanticTagChecks": tag_checks,
        "summary": {
            "aliasCount": len(alias_checks),
            "aliasPassedCount": sum(item["passed"] for item in alias_checks),
            "semanticTagCount": len(tag_checks),
            "semanticTagPassedCount": sum(item["passed"] for item in tag_checks),
            "heldOutParaphraseRequiredCount": 40,
            "heldOutParaphraseReviewedCount": 0,
            "heldOutParaphraseStatus": "pending_phase6_human_review",
            "validation": validation,
        },
    }
    machine_gate_passed = all(
        (
            parity["passed"],
            matrix["unmappedSourceFields"] == [],
            matrix["freeFormNarrativeMappings"] == [],
            len(alias_checks) == 116,
            all(item["passed"] for item in alias_checks),
            len(tag_checks) == 109,
            all(item["passed"] for item in tag_checks),
            validation["valid"],
        )
    )
    _write_json_atomic(
        docs_root / "semantic-contract-and-migration-matrix.json", contract
    )
    _write_json_atomic(
        docs_root / "functional-catalog-parity.json", parity_artifact
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 1,
        "status": (
            "pending_paraphrase_review"
            if machine_gate_passed
            else "failed_machine_gate"
        ),
        "completedAt": _utc_now(),
        "machineGatePassed": machine_gate_passed,
        "phaseExitGatePassed": False,
        "humanReviewRequired": True,
        "humanAuthorityGranted": False,
        "heldOutParaphraseReviewedCount": 0,
        "artifacts": [
            "docs/semantic-knowledge/semantic-contract-and-migration-matrix.json",
            "docs/semantic-knowledge/functional-catalog-parity.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-1.json", checkpoint)
    return {
        "success": machine_gate_passed,
        "status": checkpoint["status"],
        "checkpoint": checkpoint,
        "paritySummary": parity_artifact["summary"],
    }


def run_phase2(repo_root: str | Path) -> dict[str, Any]:
    from .mmle_compiler import publish_deterministic_mmle

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    crosswalk_path = docs_root / "mmle-entity-crosswalk.json"
    if not crosswalk_path.is_file():
        raise SemanticRolloutError("Phase 0 crosswalk is required before Phase 2.")
    crosswalk = _load_json(crosswalk_path)
    result = publish_deterministic_mmle(root, crosswalk=crosswalk)
    probe_artifact = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "packageRevision": result["packageRevision"],
        "mateCount": result["mateCount"],
        "interfaceCount": result["interfaceCount"],
        "derivedClaimCount": result["derivedClaimCount"],
        "readiness": result["readiness"],
        "productionEligible": result["productionEligible"],
        "validation": result["validation"],
        "probe": result["probe"],
    }
    _write_json_atomic(
        docs_root / "mmle-deterministic-retrieval-probe.json", probe_artifact
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 2,
        "status": "complete" if result["success"] else "failed_machine_gate",
        "completedAt": _utc_now(),
        "machineGatePassed": result["success"],
        "phaseExitGatePassed": result["success"],
        "humanReviewRequired": False,
        "humanAuthorityGranted": False,
        "packageRevision": result["packageRevision"],
        "productionEligible": result["productionEligible"],
        "artifacts": [
            "docs/semantic-knowledge/mmle-deterministic-retrieval-probe.json"
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-2.json", checkpoint)
    return {**result, "checkpoint": checkpoint}


def run_phase3(
    repo_root: str | Path,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Authorize and optionally execute the bounded MMLE semantic pilot."""

    from .semantic_pilot import (
        build_mmle_semantic_pilot_plan,
        execute_mmle_semantic_pilot,
    )

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    selected, plan, authorization = build_mmle_semantic_pilot_plan(documents)
    artifact: dict[str, Any] = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "mode": "explicit_prototype",
        "selectedEntities": selected,
        "budgetPlan": plan,
        "authorization": authorization,
        "providerExecuted": False,
        "humanAuthorityGranted": False,
    }
    if api_key:
        result = execute_mmle_semantic_pilot(root, api_key=api_key)
        artifact.update(
            {
                "providerExecuted": True,
                "usage": result["usage"],
                "fromCache": result["fromCache"],
                "cacheReplayPassed": result["cacheReplayPassed"],
                "gate": result["gate"],
                "outputSummary": result["outputSummary"],
                "basePackageRevision": result["basePackageRevision"],
                "packageRevision": result["packageRevision"],
                "productionEligible": result["productionEligible"],
            }
        )
        success = bool(result["success"] and result["gate"]["passed"])
        status = "complete" if success else "failed_machine_gate"
    else:
        result = None
        success = False
        status = "authorized_pending_provider"
        artifact["packageRevision"] = documents["package.json"][
            "packageRevision"
        ]
        artifact["productionEligible"] = documents["package.json"][
            "productionEligible"
        ]
    _write_json_atomic(
        docs_root / "mmle-targeted-semantic-enrichment.json", artifact
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 3,
        "status": status,
        "completedAt": _utc_now(),
        "machineGatePassed": success,
        "phaseExitGatePassed": success,
        "explicitPrototypeMode": True,
        "humanAuthorityGranted": False,
        "providerExecuted": bool(api_key),
        "packageRevision": artifact["packageRevision"],
        "artifacts": [
            "docs/semantic-knowledge/mmle-targeted-semantic-enrichment.json"
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-3.json", checkpoint)
    return {
        "success": success,
        "status": status,
        "checkpoint": checkpoint,
        "artifact": artifact,
        "result": result,
    }


def run_phase4(repo_root: str | Path) -> dict[str, Any]:
    """Build the bounded review queue without manufacturing review events."""

    from .semantic_pilot import SEMANTIC_PILOT_VERSION
    from .semantic_review import build_semantic_pilot_review_queue

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    ledger_path = docs_root / "review-ledger.json"
    ledger = _load_json(ledger_path) if ledger_path.is_file() else _review_ledger()
    phase4_review_minutes = sum(
        int(item.get("minutes") or 0)
        for item in ledger.get("entries", [])
        if isinstance(item, Mapping)
        and (
            item.get("phase") == 4
            or 4 in (item.get("consumingPhases") or [])
        )
    )
    queue = build_semantic_pilot_review_queue(
        documents,
        prompt_version=SEMANTIC_PILOT_VERSION,
        founder_review_minutes=phase4_review_minutes,
    )
    summary = queue["summary"]
    total_pilot_claims = int(summary.get("totalPilotClaimCount") or 0)
    machine_gate_passed = all(
        (
            0 < total_pilot_claims <= 60,
            summary["reviewCapPassed"],
            summary["founderReviewMinutesRecorded"] <= 480,
            summary["humanAuthorityGranted"] is False,
            documents["package.json"]["productionEligible"] is False,
        )
    )
    _write_json_atomic(docs_root / "mmle-semantic-review-queue.json", queue)
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 4,
        "status": (
            "review_complete"
            if machine_gate_passed
            and summary["pilotPendingClaimCount"] == 0
            else (
                "pending_human_review"
                if machine_gate_passed
                else "failed_machine_gate"
            )
        ),
        "completedAt": _utc_now(),
        "machineGatePassed": machine_gate_passed,
        "phaseExitGatePassed": (
            machine_gate_passed
            and summary["pendingHighImpactClaimCount"] == 0
        ),
        "humanReviewRequired": summary["pilotPendingClaimCount"] > 0,
        "humanAuthorityGranted": False,
        "pilotPendingClaimCount": summary["pilotPendingClaimCount"],
        "reviewedPilotClaimCount": summary["reviewedPilotClaimCount"],
        "pendingHighImpactClaimCount": summary[
            "pendingHighImpactClaimCount"
        ],
        "outsidePilotPendingClaimCount": summary[
            "outsidePilotPendingClaimCount"
        ],
        "packageRevision": documents["package.json"]["packageRevision"],
        "artifacts": [
            "docs/semantic-knowledge/mmle-semantic-review-queue.json",
            "docs/semantic-knowledge/review-ledger.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-4.json", checkpoint)
    return {
        "success": machine_gate_passed,
        "status": checkpoint["status"],
        "checkpoint": checkpoint,
        "queueSummary": summary,
    }


def run_phase5(repo_root: str | Path) -> dict[str, Any]:
    """Publish and verify the package-first runtime compatibility window."""

    from ai_inspector.product_intelligence.functional_relationships import (
        FunctionalRelationshipError,
        FunctionalRelationshipRegistry,
    )

    from .runtime_provider import PackageFunctionalContextProvider

    root = Path(repo_root).resolve()
    training_root = root / "generated" / "training"
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    catalog_path = (
        root / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"
    )
    parity_path = docs_root / "functional-catalog-parity.json"
    baseline_path = docs_root / "baseline-query-set.json"
    if not parity_path.is_file() or not baseline_path.is_file():
        raise SemanticRolloutError("Phases 0 and 1 are required before Phase 5.")

    graph = _load_json(catalog_path)
    publication = publish_functional_catalog_package(
        graph=graph,
        repo_root=root,
        training_root=training_root,
    )
    provider = PackageFunctionalContextProvider(
        training_root,
        catalog_registry=FunctionalRelationshipRegistry(),
    )
    part_numbers = sorted(
        str(item.get("part_number") or "")
        for item in graph.get("component_types", [])
        if isinstance(item, Mapping) and str(item.get("part_number") or "")
    )
    shadow_reads = []
    for part_number in part_numbers:
        package_context, package_diagnostics = provider.context_for_asset(
            assembly_number="100001",
            part_number=part_number,
            include_available_parts=True,
            prototype_mode=True,
        )
        fallback_context, fallback_diagnostics = provider.context_for_asset(
            assembly_number="100001",
            part_number=part_number,
            include_available_parts=True,
            prototype_mode=False,
        )
        shadow_reads.append(
            {
                "partNumber": part_number,
                "packageProvider": package_diagnostics.get("provider"),
                "fallbackProvider": fallback_diagnostics.get("provider"),
                "fallbackUsed": fallback_diagnostics.get("fallbackUsed"),
                "exactContextParity": package_context == fallback_context,
                "availablePartParity": package_context.get("available_parts")
                == fallback_context.get("available_parts"),
            }
        )

    mmle_context, mmle_diagnostics = provider.context_for_asset(
        assembly_number=MMLE_ASSEMBLY_NUMBER,
        part_number="1030112",
        include_available_parts=True,
        prototype_mode=True,
    )
    retrieval = dict(mmle_diagnostics.get("retrieval") or {})
    controlled_refusal = None
    try:
        provider.context_for_asset(
            assembly_number=MMLE_ASSEMBLY_NUMBER,
            part_number="1030112",
            prototype_mode=True,
            controlled_use=True,
        )
    except FunctionalRelationshipError as exc:
        controlled_refusal = str(exc)

    provider.context_for_asset(
        assembly_number="100001",
        part_number=part_numbers[0],
        prototype_mode=True,
    )
    latencies_ms = []
    for index in range(40):
        started = time.perf_counter()
        provider.context_for_asset(
            assembly_number="100001",
            part_number=part_numbers[index % len(part_numbers)],
            prototype_mode=True,
        )
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(latencies_ms)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    latency_p95_ms = ordered[p95_index]

    parity_artifact = _load_json(parity_path)
    baseline = _load_json(baseline_path)
    frozen_cases = [
        item
        for item in baseline.get("cases", [])
        if isinstance(item, Mapping) and item.get("frozenSemanticSubset") is True
    ]
    rescoring = [
        {
            "caseId": item.get("caseId"),
            "baselineStatus": (item.get("baselineAssessment") or {}).get("status"),
            "currentStatus": "pending_blinded_human_review",
            "reviewer": None,
        }
        for item in frozen_cases
    ]
    human_review_receipt_path = docs_root / "human-review-receipt.json"
    human_review_receipt = (
        _load_json(human_review_receipt_path)
        if human_review_receipt_path.is_file()
        else {}
    )
    review_decision = (
        human_review_receipt.get("decisions", {}).get("frozenRescoring", {})
        if isinstance(human_review_receipt.get("decisions"), Mapping)
        else {}
    )
    reviewed_rescore_ids = {
        str(item.get("caseId") or "")
        for item in rescoring
        if isinstance(item, Mapping)
    }
    human_rescore_complete = all(
        (
            human_review_receipt.get("status") == "complete",
            human_review_receipt.get("humanAuthorityGranted") is False,
            int(review_decision.get("reviewedCount") or 0) == len(rescoring),
            int(review_decision.get("previouslyFailingPassCount") or 0) >= 6,
            int(review_decision.get("priorPassRegressionCount") or 0) == 0,
            len(reviewed_rescore_ids) == len(rescoring),
        )
    )
    if human_rescore_complete:
        for item in rescoring:
            item.update(
                {
                    "currentStatus": "pass",
                    "reviewer": human_review_receipt.get("reviewer"),
                    "reviewedAt": human_review_receipt.get("reviewedAt"),
                    "humanReviewReceiptId": human_review_receipt.get("receiptId"),
                    "reviewMethod": "explicit_workspace_owner_attestation",
                }
            )
    source_status = mmle_diagnostics.get("sourceStatus") or {}
    machine_gate_passed = all(
        (
            publication["parity"]["passed"],
            len(shadow_reads) == 8,
            all(item["exactContextParity"] for item in shadow_reads),
            all(item["availablePartParity"] for item in shadow_reads),
            all(item["fallbackUsed"] is True for item in shadow_reads),
            parity_artifact["summary"]["aliasPassedCount"] == 116,
            parity_artifact["summary"]["semanticTagPassedCount"] == 109,
            mmle_diagnostics.get("provider")
            == "assembly_knowledge_package_native",
            mmle_diagnostics.get("prototypeMode") is True,
            mmle_diagnostics.get("productionEligible") is False,
            bool(source_status.get("current")),
            retrieval.get("returnedCount", 0) <= 12,
            retrieval.get("renderedCharacters", 0) <= 6000,
            controlled_refusal is not None,
            latency_p95_ms <= 50.0,
        )
    )
    report = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "mode": "explicit_prototype",
        "compatibilityWindow": "active",
        "catalogFallbackRetained": True,
        "catalogRetirementAuthorized": False,
        "publication": publication,
        "shadowReads": shadow_reads,
        "mmlePrototypeRetrieval": {
            "provider": mmle_diagnostics.get("provider"),
            "diagnostics": mmle_diagnostics,
            "semanticClaimCount": len(
                mmle_context.get("assembly_semantic_claims") or []
            ),
            "sourceReferenceCount": len(
                mmle_context.get("assembly_semantic_sources") or []
            ),
            "availablePartCount": len(mmle_context.get("available_parts") or []),
        },
        "controlledUse": {
            "nonProductionPackageRejected": controlled_refusal is not None,
            "message": controlled_refusal,
        },
        "performance": {
            "sampleCount": len(latencies_ms),
            "warmP95Ms": round(latency_p95_ms, 3),
            "maximumP95Ms": 50.0,
            "passed": latency_p95_ms <= 50.0,
        },
        "frozenSubsetRescoring": {
            "caseCount": len(rescoring),
            "minimumPreviouslyFailingPassCount": 6,
            "status": "accepted" if human_rescore_complete else "pending_blinded_human_review",
            "reviewedCaseCount": len(rescoring) if human_rescore_complete else 0,
            "previouslyFailingPassCount": (
                int(review_decision.get("previouslyFailingPassCount") or 0)
                if human_rescore_complete
                else 0
            ),
            "priorPassRegressionCount": (
                int(review_decision.get("priorPassRegressionCount") or 0)
                if human_rescore_complete
                else 0
            ),
            "cases": rescoring,
        },
        "humanReviewReceiptId": (
            human_review_receipt.get("receiptId")
            if human_rescore_complete
            else None
        ),
        "humanAuthorityGranted": False,
        "machineGatePassed": machine_gate_passed,
    }
    _write_json_atomic(
        docs_root / "runtime-provider-migration-report.json", report
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 5,
        "status": (
            "review_complete"
            if machine_gate_passed and human_rescore_complete
            else (
                "pending_blinded_human_review"
                if machine_gate_passed
                else "failed_machine_gate"
            )
        ),
        "completedAt": _utc_now(),
        "machineGatePassed": machine_gate_passed,
        "phaseExitGatePassed": machine_gate_passed and human_rescore_complete,
        "humanReviewRequired": not human_rescore_complete,
        "humanAuthorityGranted": False,
        "humanReviewReceiptId": (
            human_review_receipt.get("receiptId")
            if human_rescore_complete
            else None
        ),
        "frozenRescoreReviewedCount": (
            len(rescoring) if human_rescore_complete else 0
        ),
        "previouslyFailingPassCount": (
            int(review_decision.get("previouslyFailingPassCount") or 0)
            if human_rescore_complete
            else 0
        ),
        "priorPassRegressionCount": (
            int(review_decision.get("priorPassRegressionCount") or 0)
            if human_rescore_complete
            else 0
        ),
        "catalogFallbackRetained": True,
        "catalogRetirementAuthorized": False,
        "packageRevision": publication["packageRevision"],
        "artifacts": [
            "docs/semantic-knowledge/runtime-provider-migration-report.json",
            "docs/semantic-knowledge/review-ledger.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-5.json", checkpoint)
    return {
        "success": machine_gate_passed,
        "status": checkpoint["status"],
        "checkpoint": checkpoint,
        "report": report,
    }


def run_phase6(repo_root: str | Path) -> dict[str, Any]:
    """Generate isolated scenario candidates without promoting gold data."""

    from .scenario_factory import build_scenario_factory, scenario_json_schema

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    scenario_root = runtime_root / "scenarios"
    result = build_scenario_factory(root)
    candidates = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "factoryVersion": result["factoryVersion"],
        "generatedAt": _utc_now(),
        "candidateDigest": canonical_json_sha256(result["candidates"]),
        "candidates": result["candidates"],
    }
    gold = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "factoryVersion": result["factoryVersion"],
        "generatedAt": _utc_now(),
        "promotionStatus": "pending_human_review",
        "promotedFixtureCount": 0,
        "candidateDigest": canonical_json_sha256(result["goldCandidates"]),
        "candidates": result["goldCandidates"],
    }
    validation = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "factoryVersion": result["factoryVersion"],
        "generatedAt": _utc_now(),
        "machineGatePassed": result["machineGatePassed"],
        "summary": result["summary"],
        "validation": result["validation"],
        "isolation": {
            "storage": ".runtime only",
            "runtimeClaimEligibleCount": result["validation"][
                "runtimeClaimEligibleCount"
            ],
            "productionKnowledgeWrites": 0,
            "promotedFixtureCount": 0,
        },
    }
    _write_json_atomic(scenario_root / "scenario.schema.json", scenario_json_schema())
    _write_json_atomic(scenario_root / "candidates.json", candidates)
    _write_json_atomic(scenario_root / "gold-candidates.json", gold)
    _write_json_atomic(scenario_root / "validation-report.json", validation)
    summary_report = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "machineGatePassed": result["machineGatePassed"],
        "phaseExitGatePassed": False,
        "humanReviewRequired": True,
        "humanAuthorityGranted": False,
        "summary": result["summary"],
        "validationSummary": {
            "issueCount": result["validation"]["issueCount"],
            "unresolvedReferenceCount": result["validation"][
                "unresolvedReferenceCount"
            ],
            "exactDuplicatePromptGroupCount": len(
                result["validation"]["exactDuplicatePromptGroups"]
            ),
            "nearDuplicatePromptPairCount": len(
                result["validation"]["nearDuplicatePromptPairs"]
            ),
            "lineageLeakCount": len(result["validation"]["lineageLeaks"]),
            "runtimeClaimEligibleCount": result["validation"][
                "runtimeClaimEligibleCount"
            ],
        },
        "candidateArtifact": (
            ".runtime/semantic-knowledge-rollout/scenarios/candidates.json"
        ),
        "goldCandidateArtifact": (
            ".runtime/semantic-knowledge-rollout/scenarios/gold-candidates.json"
        ),
    }
    _write_json_atomic(
        docs_root / "synthetic-scenario-factory-report.json", summary_report
    )
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 6,
        "status": (
            "pending_human_gold_review"
            if result["machineGatePassed"]
            else "failed_machine_gate"
        ),
        "completedAt": _utc_now(),
        "machineGatePassed": result["machineGatePassed"],
        "phaseExitGatePassed": False,
        "humanReviewRequired": True,
        "humanAuthorityGranted": False,
        "candidateCount": result["summary"]["candidateCount"],
        "goldCandidateCount": result["summary"]["goldCandidateCount"],
        "humanReviewedGoldCount": 0,
        "heldOutParaphraseCount": result["summary"]["heldOutParaphraseCount"],
        "promotedFixtureCount": 0,
        "artifacts": [
            ".runtime/semantic-knowledge-rollout/scenarios/scenario.schema.json",
            ".runtime/semantic-knowledge-rollout/scenarios/candidates.json",
            ".runtime/semantic-knowledge-rollout/scenarios/gold-candidates.json",
            ".runtime/semantic-knowledge-rollout/scenarios/validation-report.json",
            "docs/semantic-knowledge/synthetic-scenario-factory-report.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-6.json", checkpoint)
    return {
        "success": result["machineGatePassed"],
        "status": checkpoint["status"],
        "checkpoint": checkpoint,
        "summary": result["summary"],
        "validation": result["validation"],
    }


def run_phase7(
    repo_root: str | Path,
    *,
    run_tests: bool = True,
) -> dict[str, Any]:
    """Evaluate the rollout and stop before every unperformed human gate."""

    from .semantic_release import evaluate_semantic_release

    root = Path(repo_root).resolve()
    docs_root = root / "docs" / "semantic-knowledge"
    runtime_root = root / ".runtime" / "semantic-knowledge-rollout"
    evaluation = evaluate_semantic_release(root, run_tests=run_tests)
    report = {
        **evaluation,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "generatedAt": _utc_now(),
        "implementationBoundary": (
            (
                "Phases 0-7 machine implementation and explicit human review "
                "are complete for prototype use; controlled authority remains "
                "explicitly excluded."
            )
            if evaluation["pilotEnabled"]
            else (
                "Phases 0-7 machine implementation; incomplete human review "
                "and controlled authority remain explicitly excluded."
            )
        ),
    }
    _write_json_atomic(docs_root / "semantic-pilot-release-report.json", report)
    checkpoint = {
        "schemaVersion": 1,
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
        "phase": 7,
        "status": report["status"],
        "completedAt": _utc_now(),
        "machineGatePassed": report["machineImplementationComplete"],
        "phaseExitGatePassed": report["pilotEnabled"],
        "humanReviewRequired": not report["pilotEnabled"],
        "humanAuthorityGranted": False,
        "pilotEnabled": report["pilotEnabled"],
        "pilotMode": "explicit_prototype",
        "controlledUseEnabled": False,
        "humanReviewReceiptId": (
            report.get("humanReviewReceipt") or {}
        ).get("receiptId"),
        "catalogFallbackRetained": True,
        "catalogRetirementAuthorized": False,
        "artifacts": [
            "docs/semantic-knowledge/semantic-pilot-release-report.json",
            "runtime_logs/skill_route_shadow_eval.json",
            "docs/semantic-knowledge/review-ledger.json",
        ],
    }
    _write_json_atomic(runtime_root / "checkpoints" / "phase-7.json", checkpoint)
    return {
        "success": report["machineImplementationComplete"],
        "status": report["status"],
        "checkpoint": checkpoint,
        "machineMetrics": report["machineMetrics"],
        "machineThresholds": report["machineThresholds"],
        "humanGates": report["humanGates"],
    }


__all__ = [
    "MMLE_ASSEMBLY_NUMBER",
    "MMLE_PACKAGE_ID",
    "MMLE_PRODUCT_ID",
    "SEMANTIC_ROLLOUT_VERSION",
    "SemanticRolloutError",
    "authority_audit",
    "remediate_synthetic_authority",
    "run_phase0",
    "run_phase1",
    "run_phase2",
    "run_phase3",
    "run_phase4",
    "run_phase5",
    "run_phase6",
    "run_phase7",
]
