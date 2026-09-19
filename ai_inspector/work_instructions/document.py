"""Compile Process Map evidence into operator-facing work instructions.

The first workflow slice deliberately treats the reviewed synthetic MMLE process
package as an assumed prototype baseline.  That assumption permits a complete
review document and PDF export, but it is never represented as manufacturing
approval or controlled release authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ai_inspector.operations_manual.flow import publication_layout
from ai_inspector.operations_manual.nomenclature import (
    load_publication_aliases,
    resolve_publication_description,
)
from ai_inspector.parts_manual import PARTS_MANUAL_DEFAULT_END_CONDITION
from ai_inspector.parts_manual.catalog import build_scoped_bom
from ai_inspector.parts_manual.documentation import (
    DEFAULT_DOCUMENT_THEME,
    DEFAULT_PAGE_MASTERS,
)


WORK_INSTRUCTION_SCHEMA_VERSION = 1
WORK_INSTRUCTION_PLAN_SCHEMA_VERSION = 2
WORK_INSTRUCTION_RENDER_PIPELINE_VERSION = 2
_MAX_CALLOUT_ITEMS = 7
_GENERIC_FASTENER_PATTERN = re.compile(
    r"\b(?:screw|bolt|nut|washer)\b", re.IGNORECASE
)
_LARGE_CALLOUT_TARGET_PATTERN = re.compile(
    r"\b(?:arm|barrel|battery|box|channel|cover|frame|horn|plate|platform|rim|tank|tube)\b",
    re.IGNORECASE,
)
_SMALL_CALLOUT_TARGET_PATTERN = re.compile(
    r"\b(?:ball|bushing|clip|indicator|lever|plug|ring|spacer|switch)\b",
    re.IGNORECASE,
)
_INSPECTION_LANDMARK_PATTERN = re.compile(
    r"\b(?:anchor|bracket|caster|channel|cover|frame|guard|horn|mount|plate|platform|rim|wheel)\b",
    re.IGNORECASE,
)
_FUNCTIONAL_MOTION_PATTERN = re.compile(
    r"\b(?:actuator|arm|bearing|bushing|cam|cylinder|follower|hinge|link|pin|pivot|ram|roller|shaft|wheel)\b",
    re.IGNORECASE,
)


def _operator_language(value: Any) -> str:
    """Keep CAD-origin hedging and model-policy language out of operator copy."""

    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\bmodeled\b\s*", "", text, flags=re.IGNORECASE)
    if re.search(
        r"\bwithout\s+(?:assigning|applying|inventing)\s+(?:unsupported\s+)?[^.;]+",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r";\s*(?:pressure|electrical|test|acceptance)\s+[^.;]*"
        r"(?:remain|is|are)\s+unspecified",
        text,
        flags=re.IGNORECASE,
    ):
        return (
            "HOLD - Required engineering information is unavailable for this "
            "operation. Do not perform or release it."
        )
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:1].upper() + text[1:] if text else ""


class WorkInstructionError(RuntimeError):
    """Raised when process evidence cannot produce a bounded prototype draft."""


def _stable_revision(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _technical_capture_dimensions(target_aspect_ratio: float) -> tuple[int, int]:
    ratio = max(0.1, float(target_aspect_ratio))
    baseline_pixels = 2400 * 1800
    if ratio >= 1:
        height = max(
            1200,
            math.ceil(math.sqrt(baseline_pixels / ratio)),
            math.ceil(2400 / ratio),
        )
        width = math.ceil(height * ratio)
    else:
        width = max(
            1200,
            math.ceil(math.sqrt(baseline_pixels * ratio)),
            math.ceil(2400 * ratio),
        )
        height = math.ceil(width / ratio)
    if width > 4096 or height > 3072:
        raise WorkInstructionError(
            "work-instruction figure aspect ratio exceeds the capture envelope"
        )
    return width, height


def _technical_image_request(
    *, target_aspect_ratio: float, target_occupancy: float
) -> Dict[str, Any]:
    minimum_width, minimum_height = _technical_capture_dimensions(
        target_aspect_ratio
    )
    return {
        "status": "pending",
        "minimumWidthPx": minimum_width,
        "minimumHeightPx": minimum_height,
        "background": "technical_white",
        "illustrationStyle": "HIDDEN_LINES_REMOVED",
        "targetAspectRatio": target_aspect_ratio,
        "targetForegroundOccupancy": target_occupancy,
        "minimumForegroundOccupancy": 0.30,
        "maximumForegroundOccupancy": 0.84,
        "maximumForegroundAxisOccupancy": 0.96,
        "axisConstrainedOccupancyPolicy": (
            "allow_when_uniform_scale_exceeds_axis_limit"
        ),
        "axisConstrainedFillTolerance": 0.025,
    }


def _product_name(assembly_data: Mapping[str, Any], assembly_number: str) -> str:
    identity = assembly_data.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    return str(
        identity.get("description")
        or identity.get("name")
        or assembly_data.get("name")
        or assembly_number
        or "Product"
    ).strip()


def _source_citations(
    documents: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    manifest = documents.get("source_manifest.json") or {}
    rows: list[Dict[str, Any]] = []
    sources = []
    root = manifest.get("rootAssembly")
    if isinstance(root, Mapping):
        sources.append(root)
    sources.extend(
        row for row in manifest.get("sources") or [] if isinstance(row, Mapping)
    )
    seen: set[str] = set()
    for source in sources:
        source_id = str(source.get("sourceId") or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        path = str(source.get("path") or "").strip()
        rows.append(
            {
                "citationNumber": len(rows) + 1,
                "sourceId": source_id,
                "title": Path(path).name if path else source_id,
                "kind": str(source.get("kind") or "registered_evidence"),
                "authority": "SYNTHETIC_DEMO",
                "registeredLocation": path or None,
                "sha256": str(source.get("sha256") or "") or None,
                "claimCount": 0,
                "sourcePageNumbers": [],
                "url": None,
            }
        )
    return rows


def _normalized_operation(
    source: Mapping[str, Any],
    *,
    known_occurrence_ids: set[str],
    occurrence_id_map: Mapping[str, str],
) -> Dict[str, Any]:
    operation_id = str(source.get("operationId") or "").strip()
    label = str(source.get("label") or "").strip()
    if not operation_id or not label:
        raise WorkInstructionError("work-instruction operations require identity and label")
    input_refs = _dedupe_strings(source.get("inputRefs") or [])
    occurrence_ids = [
        occurrence_id_map.get(value, value)
        for value in input_refs
        if occurrence_id_map.get(value, value) in known_occurrence_ids
    ]
    properties = source.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    return {
        "stepId": operation_id,
        "title": label,
        "operationType": str(source.get("operationType") or "operation"),
        "action": _operator_language(
            source.get("description")
            or properties.get("description")
            or label
        ),
        "predecessorStepIds": _dedupe_strings(
            source.get("predecessorOperationIds") or []
        ),
        "occurrenceIds": occurrence_ids,
        "resourceRefs": _dedupe_strings(source.get("resourceRefs") or []),
        "requirementRefs": _dedupe_strings(source.get("requirementRefs") or []),
        "evidenceRefs": _dedupe_strings(source.get("evidenceRefs") or []),
        "knowledgeStatus": str(source.get("knowledgeStatus") or "unknown"),
        "reviewStatus": str(source.get("reviewStatus") or "unknown"),
        "confidence": None,
    }


def _rounded_vector(value: Any) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(round(float(item), 7) for item in value)
    except (TypeError, ValueError):
        return ()


def _occurrence_match_keys(
    row: Mapping[str, Any], *, evidence_row: bool
) -> list[tuple[Any, ...]]:
    if evidence_row:
        properties = row.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        transform = row.get("transform")
        transform = transform if isinstance(transform, Mapping) else {}
        source_name = str(properties.get("catalogSourcePath") or "").casefold()
        item_id = str(row.get("itemId") or "").casefold()
        component_name = str(row.get("name") or "").split("/")[-1].casefold()
        translation = _rounded_vector(transform.get("translation"))
        rotation = _rounded_vector(transform.get("rotation"))
    else:
        source_name = str(
            row.get("partDataKey") or row.get("referencedFileName") or ""
        ).casefold()
        item_id = str(
            row.get("engineeringPartNumber")
            or row.get("displayPartNumber")
            or row.get("partNumber")
            or ""
        ).casefold()
        component_name = str(
            row.get("internalComponentName") or row.get("name") or ""
        ).split("/")[-1].casefold()
        translation = _rounded_vector(row.get("translation"))
        rotation = _rounded_vector(row.get("rotation"))
    return [
        ("source-transform", source_name, translation, rotation),
        ("item-transform", item_id, translation, rotation),
        ("name-transform", component_name, translation, rotation),
        ("source-name-position", source_name, component_name, translation),
    ]


def _evidence_occurrence_crosswalk(
    catalog: Mapping[str, Any], documents: Mapping[str, Mapping[str, Any]]
) -> Dict[str, str]:
    structure = documents.get("product_structure.json") or {}
    evidence_rows = [
        row
        for row in structure.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not bool((row.get("state") or {}).get("suppressed"))
    ]
    catalog_rows = [
        row
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not bool(row.get("suppressed"))
    ]
    indexes: list[Dict[tuple[Any, ...], list[str]]] = [dict() for _ in range(4)]
    for row in catalog_rows:
        occurrence_id = str(row.get("occurrenceId") or "")
        for index, key in enumerate(
            _occurrence_match_keys(row, evidence_row=False)
        ):
            indexes[index].setdefault(key, []).append(occurrence_id)
    crosswalk: Dict[str, str] = {}
    used_catalog_ids: set[str] = set()
    for row in evidence_rows:
        evidence_id = str(row.get("occurrenceId") or "")
        selected = ""
        for index, key in enumerate(
            _occurrence_match_keys(row, evidence_row=True)
        ):
            candidates = [
                value
                for value in indexes[index].get(key, [])
                if value not in used_catalog_ids
            ]
            if len(candidates) == 1:
                selected = candidates[0]
                break
        if not selected:
            raise WorkInstructionError(
                f"process evidence occurrence cannot be reconciled: {evidence_id}"
            )
        crosswalk[evidence_id] = selected
        used_catalog_ids.add(selected)
    return crosswalk


def build_work_instruction_plan(
    catalog: Mapping[str, Any],
    resolved_package: Mapping[str, Any],
    *,
    process_map_revision: str,
) -> Dict[str, Any]:
    """Build and validate the revision-bound semantic instruction plan."""

    documents = resolved_package.get("documents")
    documents = documents if isinstance(documents, Mapping) else {}
    candidates = documents.get("process_candidates.json")
    candidates = candidates if isinstance(candidates, Mapping) else {}
    binding = resolved_package.get("binding")
    binding = binding if isinstance(binding, Mapping) else {}
    prototype_authorization = resolved_package.get(
        "workInstructionPrototypeAuthorization"
    )
    prototype_authorization = (
        prototype_authorization
        if isinstance(prototype_authorization, Mapping)
        else {}
    )
    if not candidates or not binding:
        raise WorkInstructionError("a planning-ready Assembly Knowledge package is required")
    evidence_readiness = str(binding.get("readiness") or "")
    prototype_candidate_use = bool(
        prototype_authorization.get("status") == "authorized"
        and prototype_authorization.get("manufacturingApproval") is False
        and prototype_authorization.get("controlledReleaseAuthority") is False
        and str(prototype_authorization.get("evidenceReadiness") or "")
        == evidence_readiness
    )
    if evidence_readiness not in {
        "planning_ready",
        "production_ready",
    } and not prototype_candidate_use:
        raise WorkInstructionError("the Assembly Knowledge package is not planning-ready")
    source_revision = str(catalog.get("sourceRevision") or "")
    evidence_source_revision = str(binding.get("sourceRevision") or "")
    source_revision_matches = evidence_source_revision == source_revision

    occurrence_rows = [
        row
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not bool(row.get("suppressed"))
    ]
    known_occurrence_ids = {
        str(row.get("occurrenceId") or "") for row in occurrence_rows
    }
    occurrence_id_map = _evidence_occurrence_crosswalk(catalog, documents)
    top_level = {
        str(row.get("operationId") or ""): row
        for row in candidates.get("operationFamilies") or []
        if isinstance(row, Mapping) and row.get("operationId")
    }
    stage_details = [
        row
        for row in candidates.get("stageDetails") or []
        if isinstance(row, Mapping)
    ]
    if not stage_details:
        raise WorkInstructionError("the package contains no detailed process stages")

    resources = {
        str(row.get("resourceId") or ""): copy.deepcopy(dict(row))
        for row in candidates.get("resources") or []
        if isinstance(row, Mapping) and row.get("resourceId")
    }
    requirements = {
        str(row.get("requirementId") or ""): copy.deepcopy(dict(row))
        for row in candidates.get("requirements") or []
        if isinstance(row, Mapping) and row.get("requirementId")
    }
    instruction_benchmarks: Dict[str, Dict[str, Any]] = {}
    for raw in candidates.get("workInstructionBenchmarks") or []:
        if not isinstance(raw, Mapping):
            raise WorkInstructionError(
                "work-instruction benchmark records must be structured objects"
            )
        benchmark = copy.deepcopy(dict(raw))
        stage_id = str(benchmark.get("stageOperationId") or "").strip()
        if not stage_id or stage_id in instruction_benchmarks:
            raise WorkInstructionError(
                "work-instruction benchmark stage identities must be unique"
            )
        authorization = benchmark.get("authorization")
        authorization = authorization if isinstance(authorization, Mapping) else {}
        if (
            str(benchmark.get("benchmarkStatus") or "")
            != "approved_for_synthetic_demonstration"
            or authorization.get("approvedForSyntheticDemonstration") is not True
            or authorization.get("manufacturingApproval") is not False
            or authorization.get("controlledReleaseAuthority") is not False
        ):
            raise WorkInstructionError(
                f"benchmark stage {stage_id} does not preserve demo-only authority"
            )
        operation_pages = benchmark.get("operationPages")
        if not isinstance(operation_pages, list) or not operation_pages:
            raise WorkInstructionError(
                f"benchmark stage {stage_id} has no operation pages"
            )
        operation_ids = [
            str(row.get("operationId") or "")
            for row in operation_pages
            if isinstance(row, Mapping)
        ]
        if len(operation_ids) != len(operation_pages) or len(set(operation_ids)) != len(
            operation_ids
        ) or any(not value for value in operation_ids):
            raise WorkInstructionError(
                f"benchmark stage {stage_id} has invalid operation identities"
            )
        instruction_benchmarks[stage_id] = benchmark

    stages: list[Dict[str, Any]] = []
    seen_stage_ids: set[str] = set()
    seen_step_ids: set[str] = set()
    covered_occurrences: set[str] = set()
    for sequence, detail in enumerate(stage_details, start=1):
        stage_id = str(detail.get("stageOperationId") or "").strip()
        if not stage_id or stage_id in seen_stage_ids:
            raise WorkInstructionError("process stages require unique identities")
        seen_stage_ids.add(stage_id)
        stage_operation = top_level.get(stage_id)
        if not isinstance(stage_operation, Mapping):
            raise WorkInstructionError(
                f"detailed stage has no high-level process operation: {stage_id}"
            )
        evidence_stage_occurrence_ids = _dedupe_strings(
            detail.get("requiredOccurrenceIds") or []
        )
        unknown_evidence_ids = sorted(
            set(evidence_stage_occurrence_ids) - set(occurrence_id_map)
        )
        stage_occurrence_ids = _dedupe_strings(
            occurrence_id_map[value]
            for value in evidence_stage_occurrence_ids
            if value in occurrence_id_map
        )
        unknown = sorted(set(stage_occurrence_ids) - known_occurrence_ids)
        if unknown_evidence_ids or unknown:
            raise WorkInstructionError(
                f"stage {stage_id} references unknown assembly occurrences"
            )
        if not stage_occurrence_ids:
            raise WorkInstructionError(f"stage {stage_id} has no visible assembly scope")
        covered_occurrences.update(stage_occurrence_ids)
        operations = [
            _normalized_operation(
                row,
                known_occurrence_ids=known_occurrence_ids,
                occurrence_id_map=occurrence_id_map,
            )
            for row in detail.get("operationFamilies") or []
            if isinstance(row, Mapping)
        ]
        if not operations:
            raise WorkInstructionError(f"stage {stage_id} has no operator operations")
        for operation in operations:
            if operation["stepId"] in seen_step_ids:
                raise WorkInstructionError(
                    f"duplicate work-instruction step: {operation['stepId']}"
                )
            seen_step_ids.add(operation["stepId"])
        stage_resource_refs = _dedupe_strings(
            list(stage_operation.get("resourceRefs") or [])
            + [value for row in operations for value in row["resourceRefs"]]
        )
        stage_requirement_refs = _dedupe_strings(
            list(stage_operation.get("requirementRefs") or [])
            + [value for row in operations for value in row["requirementRefs"]]
        )
        missing_resources = sorted(set(stage_resource_refs) - set(resources))
        missing_requirements = sorted(
            set(stage_requirement_refs) - set(requirements)
        )
        if missing_resources or missing_requirements:
            raise WorkInstructionError(
                f"stage {stage_id} has unresolved resource or requirement references"
            )
        stage_title = str(
            stage_operation.get("label")
            or detail.get("detailMapLabel")
            or stage_id
        )
        if stage_id == "op-final-release":
            stage_title = "Review records and close demonstration build"
        stages.append(
            {
                "stageId": stage_id,
                "sequenceNumber": sequence,
                "title": stage_title,
                "description": str(stage_operation.get("description") or ""),
                "result": str(detail.get("resultLabel") or "Stage complete"),
                "predecessorStageIds": _dedupe_strings(
                    stage_operation.get("predecessorOperationIds") or []
                ),
                "occurrenceIds": stage_occurrence_ids,
                "evidenceOccurrenceIds": evidence_stage_occurrence_ids,
                "operations": operations,
                "resourceRefs": stage_resource_refs,
                "requirementRefs": stage_requirement_refs,
                "evidenceRefs": _dedupe_strings(
                    list(stage_operation.get("evidenceRefs") or [])
                    + [value for row in operations for value in row["evidenceRefs"]]
                ),
                "stageDetailHash": str(detail.get("stageDetailHash") or ""),
                "evidenceClass": "SYNTHETIC_DEMO",
                **(
                    {
                        "instructionBenchmark": copy.deepcopy(
                            instruction_benchmarks[stage_id]
                        )
                    }
                    if stage_id in instruction_benchmarks
                    else {}
                ),
            }
        )

    unknown_benchmark_stages = sorted(set(instruction_benchmarks) - seen_stage_ids)
    if unknown_benchmark_stages:
        raise WorkInstructionError(
            "work-instruction benchmarks reference unknown process stages"
        )

    missing_coverage = sorted(known_occurrence_ids - covered_occurrences)
    if missing_coverage:
        raise WorkInstructionError(
            "the instruction plan does not cover every active part occurrence"
        )

    unresolved = documents.get("unresolved.json")
    unresolved = unresolved if isinstance(unresolved, Mapping) else {}
    unresolved_rows = [
        copy.deepcopy(dict(row))
        for key in ("questions", "findings", "unresolved")
        for row in unresolved.get(key) or []
        if isinstance(row, Mapping)
    ]
    plan = {
        "schemaVersion": WORK_INSTRUCTION_PLAN_SCHEMA_VERSION,
        "planType": "work_instruction_plan",
        "planStatus": "prototype_baseline_assumed",
        "assemblyNumber": str(catalog.get("assemblyNumber") or ""),
        "sourceRevision": source_revision,
        "evidenceSourceRevision": evidence_source_revision,
        "sourceBinding": {
            "status": (
                "exact_revision"
                if source_revision_matches
                else "reconciled_by_occurrence_identity"
            ),
            "catalogSourceRevision": source_revision,
            "evidenceSourceRevision": evidence_source_revision,
            "allRequiredOccurrencesResolved": True,
            "occurrenceBindingCount": len(occurrence_id_map),
        },
        "occurrenceBindings": occurrence_id_map,
        "processMapRevision": str(process_map_revision or ""),
        "evidencePackage": copy.deepcopy(dict(binding)),
        "planningBasis": {
            "evidenceReadiness": evidence_readiness,
            "prototypeCandidateUse": prototype_candidate_use,
            "manufacturingApproval": False,
            "controlledReleaseAuthority": False,
        },
        "approvalAssumption": {
            "status": "assumed_for_prototype",
            "basis": "explicit_user_direction",
            "manufacturingApproval": False,
            "controlledReleaseAuthority": False,
        },
        "stages": stages,
        "resources": resources,
        "requirements": requirements,
        "unresolvedFindings": unresolved_rows,
        "summary": {
            "stageCount": len(stages),
            "operationCount": sum(len(stage["operations"]) for stage in stages),
            "requiredOccurrenceCount": len(known_occurrence_ids),
            "coveredOccurrenceCount": len(covered_occurrences),
            "resourceCount": len(resources),
            "requirementCount": len(requirements),
            "unresolvedFindingCount": len(unresolved_rows),
            "benchmarkStageCount": len(instruction_benchmarks),
            "benchmarkOperationPageCount": sum(
                len(row.get("operationPages") or [])
                for row in instruction_benchmarks.values()
            ),
        },
    }
    plan["planRevision"] = _stable_revision(plan)
    return plan


def _preferred_bom_rows(
    catalog: Mapping[str, Any],
    occurrence_ids: Sequence[str],
    publication_aliases: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    rows = list(build_scoped_bom(catalog.get("occurrences") or [], occurrence_ids))

    def sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        description = str(
            resolve_publication_description(row, publication_aliases).get(
                "displayDescription"
            )
            or "Component"
        )
        if _GENERIC_FASTENER_PATTERN.search(description):
            salience_rank = 3
        elif _SMALL_CALLOUT_TARGET_PATTERN.search(description):
            salience_rank = 2
        elif _LARGE_CALLOUT_TARGET_PATTERN.search(description):
            salience_rank = 0
        else:
            salience_rank = 1
        return (
            salience_rank,
            description.casefold(),
            str(row.get("definitionId") or ""),
        )

    return sorted(rows, key=sort_key)


def _stage_focus_occurrence_ids(
    stage: Mapping[str, Any],
    *,
    stages_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return parts handled or checked by a stage, separate from visual context."""

    sequence = int(stage.get("sequenceNumber") or 0)
    occurrence_ids = _dedupe_strings(stage.get("occurrenceIds") or [])
    if sequence <= 7:
        return occurrence_ids
    if sequence <= 11:
        predecessors = _dedupe_strings(stage.get("predecessorStageIds") or [])
        installed_context = set()
        if predecessors and predecessors[0] in stages_by_id:
            installed_context = set(
                _dedupe_strings(
                    stages_by_id[predecessors[0]].get("occurrenceIds") or []
                )
            )
        introduced = [
            occurrence_id
            for occurrence_id in occurrence_ids
            if occurrence_id not in installed_context
        ]
        return introduced or occurrence_ids
    if sequence <= 13:
        return occurrence_ids
    return []


def _callout_items(
    catalog: Mapping[str, Any],
    occurrence_ids: Sequence[str],
    *,
    stage_id: str,
    publication_aliases: Mapping[str, Mapping[str, Any]],
    maximum_items: int = _MAX_CALLOUT_ITEMS,
    preferred_description_pattern: Optional[re.Pattern[str]] = None,
) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    rows = _preferred_bom_rows(catalog, occurrence_ids, publication_aliases)
    if preferred_description_pattern is not None:
        rows = sorted(
            rows,
            key=lambda row: (
                0
                if preferred_description_pattern.search(
                    str(
                        resolve_publication_description(row, publication_aliases).get(
                            "displayDescription"
                        )
                        or ""
                    )
                )
                else 1,
            ),
        )
    for row in rows:
        if len(items) >= max(1, int(maximum_items)):
            break
        nomenclature = resolve_publication_description(row, publication_aliases)
        item_number = len(items) + 1
        items.append(
            {
                "itemNumber": item_number,
                "calloutId": f"wi-{stage_id}-item-{item_number}",
                "definitionId": str(row.get("definitionId") or ""),
                "partNumber": str(row.get("displayPartNumber") or "Not specified"),
                "description": nomenclature["displayDescription"],
                "quantity": int(row.get("quantity") or 1),
                "occurrenceIds": _dedupe_strings(row.get("occurrenceIds") or []),
                "anchorScope": "component_instance",
                "anchorPreference": "visible_edge",
                "endCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
            }
        )
    return items


def _callout_contract() -> Dict[str, Any]:
    return {
        "anchorMethod": "frontmost_camera_raycast",
        "leaderStyle": "straight_with_orthogonal_fallback",
        "requireVisibleAnchor": True,
        "requireLeader": True,
        "maximumLeaderCrossings": 0,
        "maximumGeometryIntersections": 0,
        "defaultRepeatedPartStrategy": "representative_with_count",
        "defaultEndCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
    }


def _stage_component_summary(
    callout_items: Sequence[Mapping[str, Any]],
    *,
    sequence: int,
) -> str:
    if sequence == 14:
        return (
            "No new parts are introduced; this step reviews the build record "
            "and open findings."
        )
    if sequence >= 12:
        return (
            "No new parts are introduced; the callouts identify representative "
            "inspection and functional-test points."
        )
    labels = []
    for item in callout_items:
        label = str(item.get("description") or "Component")
        quantity = int(item.get("quantity") or 1)
        labels.append(f"{label} ({quantity}X)" if quantity > 1 else label)
    return "Parts handled in this step: " + (
        ", ".join(labels) if labels else "Not specified"
    )


def _stage_verification(
    stage: Mapping[str, Any], requirement_texts: Sequence[str]
) -> str:
    if str(stage.get("stageId") or "") == "op-install-lift-and-platform":
        return (
            "Confirm the lift mechanism is retained at the mobile-base interfaces, "
            "the platform is secured at the upper interfaces, and the mounted "
            "assembly moves through the available unpowered range without visible "
            "interference."
        )
    if requirement_texts:
        return _operator_language(requirement_texts[0])
    return _operator_language(
        stage.get("result") or "Record the completed state."
    )


def _stage_page(
    stage: Mapping[str, Any],
    *,
    page_number: int,
    catalog: Mapping[str, Any],
    resources: Mapping[str, Mapping[str, Any]],
    requirements: Mapping[str, Mapping[str, Any]],
    publication_aliases: Mapping[str, Mapping[str, Any]],
    stages_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    sequence = int(stage.get("sequenceNumber") or 0)
    stage_id = str(stage.get("stageId") or f"stage-{sequence}")
    occurrence_ids = _dedupe_strings(stage.get("occurrenceIds") or [])
    operations = [row for row in stage.get("operations") or [] if isinstance(row, Mapping)]
    hold_actions = [
        _operator_language(row.get("action") or "")
        for row in operations
        if "HOLD -" in _operator_language(row.get("action") or "")
    ]
    hold_text = ""
    if hold_actions:
        hold_text = hold_actions[0].split("HOLD -", 1)[-1].strip()
    early_module_build = sequence <= 7
    records_review = sequence == 14
    focus_occurrence_ids = _stage_focus_occurrence_ids(
        stage,
        stages_by_id=stages_by_id,
    )
    callout_items = (
        _callout_items(
            catalog,
            focus_occurrence_ids,
            stage_id=stage_id,
            publication_aliases=publication_aliases,
            maximum_items=(
                _MAX_CALLOUT_ITEMS
                if sequence <= 7
                else 5
                if sequence == 8
                else 3
                if sequence <= 10
                else 2
            ),
            preferred_description_pattern=(
                _INSPECTION_LANDMARK_PATTERN
                if sequence == 12
                else _FUNCTIONAL_MOTION_PATTERN
                if sequence == 13
                else None
            ),
        )
        if not records_review
        else []
    )
    resource_names = [
        str(resources[value].get("name") or value)
        for value in stage.get("resourceRefs") or []
        if value in resources
    ]
    requirement_texts = [
        str(requirements[value].get("text") or value)
        for value in stage.get("requirementRefs") or []
        if value in requirements
    ]
    verification = _stage_verification(stage, requirement_texts)
    figure_frame = {"x": 34, "y": 112, "width": 520, "height": 326}
    layout_blocks: list[Dict[str, Any]] = [
        {
            "blockId": f"{stage_id}-kicker",
            "blockType": "paragraph",
            "text": (
                f"STAGE {sequence:02d}  |  "
                f"{_operator_language(stage.get('result') or 'Stage result')}"
            ),
            "style": {
                "fontSize": 9,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 34, "y": 76, "width": 892, "height": 18},
        }
    ]
    if records_review:
        layout_blocks.extend(
            [
                {
                    "blockId": f"{stage_id}-records-heading",
                    "blockType": "heading",
                    "text": "Records required",
                    "style": {
                        "fontSize": 15,
                        "lineHeight": 19,
                        "fontWeight": 700,
                        "color": "#071B2A",
                    },
                    "frame": {"x": 34, "y": 112, "width": 520, "height": 24},
                },
                {
                    "blockId": f"{stage_id}-records",
                    "blockType": "list",
                    "listStyle": "bulleted",
                    "fontSize": 10,
                    "rowHeights": [36, 36, 36, 36],
                    "items": [
                        {"itemNumber": 1, "label": "", "text": "Stage completion records"},
                        {"itemNumber": 2, "label": "", "text": "Integrated build inspection record"},
                        {"itemNumber": 3, "label": "", "text": "Functional test record"},
                        {"itemNumber": 4, "label": "", "text": "Open findings and engineering dispositions"},
                    ],
                    "frame": {"x": 34, "y": 148, "width": 520, "height": 170},
                },
                {
                    "blockId": f"{stage_id}-records-note",
                    "blockType": "draft_banner",
                    "tone": "information",
                    "text": (
                        "No CAD capture is required for record review. Resolve or "
                        "retain every open finding before the demonstration build "
                        "record is closed."
                    ),
                    "frame": {"x": 34, "y": 342, "width": 520, "height": 78},
                },
                {
                    "blockId": f"{stage_id}-components",
                    "blockType": "paragraph",
                    "text": _stage_component_summary(
                        callout_items, sequence=sequence
                    ),
                    "style": {"fontSize": 8.2, "lineHeight": 11, "color": "#596A76"},
                    "frame": {"x": 34, "y": 452, "width": 520, "height": 42},
                },
            ]
        )
    else:
        layout_blocks.extend(
            [
                {
                    "blockId": f"{stage_id}-figure",
                    "blockType": "cad_figure",
                    "caption": (
                        "Stage-specific CAD view. Numbered callouts identify the "
                        "parts handled or checked in this step."
                    ),
                    "frame": figure_frame,
                },
                {
                    "blockId": f"{stage_id}-components",
                    "blockType": "status_panel" if hold_text else "paragraph",
                    "signalWord": "NOTICE" if hold_text else None,
                    "tone": "notice" if hold_text else None,
                    "text": (
                        f"ENGINEERING DATA REQUIRED - {hold_text}"
                        if hold_text
                        else _stage_component_summary(callout_items, sequence=sequence)
                    ),
                    "style": (
                        {}
                        if hold_text
                        else {"fontSize": 7.4, "lineHeight": 10, "color": "#596A76"}
                    ),
                    "frame": {"x": 34, "y": 452, "width": 520, "height": 42},
                },
            ]
        )
    layout_blocks.extend(
        [
            {
                "blockId": f"{stage_id}-actions-heading",
                "blockType": "heading",
                "text": "Operator actions",
                "style": {
                    "fontSize": 15,
                    "lineHeight": 19,
                    "fontWeight": 700,
                    "color": "#071B2A",
                },
                "frame": {"x": 582, "y": 106, "width": 344, "height": 24},
            },
            {
                "blockId": f"{stage_id}-actions",
                "blockType": "list",
                "listStyle": "numbered",
                "fontSize": 8.2,
                "rowHeights": [
                    220.0 / max(1, len(operations)) for _row in operations
                ],
                "items": [
                    {
                        "itemNumber": index,
                        "label": "",
                        "text": _operator_language(row.get("action") or ""),
                    }
                    for index, row in enumerate(operations, start=1)
                ],
                "frame": {"x": 582, "y": 136, "width": 344, "height": 220},
            },
            {
                "blockId": f"{stage_id}-resources-heading",
                "blockType": "heading",
                "text": "Station and resources",
                "style": {
                    "fontSize": 11,
                    "lineHeight": 14,
                    "fontWeight": 700,
                    "color": "#071B2A",
                },
                "frame": {"x": 582, "y": 363, "width": 344, "height": 16},
            },
            {
                "blockId": f"{stage_id}-resources",
                "blockType": "paragraph",
                "text": ", ".join(resource_names) if resource_names else "Not specified",
                "style": {"fontSize": 9, "lineHeight": 12, "color": "#18212A"},
                "frame": {"x": 582, "y": 384, "width": 344, "height": 28},
            },
            {
                "blockId": f"{stage_id}-quality-heading",
                "blockType": "heading",
                "text": "Completion check",
                "style": {
                    "fontSize": 11,
                    "lineHeight": 14,
                    "fontWeight": 700,
                    "color": "#071B2A",
                },
                "frame": {"x": 582, "y": 417, "width": 344, "height": 16},
            },
            {
                "blockId": f"{stage_id}-quality",
                "blockType": "paragraph",
                "text": verification,
                "style": {
                    "fontSize": 8.0,
                    "lineHeight": 10.5,
                    "fontWeight": 600,
                    "color": "#18212A",
                },
                "frame": {"x": 582, "y": 438, "width": 344, "height": 56},
            },
        ]
    )
    page = {
        "pageId": f"page-wi-stage-{sequence:02d}",
        "pageNumber": page_number,
        "pageType": "work_instruction_stage",
        "sectionId": stage_id,
        "title": f"Step {sequence:02d} - {stage.get('title') or stage_id}",
        "layoutBlocks": layout_blocks,
    }
    if not records_review:
        camera_presets = {
            1: "isometric",
            2: "front",
            3: "right",
            4: "isometric",
            5: "front",
            6: "right",
            7: "isometric",
            8: "front",
            9: "right",
            10: "isometric",
            11: "right",
            12: "front",
            13: "isometric",
        }
        page["renderRequest"] = {
            "figureId": f"WI-FIG-{sequence:02d}",
            "scopeKind": "work_instruction_stage",
            "occurrenceIds": occurrence_ids,
            "occurrenceOrder": occurrence_ids,
            "focusOccurrenceIds": focus_occurrence_ids,
            "pose": "exploded" if early_module_build else "assembled",
            "cameraPreset": camera_presets.get(sequence, "isometric"),
            "explodeStrategy": "radial",
            "explodeFactor": 0.52 if early_module_build else 0.0,
            "displayStyle": "hidden_lines_removed",
            "showItemCallouts": bool(callout_items),
            "calloutItems": callout_items,
            "calloutContract": _callout_contract(),
            "frame": copy.deepcopy(figure_frame),
            "image": _technical_image_request(
                target_aspect_ratio=figure_frame["width"]
                / (figure_frame["height"] - 18),
                target_occupancy=0.67,
            ),
        }
    return page


def _benchmark_stage_rows_by_part_number(
    catalog: Mapping[str, Any],
    stage: Mapping[str, Any],
    publication_aliases: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for source in _preferred_bom_rows(
        catalog,
        _dedupe_strings(stage.get("occurrenceIds") or []),
        publication_aliases,
    ):
        part_number = str(source.get("displayPartNumber") or "").strip()
        if not part_number:
            continue
        if part_number in rows:
            raise WorkInstructionError(
                f"benchmark stage {stage.get('stageId')} has ambiguous part number {part_number}"
            )
        nomenclature = resolve_publication_description(source, publication_aliases)
        rows[part_number] = {
            "partNumber": part_number,
            "definitionId": str(source.get("definitionId") or ""),
            "description": str(
                nomenclature.get("displayDescription") or "Component"
            ),
            "quantity": int(source.get("quantity") or 1),
            "occurrenceIds": _dedupe_strings(source.get("occurrenceIds") or []),
        }
    return rows


def _benchmark_callout_items(
    operation_id: str,
    part_rows: Sequence[Mapping[str, Any]],
    callout_part_numbers: Sequence[str],
) -> list[Dict[str, Any]]:
    by_part_number = {
        str(row.get("partNumber") or ""): row for row in part_rows
    }
    result: list[Dict[str, Any]] = []
    for part_number in callout_part_numbers:
        row = by_part_number.get(str(part_number))
        if row is None:
            raise WorkInstructionError(
                f"benchmark operation {operation_id} cannot call out an unhandled part"
            )
        item_number = len(result) + 1
        result.append(
            {
                "itemNumber": item_number,
                "calloutId": f"wi-{operation_id}-item-{item_number}",
                "definitionId": str(row.get("definitionId") or ""),
                "partNumber": str(row.get("partNumber") or "Not specified"),
                "description": str(row.get("description") or "Component"),
                "quantity": int(row.get("quantity") or 1),
                "occurrenceIds": _dedupe_strings(row.get("occurrenceIds") or []),
                "anchorScope": "component_instance",
                "anchorPreference": "visible_edge",
                "endCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
            }
        )
    return result


def _compact_named_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_field: str,
    description_field: str,
) -> str:
    return ", ".join(
        f"{str(row.get(id_field) or '').strip()} {str(row.get(description_field) or '').strip()}".strip()
        for row in rows
        if str(row.get(id_field) or row.get(description_field) or "").strip()
    ) or "None"


def _benchmark_operation_page(
    stage: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    page_number: int,
    catalog: Mapping[str, Any],
    resources: Mapping[str, Mapping[str, Any]],
    publication_aliases: Mapping[str, Mapping[str, Any]],
    installed_quantities: Dict[str, int],
) -> Dict[str, Any]:
    stage_id = str(stage.get("stageId") or "")
    operation_id = str(operation.get("operationId") or "")
    sequence_label = str(operation.get("sequenceLabel") or "03")
    available_rows = _benchmark_stage_rows_by_part_number(
        catalog,
        stage,
        publication_aliases,
    )
    operation_parts: list[Dict[str, Any]] = []
    current_occurrences: Dict[str, list[str]] = {}
    for reference in operation.get("parts") or []:
        if not isinstance(reference, Mapping):
            raise WorkInstructionError(
                f"benchmark operation {operation_id} has an invalid part reference"
            )
        part_number = str(reference.get("partNumber") or "").strip()
        source = available_rows.get(part_number)
        if source is None:
            raise WorkInstructionError(
                f"benchmark operation {operation_id} references unknown part {part_number}"
            )
        quantity = int(reference.get("quantity") or 0)
        available_quantity = len(source["occurrenceIds"])
        previous_quantity = int(installed_quantities.get(part_number) or 0)
        inspection_target = "inspection" in str(reference.get("role") or "").casefold()
        if quantity <= 0 or quantity > available_quantity:
            raise WorkInstructionError(
                f"benchmark operation {operation_id} requests an invalid quantity for {part_number}"
            )
        if previous_quantity + quantity > available_quantity and not inspection_target:
            raise WorkInstructionError(
                f"benchmark operation {operation_id} consumes {part_number} more than once"
            )
        if inspection_target and previous_quantity >= available_quantity:
            selected_ids = source["occurrenceIds"][:quantity]
        else:
            selected_ids = source["occurrenceIds"][
                previous_quantity : previous_quantity + quantity
            ]
            installed_quantities[part_number] = min(
                available_quantity,
                previous_quantity + quantity,
            )
        current_occurrences[part_number] = list(selected_ids)
        operation_parts.append(
            {
                **copy.deepcopy(source),
                "quantity": quantity,
                "occurrenceIds": list(selected_ids),
                "role": str(reference.get("role") or "Component"),
            }
        )

    scene = operation.get("scene")
    scene = scene if isinstance(scene, Mapping) else {}
    visible_occurrence_ids: list[str] = []
    for part_number in scene.get("visiblePartNumbers") or []:
        source = available_rows.get(str(part_number))
        installed = int(installed_quantities.get(str(part_number)) or 0)
        if source is None or installed <= 0:
            raise WorkInstructionError(
                f"benchmark operation {operation_id} has an unresolved visible part"
            )
        visible_occurrence_ids.extend(source["occurrenceIds"][:installed])
    focus_occurrence_ids = _dedupe_strings(
        occurrence_id
        for part_number in scene.get("focusPartNumbers") or []
        for occurrence_id in current_occurrences.get(str(part_number), [])
    )
    if not focus_occurrence_ids:
        raise WorkInstructionError(
            f"benchmark operation {operation_id} has no focus geometry"
        )
    callout_items = _benchmark_callout_items(
        operation_id,
        operation_parts,
        [str(value) for value in scene.get("calloutPartNumbers") or []],
    )
    callout_numbers = {
        str(item["partNumber"]): int(item["itemNumber"])
        for item in callout_items
    }
    part_items = []
    for row in operation_parts:
        marker = callout_numbers.get(str(row["partNumber"]))
        marker_text = f"[{marker}] " if marker else ""
        part_items.append(
            {
                "itemNumber": len(part_items) + 1,
                "label": "",
                "text": (
                    f"{marker_text}{row['description']} | {row['partNumber']} | "
                    f"{row['quantity']}X"
                ),
            }
        )

    resource_names = [
        str(resources[value].get("name") or value)
        for value in operation.get("resourceRefs") or []
        if value in resources
    ]
    tool_text = _compact_named_rows(
        [row for row in operation.get("tools") or [] if isinstance(row, Mapping)],
        id_field="toolId",
        description_field="description",
    )
    material_text = _compact_named_rows(
        [row for row in operation.get("materials") or [] if isinstance(row, Mapping)],
        id_field="materialId",
        description_field="description",
    )
    key_points = [str(value) for value in operation.get("keyPoints") or []]
    tools_and_points = "\n".join(
        (
            f"Station: {', '.join(resource_names) if resource_names else 'Not specified'}",
            f"Tools: {tool_text}",
            f"Materials / PPE: {material_text}; {', '.join(operation.get('ppe') or [])}",
            "Key points: " + " ".join(key_points),
        )
    )
    specifications = [
        row
        for row in operation.get("specifications") or []
        if isinstance(row, Mapping)
    ]
    specification_text = "\n".join(
        [
            f"{row.get('label')}: {row.get('value')}"
            for row in specifications
        ]
        + [
            f"Source: {benchmark.get('documentId')} Rev "
            f"{benchmark.get('documentRevision')}, operation {sequence_label}."
        ]
    )
    checks = [
        row
        for row in operation.get("qualityChecks") or []
        if isinstance(row, Mapping)
    ]
    record = operation.get("recordRequirement")
    record = record if isinstance(record, Mapping) else {}
    transition_gate = operation.get("transitionGate")
    transition_gate = (
        transition_gate if isinstance(transition_gate, Mapping) else {}
    )
    record_line = f"Record: {record.get('recordId') or 'Not specified'}"
    if transition_gate:
        record_line = (
            f"GATE / RECORD: {record.get('recordId') or 'Not specified'} required. "
            "Failed or missing results = HOLD FOR ENGINEERING REVIEW; main "
            "integration is blocked."
        )
    quality_text = "\n".join(
        [
            f"{str(row.get('method') or 'check').upper()}: {row.get('criterion')}"
            for row in checks
        ]
        + [record_line]
    )
    safety_controls = [
        row
        for row in operation.get("safetyControls") or []
        if isinstance(row, Mapping)
    ]
    severity_rank = {"DANGER": 0, "WARNING": 1, "CAUTION": 2, "NOTICE": 3}
    primary_safety = min(
        safety_controls,
        key=lambda row: severity_rank.get(
            str(row.get("signalWord") or "NOTICE").upper(), 4
        ),
    )

    figure_frame = {"x": 34, "y": 104, "width": 516, "height": 286}
    layout_blocks: list[Dict[str, Any]] = [
        {
            "blockId": f"{operation_id}-kicker",
            "blockType": "paragraph",
            "text": (
                f"OPERATION {sequence_label}  |  "
                f"{_operator_language(stage.get('title') or 'Lift mechanism')}"
            ),
            "style": {
                "fontSize": 9,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 34, "y": 76, "width": 892, "height": 18},
        },
        {
            "blockId": f"{operation_id}-figure",
            "blockType": "cad_figure",
            "caption": (
                "Operation-specific CAD state. Numbered callouts match the parts "
                "handled or checked on this page."
            ),
            "frame": figure_frame,
        },
        {
            "blockId": f"{operation_id}-parts-heading",
            "blockType": "heading",
            "text": "Parts handled or checked",
            "style": {
                "fontSize": 10,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#071B2A",
            },
            "frame": {"x": 34, "y": 396, "width": 516, "height": 14},
        },
        {
            "blockId": f"{operation_id}-parts",
            "blockType": "list",
            "listStyle": "bulleted",
            "columns": 2,
            "columnGap": 12,
            "fontSize": 6.3,
            "rowHeights": [11.0] * max(1, math.ceil(len(part_items) / 2)),
            "items": part_items,
            "frame": {"x": 34, "y": 412, "width": 516, "height": 34},
        },
        {
            "blockId": f"{operation_id}-safety",
            "blockType": "status_panel",
            "signalWord": str(primary_safety.get("signalWord") or "NOTICE"),
            "tone": str(primary_safety.get("signalWord") or "notice").lower(),
            "text": str(primary_safety.get("text") or ""),
            "frame": {"x": 34, "y": 450, "width": 516, "height": 46},
        },
        {
            "blockId": f"{operation_id}-actions-heading",
            "blockType": "heading",
            "text": "DO - OPERATOR ACTIONS",
            "style": {
                "fontSize": 14,
                "lineHeight": 18,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 580, "y": 102, "width": 346, "height": 20},
        },
        {
            "blockId": f"{operation_id}-actions",
            "blockType": "list",
            "listStyle": "numbered",
            "fontSize": 7.2,
            "rowHeights": [29.0] * len(operation.get("actions") or []),
            "items": [
                {"itemNumber": index, "label": "", "text": str(action)}
                for index, action in enumerate(operation.get("actions") or [], start=1)
            ],
            "frame": {"x": 580, "y": 126, "width": 346, "height": 116},
        },
        {
            "blockId": f"{operation_id}-resources-heading",
            "blockType": "heading",
            "text": "TOOLS / MATERIALS / KEY POINTS",
            "style": {
                "fontSize": 9.5,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 580, "y": 249, "width": 346, "height": 14},
        },
        {
            "blockId": f"{operation_id}-resources",
            "blockType": "paragraph",
            "text": tools_and_points,
            "style": {"fontSize": 6.8, "lineHeight": 8.4, "color": "#18212A"},
            "frame": {"x": 580, "y": 267, "width": 346, "height": 59},
        },
        {
            "blockId": f"{operation_id}-specifications-heading",
            "blockType": "heading",
            "text": "SPECIFICATION",
            "style": {
                "fontSize": 9.5,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 580, "y": 332, "width": 346, "height": 14},
        },
        {
            "blockId": f"{operation_id}-specifications",
            "blockType": "paragraph",
            "text": specification_text,
            "style": {
                "fontSize": 7.0,
                "lineHeight": 8.8,
                "fontWeight": 600,
                "color": "#18212A",
            },
            "frame": {"x": 580, "y": 350, "width": 346, "height": 52},
        },
        {
            "blockId": f"{operation_id}-quality-heading",
            "blockType": "heading",
            "text": "VERIFY / RECORD",
            "style": {
                "fontSize": 9.5,
                "lineHeight": 12,
                "fontWeight": 700,
                "color": "#148FD0",
            },
            "frame": {"x": 580, "y": 408, "width": 346, "height": 14},
        },
        {
            "blockId": f"{operation_id}-quality",
            "blockType": "paragraph",
            "text": quality_text,
            "style": {
                "fontSize": 6.4 if transition_gate else 6.8,
                "lineHeight": 8.0 if transition_gate else 8.4,
                "fontWeight": 600,
                "color": "#18212A",
            },
            "frame": {"x": 580, "y": 426, "width": 346, "height": 74},
        },
    ]
    image_request = _technical_image_request(
        target_aspect_ratio=figure_frame["width"] / (figure_frame["height"] - 18),
        target_occupancy=0.69,
    )
    return {
        "pageId": f"page-wi-operation-{operation_id}",
        "pageNumber": page_number,
        "pageType": "work_instruction_operation",
        "sectionId": operation_id,
        "parentSectionId": stage_id,
        "title": f"Step {sequence_label} - {operation.get('title') or operation_id}",
        "layoutBlocks": layout_blocks,
        "instructionOperation": {
            **copy.deepcopy(dict(operation)),
            "resolvedParts": operation_parts,
            "evidenceBinding": {
                "documentId": str(benchmark.get("documentId") or ""),
                "revision": str(benchmark.get("documentRevision") or ""),
                "sourceRef": str(benchmark.get("sourceRef") or ""),
                "evidenceRef": str(benchmark.get("evidenceRef") or ""),
                "benchmarkHash": str(benchmark.get("benchmarkHash") or ""),
            },
        },
        "renderRequest": {
            "figureId": f"WI-FIG-{sequence_label}",
            "scopeKind": "work_instruction_operation",
            "occurrenceIds": _dedupe_strings(visible_occurrence_ids),
            "occurrenceOrder": _dedupe_strings(visible_occurrence_ids),
            "focusOccurrenceIds": focus_occurrence_ids,
            "pose": str(scene.get("pose") or "assembled"),
            "cameraPreset": str(scene.get("cameraPreset") or "isometric"),
            "explodeStrategy": "radial",
            "explodeFactor": float(scene.get("explodeFactor") or 0.0),
            "displayStyle": "hidden_lines_removed",
            "showItemCallouts": bool(callout_items),
            "calloutItems": callout_items,
            "calloutContract": _callout_contract(),
            "frame": copy.deepcopy(figure_frame),
            "image": image_request,
        },
    }


def _apply_scene(
    pages: list[Dict[str, Any]],
    documentation_scene: Optional[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    scene = documentation_scene if isinstance(documentation_scene, Mapping) else {}
    composition_pages = (
        scene.get("pages") if isinstance(scene.get("pages"), Mapping) else {}
    )
    theme = copy.deepcopy(
        scene.get("theme")
        if isinstance(scene.get("theme"), Mapping)
        else DEFAULT_DOCUMENT_THEME
    )
    page_masters = copy.deepcopy(
        scene.get("pageMasters")
        if isinstance(scene.get("pageMasters"), Mapping)
        else DEFAULT_PAGE_MASTERS
    )
    for page in pages:
        page_id = str(page.get("pageId") or "")
        composition = copy.deepcopy(
            composition_pages.get(page_id)
            if isinstance(composition_pages.get(page_id), Mapping)
            else {}
        )
        if page.get("pageType") == "operations_cover":
            composition.pop("manualGroupOverrides", None)
            composition.pop("occurrenceOverrides", None)
        page["documentationComposition"] = composition
        page["documentationObjects"] = copy.deepcopy(
            composition.get("documentObjects")
            if isinstance(composition.get("documentObjects"), Mapping)
            else {}
        )
        page["pageMasterId"] = (
            "cover" if page.get("pageType") == "operations_cover" else "reference"
        )
        if isinstance(page.get("renderRequest"), dict):
            page["renderRequest"]["composition"] = copy.deepcopy(composition)
    return theme, page_masters


def build_work_instruction_document(
    assembly_data: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    resolved_package: Mapping[str, Any],
    process_map_revision: str,
    nomenclature_root: str | Path | None = None,
    documentation_scene: Optional[Mapping[str, Any]] = None,
    documentation_scene_revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile the semantic plan into a 16:9 operator-facing review document."""

    plan = build_work_instruction_plan(
        catalog,
        resolved_package,
        process_map_revision=process_map_revision,
    )
    assembly_number = str(catalog.get("assemblyNumber") or "")
    product_name = _product_name(assembly_data, assembly_number)
    occurrence_ids = [
        str(row.get("occurrenceId") or "")
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not bool(row.get("suppressed"))
    ]
    publication_aliases = (
        load_publication_aliases(nomenclature_root, assembly_number)
        if nomenclature_root is not None
        else {}
    )
    layout = publication_layout()
    cover = layout["pageTypes"]["operations_cover"]
    benchmark_stage_ids = [
        str(stage.get("stageId") or "")
        for stage in plan["stages"]
        if isinstance(stage.get("instructionBenchmark"), Mapping)
    ]
    process_plan_only_stage_ids = [
        str(stage.get("stageId") or "")
        for stage in plan["stages"]
        if str(stage.get("stageId") or "") not in benchmark_stage_ids
    ]
    benchmark_operation_page_count = sum(
        len((stage.get("instructionBenchmark") or {}).get("operationPages") or [])
        for stage in plan["stages"]
        if isinstance(stage.get("instructionBenchmark"), Mapping)
    )
    pages: list[Dict[str, Any]] = [
        {
            "pageId": "page-work-instructions-cover",
            "pageNumber": 1,
            "pageType": "operations_cover",
            "sectionId": "cover",
            "title": f"{product_name} Assembly Work Instructions",
            "layoutBlocks": [
                {
                    "blockId": "wi-cover-kicker",
                    "blockType": "cover_kicker",
                    "text": "ASSEMBLY WORK INSTRUCTIONS",
                    "lines": ["ASSEMBLY WORK INSTRUCTIONS"],
                    "style": {
                        "fontSize": 16,
                        "lineHeight": 22,
                        "fontWeight": 700,
                        "color": "#43B5EE",
                    },
                    "frame": copy.deepcopy(cover["kicker"]),
                },
                {
                    "blockId": "wi-cover-title",
                    "blockType": "cover_title",
                    "text": product_name,
                    "lines": [product_name],
                    "style": {
                        "fontSize": 30,
                        "lineHeight": 36,
                        "fontWeight": 700,
                        "color": "#071B2A",
                    },
                    "frame": copy.deepcopy(cover["title"]),
                },
                {
                    "blockId": "wi-cover-status",
                    "blockType": "paragraph",
                    "text": "PROTOTYPE BASELINE  |  SYNTHETIC DEMONSTRATION PROCESS DATA",
                    "style": {
                        "fontSize": 8.2,
                        "lineHeight": 11,
                        "fontWeight": 700,
                        "color": "#596A76",
                    },
                    "frame": {"x": 64, "y": 158, "width": 832, "height": 14},
                },
            ],
            "renderRequest": {
                "figureId": "WI-FIG-COVER",
                "scopeKind": "assembly",
                "occurrenceIds": occurrence_ids,
                "occurrenceOrder": occurrence_ids,
                "pose": "assembled",
                "cameraPreset": "isometric",
                "explodeStrategy": "radial",
                "explodeFactor": 0.0,
                "displayStyle": "hidden_lines_removed",
                "showItemCallouts": False,
                "calloutItems": [],
                "frame": copy.deepcopy(cover["illustration"]),
                "image": _technical_image_request(
                    target_aspect_ratio=cover["illustration"]["width"]
                    / cover["illustration"]["height"],
                    target_occupancy=0.58,
                ),
            },
        },
        {
            "pageId": "page-work-instructions-sequence",
            "pageNumber": 2,
            "pageType": "work_instruction_sequence",
            "sectionId": "sequence-overview",
            "title": "Assembly Sequence Overview",
            "layoutBlocks": [
                {
                    "blockId": "wi-sequence-intro",
                    "blockType": "paragraph",
                    "text": (
                        "Follow the stages in the numbered order shown. Parallel module "
                        "builds converge at main integration before inspection and test."
                    ),
                    "style": {"fontSize": 10, "lineHeight": 14, "color": "#18212A"},
                    "frame": {"x": 56, "y": 82, "width": 848, "height": 34},
                },
                {
                    "blockId": "wi-sequence-list",
                    "blockType": "list",
                    "listStyle": "numbered",
                    "columns": 2,
                    "items": [
                        {
                            "itemNumber": int(stage["sequenceNumber"]),
                            "label": str(stage["title"]),
                            "text": str(stage["result"]),
                        }
                        for stage in plan["stages"]
                    ],
                    "rowHeights": [28.0] * 7,
                    "frame": {"x": 56, "y": 126, "width": 848, "height": 200},
                },
                {
                    "blockId": "wi-sequence-status",
                    "blockType": "draft_banner",
                    "tone": "prototype",
                    "text": (
                        "DOCUMENT STATUS - PROTOTYPE / NOT RELEASED. Only Stage 03 has "
                        f"detailed evidence-bound coverage ({benchmark_operation_page_count} "
                        "synthetic operation pages). The remaining stages are process-plan "
                        "coverage and are not executable controlled instructions."
                    ),
                    "frame": {"x": 56, "y": 338, "width": 848, "height": 52},
                },
                {
                    "blockId": "wi-sequence-coverage-heading",
                    "blockType": "heading",
                    "text": "VALIDATED INSTRUCTION COVERAGE",
                    "style": {
                        "fontSize": 9.5,
                        "lineHeight": 12,
                        "fontWeight": 700,
                        "color": "#148FD0",
                    },
                    "frame": {"x": 56, "y": 406, "width": 400, "height": 14},
                },
                {
                    "blockId": "wi-sequence-coverage",
                    "blockType": "list",
                    "listStyle": "definitions",
                    "fontSize": 7.2,
                    "rowHeights": [30.0, 30.0],
                    "items": [
                        {
                            "itemNumber": 1,
                            "label": "Stage 03",
                            "text": (
                                f"{benchmark_operation_page_count} evidence-bound synthetic "
                                "operation pages with tools, specifications, safety, checks, "
                                "and records."
                            ),
                        },
                        {
                            "itemNumber": 2,
                            "label": "Stages 01-02 and 04-14",
                            "text": (
                                "Process-plan coverage only; controlled engineering detail "
                                "is incomplete."
                            ),
                        },
                    ],
                    "frame": {"x": 56, "y": 426, "width": 400, "height": 64},
                },
                {
                    "blockId": "wi-sequence-blockers-heading",
                    "blockType": "heading",
                    "text": "RELEASE BLOCKERS",
                    "style": {
                        "fontSize": 9.5,
                        "lineHeight": 12,
                        "fontWeight": 700,
                        "color": "#B24A3B",
                    },
                    "frame": {"x": 496, "y": 406, "width": 408, "height": 14},
                },
                {
                    "blockId": "wi-sequence-blockers",
                    "blockType": "list",
                    "listStyle": "definitions",
                    "columns": 2,
                    "columnGap": 14,
                    "fontSize": 7.0,
                    "rowHeights": [21.0, 21.0, 21.0],
                    "items": [
                        {"itemNumber": 1, "label": "Torque", "text": "Actual MMLE requirements"},
                        {"itemNumber": 2, "label": "Hydraulics", "text": "Settings and limits"},
                        {"itemNumber": 3, "label": "Electrical", "text": "Routing and acceptance"},
                        {"itemNumber": 4, "label": "Test", "text": "Production acceptance limits"},
                        {"itemNumber": 5, "label": "Safety", "text": "Approved controls"},
                        {"itemNumber": 6, "label": "Approval", "text": "Manufacturing approval"},
                    ],
                    "frame": {"x": 496, "y": 426, "width": 408, "height": 64},
                },
            ],
        },
    ]
    stages_by_id = {
        str(stage.get("stageId") or ""): stage for stage in plan["stages"]
    }
    for stage in plan["stages"]:
        benchmark = stage.get("instructionBenchmark")
        if isinstance(benchmark, Mapping):
            installed_quantities: Dict[str, int] = {}
            for operation in benchmark.get("operationPages") or []:
                if not isinstance(operation, Mapping):
                    continue
                pages.append(
                    _benchmark_operation_page(
                        stage,
                        benchmark,
                        operation,
                        page_number=len(pages) + 1,
                        catalog=catalog,
                        resources=plan["resources"],
                        publication_aliases=publication_aliases,
                        installed_quantities=installed_quantities,
                    )
                )
        else:
            pages.append(
                _stage_page(
                    stage,
                    page_number=len(pages) + 1,
                    catalog=catalog,
                    resources=plan["resources"],
                    requirements=plan["requirements"],
                    publication_aliases=publication_aliases,
                    stages_by_id=stages_by_id,
                )
            )
    for page in pages:
        page["pageCount"] = len(pages)
    theme, page_masters = _apply_scene(pages, documentation_scene)
    citations = _source_citations(resolved_package.get("documents") or {})
    release_findings = [
        {
            "findingId": "WI-PROTOTYPE-ASSUMED-PLAN",
            "code": "PROTOTYPE_PLAN_ASSUMPTION",
            "severity": "P1",
            "blocking": True,
            "message": (
                "The process plan is assumed accepted for prototype generation; "
                "manufacturing approval has not been recorded."
            ),
        },
        {
            "findingId": "WI-SYNTHETIC-EVIDENCE",
            "code": "SYNTHETIC_PROCESS_EVIDENCE",
            "severity": "P1",
            "blocking": True,
            "message": (
                "Sequence, resource, and verification content is synthetic demo "
                "evidence and cannot authorize production work."
            ),
        },
        {
            "findingId": "WI-SYNTHETIC-BENCHMARK-SPECIFICATIONS",
            "code": "SYNTHETIC_BENCHMARK_SPECIFICATIONS",
            "severity": "P1",
            "blocking": True,
            "message": (
                "Stage 03 tools, torque values, endplay limits, safety controls, "
                "and acceptance checks are revisioned synthetic demonstration "
                "requirements. They do not authorize MMLE-50D production work."
            ),
        },
    ]
    unresolved_ids = {
        str(row.get("id") or row.get("findingId") or "")
        for row in plan.get("unresolvedFindings") or []
        if isinstance(row, Mapping)
    }
    unresolved_gate_rows = [
        (
            "question-torque-values",
            "WI-MISSING-TORQUE",
            "MISSING_APPROVED_TORQUE_REQUIREMENTS",
            (
                "Approved fastener torque requirements are unavailable. The review "
                "draft may identify retained joints, but controlled release remains "
                "blocked until the requirements are supplied."
            ),
        ),
        (
            "question-test-limits",
            "WI-MISSING-TEST-LIMITS",
            "MISSING_APPROVED_TEST_LIMITS",
            (
                "Approved electrical, hydraulic, and functional acceptance limits "
                "are unavailable. Functional-test content cannot establish production "
                "acceptance until those limits are supplied."
            ),
        ),
        (
            "question-safety-controls",
            "WI-MISSING-SAFETY-CONTROLS",
            "MISSING_APPROVED_SAFETY_CONTROLS",
            (
                "Approved lockout, isolation, guarding, and load-control procedures "
                "are unavailable. Controlled assembly and test release remains blocked."
            ),
        ),
    ]
    prototype_candidate_use = bool(
        plan.get("planningBasis", {}).get("prototypeCandidateUse")
    )
    for unresolved_id, finding_id, code, message in unresolved_gate_rows:
        if unresolved_id in unresolved_ids or prototype_candidate_use:
            release_findings.append(
                {
                    "findingId": finding_id,
                    "code": code,
                    "severity": "P1",
                    "blocking": True,
                    "message": message,
                }
            )
    if plan["sourceBinding"]["status"] != "exact_revision":
        release_findings.append(
            {
                "findingId": "WI-EVIDENCE-SOURCE-BINDING",
                "code": "EVIDENCE_SOURCE_REVISION_RECONCILED",
                "severity": "P1",
                "blocking": True,
                "message": (
                    "The synthetic process package predates the current catalog "
                    "metadata revision. Every required occurrence was resolved, but "
                    "controlled release requires a freshly bound evidence package."
                ),
            }
        )
    document = {
        "schemaVersion": WORK_INSTRUCTION_SCHEMA_VERSION,
        "documentType": "work_instructions",
        "renderPipelineVersion": WORK_INSTRUCTION_RENDER_PIPELINE_VERSION,
        "status": "prototype_ready",
        "statusLabel": "PROTOTYPE BASELINE",
        "title": f"{product_name} Assembly Work Instructions",
        "coverKicker": "ASSEMBLY WORK INSTRUCTIONS",
        "documentNumber": f"WI-{assembly_number.upper()}-001",
        "revision": None,
        "product": {
            "assemblyNumber": assembly_number,
            "name": product_name,
        },
        "sourceRevision": str(catalog.get("sourceRevision") or ""),
        "evidenceRevision": str(
            (resolved_package.get("binding") or {}).get("packageRevision") or ""
        ),
        "processMapRevision": str(process_map_revision or ""),
        "manualPlanRevision": str(plan["planRevision"]),
        "documentationSceneRevision": str(documentation_scene_revision or "baseline"),
        "publicationLayout": layout,
        "theme": theme,
        "pageMasters": page_masters,
        "pages": pages,
        "pageCount": len(pages),
        "workInstructionPlan": copy.deepcopy(plan),
        "evidenceCitations": citations,
        "evidenceSummary": {
            "evidenceClass": "SYNTHETIC_DEMO",
            "sourceCount": len(citations),
            "stageCount": plan["summary"]["stageCount"],
            "operationCount": plan["summary"]["operationCount"],
            "requiredOccurrenceCount": plan["summary"]["requiredOccurrenceCount"],
            "coveredOccurrenceCount": plan["summary"]["coveredOccurrenceCount"],
            "benchmarkStageCount": plan["summary"]["benchmarkStageCount"],
            "benchmarkOperationPageCount": plan["summary"][
                "benchmarkOperationPageCount"
            ],
        },
        "releaseGate": {
            "status": "PROTOTYPE_REVIEW_READY",
            "reviewPdfAllowed": True,
            "controlledPdfAllowed": False,
            "controlledReleaseStatus": "BLOCKED",
            "assumedPlanAccepted": True,
            "coverage": {
                "validatedBenchmarkStageIds": benchmark_stage_ids,
                "validatedBenchmarkOperationPageCount": benchmark_operation_page_count,
                "processPlanOnlyStageIds": process_plan_only_stage_ids,
                "controlledReleaseBlocked": True,
            },
            "findings": release_findings,
        },
    }
    revision_payload = copy.deepcopy(document)
    revision_payload.pop("documentRevision", None)
    document["documentRevision"] = _stable_revision(revision_payload)
    return document
