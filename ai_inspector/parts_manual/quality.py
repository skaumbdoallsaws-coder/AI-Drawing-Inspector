"""Publication-readiness audits for illustrated parts manual plans."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .schema import PartsManualValidationError


_INTERNAL_TITLE_PATTERNS = (
    re.compile(r"^__"),
    re.compile(r"\b(?:smoke|test|testing|temp|temporary|debug|selection|unnamed)\b", re.IGNORECASE),
    re.compile(r"^(?:body|group\s*\d*|selection\s*\d*|unnamed\s*\d*)$", re.IGNORECASE),
    re.compile(r"\.(?:sldprt|sldasm)$", re.IGNORECASE),
    re.compile(r"^(?:swpr|swpa)[-_]", re.IGNORECASE),
)


def is_publishable_section_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        return False
    return not any(pattern.search(text) for pattern in _INTERNAL_TITLE_PATTERNS)


def _finding(code: str, message: str, path: str, **detail: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "severity": "error",
        "code": code,
        "message": message,
        "path": path,
    }
    if detail:
        result["detail"] = detail
    return result


def _active_parts(catalog: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in catalog
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not row.get("suppressed")
        and row.get("occurrenceId")
    ]


def _ancestor_pairs(sections: Iterable[Mapping[str, Any]]) -> Set[tuple[str, str]]:
    parent_by_id = {
        str(row.get("sectionId")): str(row.get("parentSectionId"))
        if row.get("parentSectionId")
        else None
        for row in sections
        if row.get("sectionId")
    }
    result: Set[tuple[str, str]] = set()
    for section_id in parent_by_id:
        cursor = parent_by_id.get(section_id)
        seen = {section_id}
        while cursor and cursor not in seen:
            result.add((cursor, section_id))
            seen.add(cursor)
            cursor = parent_by_id.get(cursor)
    return result


def _group_quality(
    section: Mapping[str, Any],
    rows_by_occurrence: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    occurrence_ids = [
        str(value)
        for value in section.get("occurrenceIds") or []
        if str(value) in rows_by_occurrence
    ]
    definitions = {
        str(rows_by_occurrence[value].get("definitionId") or "")
        for value in occurrence_ids
        if rows_by_occurrence[value].get("definitionId")
    }
    source = str(section.get("source") or "manual")
    source_scores = {
        "library_manual_profile": (0.97, 0.94, 0.90),
        "cad_hierarchy": (0.96, 0.95, 0.72),
        "process_map": (0.92, 0.86, 0.96),
        "manual": (0.82, 0.76, 0.68),
        "inferred": (0.65, 0.58, 0.55),
    }
    functional, mechanical, process = source_scores.get(source, (0.60, 0.55, 0.50))
    confidence = section.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        functional = (functional + float(confidence)) / 2
        process = (process + float(confidence)) / 2
    naming = 1.0 if is_publishable_section_name(section.get("name")) else 0.0
    component_count = len(occurrence_ids)
    component_score = 1.0 if component_count >= 2 else 0.20
    overall = (
        functional * 0.28
        + mechanical * 0.22
        + process * 0.22
        + naming * 0.18
        + component_score * 0.10
    )
    return {
        "sectionId": str(section.get("sectionId") or ""),
        "name": str(section.get("name") or ""),
        "occurrenceCount": component_count,
        "uniqueServicePartCount": len(definitions),
        "functionalCoherence": round(functional, 3),
        "mechanicalConnectivity": round(mechanical, 3),
        "processCoherence": round(process, 3),
        "namingConfidence": round(naming, 3),
        "componentCountScore": round(component_score, 3),
        "overall": round(overall, 3),
    }


def audit_manual_plan(
    plan: Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return a deterministic publication audit without modifying the plan."""
    active_rows = _active_parts(catalog)
    rows_by_occurrence = {
        str(row["occurrenceId"]): row
        for row in active_rows
    }
    eligible_ids = set(rows_by_occurrence)
    unique_definitions = {
        str(row.get("definitionId") or "")
        for row in active_rows
        if row.get("definitionId")
    }
    sections = [
        dict(row)
        for row in plan.get("sections") or []
        if isinstance(row, Mapping) and row.get("includeInManual", True)
    ]
    findings: List[Dict[str, Any]] = []
    if not sections:
        findings.append(
            _finding(
                "manual_publication_no_sections",
                "Create and approve at least one functional manual section before export.",
                "$.sections",
            )
        )

    ownership: Dict[str, List[str]] = defaultdict(list)
    group_quality: List[Dict[str, Any]] = []
    for index, section in enumerate(sections):
        path = f"$.sections[{index}]"
        section_id = str(section.get("sectionId") or "")
        name = str(section.get("name") or "").strip()
        if not is_publishable_section_name(name):
            findings.append(
                _finding(
                    "manual_publication_section_name",
                    f"'{name or 'Unnamed section'}' is not a customer-facing functional assembly name.",
                    f"{path}.name",
                    sectionId=section_id,
                )
            )
        occurrence_ids = [str(value) for value in section.get("occurrenceIds") or []]
        for occurrence_id in occurrence_ids:
            if occurrence_id in eligible_ids:
                ownership[occurrence_id].append(section_id)
        if len(occurrence_ids) == 1 and not bool(section.get("allowSinglePartPage")):
            findings.append(
                _finding(
                    "manual_publication_single_part_section",
                    f"'{name}' contains one ordinary component; merge it into a functional parent or explicitly approve a single-part page.",
                    f"{path}.occurrenceIds",
                    sectionId=section_id,
                )
            )
        quality = _group_quality(section, rows_by_occurrence)
        group_quality.append(quality)
        if quality["overall"] < 0.60:
            findings.append(
                _finding(
                    "manual_publication_group_quality",
                    f"'{name}' has insufficient functional grouping quality ({quality['overall']:.2f}).",
                    path,
                    sectionId=section_id,
                    score=quality["overall"],
                )
            )

    ancestors = _ancestor_pairs(sections)
    multiply_assigned: Dict[str, List[str]] = {}
    for occurrence_id, owners in ownership.items():
        unrelated = False
        for left_index, left in enumerate(owners):
            for right in owners[left_index + 1 :]:
                if (left, right) not in ancestors and (right, left) not in ancestors:
                    unrelated = True
        if unrelated:
            multiply_assigned[occurrence_id] = owners

    exclusions = plan.get("excludedOccurrences") or []
    exclusion_ids: Set[str] = set()
    excluded_records: List[Dict[str, str]] = []
    if not isinstance(exclusions, list):
        findings.append(
            _finding(
                "manual_publication_exclusions",
                "excludedOccurrences must be an array.",
                "$.excludedOccurrences",
            )
        )
        exclusions = []
    for index, value in enumerate(exclusions):
        path = f"$.excludedOccurrences[{index}]"
        if not isinstance(value, Mapping):
            findings.append(_finding("manual_publication_exclusion", "Exclusion must be an object.", path))
            continue
        occurrence_id = str(value.get("occurrenceId") or "")
        reason = str(value.get("reason") or "").strip()
        if occurrence_id not in eligible_ids or not reason:
            findings.append(
                _finding(
                    "manual_publication_exclusion",
                    "Every exclusion requires a known occurrence and an explicit reason.",
                    path,
                )
            )
            continue
        exclusion_ids.add(occurrence_id)
        excluded_records.append({"occurrenceId": occurrence_id, "reason": reason})

    assigned_ids = set(ownership)
    unassigned_ids = sorted(eligible_ids - assigned_ids - exclusion_ids)
    if unassigned_ids:
        findings.append(
            _finding(
                "manual_publication_incomplete_coverage",
                f"{len(unassigned_ids)} serviceable component occurrence(s) are not assigned or explicitly excluded.",
                "$.sections",
                occurrenceIds=unassigned_ids,
            )
        )
    if multiply_assigned:
        findings.append(
            _finding(
                "manual_publication_duplicate_assignment",
                f"{len(multiply_assigned)} occurrence(s) are assigned to unrelated sections.",
                "$.sections",
                occurrences=multiply_assigned,
            )
        )

    explained = len(assigned_ids | exclusion_ids)
    coverage_percent = 100.0 if not eligible_ids else explained / len(eligible_ids) * 100.0
    return {
        "status": "PASS" if not findings else "FAIL",
        "eligibleOccurrenceCount": len(eligible_ids),
        "uniqueServicePartCount": len(unique_definitions),
        "assignedOccurrenceCount": len(assigned_ids),
        "unassignedOccurrenceCount": len(unassigned_ids),
        "multiplyAssignedOccurrenceCount": len(multiply_assigned),
        "excludedOccurrenceCount": len(exclusion_ids),
        "coveragePercent": round(coverage_percent, 3),
        "unassignedOccurrenceIds": unassigned_ids,
        "multiplyAssignedOccurrences": multiply_assigned,
        "excludedOccurrences": excluded_records,
        "groupQuality": group_quality,
        "findings": findings,
    }


def require_publishable_manual_plan(
    plan: Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    audit = audit_manual_plan(plan, catalog)
    if audit["status"] != "PASS":
        raise PartsManualValidationError(list(audit["findings"]))
    return audit


__all__ = [
    "audit_manual_plan",
    "is_publishable_section_name",
    "require_publishable_manual_plan",
]
