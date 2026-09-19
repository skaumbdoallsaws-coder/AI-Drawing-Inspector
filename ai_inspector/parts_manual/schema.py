"""Validation and canonical forms for illustrated parts manual plans."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set


PARTS_MANUAL_SCHEMA_VERSION = 1
MANUAL_SECTION_SOURCES = frozenset(
    {"manual", "library_manual_profile", "cad_hierarchy", "process_map", "inferred"}
)
MANUAL_EXPLODE_STRATEGIES = frozenset({"radial", "process_sequence"})
MANUAL_CAMERA_PRESETS = frozenset({"current", "isometric", "front", "top", "right"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECTION_ID_RE = re.compile(r"^section-[0-9a-f]{8,32}$")


class PartsManualValidationError(ValueError):
    def __init__(self, findings: List[Dict[str, Any]]):
        self.findings = findings
        super().__init__("parts manual failed validation")


def _finding(code: str, message: str, path: str) -> Dict[str, str]:
    return {"severity": "error", "code": code, "message": message, "path": path}


def default_section_visualization() -> Dict[str, Any]:
    return {
        "explodeStrategy": "radial",
        "explodeFactor": 1.0,
        "cameraPreset": "isometric",
        "showItemCallouts": True,
    }


def validate_manual_plan(
    value: Any,
    *,
    known_occurrence_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not isinstance(value, Mapping):
        return [_finding("manual_plan_not_object", "Manual plan must be an object.", "$")]
    if value.get("schemaVersion") != PARTS_MANUAL_SCHEMA_VERSION:
        findings.append(_finding("manual_schema_version", "Unsupported manual schema version.", "$.schemaVersion"))
    assembly_number = value.get("assemblyNumber")
    if not isinstance(assembly_number, str) or not assembly_number.strip():
        findings.append(_finding("manual_assembly_required", "assemblyNumber is required.", "$.assemblyNumber"))
    source_revision = value.get("sourceRevision")
    if not isinstance(source_revision, str) or _SHA256_RE.fullmatch(source_revision) is None:
        findings.append(_finding("manual_source_revision", "sourceRevision must be a SHA-256 value.", "$.sourceRevision"))
    title = value.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        findings.append(_finding("manual_title", "title must contain 1 to 160 characters.", "$.title"))

    known = set(str(item) for item in known_occurrence_ids) if known_occurrence_ids is not None else None
    sections = value.get("sections")
    if not isinstance(sections, list):
        findings.append(_finding("manual_sections", "sections must be an array.", "$.sections"))
        return findings

    section_ids: Set[str] = set()
    direct_membership: Dict[str, List[str]] = {}
    parent_by_id: Dict[str, Optional[str]] = {}
    for index, section in enumerate(sections):
        path = f"$.sections[{index}]"
        if not isinstance(section, Mapping):
            findings.append(_finding("manual_section_not_object", "Section must be an object.", path))
            continue
        section_id = section.get("sectionId")
        if not isinstance(section_id, str) or _SECTION_ID_RE.fullmatch(section_id) is None:
            findings.append(_finding("manual_section_id", "sectionId is invalid.", f"{path}.sectionId"))
            continue
        if section_id in section_ids:
            findings.append(_finding("manual_section_duplicate", "sectionId must be unique.", f"{path}.sectionId"))
        section_ids.add(section_id)
        parent = section.get("parentSectionId")
        parent_by_id[section_id] = str(parent) if parent is not None else None
        name = section.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            findings.append(_finding("manual_section_name", "Section name must contain 1 to 120 characters.", f"{path}.name"))
        source = section.get("source")
        if source not in MANUAL_SECTION_SOURCES:
            findings.append(_finding("manual_section_source", "Section source is invalid.", f"{path}.source"))
        confidence = section.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
        ):
            findings.append(_finding("manual_section_confidence", "confidence must be between 0 and 1.", f"{path}.confidence"))
        occurrence_ids = section.get("occurrenceIds")
        if not isinstance(occurrence_ids, list) or not occurrence_ids:
            findings.append(_finding("manual_section_empty", "A manual section requires at least one occurrence.", f"{path}.occurrenceIds"))
            occurrence_ids = []
        normalized_ids = [str(item) for item in occurrence_ids if isinstance(item, str) and item]
        if len(normalized_ids) != len(occurrence_ids) or len(set(normalized_ids)) != len(normalized_ids):
            findings.append(_finding("manual_section_occurrences", "occurrenceIds must be unique non-empty strings.", f"{path}.occurrenceIds"))
        for occurrence_id in normalized_ids:
            direct_membership.setdefault(occurrence_id, []).append(section_id)
            if known is not None and occurrence_id not in known:
                findings.append(_finding("manual_occurrence_unknown", f"Unknown occurrence: {occurrence_id}", f"{path}.occurrenceIds"))
        allow_single = section.get("allowSinglePartPage", False)
        if not isinstance(allow_single, bool):
            findings.append(
                _finding(
                    "manual_single_part_page",
                    "allowSinglePartPage must be a boolean.",
                    f"{path}.allowSinglePartPage",
                )
            )
        process_operation_ids = section.get("processOperationIds", [])
        if not isinstance(process_operation_ids, list) or any(
            not isinstance(value, str) or not value
            for value in process_operation_ids
        ):
            findings.append(
                _finding(
                    "manual_process_operations",
                    "processOperationIds must be an array of non-empty strings.",
                    f"{path}.processOperationIds",
                )
            )
        occurrence_order = section.get("occurrenceOrder", normalized_ids)
        if not isinstance(occurrence_order, list) or any(
            not isinstance(value, str) or value not in normalized_ids
            for value in occurrence_order
        ) or len(set(occurrence_order)) != len(occurrence_order):
            findings.append(
                _finding(
                    "manual_occurrence_order",
                    "occurrenceOrder must contain unique occurrences from the section.",
                    f"{path}.occurrenceOrder",
                )
            )
        assignments = section.get("itemAssignments")
        if not isinstance(assignments, list):
            findings.append(_finding("manual_item_assignments", "itemAssignments must be an array.", f"{path}.itemAssignments"))
        else:
            definition_ids = set()
            item_numbers = set()
            for assignment_index, assignment in enumerate(assignments):
                assignment_path = f"{path}.itemAssignments[{assignment_index}]"
                if not isinstance(assignment, Mapping):
                    findings.append(_finding("manual_item_assignment", "Item assignment must be an object.", assignment_path))
                    continue
                definition_id = assignment.get("definitionId")
                item_number = assignment.get("itemNumber")
                if not isinstance(definition_id, str) or not definition_id:
                    findings.append(_finding("manual_definition_id", "definitionId is required.", f"{assignment_path}.definitionId"))
                elif definition_id in definition_ids:
                    findings.append(_finding("manual_definition_duplicate", "definitionId must be unique in a section.", f"{assignment_path}.definitionId"))
                definition_ids.add(definition_id)
                if not isinstance(item_number, int) or isinstance(item_number, bool) or item_number < 1:
                    findings.append(_finding("manual_item_number", "itemNumber must be a positive integer.", f"{assignment_path}.itemNumber"))
                elif item_number in item_numbers:
                    findings.append(_finding("manual_item_number_duplicate", "itemNumber must be unique in a section.", f"{assignment_path}.itemNumber"))
                item_numbers.add(item_number)

        visualization = section.get("visualization")
        if visualization is not None:
            visualization_path = f"{path}.visualization"
            if not isinstance(visualization, Mapping):
                findings.append(_finding("manual_visualization", "visualization must be an object.", visualization_path))
            else:
                unknown_keys = set(visualization) - set(default_section_visualization())
                if unknown_keys:
                    findings.append(
                        _finding(
                            "manual_visualization_fields",
                            "Unsupported visualization fields: " + ", ".join(sorted(unknown_keys)),
                            visualization_path,
                        )
                    )
                if visualization.get("explodeStrategy") not in MANUAL_EXPLODE_STRATEGIES:
                    findings.append(_finding("manual_explode_strategy", "explodeStrategy is invalid.", f"{visualization_path}.explodeStrategy"))
                explode_factor = visualization.get("explodeFactor")
                if (
                    not isinstance(explode_factor, (int, float))
                    or isinstance(explode_factor, bool)
                    or not 0.25 <= float(explode_factor) <= 3.0
                ):
                    findings.append(_finding("manual_explode_factor", "explodeFactor must be between 0.25 and 3.0.", f"{visualization_path}.explodeFactor"))
                if visualization.get("cameraPreset") not in MANUAL_CAMERA_PRESETS:
                    findings.append(_finding("manual_camera_preset", "cameraPreset is invalid.", f"{visualization_path}.cameraPreset"))
                if not isinstance(visualization.get("showItemCallouts"), bool):
                    findings.append(_finding("manual_item_callouts", "showItemCallouts must be a boolean.", f"{visualization_path}.showItemCallouts"))

    for section_id, parent_id in parent_by_id.items():
        if parent_id is not None and parent_id not in section_ids:
            findings.append(_finding("manual_parent_unknown", f"Unknown parent section: {parent_id}", f"$.sections[{section_id}].parentSectionId"))
        seen = {section_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                findings.append(_finding("manual_section_cycle", "Manual section hierarchy contains a cycle.", f"$.sections[{section_id}].parentSectionId"))
                break
            seen.add(cursor)
            cursor = parent_by_id.get(cursor)

    def is_ancestor(candidate: str, section_id: str) -> bool:
        cursor = parent_by_id.get(section_id)
        while cursor is not None:
            if cursor == candidate:
                return True
            cursor = parent_by_id.get(cursor)
        return False

    for occurrence_id, owners in direct_membership.items():
        for left_index, left in enumerate(owners):
            for right in owners[left_index + 1 :]:
                if not is_ancestor(left, right) and not is_ancestor(right, left):
                    findings.append(
                        _finding(
                            "manual_occurrence_sibling_overlap",
                            f"Occurrence {occurrence_id} is assigned directly to unrelated sections.",
                            "$.sections",
                        )
                    )
    exclusions = value.get("excludedOccurrences", [])
    if not isinstance(exclusions, list):
        findings.append(
            _finding(
                "manual_exclusions",
                "excludedOccurrences must be an array.",
                "$.excludedOccurrences",
            )
        )
    document_control = value.get("documentControl")
    if document_control is not None and not isinstance(document_control, Mapping):
        findings.append(
            _finding(
                "manual_document_control",
                "documentControl must be an object.",
                "$.documentControl",
            )
        )
    return findings


def require_valid_manual_plan(
    value: Any,
    *,
    known_occurrence_ids: Optional[Iterable[str]] = None,
) -> None:
    findings = validate_manual_plan(value, known_occurrence_ids=known_occurrence_ids)
    if findings:
        raise PartsManualValidationError(findings)
