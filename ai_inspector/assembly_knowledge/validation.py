"""Cross-document semantic validation for Assembly Knowledge Packages."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .manifest import canonical_json_sha256
from .evidence import EVIDENCE_COMPILER_VERSION
from .schema import validate_package_documents


_AUTHORITATIVE_EVIDENCE_TYPES = {
    "procedure",
    "work_instruction",
    "standard",
    "user_statement",
}
_PROCESS_PREDICATES = {
    "candidate_operation_family",
    "candidate_process_branch",
    "candidate_intermediate_result",
    "manufacturing_order",
    "precedes",
    "assembly_sequence",
}
_NUMERIC_MANUFACTURING_TERMS = {
    "torque",
    "tolerance",
    "dimension",
    "speed",
    "pressure",
    "temperature",
    "duration",
    "setting",
    "inspection_limit",
}


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    priority: int = 50,
    details: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
        "priority": priority,
    }
    subjects = sorted(set(subject_refs))
    evidence = sorted(set(evidence_refs))
    if subjects:
        result["subjectRefs"] = subjects
    if evidence:
        result["evidenceRefs"] = evidence
    if details:
        result["details"] = dict(details)
    return result


def _contains_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_number(item) for item in value)
    return False


def _claims(documents: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for name in ("functional_context.json", "process_candidates.json"):
        for item in documents.get(name, {}).get("claims", []):
            if isinstance(item, Mapping):
                rows.append(dict(item))
    return rows


def _cycle_nodes(
    operations: Sequence[Mapping[str, Any]],
) -> set[str]:
    operation_ids = {
        item.get("operationId")
        for item in operations
        if isinstance(item.get("operationId"), str)
    }
    adjacency: Dict[str, list[str]] = {item: [] for item in operation_ids}
    for item in operations:
        target = item.get("operationId")
        if target not in adjacency:
            continue
        for predecessor in item.get("predecessorOperationIds", []):
            if predecessor in adjacency:
                adjacency[predecessor].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            if node in stack:
                cycle.update(stack[stack.index(node) :])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for target in adjacency[node]:
            visit(target, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacency):
        visit(node, [])
    return cycle


def validate_assembly_knowledge_package(
    documents: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = [
        {
            **item,
            "priority": 5 if item.get("severity") == "error" else 40,
        }
        for item in validate_package_documents(documents)
    ]
    package = documents.get("package.json", {})
    source_revision = package.get("sourceRevision")
    for name, document in sorted(documents.items()):
        if name == "package.json" or not isinstance(document, Mapping):
            continue
        document_revision = document.get("sourceRevision")
        if document_revision is not None and document_revision != source_revision:
            findings.append(
                _finding(
                    "error",
                    "stale_source_revision",
                    f"{name} targets a different source revision.",
                    priority=1,
                    details={"document": name},
                )
            )

    structure = documents.get("product_structure.json", {})
    interface_graph = documents.get("interface_graph.json", {})
    visual = documents.get("visual_manifest.json", {})
    evidence_catalog = documents.get("evidence_catalog.json", {})
    process = documents.get("process_candidates.json", {})
    occurrences = {
        item.get("occurrenceId"): item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and isinstance(item.get("occurrenceId"), str)
    }
    mates = {
        item.get("mateId"): item
        for item in interface_graph.get("mates", [])
        if isinstance(item, Mapping) and isinstance(item.get("mateId"), str)
    }
    interfaces = {
        item.get("interfaceId"): item
        for item in interface_graph.get("interfaces", [])
        if isinstance(item, Mapping) and isinstance(item.get("interfaceId"), str)
    }
    views = {
        item.get("viewId"): item
        for item in visual.get("views", [])
        if isinstance(item, Mapping) and isinstance(item.get("viewId"), str)
    }
    evidence = {
        item.get("evidenceId"): item
        for item in evidence_catalog.get("sources", [])
        if isinstance(item, Mapping) and isinstance(item.get("evidenceId"), str)
    }
    claims = _claims(documents)
    claim_ids = [item.get("claimId") for item in claims]
    if len(claim_ids) != len(set(claim_ids)):
        findings.append(
            _finding(
                "error",
                "duplicate_claim_id_across_documents",
                "claimId must be unique across functional and process claims.",
                priority=1,
            )
        )

    expected_fingerprint = canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": source_revision,
            "sources": sorted(
                evidence.values(), key=lambda item: item["evidenceId"]
            ),
        }
    )
    if evidence_catalog.get("evidenceFingerprint") != expected_fingerprint:
        findings.append(
            _finding(
                "error",
                "evidence_fingerprint_mismatch",
                "Evidence fingerprint does not match the evidence catalog.",
                priority=1,
            )
        )
    for name in ("functional_context.json", "process_candidates.json"):
        if documents.get(name, {}).get("evidenceFingerprint") != expected_fingerprint:
            findings.append(
                _finding(
                    "error",
                    "claim_evidence_fingerprint_mismatch",
                    f"{name} is not bound to the current evidence catalog.",
                    priority=1,
                    details={"document": name},
                )
            )

    known_object_refs = (
        set(occurrences)
        | set(mates)
        | set(interfaces)
        | {
            item.get("branchId")
            for item in process.get("branches", [])
            if isinstance(item, Mapping)
        }
        | {
            item.get("intermediateResultId")
            for item in process.get("intermediateResults", [])
            if isinstance(item, Mapping)
        }
        | {
            item.get("operationId")
            for item in process.get("operationFamilies", [])
            if isinstance(item, Mapping)
        }
        | {
            item.get("stageOperationId")
            for item in process.get("stageDetails", [])
            if isinstance(item, Mapping)
        }
        | {
            operation.get("operationId")
            for stage in process.get("stageDetails", [])
            if isinstance(stage, Mapping)
            for operation in stage.get("operationFamilies", [])
            if isinstance(operation, Mapping)
        }
        | {
            result.get("intermediateResultId")
            for stage in process.get("stageDetails", [])
            if isinstance(stage, Mapping)
            for result in stage.get("intermediateResults", [])
            if isinstance(result, Mapping)
        }
    )
    for claim in claims:
        claim_id = str(claim.get("claimId"))
        subject = claim.get("subjectRef")
        if subject not in known_object_refs:
            findings.append(
                _finding(
                    "error",
                    "unknown_claim_subject",
                    f"Claim {claim_id} references an unknown subject.",
                    subject_refs=[str(subject)],
                    priority=2,
                )
            )
        unknown_objects = [
            ref for ref in claim.get("objectRefs", []) if ref not in known_object_refs
        ]
        if unknown_objects:
            findings.append(
                _finding(
                    "error",
                    "unknown_claim_object",
                    f"Claim {claim_id} references unknown objects.",
                    subject_refs=[claim_id, *unknown_objects],
                    priority=2,
                )
            )
        unknown_evidence = [
            ref for ref in claim.get("evidenceRefs", []) if ref not in evidence
        ]
        if unknown_evidence:
            findings.append(
                _finding(
                    "error",
                    "unknown_evidence_reference",
                    f"Claim {claim_id} references unknown evidence.",
                    subject_refs=[claim_id],
                    evidence_refs=unknown_evidence,
                    priority=1,
                )
            )
        generated = claim.get("generatedBy", {})
        if generated.get("kind") == "model" and (
            claim.get("knowledgeStatus") != "inferred"
            or claim.get("authority") != "supporting"
        ):
            findings.append(
                _finding(
                    "error",
                    "model_claim_authority_violation",
                    "Model-generated claims must remain inferred and supporting.",
                    subject_refs=[claim_id],
                    evidence_refs=claim.get("evidenceRefs", []),
                    priority=1,
                )
            )
        authoritative = claim.get("authority") in {"approved", "authored"}
        evidence_types = {
            evidence[ref].get("sourceType")
            for ref in claim.get("evidenceRefs", [])
            if ref in evidence
        }
        if authoritative and not (
            evidence_types & _AUTHORITATIVE_EVIDENCE_TYPES
        ):
            findings.append(
                _finding(
                    "error",
                    "unsupported_authoritative_claim",
                    "Authoritative claim lacks authored or approved source evidence.",
                    subject_refs=[claim_id],
                    evidence_refs=claim.get("evidenceRefs", []),
                    priority=1,
                )
            )
        predicate = str(claim.get("predicate", "")).lower()
        numeric_manufacturing = (
            any(term in predicate for term in _NUMERIC_MANUFACTURING_TERMS)
            and _contains_number(claim.get("value"))
        )
        if numeric_manufacturing and not (
            evidence_types & _AUTHORITATIVE_EVIDENCE_TYPES
        ):
            findings.append(
                _finding(
                    "error",
                    "unsupported_numeric_manufacturing_value",
                    "Numeric manufacturing value lacks exact authoritative evidence.",
                    subject_refs=[claim_id],
                    evidence_refs=claim.get("evidenceRefs", []),
                    priority=2,
                )
            )
        if (
            claim.get("predicate") in _PROCESS_PREDICATES
            and claim.get("authority") in {"approved", "authored"}
            and evidence_types
            and evidence_types
            <= {"mate_relationship", "geometry", "assembly_structure", "visual"}
        ):
            findings.append(
                _finding(
                    "error",
                    "manufacturing_sequence_from_cad_only",
                    "CAD relationships alone cannot establish manufacturing order.",
                    subject_refs=[claim_id],
                    evidence_refs=claim.get("evidenceRefs", []),
                    priority=1,
                )
            )
        if (
            claim.get("knowledgeStatus") == "inferred"
            and claim.get("reviewStatus") == "pending"
        ):
            findings.append(
                _finding(
                    "warning",
                    "inferred_claim_pending_review",
                    "Inferred claim is pending review.",
                    subject_refs=[claim_id, str(subject)],
                    evidence_refs=claim.get("evidenceRefs", []),
                    priority=30,
                    details={"predicate": claim.get("predicate")},
                )
            )

    authoritative_by_key: Dict[tuple[str, str], Dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for claim in claims:
        if claim.get("authority") not in {"approved", "authored"}:
            continue
        key = (str(claim.get("subjectRef")), str(claim.get("predicate")))
        serialized = json.dumps(
            claim.get("value"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        authoritative_by_key[key][serialized].add(str(claim.get("claimId")))
    for (subject, predicate), values in authoritative_by_key.items():
        if len(values) > 1:
            claim_refs = sorted({ref for refs in values.values() for ref in refs})
            findings.append(
                _finding(
                    "error",
                    "contradictory_authoritative_claims",
                    f"Authoritative claims conflict for {predicate}.",
                    subject_refs=[subject, *claim_refs],
                    priority=2,
                )
            )

    for mate in mates.values():
        unknown = [
            ref for ref in mate.get("occurrenceRefs", []) if ref not in occurrences
        ]
        if unknown:
            findings.append(
                _finding(
                    "error",
                    "unknown_mate_occurrence",
                    "Mate references an unknown occurrence.",
                    subject_refs=[mate["mateId"], *unknown],
                    priority=1,
                )
            )
    for interface in interfaces.values():
        unknown_occurrences = [
            ref
            for ref in interface.get("occurrenceRefs", [])
            if ref not in occurrences
        ]
        unknown_mates = [
            ref for ref in interface.get("mateRefs", []) if ref not in mates
        ]
        if unknown_occurrences or unknown_mates:
            findings.append(
                _finding(
                    "error",
                    "invalid_interface_reference",
                    "Interface references unknown CAD objects.",
                    subject_refs=[
                        interface["interfaceId"],
                        *unknown_occurrences,
                        *unknown_mates,
                    ],
                    priority=1,
                )
            )
    for view in views.values():
        unknown = [
            ref
            for ref in view.get("visibleOccurrenceIds", [])
            if ref not in occurrences
        ]
        if unknown:
            findings.append(
                _finding(
                    "error",
                    "unknown_view_occurrence",
                    "Visual evidence references an unknown occurrence.",
                    subject_refs=[view["viewId"], *unknown],
                    priority=2,
                )
            )

    operations = [
        item
        for item in process.get("operationFamilies", [])
        if isinstance(item, Mapping)
    ]
    operation_ids = {
        item.get("operationId")
        for item in operations
        if isinstance(item.get("operationId"), str)
    }
    state_ids = {
        item.get("intermediateResultId")
        for item in process.get("intermediateResults", [])
        if isinstance(item, Mapping)
    }
    valid_process_refs = set(occurrences) | state_ids
    for operation in operations:
        operation_id = str(operation.get("operationId"))
        invalid_inputs = [
            ref for ref in operation.get("inputRefs", []) if ref not in valid_process_refs
        ]
        output_ref = operation.get("outputRef")
        invalid_predecessors = [
            ref
            for ref in operation.get("predecessorOperationIds", [])
            if ref not in operation_ids
        ]
        if invalid_inputs or (
            output_ref is not None and output_ref not in valid_process_refs
        ) or invalid_predecessors:
            findings.append(
                _finding(
                    "error",
                    "invalid_process_candidate_reference",
                    "Operation candidate references an unknown input, output, or predecessor.",
                    subject_refs=[
                        operation_id,
                        *invalid_inputs,
                        *invalid_predecessors,
                    ],
                    priority=2,
                )
            )
    cycle = _cycle_nodes(operations)
    if cycle:
        findings.append(
            _finding(
                "error",
                "process_candidate_cycle",
                "Candidate operation precedence contains a cycle.",
                subject_refs=cycle,
                priority=1,
            )
        )

    requirement_ids = {
        item.get("requirementId")
        for item in process.get("requirements", [])
        if isinstance(item, Mapping)
    }
    resource_ids = {
        item.get("resourceId")
        for item in process.get("resources", [])
        if isinstance(item, Mapping)
    }
    stage_details = [
        item
        for item in process.get("stageDetails", [])
        if isinstance(item, Mapping)
    ]
    if stage_details and {
        item.get("stageOperationId") for item in stage_details
    } != operation_ids:
        findings.append(
            _finding(
                "error",
                "stage_detail_coverage_invalid",
                "Every high-level operation requires exactly one stage-detail record.",
                subject_refs=sorted(str(item) for item in operation_ids if item),
                priority=1,
            )
        )
    for stage in stage_details:
        stage_id = str(stage.get("stageOperationId") or "")
        expected_hash = canonical_json_sha256(
            {
                key: value
                for key, value in stage.items()
                if key != "stageDetailHash"
            }
        )
        if stage.get("stageDetailHash") != expected_hash:
            findings.append(
                _finding(
                    "error",
                    "stage_detail_hash_mismatch",
                    "Stage-detail content does not match its declared hash.",
                    subject_refs=[stage_id],
                    priority=1,
                )
            )
        required_occurrences = [
            str(item) for item in stage.get("requiredOccurrenceIds", [])
        ]
        unknown_occurrences = sorted(set(required_occurrences) - set(occurrences))
        if unknown_occurrences or len(required_occurrences) != len(
            set(required_occurrences)
        ):
            findings.append(
                _finding(
                    "error",
                    "stage_detail_occurrence_scope_invalid",
                    "Stage-detail occurrence scope contains unknown or duplicate occurrences.",
                    subject_refs=[stage_id, *unknown_occurrences],
                    priority=1,
                )
            )
        detail_operations = [
            item
            for item in stage.get("operationFamilies", [])
            if isinstance(item, Mapping)
        ]
        detail_ids = {
            item.get("operationId")
            for item in detail_operations
            if isinstance(item.get("operationId"), str)
        }
        detail_states = {
            item.get("intermediateResultId")
            for item in stage.get("intermediateResults", [])
            if isinstance(item, Mapping)
        }
        valid_detail_refs = set(occurrences) | detail_states
        consumed_occurrences: list[str] = []
        final_producers = 0
        invalid_detail_refs: set[str] = set()
        invalid_requirements: set[str] = set()
        invalid_resources: set[str] = set()
        for operation in detail_operations:
            for ref in operation.get("inputRefs", []):
                ref_text = str(ref)
                if ref_text in occurrences:
                    consumed_occurrences.append(ref_text)
                elif ref_text not in valid_detail_refs:
                    invalid_detail_refs.add(ref_text)
            output_ref = operation.get("outputRef")
            if output_ref == structure.get("rootOccurrenceId"):
                final_producers += 1
            elif output_ref not in valid_detail_refs:
                invalid_detail_refs.add(str(output_ref))
            invalid_detail_refs.update(
                str(ref)
                for ref in operation.get("predecessorOperationIds", [])
                if ref not in detail_ids
            )
            invalid_requirements.update(
                str(ref)
                for ref in operation.get("requirementRefs", [])
                if ref not in requirement_ids
            )
            invalid_resources.update(
                str(ref)
                for ref in operation.get("resourceRefs", [])
                if ref not in resource_ids
            )
        duplicated_occurrences = {
            ref
            for ref in consumed_occurrences
            if consumed_occurrences.count(ref) > 1
        }
        if (
            set(consumed_occurrences) != set(required_occurrences)
            or duplicated_occurrences
            or final_producers != 1
            or invalid_detail_refs
            or invalid_requirements
            or invalid_resources
        ):
            findings.append(
                _finding(
                    "error",
                    "stage_detail_process_invalid",
                    "Stage-detail operations do not resolve to one complete evidence-bound process.",
                    subject_refs=[
                        stage_id,
                        *sorted(invalid_detail_refs),
                        *sorted(invalid_requirements),
                        *sorted(invalid_resources),
                    ],
                    priority=1,
                )
            )
        detail_cycle = _cycle_nodes(detail_operations)
        if detail_cycle:
            findings.append(
                _finding(
                    "error",
                    "stage_detail_cycle",
                    "Stage-detail precedence contains a cycle.",
                    subject_refs=[stage_id, *detail_cycle],
                    priority=1,
                )
            )

    root_id = structure.get("rootOccurrenceId")
    if root_id not in occurrences:
        findings.append(
            _finding(
                "error",
                "root_occurrence_missing",
                "Product-structure root occurrence is missing.",
                priority=1,
            )
        )
    for occurrence_id, occurrence in occurrences.items():
        parent = occurrence.get("parentOccurrenceId")
        if parent is not None and parent not in occurrences:
            findings.append(
                _finding(
                    "error",
                    "unknown_parent_occurrence",
                    "Occurrence references an unknown parent.",
                    subject_refs=[occurrence_id, str(parent)],
                    priority=1,
                )
            )
    return sorted(
        findings,
        key=lambda item: (
            int(item.get("priority", 50)),
            0 if item.get("severity") == "error" else 1,
            str(item.get("code")),
            json.dumps(item.get("subjectRefs", [])),
        ),
    )


def validation_summary(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for item in findings:
        severity = str(item.get("severity", "warning"))
        counts[severity] = counts.get(severity, 0) + 1
    return {
        "valid": counts["error"] == 0,
        "counts": counts,
        "topCodes": [
            item.get("code")
            for item in findings[:10]
        ],
    }
