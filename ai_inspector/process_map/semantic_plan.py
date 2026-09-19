"""Semantic Process Plan v1 validation and deterministic compilation.

The model specifies manufacturing meaning. This module owns IDs, coordinates,
ports, routing, validation, and the exact Builder operation batch.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .operations import apply_process_map_operations
from .schema_v3 import (
    JUNCTION_TYPES,
    PROCESS_STEP_PROPERTY_LIMITS,
    PROCESS_STEP_TYPES,
    SEMANTIC_EVIDENCE_SOURCE_TYPES,
    SEMANTIC_KNOWLEDGE_STATUSES,
)
from .spatial import compile_spatial_scene, route_orthogonal_edge


SEMANTIC_PROCESS_PLAN_VERSION = 1
SEMANTIC_PROCESS_PLAN_TOOL = "build_process_map_preview"
MAX_SEMANTIC_PLAN_OPERATIONS = 500
_SPATIAL_KEYS = {
    "x",
    "y",
    "position",
    "coordinates",
    "waypoints",
    "screen",
    "pixels",
    "pan",
    "zoom",
    "viewport",
    "path",
}
_AUTHORITATIVE_SOURCES = {
    "procedure",
    "work_instruction",
    "standard",
    "user_authored_map",
    "user_statement",
}
_AUTHORITATIVE_PROPERTIES = {
    "duration",
    "fastenersConsumables",
    "torqueRequirements",
    "inspectionRequirements",
    "constraints",
}


class SemanticProcessPlanError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Optional[Sequence[Mapping[str, Any]]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.findings = [deepcopy(dict(item)) for item in findings or []]


def semantic_process_plan_tool_spec() -> Dict[str, Any]:
    return {
        "name": SEMANTIC_PROCESS_PLAN_TOOL,
        "description": (
            "Build one complete, review-only Process Map ghost preview from a "
            "Semantic Process Plan. Supply manufacturing meaning and evidence, "
            "never coordinates, ports, routes, or low-level Builder operations. "
            "The deterministic server validates, lays out, routes, and binds the "
            "proposal to the saved map revision. Nothing is written until the "
            "user approves the exact preview."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scope_occurrence_id", "semantic_plan"],
            "properties": {
                "scope_occurrence_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "semantic_plan": {
                    "type": "object",
                    "description": (
                        "Semantic Process Plan v1: scope, requiredOccurrences, "
                        "operations, intermediateResults, optional junctions, "
                        "branches, evidence, assumptions, and layoutHints."
                    ),
                },
            },
        },
    }


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    result = {"severity": severity, "code": code, "message": message}
    if ref:
        result["ref"] = ref
    return result


def _text(value: Any, *, maximum: int = 2000) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned) <= 128 else None


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(prefix: str, plan_id: str, semantic_ref: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", semantic_ref.lower()).strip("-")[:32]
    digest = hashlib.sha256(f"{plan_id}:{semantic_ref}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug or 'item'}-{digest}"


def _reject_spatial_fields(value: Any, path: str, findings: list[Dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SPATIAL_KEYS:
                findings.append(
                    _finding(
                        "error",
                        "semantic_plan_contains_spatial_data",
                        (
                            f"{path}.{key_text} is not allowed. Sage specifies "
                            "meaning; the deterministic planner owns geometry."
                        ),
                    )
                )
            _reject_spatial_fields(item, f"{path}.{key_text}", findings)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_spatial_fields(item, f"{path}[{index}]", findings)


def _occurrence_indexes(
    product_structure: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[str]]]:
    by_id = {
        str(item["occurrenceId"]): item
        for item in product_structure.get("occurrences", [])
        if isinstance(item, Mapping) and item.get("occurrenceId")
    }
    children: dict[str, list[str]] = defaultdict(list)
    for occurrence_id, item in by_id.items():
        parent = item.get("parentOccurrenceId")
        if isinstance(parent, str) and parent:
            children[parent].append(occurrence_id)
    for values in children.values():
        values.sort()
    return by_id, children


def _leaf_descendants(
    scope_id: str,
    by_id: Mapping[str, Mapping[str, Any]],
    children: Mapping[str, Sequence[str]],
) -> list[str]:
    result = []
    pending = [scope_id]
    while pending:
        current = pending.pop()
        descendants = list(children.get(current, ()))
        if descendants:
            pending.extend(reversed(descendants))
        elif current != scope_id and by_id.get(current, {}).get("kind") == "part":
            result.append(current)
    return sorted(result)


def _normalize_evidence(value: Any) -> list[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:24]:
        if not isinstance(item, Mapping):
            continue
        source_type = item.get("sourceType")
        source_ref = _identifier(item.get("sourceRef"))
        if source_type in SEMANTIC_EVIDENCE_SOURCE_TYPES and source_ref:
            record = {"sourceType": str(source_type), "sourceRef": source_ref}
            claim = _text(item.get("supports"), maximum=160)
            if claim:
                record["supports"] = claim
            result.append(record)
    return result


def _semantic_metadata(
    plan_id: str,
    semantic_ref: str,
    value: Mapping[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "planId": plan_id,
        "semanticRef": semantic_ref,
        "knowledgeStatus": value.get("knowledgeStatus", "inferred"),
        "evidence": _normalize_evidence(value.get("evidence")),
        "assumptionIds": sorted(
            {
                item
                for item in value.get("assumptionIds", [])
                if _identifier(item)
            }
        )[:24],
    }
    for key in ("branchId", "intermediateResultId"):
        if _identifier(value.get(key)):
            result[key] = str(value[key])
    if isinstance(value.get("stageIndex"), int) and not isinstance(value.get("stageIndex"), bool):
        result["stageIndex"] = value["stageIndex"]
    if value.get("stageDetailAvailable") is True:
        result["stageDetailAvailable"] = True
    if isinstance(value.get("stageDetailStepCount"), int) and not isinstance(
        value.get("stageDetailStepCount"), bool
    ):
        result["stageDetailStepCount"] = value["stageDetailStepCount"]
    if isinstance(value.get("stageDetailHash"), str):
        result["stageDetailHash"] = value["stageDetailHash"]
    return result


def _assembly_knowledge_refs(
    assembly_knowledge: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    context = assembly_knowledge.get("context")
    documents = assembly_knowledge.get("documents")
    occurrence_ids: set[str] = set()
    known_refs: set[str] = set()
    if isinstance(documents, Mapping):
        structure = documents.get("product_structure.json")
        if isinstance(structure, Mapping):
            occurrence_ids.update(
                str(item["occurrenceId"])
                for item in structure.get("occurrences", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("occurrenceId"), str)
            )
        evidence = documents.get("evidence_catalog.json")
        if isinstance(evidence, Mapping):
            known_refs.update(
                str(item["evidenceId"])
                for item in evidence.get("sources", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("evidenceId"), str)
            )
        for document_name in (
            "functional_context.json",
            "process_candidates.json",
        ):
            document = documents.get(document_name)
            if not isinstance(document, Mapping):
                continue
            for item in document.get("claims", []):
                if not isinstance(item, Mapping):
                    continue
                for key in ("claimId", "subjectRef"):
                    if isinstance(item.get(key), str):
                        known_refs.add(str(item[key]))
                known_refs.update(
                    str(value)
                    for value in item.get("objectRefs", [])
                    if isinstance(value, str)
                )
                known_refs.update(
                    str(value)
                    for value in item.get("evidenceRefs", [])
                    if isinstance(value, str)
                )
            for field, identifier in (
                ("relationships", "relationshipId"),
                ("branches", "branchId"),
                ("intermediateResults", "intermediateResultId"),
                ("operationFamilies", "operationId"),
                ("assumptions", "id"),
                ("unresolvedQuestions", "id"),
            ):
                for item in document.get(field, []):
                    if not isinstance(item, Mapping):
                        continue
                    if isinstance(item.get(identifier), str):
                        known_refs.add(str(item[identifier]))
                    if isinstance(item.get("claimId"), str):
                        known_refs.add(str(item["claimId"]))
                    known_refs.update(
                        str(value)
                        for value in item.get("evidenceRefs", [])
                        if isinstance(value, str)
                    )
            for stage in document.get("stageDetails", []):
                if not isinstance(stage, Mapping):
                    continue
                for key in ("stageOperationId", "stageDetailHash"):
                    if isinstance(stage.get(key), str):
                        known_refs.add(str(stage[key]))
                for field, identifier in (
                    ("operationFamilies", "operationId"),
                    ("intermediateResults", "intermediateResultId"),
                    ("branches", "branchId"),
                ):
                    for item in stage.get(field, []):
                        if not isinstance(item, Mapping):
                            continue
                        if isinstance(item.get(identifier), str):
                            known_refs.add(str(item[identifier]))
                        if isinstance(item.get("claimId"), str):
                            known_refs.add(str(item["claimId"]))
                        known_refs.update(
                            str(value)
                            for value in item.get("evidenceRefs", [])
                            if isinstance(value, str)
                        )
    if isinstance(context, Mapping):
        identity = context.get("identity")
        if isinstance(identity, Mapping):
            known_refs.update(
                str(identity[field])
                for field in (
                    "packageId",
                    "packageRevision",
                    "sourceRevision",
                    "evidenceFingerprint",
                    "contextFingerprint",
                )
                if isinstance(identity.get(field), str)
            )
    known_refs.update(occurrence_ids)
    return occurrence_ids, known_refs


def _trusted_stage_detail(
    assembly_knowledge: Mapping[str, Any] | None,
    stage_operation_id: str | None,
) -> Mapping[str, Any] | None:
    if not assembly_knowledge or not stage_operation_id:
        return None
    documents = assembly_knowledge.get("documents")
    process_document = (
        documents.get("process_candidates.json")
        if isinstance(documents, Mapping)
        else None
    )
    if not isinstance(process_document, Mapping):
        return None
    matches = [
        item
        for item in process_document.get("stageDetails", [])
        if isinstance(item, Mapping)
        and item.get("stageOperationId") == stage_operation_id
    ]
    return matches[0] if len(matches) == 1 else None


def build_semantic_process_plan_from_evidence(
    evidence_context: Mapping[str, Any],
    *,
    scope_occurrence_id: str,
) -> Dict[str, Any]:
    """Adapt trusted process candidates into Semantic Process Plan v1.

    This is a structural backstop for an omitted provider tool argument. It
    does not infer manufacturing meaning: every operation, dependency,
    assumption, and evidence reference must already exist in the trusted
    Assembly Knowledge context.
    """

    if not isinstance(evidence_context, Mapping):
        raise SemanticProcessPlanError(
            "process_map_evidence_missing",
            "Trusted process-map evidence is required.",
        )
    identity = evidence_context.get("identity")
    process_candidates = evidence_context.get("processCandidates")
    occurrences = evidence_context.get("occurrences")
    if (
        not isinstance(identity, Mapping)
        or not isinstance(process_candidates, Mapping)
        or not isinstance(occurrences, list)
    ):
        raise SemanticProcessPlanError(
            "process_map_evidence_incomplete",
            "Trusted process-map evidence is incomplete.",
        )

    candidate_operations = process_candidates.get("operationFamilies")
    if not isinstance(candidate_operations, list) or not candidate_operations:
        raise SemanticProcessPlanError(
            "process_candidates_missing",
            "The trusted package has no process-operation candidates.",
        )
    presentation = process_candidates.get("presentation")
    high_level_presentation = bool(
        isinstance(presentation, Mapping)
        and presentation.get("mode") == "high_level"
        and presentation.get("showOccurrenceInputs") is False
    )
    stage_detail_presentation = bool(
        isinstance(presentation, Mapping)
        and presentation.get("mode") == "stage_detail"
        and presentation.get("showOccurrenceInputs") is False
    )
    by_id, children = _occurrence_indexes({"occurrences": occurrences})
    if scope_occurrence_id not in by_id:
        raise SemanticProcessPlanError(
            "semantic_scope_unknown",
            f"Occurrence '{scope_occurrence_id}' does not exist.",
        )
    required_ids = _leaf_descendants(scope_occurrence_id, by_id, children)
    if stage_detail_presentation:
        supplied_required_ids = process_candidates.get("requiredOccurrenceIds")
        if not isinstance(supplied_required_ids, list):
            raise SemanticProcessPlanError(
                "stage_detail_occurrence_scope_missing",
                "Trusted stage detail is missing its occurrence scope.",
            )
        required_ids = sorted(
            {
                str(item)
                for item in supplied_required_ids
                if _identifier(item) and str(item) in by_id
            }
        )
        if len(required_ids) != len(supplied_required_ids):
            raise SemanticProcessPlanError(
                "stage_detail_occurrence_scope_invalid",
                "Trusted stage detail contains unknown or duplicate occurrences.",
            )
    elif not required_ids and high_level_presentation:
        candidate_intermediate_ids = {
            str(item["intermediateResultId"])
            for item in process_candidates.get("intermediateResults", [])
            if isinstance(item, Mapping)
            and _identifier(item.get("intermediateResultId"))
        }
        required_ids = sorted(
            {
                str(ref)
                for operation in candidate_operations
                if isinstance(operation, Mapping)
                for ref in operation.get("inputRefs", [])
                if _identifier(ref)
                and str(ref) not in candidate_intermediate_ids
            }
        )
        scope_context = evidence_context.get("scope")
        expected_count = (
            scope_context.get("requiredOccurrenceCount")
            if isinstance(scope_context, Mapping)
            else None
        )
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count != len(required_ids)
        ):
            raise SemanticProcessPlanError(
                "process_candidate_occurrence_catalog_invalid",
                "High-level process candidates do not match the trusted required-occurrence count.",
            )
    if not required_ids:
        raise SemanticProcessPlanError(
            "semantic_scope_has_no_parts",
            "The requested assembly scope has no required part occurrences.",
        )
    operations_by_id: dict[str, Mapping[str, Any]] = {}
    for item in candidate_operations:
        operation_id = (
            _identifier(item.get("operationId"))
            if isinstance(item, Mapping)
            else None
        )
        if not operation_id or operation_id in operations_by_id:
            raise SemanticProcessPlanError(
                "process_candidate_id_invalid",
                "Every process candidate requires a unique operationId.",
            )
        operations_by_id[operation_id] = item

    final_ids = sorted(
        operation_id
        for operation_id, item in operations_by_id.items()
        if item.get("outputRef") == scope_occurrence_id
    )
    if len(final_ids) != 1:
        raise SemanticProcessPlanError(
            "process_candidate_final_result_invalid",
            "Exactly one trusted process candidate must produce the requested assembly.",
        )

    selected_ids: set[str] = set()

    def select_predecessors(operation_id: str, stack: tuple[str, ...] = ()) -> None:
        if operation_id in selected_ids:
            return
        if operation_id in stack:
            raise SemanticProcessPlanError(
                "process_candidate_precedence_cycle",
                "Trusted process candidates contain a precedence cycle.",
            )
        item = operations_by_id[operation_id]
        predecessors = item.get("predecessorOperationIds", [])
        if not isinstance(predecessors, list):
            raise SemanticProcessPlanError(
                "process_candidate_predecessors_invalid",
                f"Process candidate '{operation_id}' has invalid predecessors.",
            )
        for predecessor in predecessors:
            predecessor_id = _identifier(predecessor)
            if not predecessor_id or predecessor_id not in operations_by_id:
                raise SemanticProcessPlanError(
                    "process_candidate_predecessor_unknown",
                    f"Process candidate '{operation_id}' has an unknown predecessor.",
                )
            select_predecessors(predecessor_id, stack + (operation_id,))
        selected_ids.add(operation_id)

    select_predecessors(final_ids[0])

    ranks: dict[str, int] = {}

    def operation_rank(operation_id: str) -> int:
        if operation_id in ranks:
            return ranks[operation_id]
        predecessors = [
            str(item)
            for item in operations_by_id[operation_id].get(
                "predecessorOperationIds", []
            )
            if str(item) in selected_ids
        ]
        ranks[operation_id] = 1 + max(
            (operation_rank(item) for item in predecessors),
            default=0,
        )
        return ranks[operation_id]

    for operation_id in sorted(selected_ids):
        operation_rank(operation_id)
    ordered_ids = sorted(selected_ids, key=lambda item: (ranks[item], item))

    required_set = set(required_ids)
    candidate_intermediates = {
        str(item["intermediateResultId"]): item
        for item in process_candidates.get("intermediateResults", [])
        if isinstance(item, Mapping)
        and _identifier(item.get("intermediateResultId"))
    } if isinstance(process_candidates.get("intermediateResults", []), list) else {}
    consumed: list[str] = []
    unknown_inputs: set[str] = set()
    for operation_id in ordered_ids:
        input_refs = operations_by_id[operation_id].get("inputRefs", [])
        if not isinstance(input_refs, list):
            raise SemanticProcessPlanError(
                "process_candidate_inputs_invalid",
                f"Process candidate '{operation_id}' has invalid inputs.",
            )
        for item in input_refs:
            ref = str(item)
            if ref in required_set:
                consumed.append(ref)
            elif ref not in candidate_intermediates:
                unknown_inputs.add(ref)
    unknown_input_ids = sorted(unknown_inputs)
    missing_inputs = sorted(required_set - set(consumed))
    duplicate_inputs = sorted(
        occurrence_id
        for occurrence_id in set(consumed)
        if consumed.count(occurrence_id) > 1
    )
    if unknown_input_ids or missing_inputs or duplicate_inputs:
        details = []
        if unknown_input_ids:
            details.append("unknown: " + ", ".join(unknown_input_ids))
        if missing_inputs:
            details.append("missing: " + ", ".join(missing_inputs))
        if duplicate_inputs:
            details.append("duplicated: " + ", ".join(duplicate_inputs))
        raise SemanticProcessPlanError(
            "process_candidate_occurrence_coverage_invalid",
            "Trusted process candidates do not cover each required occurrence "
            "exactly once (" + "; ".join(details) + ").",
        )

    binding_fields = (
        "packageId",
        "packageRevision",
        "sourceRevision",
        "evidenceFingerprint",
        "contextFingerprint",
    )
    if any(not isinstance(identity.get(field), str) for field in binding_fields):
        raise SemanticProcessPlanError(
            "process_map_evidence_binding_incomplete",
            "Trusted process-map evidence has an incomplete revision binding.",
        )
    stage_operation_id = (
        _identifier(process_candidates.get("stageOperationId"))
        if stage_detail_presentation
        else None
    )
    plan_id = "plan-ak-" + hashlib.sha256(
        (
            scope_occurrence_id
            + ":"
            + str(identity["contextFingerprint"])
            + ":"
            + str(stage_operation_id or "root")
        ).encode("ascii")
    ).hexdigest()[:20]

    branch_records = process_candidates.get("branches", [])
    branches = []
    known_branch_ids: set[str] = set()
    if isinstance(branch_records, list):
        for item in branch_records:
            branch_id = (
                _identifier(item.get("branchId"))
                if isinstance(item, Mapping)
                else None
            )
            label = _text(item.get("label")) if isinstance(item, Mapping) else ""
            if branch_id and label and branch_id not in known_branch_ids:
                known_branch_ids.add(branch_id)
                branches.append({"id": branch_id, "label": label})

    assumption_records = evidence_context.get("assumptions", [])
    assumptions_by_id = {
        str(item["id"]): item
        for item in assumption_records
        if isinstance(item, Mapping)
        and _identifier(item.get("id"))
        and _text(item.get("text"))
    } if isinstance(assumption_records, list) else {}
    used_assumption_ids = sorted(
        {
            str(assumption_id)
            for operation_id in ordered_ids
            for assumption_id in operations_by_id[operation_id].get(
                "assumptionIds", []
            )
            if str(assumption_id) in assumptions_by_id
        }
    )

    final_id = final_ids[0]
    intermediate_ids = {
        operation_id: (
            str(operations_by_id[operation_id].get("outputRef"))
            if str(operations_by_id[operation_id].get("outputRef"))
            in candidate_intermediates
            else _stable_id("state", plan_id, operation_id)
        )
        for operation_id in ordered_ids
        if operation_id != final_id
    }
    semantic_operations = []
    semantic_junctions = []
    intermediate_results = []
    layout_hints = []
    for operation_id in ordered_ids:
        candidate = operations_by_id[operation_id]
        predecessor_ids = [
            str(item)
            for item in candidate.get("predecessorOperationIds", [])
            if str(item) in selected_ids
        ]
        inputs = []
        for item in candidate.get("inputRefs", []):
            ref = str(item)
            inputs.append(
                {
                    "ref": ref,
                    "type": (
                        "occurrence"
                        if ref in required_set
                        else "intermediateResult"
                    ),
                }
            )
        existing_input_refs = {item["ref"] for item in inputs}
        inputs.extend(
            {
                "ref": intermediate_ids[predecessor],
                "type": "intermediateResult",
            }
            for predecessor in predecessor_ids
            if predecessor in intermediate_ids
            and intermediate_ids[predecessor] not in existing_input_refs
        )
        intermediate_source = candidate_intermediates.get(
            intermediate_ids.get(operation_id, "")
        )
        intermediate_label = (
            _text(intermediate_source.get("label"))
            if isinstance(intermediate_source, Mapping)
            else ""
        ) or (_text(candidate.get("label")) + " result")
        output = (
            {"ref": scope_occurrence_id, "type": "occurrence"}
            if operation_id == final_id
            else {
                "ref": intermediate_ids[operation_id],
                "type": "intermediateResult",
                "label": intermediate_label,
            }
        )
        branch_id = _identifier(candidate.get("branchId"))
        semantic_operation = {
            "id": operation_id,
            "operationType": (
                candidate.get("operationType")
                if candidate.get("operationType") in PROCESS_STEP_TYPES
                else "operation"
            ),
            "label": _text(candidate.get("label")),
            "inputs": inputs,
            "output": output,
            "stageIndex": ranks[operation_id],
            "knowledgeStatus": (
                candidate.get("knowledgeStatus")
                if candidate.get("knowledgeStatus") in SEMANTIC_KNOWLEDGE_STATUSES
                else "inferred"
            ),
            "evidence": [
                {
                    "sourceType": (
                        candidate.get("evidenceSourceType")
                        if candidate.get("evidenceSourceType")
                        in SEMANTIC_EVIDENCE_SOURCE_TYPES
                        else "domain_heuristic"
                    ),
                    "sourceRef": str(candidate["claimId"]),
                    "supports": "candidate-operation",
                }
            ],
            "assumptionIds": [
                str(item)
                for item in candidate.get("assumptionIds", [])
                if str(item) in assumptions_by_id
            ],
            "properties": {
                key: _text(value, maximum=PROCESS_STEP_PROPERTY_LIMITS[key])
                for key, value in (candidate.get("properties") or {}).items()
                if key in PROCESS_STEP_PROPERTY_LIMITS and _text(value)
            },
        }
        if candidate.get("stageDetailAvailable") is True:
            semantic_operation["stageDetailAvailable"] = True
        if isinstance(candidate.get("stageDetailStepCount"), int):
            semantic_operation["stageDetailStepCount"] = candidate[
                "stageDetailStepCount"
            ]
        if isinstance(candidate.get("stageDetailHash"), str):
            semantic_operation["stageDetailHash"] = candidate["stageDetailHash"]
        if branch_id in known_branch_ids:
            semantic_operation["branchId"] = branch_id
        semantic_operations.append(semantic_operation)
        predecessor_outputs = [
            intermediate_ids[predecessor]
            for predecessor in predecessor_ids
            if predecessor in intermediate_ids
        ]
        if len(predecessor_outputs) >= 2:
            semantic_junctions.append(
                {
                    "id": _stable_id("junction", plan_id, operation_id),
                    "junctionType": "parallel_and",
                    "inputs": predecessor_outputs,
                    "outputs": [operation_id],
                    "knowledgeStatus": "inferred",
                    "evidence": [
                        {
                            "sourceType": "domain_heuristic",
                            "sourceRef": str(candidate["claimId"]),
                            "supports": "candidate-flow-topology",
                        }
                    ],
                    "assumptionIds": [
                        str(item)
                        for item in candidate.get("assumptionIds", [])
                        if str(item) in assumptions_by_id
                    ],
                }
            )
        if operation_id != final_id:
            intermediate_results.append(
                {
                    "id": intermediate_ids[operation_id],
                    "label": intermediate_label,
                    "producedBy": operation_id,
                }
            )
        hint = {
            "ref": operation_id,
            "stageIndex": ranks[operation_id],
        }
        if branch_id in known_branch_ids:
            hint["branchId"] = branch_id
        layout_hints.append(hint)

    unresolved = evidence_context.get("unresolvedQuestions", [])
    unresolved_questions = [
        {"id": str(item["id"]), "text": _text(item.get("text"))}
        for item in unresolved
        if isinstance(item, Mapping)
        and _identifier(item.get("id"))
        and _text(item.get("text"))
    ] if isinstance(unresolved, list) else []

    scope_name = _text(by_id[scope_occurrence_id].get("name"))
    presentation_mode = (
        str(presentation.get("mode"))
        if isinstance(presentation, Mapping)
        and presentation.get("mode") in {"detailed", "high_level", "stage_detail"}
        else "detailed"
    )
    scope_payload = {
        "assemblyOccurrenceId": scope_occurrence_id,
        "label": scope_name or scope_occurrence_id,
        "presentationMode": presentation_mode,
    }
    if stage_detail_presentation:
        if not stage_operation_id:
            raise SemanticProcessPlanError(
                "stage_detail_operation_missing",
                "Trusted stage detail is missing its parent stage identity.",
            )
        scope_payload.update(
            {
                "label": _text(
                    process_candidates.get("detailMapLabel")
                    or scope_name
                    or scope_occurrence_id,
                    maximum=160,
                ),
                "stageOperationId": stage_operation_id,
                "stageDetailHash": str(
                    process_candidates.get("stageDetailHash") or ""
                ),
                "resultLabel": _text(
                    process_candidates.get("resultLabel") or "Stage complete",
                    maximum=160,
                ),
            }
        )
    return {
        "schemaVersion": SEMANTIC_PROCESS_PLAN_VERSION,
        "planId": plan_id,
        "evidenceBinding": {
            field: str(identity[field]) for field in binding_fields
        },
        "scope": scope_payload,
        "requiredOccurrences": [
            {
                "occurrenceId": occurrence_id,
                "quantity": 1,
                "role": "input",
                "knowledgeStatus": "derived",
                "evidence": [
                    {
                        "sourceType": "assembly_structure",
                        "sourceRef": str(identity["sourceRevision"]),
                        "supports": "component-membership",
                    }
                ],
            }
            for occurrence_id in required_ids
        ],
        "operations": semantic_operations,
        "intermediateResults": intermediate_results,
        "junctions": semantic_junctions,
        "branches": branches,
        "evidence": [],
        "assumptions": [
            {
                "id": assumption_id,
                "text": _text(assumptions_by_id[assumption_id].get("text")),
            }
            for assumption_id in used_assumption_ids
        ],
        "layoutHints": layout_hints,
        "unresolvedQuestions": unresolved_questions,
    }


def build_stage_detail_semantic_process_plan(
    assembly_knowledge: Mapping[str, Any],
    *,
    scope_occurrence_id: str,
    stage_operation_id: str,
) -> Dict[str, Any]:
    """Build one exact stage-detail plan from server-owned package records."""

    documents = assembly_knowledge.get("documents")
    base_context = assembly_knowledge.get("context")
    if not isinstance(documents, Mapping) or not isinstance(base_context, Mapping):
        raise SemanticProcessPlanError(
            "assembly_knowledge_invalid",
            "Trusted assembly knowledge is incomplete.",
        )
    process_document = documents.get("process_candidates.json")
    structure = documents.get("product_structure.json")
    if not isinstance(process_document, Mapping) or not isinstance(
        structure, Mapping
    ):
        raise SemanticProcessPlanError(
            "stage_detail_evidence_missing",
            "Trusted stage-detail evidence is unavailable.",
        )
    matches = [
        item
        for item in process_document.get("stageDetails", [])
        if isinstance(item, Mapping)
        and item.get("stageOperationId") == stage_operation_id
    ]
    if len(matches) != 1:
        raise SemanticProcessPlanError(
            "stage_detail_not_found",
            f"No unique stage detail exists for '{stage_operation_id}'.",
        )
    stage = matches[0]
    context = deepcopy(dict(base_context))
    context["occurrences"] = [
        {
            "occurrenceId": item.get("occurrenceId"),
            "parentOccurrenceId": item.get("parentOccurrenceId"),
            "itemId": item.get("itemId"),
            "name": item.get("name"),
            "kind": item.get("kind"),
            "quantity": item.get("quantity", 1),
            "size": None,
        }
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and _identifier(item.get("occurrenceId"))
    ]
    required_ids = list(stage.get("requiredOccurrenceIds", []))
    scope = deepcopy(dict(context.get("scope") or {}))
    scope["requiredOccurrenceCount"] = len(required_ids)
    scope["occurrenceCatalogMode"] = "stage_detail_inputs"
    context["scope"] = scope
    context["processCandidates"] = {
        "presentation": deepcopy(
            stage.get(
                "presentation",
                {"mode": "stage_detail", "showOccurrenceInputs": False},
            )
        ),
        "stageOperationId": stage_operation_id,
        "detailMapLabel": stage.get("detailMapLabel"),
        "stageDetailHash": stage.get("stageDetailHash"),
        "resultLabel": stage.get("resultLabel"),
        "requiredOccurrenceIds": required_ids,
        "branches": deepcopy(stage.get("branches", [])),
        "intermediateResults": deepcopy(stage.get("intermediateResults", [])),
        "operationFamilies": deepcopy(stage.get("operationFamilies", [])),
    }
    return build_semantic_process_plan_from_evidence(
        context,
        scope_occurrence_id=scope_occurrence_id,
    )


def validate_semantic_process_plan(
    plan: Any,
    *,
    scope_occurrence_id: str,
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    assembly_knowledge: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Validate semantics and return a normalized plan plus typed findings."""

    findings: list[Dict[str, Any]] = []
    if not isinstance(plan, Mapping):
        raise SemanticProcessPlanError("semantic_plan_not_object", "semantic_plan must be an object.")
    normalized = deepcopy(dict(plan))
    _reject_spatial_fields(normalized, "semantic_plan", findings)
    if normalized.get("schemaVersion") not in {1, "1", "1.0"}:
        findings.append(
            _finding("error", "unsupported_semantic_plan_version", "Semantic Process Plan schemaVersion must be 1.")
        )
    plan_id = _identifier(normalized.get("planId"))
    if not plan_id:
        findings.append(_finding("error", "semantic_plan_id_missing", "Semantic Process Plan requires planId."))
    scope = normalized.get("scope")
    if not isinstance(scope, Mapping):
        findings.append(_finding("error", "semantic_scope_missing", "Semantic Process Plan requires scope."))
        scope = {}
    if scope.get("assemblyOccurrenceId") != scope_occurrence_id:
        findings.append(
            _finding(
                "error",
                "semantic_scope_mismatch",
                "The plan scope does not match the requested assembly occurrence.",
            )
        )
    presentation_mode = scope.get("presentationMode", "detailed")
    if presentation_mode not in {"detailed", "high_level", "stage_detail"}:
        findings.append(
            _finding(
                "error",
                "semantic_presentation_mode_invalid",
                "scope.presentationMode must be detailed, high_level, or stage_detail.",
            )
        )
        presentation_mode = "detailed"
    stage_operation_id = (
        _identifier(scope.get("stageOperationId"))
        if presentation_mode == "stage_detail"
        else None
    )
    trusted_stage_detail: Mapping[str, Any] | None = None

    by_id, children = _occurrence_indexes(product_structure)
    known_evidence_refs: set[str] = set()
    knowledge_context: Mapping[str, Any] | None = None
    if assembly_knowledge is not None:
        context = assembly_knowledge.get("context")
        binding = assembly_knowledge.get("binding")
        if not isinstance(context, Mapping) or not isinstance(binding, Mapping):
            findings.append(
                _finding(
                    "error",
                    "assembly_knowledge_invalid",
                    "Trusted assembly knowledge is incomplete.",
                )
            )
            binding = {}
        if isinstance(context, Mapping):
            knowledge_context = context
        supplied_binding = normalized.get("evidenceBinding")
        expected_binding = {
            field: binding.get(field)
            for field in (
                "packageId",
                "packageRevision",
                "sourceRevision",
                "evidenceFingerprint",
                "contextFingerprint",
            )
        }
        if not isinstance(supplied_binding, Mapping):
            findings.append(
                _finding(
                    "error",
                    "assembly_knowledge_binding_required",
                    (
                        "Semantic Process Plan requires the trusted assembly "
                        "knowledge identity it was generated from."
                    ),
                )
            )
        elif {
            field: supplied_binding.get(field)
            for field in expected_binding
        } != expected_binding:
            findings.append(
                _finding(
                    "error",
                    "stale_assembly_knowledge_binding",
                    (
                        "Semantic Process Plan targets a stale or different "
                        "assembly knowledge package."
                    ),
                )
            )
        if binding.get("readiness") not in {
            "planning_ready",
            "production_ready",
        }:
            findings.append(
                _finding(
                    "error",
                    "assembly_knowledge_not_planning_ready",
                    "Assembly knowledge must be planning-ready before generation.",
                )
            )
        review = context.get("review") if isinstance(context, Mapping) else None
        pending_claim_count = (
            review.get("pendingClaimCount")
            if isinstance(review, Mapping)
            and isinstance(review.get("pendingClaimCount"), int)
            else 0
        )
        if pending_claim_count:
            findings.append(
                _finding(
                    "warning",
                    "assembly_knowledge_pending_review",
                    (
                        f"{pending_claim_count} Assembly Knowledge claim(s) "
                        "remain pending review; generated process steps stay inferred."
                    ),
                )
            )
        package_occurrence_ids, known_evidence_refs = _assembly_knowledge_refs(
            assembly_knowledge
        )
        if presentation_mode == "stage_detail":
            trusted_stage_detail = _trusted_stage_detail(
                assembly_knowledge,
                stage_operation_id,
            )
            if trusted_stage_detail is None:
                findings.append(
                    _finding(
                        "error",
                        "stage_detail_not_trusted",
                        "The requested stage detail is absent from the trusted package.",
                        ref=stage_operation_id,
                    )
                )
            else:
                if scope.get("stageDetailHash") != trusted_stage_detail.get(
                    "stageDetailHash"
                ):
                    findings.append(
                        _finding(
                            "error",
                            "stage_detail_binding_mismatch",
                            "The stage-detail plan is stale or targets different evidence.",
                            ref=stage_operation_id,
                        )
                    )
                if scope.get("resultLabel") != trusted_stage_detail.get(
                    "resultLabel"
                ):
                    findings.append(
                        _finding(
                            "error",
                            "stage_detail_result_label_mismatch",
                            "The stage-detail result label differs from trusted evidence.",
                            ref=stage_operation_id,
                        )
                    )
        if scope_occurrence_id not in package_occurrence_ids:
            findings.append(
                _finding(
                    "error",
                    "semantic_scope_missing_from_assembly_knowledge",
                    "The requested scope is absent from the trusted package.",
                    ref=scope_occurrence_id,
                )
            )
        structure_ids = set(by_id)
        if package_occurrence_ids and structure_ids != package_occurrence_ids:
            findings.append(
                _finding(
                    "error",
                    "assembly_knowledge_structure_mismatch",
                    (
                        "The Process Map product structure and Assembly "
                        "Knowledge Package do not describe the same occurrences."
                    ),
                )
            )
        source_structure_revision = process_map.get("sourceStructureRevision")
        if isinstance(source_structure_revision, str):
            known_evidence_refs.add(source_structure_revision)
    elif isinstance(normalized.get("evidenceBinding"), Mapping):
        findings.append(
            _finding(
                "error",
                "assembly_knowledge_unavailable",
                "The plan cites assembly knowledge that the server did not resolve.",
            )
        )
    if scope_occurrence_id not in by_id:
        findings.append(
            _finding("error", "semantic_scope_unknown", f"Occurrence '{scope_occurrence_id}' does not exist.")
        )
    if process_map.get("canvasNodes") or process_map.get("canvasEdges"):
        findings.append(
            _finding(
                "error",
                "semantic_generation_requires_empty_map",
                "Semantic Process Plan v1 generates into an empty map to preserve authored data.",
            )
        )

    required = normalized.get("requiredOccurrences")
    if not isinstance(required, list):
        findings.append(
            _finding("error", "required_occurrences_not_array", "requiredOccurrences must be an array.")
        )
        required = []
    required_ids: list[str] = []
    for index, item in enumerate(required):
        if not isinstance(item, Mapping):
            findings.append(
                _finding("error", "required_occurrence_not_object", f"requiredOccurrences[{index}] must be an object.")
            )
            continue
        occurrence_id = _identifier(item.get("occurrenceId"))
        if not occurrence_id or occurrence_id not in by_id:
            findings.append(
                _finding(
                    "error",
                    "required_occurrence_unknown",
                    f"requiredOccurrences[{index}] references an unknown occurrence.",
                )
            )
            continue
        quantity = item.get("quantity", 1)
        if quantity != 1:
            findings.append(
                _finding(
                    "error",
                    "occurrence_quantity_mismatch",
                    (
                        f"Occurrence '{occurrence_id}' is an assembly occurrence and "
                        "must be represented exactly once."
                    ),
                    ref=occurrence_id,
                )
            )
        if known_evidence_refs:
            unknown_refs = sorted(
                {
                    evidence["sourceRef"]
                    for evidence in _normalize_evidence(item.get("evidence"))
                    if evidence["sourceRef"] not in known_evidence_refs
                }
            )
            if unknown_refs:
                findings.append(
                    _finding(
                        "error",
                        "semantic_evidence_ref_unknown",
                        (
                            f"Required occurrence '{occurrence_id}' cites "
                            "evidence outside the trusted package: "
                            + ", ".join(unknown_refs)
                            + "."
                        ),
                        ref=occurrence_id,
                    )
                )
        required_ids.append(occurrence_id)
    if len(required_ids) != len(set(required_ids)):
        findings.append(
            _finding("error", "duplicate_required_occurrence", "A required occurrence is listed more than once.")
        )
    expected_leaves = (
        sorted(
            str(item)
            for item in trusted_stage_detail.get("requiredOccurrenceIds", [])
        )
        if presentation_mode == "stage_detail"
        and isinstance(trusted_stage_detail, Mapping)
        else _leaf_descendants(scope_occurrence_id, by_id, children)
    )
    missing = sorted(set(expected_leaves) - set(required_ids))
    extra = sorted(set(required_ids) - set(expected_leaves))
    if missing:
        findings.append(
            _finding(
                "error",
                "required_occurrence_coverage_missing",
                "Required occurrence coverage is incomplete: " + ", ".join(missing) + ".",
            )
        )
    if extra:
        findings.append(
            _finding(
                "error",
                "required_occurrence_outside_scope",
                "Required occurrences fall outside the requested scope: " + ", ".join(extra) + ".",
            )
        )

    assumptions = normalized.get("assumptions", [])
    if not isinstance(assumptions, list):
        findings.append(
            _finding("error", "semantic_assumptions_not_array", "assumptions must be an array.")
        )
        assumptions = []
    assumption_ids: set[str] = set()
    for index, item in enumerate(assumptions):
        assumption_id = (
            _identifier(item.get("id")) if isinstance(item, Mapping) else None
        )
        assumption_text = (
            _text(item.get("text")) if isinstance(item, Mapping) else ""
        )
        if (
            not assumption_id
            or assumption_id in assumption_ids
            or not assumption_text
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_assumption_invalid",
                    f"assumptions[{index}] requires a unique id and non-empty text.",
                )
            )
            continue
        assumption_ids.add(assumption_id)

    unresolved_questions = normalized.get("unresolvedQuestions", [])
    if not isinstance(unresolved_questions, list):
        findings.append(
            _finding(
                "error",
                "semantic_unresolved_questions_not_array",
                "unresolvedQuestions must be an array.",
            )
        )
        unresolved_questions = []
    question_ids: set[str] = set()
    for index, item in enumerate(unresolved_questions):
        question_id = (
            _identifier(item.get("id")) if isinstance(item, Mapping) else None
        )
        question_text = (
            _text(item.get("text")) if isinstance(item, Mapping) else ""
        )
        if not question_id or question_id in question_ids or not question_text:
            findings.append(
                _finding(
                    "error",
                    "semantic_unresolved_question_invalid",
                    (
                        f"unresolvedQuestions[{index}] requires a unique id "
                        "and non-empty text."
                    ),
                )
            )
            continue
        question_ids.add(question_id)

    intermediate_results = normalized.get("intermediateResults", [])
    if not isinstance(intermediate_results, list):
        findings.append(
            _finding(
                "error",
                "intermediate_results_not_array",
                "intermediateResults must be an array.",
            )
        )
        intermediate_results = []
    intermediate_by_id: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(intermediate_results):
        result_id = _identifier(item.get("id")) if isinstance(item, Mapping) else None
        produced_by = (
            _identifier(item.get("producedBy"))
            if isinstance(item, Mapping)
            else None
        )
        result_label = (
            _text(item.get("label")) if isinstance(item, Mapping) else ""
        )
        if (
            not result_id
            or result_id in intermediate_by_id
            or not result_label
            or not produced_by
        ):
            findings.append(
                _finding(
                    "error",
                    "intermediate_result_invalid",
                    (
                        f"intermediateResults[{index}] requires a unique id, "
                        "label, and producedBy operation id."
                    ),
                )
            )
            continue
        intermediate_by_id[result_id] = item

    operations = normalized.get("operations")
    if not isinstance(operations, list) or not operations:
        findings.append(_finding("error", "semantic_operations_missing", "The plan requires at least one operation."))
        operations = []
    operation_ids: set[str] = set()
    intermediate_producers: dict[str, str] = {}
    intermediate_consumers: set[str] = set()
    final_producers = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            findings.append(_finding("error", "semantic_operation_not_object", f"operations[{index}] must be an object."))
            continue
        operation_id = _identifier(operation.get("id"))
        if not operation_id or operation_id in operation_ids:
            findings.append(_finding("error", "semantic_operation_id_invalid", f"operations[{index}] has a missing or duplicate id."))
            continue
        operation_ids.add(operation_id)
        status = operation.get("knowledgeStatus")
        if status not in SEMANTIC_KNOWLEDGE_STATUSES:
            findings.append(
                _finding("error", "invalid_semantic_knowledge_status", f"Operation '{operation_id}' requires a valid knowledgeStatus.", ref=operation_id)
            )
        evidence = _normalize_evidence(operation.get("evidence"))
        if known_evidence_refs:
            unknown_refs = sorted(
                {
                    item["sourceRef"]
                    for item in evidence
                    if item["sourceRef"] not in known_evidence_refs
                }
            )
            if unknown_refs:
                findings.append(
                    _finding(
                        "error",
                        "semantic_evidence_ref_unknown",
                        (
                            f"Operation '{operation_id}' cites evidence outside "
                            f"the trusted package: {', '.join(unknown_refs)}."
                        ),
                        ref=operation_id,
                    )
                )
        assumption_refs = {
            item for item in operation.get("assumptionIds", []) if _identifier(item)
        } if isinstance(operation.get("assumptionIds", []), list) else set()
        if status in {"authored", "derived"} and not evidence:
            findings.append(
                _finding("error", "authoritative_evidence_required", f"Operation '{operation_id}' needs evidence.", ref=operation_id)
            )
        if status in {"authored", "derived"} and not any(
            item["sourceType"] in _AUTHORITATIVE_SOURCES for item in evidence
        ):
            findings.append(
                _finding(
                    "error",
                    "assembly_evidence_does_not_prove_order",
                    (
                        f"Operation '{operation_id}' cannot be authoritative from "
                        "assembly structure, mates, geometry, or heuristics alone."
                    ),
                    ref=operation_id,
                )
            )
        if status == "inferred" and not evidence and not assumption_refs:
            findings.append(
                _finding("error", "inference_basis_required", f"Operation '{operation_id}' needs evidence or an assumption.", ref=operation_id)
            )
        if not assumption_refs.issubset(assumption_ids):
            findings.append(
                _finding("error", "unknown_semantic_assumption", f"Operation '{operation_id}' references an unknown assumption.", ref=operation_id)
            )
        properties = operation.get("properties", {})
        if properties is not None and not isinstance(properties, Mapping):
            findings.append(_finding("error", "invalid_semantic_properties", f"Operation '{operation_id}' properties must be an object.", ref=operation_id))
            properties = {}
        unknown_properties = sorted(set(properties or {}) - set(PROCESS_STEP_PROPERTY_LIMITS))
        if unknown_properties:
            findings.append(
                _finding("error", "unknown_process_step_property", f"Operation '{operation_id}' has unsupported properties: {', '.join(unknown_properties)}.", ref=operation_id)
            )
        if status in {"inferred", "unknown"} and any(
            properties.get(key) for key in _AUTHORITATIVE_PROPERTIES
        ):
            findings.append(
                _finding(
                    "error",
                    "unsupported_authoritative_manufacturing_value",
                    (
                        f"Operation '{operation_id}' includes manufacturing values "
                        "that require authoritative evidence."
                    ),
                    ref=operation_id,
                )
            )
        inputs = operation.get("inputs")
        output = operation.get("output")
        if not isinstance(inputs, list) or not inputs:
            findings.append(_finding("error", "semantic_operation_inputs_missing", f"Operation '{operation_id}' requires inputs.", ref=operation_id))
            inputs = []
        for input_item in inputs:
            if not isinstance(input_item, Mapping) or not _identifier(input_item.get("ref")):
                findings.append(_finding("error", "semantic_input_invalid", f"Operation '{operation_id}' has an invalid input.", ref=operation_id))
                continue
            input_ref = str(input_item["ref"])
            input_type = input_item.get("type")
            if input_type == "occurrence":
                if input_ref not in required_ids:
                    findings.append(
                        _finding(
                            "error",
                            "semantic_input_occurrence_invalid",
                            (
                                f"Operation '{operation_id}' references occurrence "
                                f"'{input_ref}' outside requiredOccurrences."
                            ),
                            ref=operation_id,
                        )
                    )
            elif input_type == "intermediateResult":
                intermediate_consumers.add(input_ref)
                if input_ref not in intermediate_by_id:
                    findings.append(
                        _finding(
                            "error",
                            "semantic_input_intermediate_unknown",
                            (
                                f"Operation '{operation_id}' references undeclared "
                                f"intermediate result '{input_ref}'."
                            ),
                            ref=operation_id,
                        )
                    )
            else:
                findings.append(
                    _finding(
                        "error",
                        "semantic_input_type_invalid",
                        (
                            f"Operation '{operation_id}' input '{input_ref}' must "
                            "be an occurrence or intermediateResult."
                        ),
                        ref=operation_id,
                    )
                )
        if not isinstance(output, Mapping) or not _identifier(output.get("ref")):
            findings.append(_finding("error", "semantic_output_invalid", f"Operation '{operation_id}' requires one output.", ref=operation_id))
        else:
            output_ref = str(output["ref"])
            output_type = output.get("type")
            if output_type == "intermediateResult":
                if output_ref not in intermediate_by_id:
                    findings.append(
                        _finding(
                            "error",
                            "semantic_output_intermediate_unknown",
                            (
                                f"Operation '{operation_id}' produces undeclared "
                                f"intermediate result '{output_ref}'."
                            ),
                            ref=operation_id,
                        )
                    )
                if output_ref in intermediate_producers:
                    findings.append(_finding("error", "intermediate_result_multiple_producers", f"Intermediate result '{output_ref}' has multiple producers.", ref=output_ref))
                intermediate_producers[output_ref] = operation_id
            elif output_type == "occurrence" and output_ref == scope_occurrence_id:
                final_producers.append(operation_id)
            else:
                findings.append(_finding("error", "semantic_output_unknown", f"Operation '{operation_id}' output does not resolve to an intermediate result or the requested subassembly.", ref=operation_id))
    if len(final_producers) != 1:
        findings.append(
            _finding(
                "error",
                "final_result_not_unique",
                "Exactly one operation must produce the requested subassembly.",
            )
        )
    if presentation_mode == "stage_detail" and isinstance(
        trusted_stage_detail, Mapping
    ):
        trusted_operations = {
            str(item.get("operationId")): item
            for item in trusted_stage_detail.get("operationFamilies", [])
            if isinstance(item, Mapping) and _identifier(item.get("operationId"))
        }
        supplied_operations = {
            str(item.get("id")): item
            for item in operations
            if isinstance(item, Mapping) and _identifier(item.get("id"))
        }
        if set(supplied_operations) != set(trusted_operations):
            findings.append(
                _finding(
                    "error",
                    "stage_detail_operation_set_mismatch",
                    "Stage-detail operations must exactly match the trusted stage record.",
                    ref=stage_operation_id,
                )
            )
        else:
            for operation_id, trusted_operation in trusted_operations.items():
                supplied = supplied_operations[operation_id]
                if (
                    supplied.get("label") != trusted_operation.get("label")
                    or supplied.get("operationType")
                    != trusted_operation.get("operationType")
                ):
                    findings.append(
                        _finding(
                            "error",
                            "stage_detail_operation_content_mismatch",
                            "A stage-detail operation differs from trusted evidence.",
                            ref=operation_id,
                        )
                    )
    for intermediate_ref in sorted(intermediate_consumers):
        if intermediate_ref not in intermediate_producers:
            findings.append(
                _finding("error", "intermediate_result_missing_producer", f"Intermediate result '{intermediate_ref}' is consumed but never produced.", ref=intermediate_ref)
            )
    for intermediate_ref, item in sorted(intermediate_by_id.items()):
        if intermediate_producers.get(intermediate_ref) != item.get("producedBy"):
            findings.append(
                _finding(
                    "error",
                    "intermediate_result_producer_mismatch",
                    (
                        f"Intermediate result '{intermediate_ref}' producedBy does "
                        "not match the operation output."
                    ),
                    ref=intermediate_ref,
                )
            )
    for intermediate_ref in sorted(set(intermediate_producers) - intermediate_consumers):
        if intermediate_ref:
            findings.append(
                _finding("warning", "intermediate_result_unused", f"Intermediate result '{intermediate_ref}' is never consumed.", ref=intermediate_ref)
            )

    junctions = normalized.get("junctions", [])
    if not isinstance(junctions, list):
        findings.append(_finding("error", "semantic_junctions_not_array", "junctions must be an array."))
        junctions = []
    junction_ids: set[str] = set()
    valid_semantic_refs = set(required_ids) | operation_ids | set(intermediate_by_id)
    for junction in junctions:
        if not isinstance(junction, Mapping) or junction.get("junctionType") not in JUNCTION_TYPES:
            findings.append(_finding("error", "semantic_junction_invalid", "Every junction requires a supported junctionType."))
            continue
        junction_id = _identifier(junction.get("id"))
        if not junction_id or junction_id in junction_ids:
            findings.append(
                _finding(
                    "error",
                    "semantic_junction_id_invalid",
                    "Every junction requires a unique stable id.",
                )
            )
            continue
        junction_ids.add(junction_id)
        forbidden = {"operationName", "properties", "duration", "requirements"} & set(junction)
        if forbidden:
            findings.append(
                _finding(
                    "error",
                    "junction_cannot_represent_work",
                    "Routing junctions represent topology and cannot carry manufacturing work.",
                    ref=_identifier(junction.get("id")),
                )
            )
        if known_evidence_refs:
            unknown_refs = sorted(
                {
                    evidence["sourceRef"]
                    for evidence in _normalize_evidence(junction.get("evidence"))
                    if evidence["sourceRef"] not in known_evidence_refs
                }
            )
            if unknown_refs:
                findings.append(
                    _finding(
                        "error",
                        "semantic_evidence_ref_unknown",
                        (
                            f"Junction '{junction_id}' cites evidence outside "
                            f"the trusted package: {', '.join(unknown_refs)}."
                        ),
                        ref=junction_id,
                    )
                )
        for field in ("inputs", "outputs"):
            refs = junction.get(field, [])
            if not isinstance(refs, list) or not refs:
                findings.append(
                    _finding(
                        "error",
                        "semantic_junction_endpoint_invalid",
                        f"Junction '{junction_id}' requires non-empty {field}.",
                        ref=junction_id,
                    )
                )
                continue
            for ref in refs:
                if not _identifier(ref) or str(ref) not in valid_semantic_refs:
                    findings.append(
                        _finding(
                            "error",
                            "semantic_junction_endpoint_unknown",
                            f"Junction '{junction_id}' has an unknown {field} reference.",
                            ref=junction_id,
                        )
                    )

    branches = normalized.get("branches", [])
    if not isinstance(branches, list):
        findings.append(
            _finding("error", "semantic_branches_not_array", "branches must be an array.")
        )
        branches = []
    branch_ids = [
        _identifier(item.get("id")) if isinstance(item, Mapping) else None
        for item in branches
    ]
    if any(not item for item in branch_ids) or len(set(branch_ids)) != len(branch_ids):
        findings.append(
            _finding(
                "error",
                "semantic_branch_id_invalid",
                "Every branch requires a unique stable id.",
            )
        )
    known_branch_ids = {item for item in branch_ids if item}
    for operation in operations:
        if (
            isinstance(operation, Mapping)
            and operation.get("branchId") is not None
            and operation.get("branchId") not in known_branch_ids
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_operation_branch_unknown",
                    f"Operation '{operation.get('id')}' references an unknown branch.",
                    ref=_identifier(operation.get("id")),
                )
            )

    layout_hints = normalized.get("layoutHints", [])
    if not isinstance(layout_hints, list):
        findings.append(
            _finding(
                "error",
                "semantic_layout_hints_not_array",
                "layoutHints must be an array.",
            )
        )
    else:
        known_hint_refs = valid_semantic_refs | junction_ids
        for index, hint in enumerate(layout_hints):
            if (
                not isinstance(hint, Mapping)
                or not _identifier(hint.get("ref"))
                or str(hint.get("ref")) not in known_hint_refs
            ):
                findings.append(
                    _finding(
                        "error",
                        "semantic_layout_hint_invalid",
                        f"layoutHints[{index}] references an unknown semantic item.",
                    )
                )

    errors = [item for item in findings if item["severity"] == "error"]
    if errors:
        raise SemanticProcessPlanError(
            "semantic_plan_invalid",
            f"Semantic Process Plan has {len(errors)} error(s).",
            findings=findings,
        )
    normalized["schemaVersion"] = 1
    normalized["planId"] = plan_id
    normalized["scope"] = dict(scope)
    return {"plan": normalized, "findings": findings}


def _semantic_graph(
    plan: Mapping[str, Any],
    scope_occurrence_id: str,
    *,
    include_occurrence_inputs: bool = True,
) -> Dict[str, Any]:
    producers = {}
    operations = {str(item["id"]): item for item in plan["operations"]}
    junctions = {str(item["id"]): item for item in plan.get("junctions", [])}
    junction_routed_inputs: dict[str, set[str]] = defaultdict(set)
    for junction in junctions.values():
        inputs = {
            str(ref)
            for ref in junction.get("inputs", [])
            if _identifier(ref)
        }
        for output in junction.get("outputs", []):
            output_ref = str(output)
            if output_ref in operations:
                junction_routed_inputs[output_ref].update(inputs)
    for operation_id, operation in operations.items():
        output = operation["output"]
        producers[str(output["ref"])] = operation_id
    edges: set[tuple[str, str]] = set()
    for operation_id, operation in operations.items():
        for item in operation["inputs"]:
            ref = str(item["ref"])
            if item.get("type") == "occurrence" and not include_occurrence_inputs:
                continue
            if ref in junction_routed_inputs.get(operation_id, set()):
                continue
            source = producers.get(ref, ref)
            edges.add((source, operation_id))
        if operation["output"].get("type") == "occurrence":
            edges.add((operation_id, scope_occurrence_id))
    for junction_id, junction in junctions.items():
        for ref in junction.get("inputs", []):
            source = producers.get(str(ref), str(ref))
            edges.add((source, junction_id))
        for ref in junction.get("outputs", []):
            target = producers.get(str(ref), str(ref))
            edges.add((junction_id, target))
    return {
        "operations": operations,
        "junctions": junctions,
        "edges": sorted(edges),
        "visibleOccurrenceRefs": (
            sorted(
                {
                    str(item["occurrenceId"])
                    for item in plan.get("requiredOccurrences", [])
                    if isinstance(item, Mapping)
                    and _identifier(item.get("occurrenceId"))
                }
            )
            if include_occurrence_inputs
            else []
        ),
    }


def _topological_ranks(node_ids: Iterable[str], edges: Sequence[tuple[str, str]]) -> dict[str, int]:
    incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        incoming.setdefault(source, 0)
        incoming[target] = incoming.get(target, 0) + 1
        outgoing[source].append(target)
    queue = deque(sorted(node_id for node_id, count in incoming.items() if count == 0))
    ranks = {node_id: 0 for node_id in queue}
    visited = []
    while queue:
        source = queue.popleft()
        visited.append(source)
        for target in sorted(outgoing.get(source, [])):
            ranks[target] = max(ranks.get(target, 0), ranks[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if len(visited) != len(incoming):
        raise SemanticProcessPlanError("semantic_precedence_cycle", "Semantic Process Plan contains a cycle.")
    return ranks


def _semantic_layout_positions(
    plan: Mapping[str, Any],
    graph: Mapping[str, Any],
    scope_occurrence_id: str,
    product_structure: Mapping[str, Any],
) -> dict[str, Dict[str, float]]:
    """Lay out complete generated maps as parallel process lanes.

    Product inputs sit immediately before the operation that consumes them.
    Independent operation roots receive separate vertical bands, while
    synchronization junctions and downstream stages converge between those
    bands. The model never supplies these coordinates.
    """

    operations = graph["operations"]
    junctions = graph["junctions"]
    required_ids = set(graph.get("visibleOccurrenceRefs", []))
    compact_presentation = plan.get("scope", {}).get("presentationMode") in {
        "high_level",
        "stage_detail",
    }
    process_refs = set(operations) | set(junctions)
    semantic_refs = required_ids | process_refs | {scope_occurrence_id}
    edges = list(graph["edges"])
    ranks = _topological_ranks(semantic_refs, edges)
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        incoming[target].append(source)
        outgoing[source].append(target)
    for values in incoming.values():
        values.sort()
    for values in outgoing.values():
        values.sort()

    root_operations = [
        operation_id
        for operation_id in operations
        if not any(source in process_refs for source in incoming[operation_id])
    ]
    root_operations.sort(
        key=lambda operation_id: (
            _text(operations[operation_id].get("label")).lower(),
            operation_id,
        )
    )
    if not root_operations:
        root_operations = sorted(operations)
    root_index = {
        operation_id: index for index, operation_id in enumerate(root_operations)
    }

    lineages: dict[str, set[int]] = {}
    for ref in sorted(process_refs, key=lambda item: (ranks.get(item, 0), item)):
        inherited: set[int] = set()
        for source in incoming.get(ref, []):
            if source in process_refs:
                inherited.update(lineages.get(source, set()))
        if inherited:
            lineages[ref] = inherited
        elif ref in root_index:
            lineages[ref] = {root_index[ref]}
        else:
            lineages[ref] = {0}
    final_lineage: set[int] = set()
    for source in incoming.get(scope_occurrence_id, []):
        final_lineage.update(lineages.get(source, set()))
    lineages[scope_occurrence_id] = final_lineage or set(range(len(root_operations))) or {0}

    inputs_by_target: dict[str, list[str]] = defaultdict(list)
    for occurrence_id in required_ids:
        targets = [
            target for target in outgoing.get(occurrence_id, [])
            if target in process_refs
        ]
        if targets:
            inputs_by_target[targets[0]].append(occurrence_id)

    minimum_lane_inputs = 1 if compact_presentation else 2
    maximum_inputs = [minimum_lane_inputs for _item in root_operations] or [
        minimum_lane_inputs
    ]
    for target, occurrence_ids in inputs_by_target.items():
        target_lineage = lineages.get(target, {0})
        if len(target_lineage) != 1:
            continue
        lane = next(iter(target_lineage))
        if 0 <= lane < len(maximum_inputs):
            maximum_inputs[lane] = max(maximum_inputs[lane], len(occurrence_ids))

    input_step = 150.0 if compact_presentation else 170.0
    band_gap = 70.0 if compact_presentation else 120.0
    band_padding = 40.0 if compact_presentation else 60.0
    cursor_y = 80.0
    lane_centers: list[float] = []
    for count in maximum_inputs:
        band_height = max(minimum_lane_inputs, count) * input_step + band_padding
        lane_centers.append(cursor_y + band_height / 2.0)
        cursor_y += band_height + band_gap

    def center_y(ref: str) -> float:
        lineage = lineages.get(ref) or {0}
        centers = [
            lane_centers[index]
            for index in sorted(lineage)
            if 0 <= index < len(lane_centers)
        ]
        return sum(centers) / len(centers) if centers else lane_centers[0]

    rank_multiplier = 1 if compact_presentation else 2
    display_ranks: dict[str, int] = {
        ref: ranks.get(ref, 0) * rank_multiplier
        for ref in process_refs | {scope_occurrence_id}
    }
    for occurrence_id in required_ids:
        target_ranks = [
            ranks.get(target, 1)
            for target in outgoing.get(occurrence_id, [])
            if target in process_refs
        ]
        display_ranks[occurrence_id] = max(
            0,
            (min(target_ranks) if target_ranks else 1) * rank_multiplier
            - (0 if compact_presentation else 1),
        )
    minimum_rank = min(display_ranks.values(), default=0)
    if minimum_rank:
        display_ranks = {
            ref: rank - minimum_rank for ref, rank in display_ranks.items()
        }

    occurrence_by_id, _children = _occurrence_indexes(product_structure)
    column_step = 220.0 if compact_presentation else 340.0
    card_height = 146.0
    positions: dict[str, Dict[str, float]] = {}
    for target, occurrence_ids in sorted(inputs_by_target.items()):
        ordered = sorted(
            occurrence_ids,
            key=lambda occurrence_id: (
                _text(occurrence_by_id.get(occurrence_id, {}).get("name")).lower(),
                occurrence_id,
            ),
        )
        midpoint = (len(ordered) - 1) / 2.0
        for index, occurrence_id in enumerate(ordered):
            positions[occurrence_id] = {
                "x": float(80.0 + display_ranks[occurrence_id] * column_step),
                "y": float(
                    center_y(target)
                    + (index - midpoint) * input_step
                    - card_height / 2.0
                ),
            }

    for ref in sorted(process_refs, key=lambda item: (display_ranks[item], item)):
        x = float(80.0 + display_ranks[ref] * column_step)
        y = center_y(ref)
        positions[ref] = (
            {"x": x, "y": float(y)}
            if ref in junctions
            else {"x": x, "y": float(y - card_height / 2.0)}
        )
    positions[scope_occurrence_id] = {
        "x": float(80.0 + display_ranks[scope_occurrence_id] * column_step),
        "y": float(center_y(scope_occurrence_id) - card_height / 2.0),
    }
    return positions


def compile_semantic_process_plan(
    plan: Mapping[str, Any],
    *,
    scope_occurrence_id: str,
    base_revision: str,
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    structure_revision: str,
    assembly_knowledge: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compile a validated semantic plan into deterministic Builder operations."""

    validated = validate_semantic_process_plan(
        plan,
        scope_occurrence_id=scope_occurrence_id,
        process_map=process_map,
        product_structure=product_structure,
        assembly_knowledge=assembly_knowledge,
    )
    normalized = validated["plan"]
    plan_id = str(normalized["planId"])
    presentation_mode = str(
        normalized.get("scope", {}).get("presentationMode") or "detailed"
    )
    show_occurrence_inputs = presentation_mode not in {
        "high_level",
        "stage_detail",
    }
    graph = _semantic_graph(
        normalized,
        scope_occurrence_id,
        include_occurrence_inputs=show_occurrence_inputs,
    )
    required_ids = [str(item["occurrenceId"]) for item in normalized["requiredOccurrences"]]
    visible_required_ids = required_ids if show_occurrence_inputs else []
    semantic_refs = set(visible_required_ids)
    semantic_refs.update(graph["operations"])
    semantic_refs.update(graph["junctions"])
    semantic_refs.add(scope_occurrence_id)

    operation_by_id = graph["operations"]
    positions = _semantic_layout_positions(
        normalized,
        graph,
        scope_occurrence_id,
        product_structure,
    )

    node_ids = {
        ref: _stable_id(
            "pm-sem" if ref in operation_by_id else (
                "pm-j" if ref in graph["junctions"] else "pm-occ"
            ),
            plan_id,
            ref,
        )
        for ref in semantic_refs
    }
    operations: list[Dict[str, Any]] = []
    required_by_id = {
        str(item["occurrenceId"]): item for item in normalized["requiredOccurrences"]
    }
    for occurrence_id in sorted(set(visible_required_ids + [scope_occurrence_id])):
        source = required_by_id.get(occurrence_id, {})
        semantic_source = {
            **source,
            "knowledgeStatus": source.get("knowledgeStatus", "derived"),
            "evidence": source.get("evidence") or [
                {
                    "sourceType": "assembly_structure",
                    "sourceRef": structure_revision,
                    "supports": "component-membership",
                }
            ],
        }
        place_operation = {
                "op": "place_occurrence",
                "nodeId": node_ids[occurrence_id],
                "occurrenceId": occurrence_id,
                "position": positions[occurrence_id],
                "positionMode": "auto",
                "semantic": _semantic_metadata(plan_id, occurrence_id, semantic_source),
            }
        if (
            presentation_mode == "stage_detail"
            and occurrence_id == scope_occurrence_id
        ):
            place_operation["label"] = _text(
                normalized.get("scope", {}).get("resultLabel") or "Stage complete",
                maximum=160,
            )
        operations.append(place_operation)
    for operation_id, operation in sorted(operation_by_id.items()):
        properties = {
            key: _text(value, maximum=PROCESS_STEP_PROPERTY_LIMITS[key])
            for key, value in (operation.get("properties") or {}).items()
            if key in PROCESS_STEP_PROPERTY_LIMITS and _text(value)
        }
        output = operation.get("output") or {}
        if output.get("type") == "intermediateResult":
            properties.setdefault("resultLabel", _text(output.get("label") or output.get("ref"), maximum=160))
        builder_operation: Dict[str, Any] = {
            "op": "add_process_step",
            "nodeId": node_ids[operation_id],
            "processType": (
                str(operation.get("operationType"))
                if operation.get("operationType") in PROCESS_STEP_TYPES
                else "operation"
            ),
            "name": _text(operation.get("label") or operation_id, maximum=120),
            "position": positions[operation_id],
            "positionMode": "auto",
            "semantic": _semantic_metadata(plan_id, operation_id, operation),
        }
        if properties:
            builder_operation["properties"] = properties
        operations.append(builder_operation)
    for junction_id, junction in sorted(graph["junctions"].items()):
        junction_source = {
            **junction,
            "knowledgeStatus": junction.get("knowledgeStatus", "inferred"),
        }
        if (
            junction_source["knowledgeStatus"] == "inferred"
            and not junction_source.get("evidence")
            and not junction_source.get("assumptionIds")
        ):
            junction_source["evidence"] = [
                {
                    "sourceType": "domain_heuristic",
                    "sourceRef": plan_id,
                    "supports": "candidate-flow-topology",
                }
            ]
        operations.append(
            {
                "op": "add_junction",
                "nodeId": node_ids[junction_id],
                "junctionType": junction["junctionType"],
                "position": positions[junction_id],
                "positionMode": "auto",
                "semantic": _semantic_metadata(
                    plan_id,
                    junction_id,
                    junction_source,
                ),
            }
        )
    for source, target in graph["edges"]:
        if source not in node_ids or target not in node_ids:
            raise SemanticProcessPlanError(
                "semantic_reference_unresolved",
                f"Semantic connection '{source}' -> '{target}' cannot be resolved.",
            )
        semantic_ref = f"{source}->{target}"
        operations.append(
            {
                "op": "connect",
                "edgeId": _stable_id("pm-edge", plan_id, semantic_ref),
                "fromNodeId": node_ids[source],
                "toNodeId": node_ids[target],
                "fromPort": "out",
                "toPort": "in",
                "kind": "precedence",
                "semantic": {
                    "planId": plan_id,
                    "semanticRef": semantic_ref,
                    "knowledgeStatus": "inferred",
                    "evidence": [
                        {
                            "sourceType": "domain_heuristic",
                            "sourceRef": plan_id,
                            "supports": "candidate-precedence",
                        }
                    ],
                    "assumptionIds": sorted(
                        {
                            assumption_id
                            for operation in operation_by_id.values()
                            for assumption_id in operation.get("assumptionIds", [])
                            if _identifier(assumption_id)
                        }
                    )[:24],
                },
            }
        )

    if len(operations) > MAX_SEMANTIC_PLAN_OPERATIONS:
        raise SemanticProcessPlanError(
            "semantic_plan_too_large",
            f"The plan compiles to more than {MAX_SEMANTIC_PLAN_OPERATIONS} operations.",
        )
    applied = apply_process_map_operations(
        process_map,
        product_structure,
        operations,
        maximum_operations=MAX_SEMANTIC_PLAN_OPERATIONS,
    )
    provisional = applied["map"]
    scene = compile_spatial_scene(provisional, revision=base_revision)
    route_operations = []
    unresolved = [
        {
            "type": "semantic_question",
            "id": str(item["id"]),
            "text": _text(item.get("text")),
            "subjectRefs": sorted(
                {
                    str(value)
                    for value in item.get("subjectRefs", [])
                    if _identifier(value)
                }
            ),
        }
        for item in normalized.get("unresolvedQuestions", [])
        if isinstance(item, Mapping)
        and _identifier(item.get("id"))
        and _text(item.get("text"))
    ]
    for edge in sorted(provisional.get("canvasEdges", []), key=lambda item: str(item.get("edgeId"))):
        edge_id = str(edge["edgeId"])
        route = route_orthogonal_edge(scene, edge_id)
        if not route.get("accepted"):
            unresolved.append(
                {
                    "type": "route",
                    "edgeId": edge_id,
                    "reason": route.get("failureReason") or "route_not_found",
                }
            )
            continue
        route_operations.append(
            {
                "op": "set_edge_routing",
                "edgeId": edge_id,
                "routing": {
                    "mode": "orthogonal_auto",
                    "routerVersion": route["routerVersion"],
                    "waypoints": route["waypoints"],
                    "obstacleFingerprint": route["obstacleFingerprint"],
                },
            }
        )
    operations.extend(route_operations)
    plan_hash = _hash(normalized)
    binding = {
        "schemaVersion": SEMANTIC_PROCESS_PLAN_VERSION,
        "planId": plan_id,
        "planHash": plan_hash,
        "productId": process_map.get("productId"),
        "mapId": process_map.get("mapId"),
        "baseRevision": base_revision,
        "structureRevision": structure_revision,
        "scopeOccurrenceId": scope_occurrence_id,
        "operationsHash": _hash(operations),
    }
    if assembly_knowledge is not None:
        knowledge_binding = assembly_knowledge.get("binding")
        if isinstance(knowledge_binding, Mapping):
            binding["assemblyKnowledge"] = {
                field: knowledge_binding.get(field)
                for field in (
                    "packageId",
                    "packageRevision",
                    "sourceRevision",
                    "evidenceFingerprint",
                    "contextFingerprint",
                )
            }
    summary = {
        "message": f"Review the complete {normalized['scope'].get('label') or scope_occurrence_id} process-map proposal.",
        "requiredOccurrenceCount": len(required_ids),
        "operationCount": len(operation_by_id),
        "junctionCount": len(graph["junctions"]),
        "connectionCount": len(graph["edges"]),
        "assumptionCount": len(normalized.get("assumptions", [])),
        "unresolvedCount": len(unresolved),
        "inferredOperationCount": sum(
            1 for operation in operation_by_id.values()
            if operation.get("knowledgeStatus") == "inferred"
        ),
    }
    if assembly_knowledge is not None:
        knowledge_binding = assembly_knowledge.get("binding")
        if isinstance(knowledge_binding, Mapping):
            knowledge_context = assembly_knowledge.get("context")
            summary.update(
                {
                    "assemblyKnowledgeReadiness": knowledge_binding.get(
                        "readiness"
                    ),
                    "productionEligible": bool(
                        knowledge_binding.get("productionEligible")
                    ),
                    "pendingKnowledgeReviewCount": (
                        knowledge_context.get("review", {}).get(
                            "pendingClaimCount", 0
                        )
                        if isinstance(knowledge_context, Mapping)
                        and isinstance(
                            knowledge_context.get("review"), Mapping
                        )
                        else 0
                    ),
                }
            )
    return {
        "plan": normalized,
        "planHash": plan_hash,
        "binding": binding,
        "bindingHash": _hash(binding),
        "operations": operations,
        "summary": summary,
        "unresolvedItems": unresolved,
        "findings": validated["findings"],
        "createdIds": {
            "nodeIds": sorted(node_ids.values()),
            "edgeIds": sorted(
                operation["edgeId"] for operation in operations if operation["op"] == "connect"
            ),
        },
    }
