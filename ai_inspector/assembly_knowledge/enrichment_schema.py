"""Strict model-output contract for Assembly Knowledge enrichment."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


ENRICHMENT_OUTPUT_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_ROOT_FIELDS = {
    "schemaVersion",
    "sourceRevision",
    "occurrenceRoles",
    "functionalRelationships",
    "jointArchetypes",
    "processBranches",
    "intermediateResults",
    "operationFamilies",
    "assumptions",
    "unresolvedQuestions",
}
_LIST_FIELDS: Dict[str, tuple[set[str], tuple[str, ...]]] = {
    "occurrenceRoles": (
        {"occurrenceId", "role", "function", "evidenceRefs", "assumptionRefs"},
        ("occurrenceId", "role", "function"),
    ),
    "functionalRelationships": (
        {
            "candidateKey",
            "occurrenceRefs",
            "relationshipType",
            "description",
            "evidenceRefs",
            "assumptionRefs",
        },
        ("candidateKey", "relationshipType", "description"),
    ),
    "jointArchetypes": (
        {
            "candidateKey",
            "interfaceId",
            "archetype",
            "description",
            "evidenceRefs",
            "assumptionRefs",
        },
        ("candidateKey", "interfaceId", "archetype", "description"),
    ),
    "processBranches": (
        {
            "candidateKey",
            "label",
            "occurrenceRefs",
            "description",
            "evidenceRefs",
            "assumptionRefs",
        },
        ("candidateKey", "label", "description"),
    ),
    "intermediateResults": (
        {
            "candidateKey",
            "label",
            "inputOccurrenceRefs",
            "description",
            "branchKey",
            "evidenceRefs",
            "assumptionRefs",
        },
        ("candidateKey", "label", "description"),
    ),
    "operationFamilies": (
        {
            "candidateKey",
            "label",
            "family",
            "inputRefs",
            "outputRef",
            "branchKey",
            "predecessorKeys",
            "description",
            "evidenceRefs",
            "assumptionRefs",
        },
        ("candidateKey", "label", "family", "description"),
    ),
    "assumptions": (
        {"candidateKey", "text", "subjectRefs"},
        ("candidateKey", "text"),
    ),
    "unresolvedQuestions": (
        {"candidateKey", "text", "subjectRefs"},
        ("candidateKey", "text"),
    ),
}
_REFERENCE_FIELDS = {
    "occurrenceRefs",
    "inputOccurrenceRefs",
    "evidenceRefs",
    "assumptionRefs",
    "inputRefs",
    "predecessorKeys",
    "subjectRefs",
}


class EnrichmentOutputError(ValueError):
    def __init__(self, findings: Sequence[Mapping[str, Any]]):
        self.findings = [dict(item) for item in findings]
        message = "; ".join(
            f"{item['path']}: {item['message']}" for item in self.findings[:8]
        )
        super().__init__(message or "invalid enrichment output")


def enrichment_output_json_schema(
    *,
    require_process_plan: bool = True,
) -> Dict[str, Any]:
    reference_array = {
        "type": "array",
        "items": {"type": "string", "pattern": _ID_RE.pattern},
    }

    def object_schema(
        fields: Iterable[str],
        *,
        nullable: Iterable[str] = (),
    ) -> Dict[str, Any]:
        nullable_set = set(nullable)
        properties: Dict[str, Any] = {}
        for field in fields:
            if field in _REFERENCE_FIELDS:
                properties[field] = reference_array
            elif field in nullable_set:
                properties[field] = {
                    "anyOf": [
                        {"type": "string", "pattern": _ID_RE.pattern},
                        {"type": "null"},
                    ]
                }
            elif field.endswith("Id") or field.endswith("Key"):
                properties[field] = {"type": "string", "pattern": _ID_RE.pattern}
            else:
                properties[field] = {"type": "string", "maxLength": 1000}
        return {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(fields),
            "properties": properties,
        }

    properties: Dict[str, Any] = {
        "schemaVersion": {"type": "integer", "const": 1},
        "sourceRevision": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }
    field_order = (
        "processBranches",
        "intermediateResults",
        "operationFamilies",
        "assumptions",
        "unresolvedQuestions",
        "occurrenceRoles",
        "functionalRelationships",
        "jointArchetypes",
    )
    for field in field_order:
        fields, _ = _LIST_FIELDS[field]
        nullable: tuple[str, ...] = ()
        if field == "intermediateResults":
            nullable = ("branchKey",)
        elif field == "operationFamilies":
            nullable = ("outputRef", "branchKey")
        properties[field] = {
            "type": "array",
            "items": object_schema(fields, nullable=nullable),
        }
        if require_process_plan and field in {
            "processBranches",
            "operationFamilies",
        }:
            properties[field]["minItems"] = 1
        if field == "intermediateResults":
            properties[field]["maxItems"] = 0
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ROOT_FIELDS),
        "properties": properties,
    }


def _finding(
    findings: List[Dict[str, Any]],
    path: str,
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> None:
    finding = {
        "severity": "error",
        "path": path,
        "code": code,
        "message": message,
    }
    if details:
        finding["details"] = dict(details)
    findings.append(finding)


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def validate_enrichment_output(
    value: Any,
    *,
    source_revision: str,
    occurrence_ids: Iterable[str],
    interface_ids: Iterable[str],
    evidence_ids: Iterable[str],
    root_occurrence_id: str,
    required_input_occurrence_ids: Iterable[str],
    require_process_plan: bool = True,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not isinstance(value, dict):
        return [
            {
                "severity": "error",
                "path": "$",
                "code": "expected_object",
                "message": "Enrichment output must be an object.",
            }
        ]
    unknown_root = sorted(set(value) - _ROOT_FIELDS)
    missing_root = sorted(_ROOT_FIELDS - set(value))
    for field in missing_root:
        _finding(findings, f"$.{field}", "missing_field", "Field is required.")
    for field in unknown_root:
        _finding(findings, f"$.{field}", "unknown_field", "Field is not allowed.")
    if value.get("schemaVersion") != ENRICHMENT_OUTPUT_SCHEMA_VERSION:
        _finding(
            findings,
            "$.schemaVersion",
            "invalid_schema_version",
            "schemaVersion must equal 1.",
        )
    if value.get("sourceRevision") != source_revision:
        _finding(
            findings,
            "$.sourceRevision",
            "stale_source_revision",
            "Output sourceRevision does not match the package.",
        )

    known_occurrences = set(occurrence_ids)
    known_interfaces = set(interface_ids)
    known_evidence = set(evidence_ids)
    keys_by_field: Dict[str, set[str]] = {}
    for field, (allowed_fields, required_strings) in _LIST_FIELDS.items():
        rows = value.get(field)
        if not isinstance(rows, list):
            _finding(findings, f"$.{field}", "expected_array", "Field must be an array.")
            continue
        seen = set()
        for index, row in enumerate(rows):
            path = f"$.{field}[{index}]"
            if not isinstance(row, dict):
                _finding(findings, path, "expected_object", "Entry must be an object.")
                continue
            for missing in sorted(allowed_fields - set(row)):
                _finding(findings, f"{path}.{missing}", "missing_field", "Field is required.")
            for unknown in sorted(set(row) - allowed_fields):
                _finding(findings, f"{path}.{unknown}", "unknown_field", "Field is not allowed.")
            for string_field in required_strings:
                if not isinstance(row.get(string_field), str) or not row[
                    string_field
                ].strip():
                    _finding(
                        findings,
                        f"{path}.{string_field}",
                        "invalid_string",
                        "Field must be a non-empty string.",
                    )
            key = row.get("candidateKey")
            if key is not None:
                if not _valid_identifier(key):
                    _finding(
                        findings,
                        f"{path}.candidateKey",
                        "invalid_identifier",
                        "candidateKey must be a stable identifier.",
                    )
                elif key in seen:
                    _finding(
                        findings,
                        f"{path}.candidateKey",
                        "duplicate_candidate_key",
                        "candidateKey must be unique in its collection.",
                    )
                seen.add(key)
            for reference_field in _REFERENCE_FIELDS & set(row):
                refs = row.get(reference_field)
                if not isinstance(refs, list):
                    _finding(
                        findings,
                        f"{path}.{reference_field}",
                        "expected_array",
                        "Reference field must be an array.",
                    )
                    continue
                for ref_index, ref in enumerate(refs):
                    if not _valid_identifier(ref):
                        _finding(
                            findings,
                            f"{path}.{reference_field}[{ref_index}]",
                            "invalid_identifier",
                            "Reference must be a stable identifier.",
                        )
            for nullable_field in ("branchKey", "outputRef"):
                if nullable_field in row and row[nullable_field] is not None:
                    if not _valid_identifier(row[nullable_field]):
                        _finding(
                            findings,
                            f"{path}.{nullable_field}",
                            "invalid_identifier",
                            "Reference must be null or a stable identifier.",
                        )
        keys_by_field[field] = seen

    assumption_keys = keys_by_field.get("assumptions", set())
    branch_keys = keys_by_field.get("processBranches", set())
    intermediate_keys = keys_by_field.get("intermediateResults", set())
    operation_keys = keys_by_field.get("operationFamilies", set())
    known_semantic_subjects = (
        known_occurrences
        | known_interfaces
        | known_evidence
        | set().union(*keys_by_field.values())
    )
    if (
        require_process_plan
        and isinstance(value.get("processBranches"), list)
        and not value["processBranches"]
    ):
        _finding(
            findings,
            "$.processBranches",
            "process_branch_required",
            "At least one process branch is required for planning readiness.",
        )
    if (
        require_process_plan
        and isinstance(value.get("operationFamilies"), list)
        and not value["operationFamilies"]
    ):
        _finding(
            findings,
            "$.operationFamilies",
            "operation_family_required",
            "At least one operation family is required for planning readiness.",
        )
    for field, rows in value.items():
        if field not in _LIST_FIELDS or not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            path = f"$.{field}[{index}]"
            for ref in row.get("evidenceRefs", []):
                if ref not in known_evidence:
                    _finding(
                        findings,
                        f"{path}.evidenceRefs",
                        "unknown_evidence_ref",
                        f"Unknown evidence reference: {ref}",
                    )
            for ref in row.get("assumptionRefs", []):
                if ref not in assumption_keys:
                    _finding(
                        findings,
                        f"{path}.assumptionRefs",
                        "unknown_assumption_ref",
                        f"Unknown assumption reference: {ref}",
                    )
            for name in ("occurrenceRefs", "inputOccurrenceRefs"):
                for ref in row.get(name, []):
                    if ref not in known_occurrences:
                        _finding(
                            findings,
                            f"{path}.{name}",
                            "unknown_occurrence_ref",
                            f"Unknown occurrence reference: {ref}",
                        )
            for ref in row.get("subjectRefs", []):
                if ref not in known_semantic_subjects:
                    _finding(
                        findings,
                        f"{path}.subjectRefs",
                        "unknown_semantic_subject_ref",
                        f"Unknown semantic subject reference: {ref}",
                    )
            occurrence_id = row.get("occurrenceId")
            if occurrence_id is not None and occurrence_id not in known_occurrences:
                _finding(
                    findings,
                    f"{path}.occurrenceId",
                    "unknown_occurrence_ref",
                    f"Unknown occurrence reference: {occurrence_id}",
                )
            interface_id = row.get("interfaceId")
            if interface_id is not None and interface_id not in known_interfaces:
                _finding(
                    findings,
                    f"{path}.interfaceId",
                    "unknown_interface_ref",
                    f"Unknown interface reference: {interface_id}",
                )
            branch_key = row.get("branchKey")
            if branch_key is not None and branch_key not in branch_keys:
                _finding(
                    findings,
                    f"{path}.branchKey",
                    "unknown_branch_ref",
                    f"Unknown process branch: {branch_key}",
                )
            for ref in row.get("inputRefs", []):
                if ref not in known_occurrences and ref not in intermediate_keys:
                    _finding(
                        findings,
                        f"{path}.inputRefs",
                        "unknown_process_input",
                        f"Unknown process input: {ref}",
                    )
            output_ref = row.get("outputRef")
            if (
                output_ref is not None
                and output_ref not in known_occurrences
                and output_ref not in intermediate_keys
            ):
                _finding(
                    findings,
                    f"{path}.outputRef",
                    "unknown_process_output",
                    f"Unknown process output: {output_ref}",
                )
            for ref in row.get("predecessorKeys", []):
                if ref not in operation_keys:
                    _finding(
                        findings,
                        f"{path}.predecessorKeys",
                        "unknown_operation_ref",
                        f"Unknown predecessor operation: {ref}",
                    )

    if not require_process_plan:
        return findings

    operation_rows = [
        row
        for row in value.get("operationFamilies", [])
        if isinstance(row, dict) and _valid_identifier(row.get("candidateKey"))
    ]
    covered_occurrences = {
        ref
        for row in operation_rows
        for ref in row.get("inputRefs", [])
        if ref in known_occurrences
    }
    covered_occurrences.update(
        ref
        for row in value.get("intermediateResults", [])
        if isinstance(row, dict)
        for ref in row.get("inputOccurrenceRefs", [])
        if ref in known_occurrences
    )
    explicitly_unresolved_occurrences = {
        ref
        for row in value.get("unresolvedQuestions", [])
        if isinstance(row, dict)
        for ref in row.get("subjectRefs", [])
        if ref in known_occurrences
    }
    missing_inputs = sorted(
        set(required_input_occurrence_ids)
        - covered_occurrences
        - explicitly_unresolved_occurrences
    )
    if missing_inputs:
        preview = ", ".join(missing_inputs[:8])
        suffix = (
            f" and {len(missing_inputs) - 8} more"
            if len(missing_inputs) > 8
            else ""
        )
        _finding(
            findings,
            "$.operationFamilies",
            "process_input_coverage_missing",
            f"Required occurrence inputs are not covered: {preview}{suffix}.",
            details={"occurrenceIds": missing_inputs},
        )

    predecessor_keys = {
        ref
        for row in operation_rows
        for ref in row.get("predecessorKeys", [])
        if ref in operation_keys
    }
    terminal_operations = [
        row
        for row in operation_rows
        if row["candidateKey"] not in predecessor_keys
    ]
    if not terminal_operations:
        _finding(
            findings,
            "$.operationFamilies",
            "final_assembly_output_missing",
            "At least one terminal operation must produce the root assembly.",
        )
    else:
        invalid_terminal_keys = sorted(
            row["candidateKey"]
            for row in terminal_operations
            if row.get("outputRef") != root_occurrence_id
        )
    if terminal_operations and invalid_terminal_keys:
        _finding(
            findings,
            "$.operationFamilies",
            "final_assembly_output_missing",
            "Every terminal operation must produce the root assembly occurrence.",
            details={
                "candidateKeys": invalid_terminal_keys,
                "rootOccurrenceId": root_occurrence_id,
            },
        )

    producer_counts = {key: 0 for key in intermediate_keys}
    for row in operation_rows:
        output_ref = row.get("outputRef")
        if output_ref in producer_counts:
            producer_counts[output_ref] += 1
    for intermediate_key, count in sorted(producer_counts.items()):
        if count == 0:
            _finding(
                findings,
                "$.operationFamilies",
                "intermediate_result_producer_missing",
                f"Intermediate result has no producing operation: {intermediate_key}",
            )
        elif count > 1:
            _finding(
                findings,
                "$.operationFamilies",
                "intermediate_result_producer_duplicate",
                (
                    "Intermediate result must be produced by one operation: "
                    f"{intermediate_key}"
                ),
            )

    predecessors = {
        row["candidateKey"]: [
            ref
            for ref in row.get("predecessorKeys", [])
            if ref in operation_keys
        ]
        for row in operation_rows
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def has_cycle(operation_key: str) -> bool:
        if operation_key in visiting:
            return True
        if operation_key in visited:
            return False
        visiting.add(operation_key)
        for predecessor in predecessors.get(operation_key, []):
            if has_cycle(predecessor):
                return True
        visiting.remove(operation_key)
        visited.add(operation_key)
        return False

    if any(has_cycle(key) for key in sorted(predecessors)):
        _finding(
            findings,
            "$.operationFamilies",
            "operation_precedence_cycle",
            "Operation predecessor relationships must be acyclic.",
        )
    return findings


def require_valid_enrichment_output(
    value: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    findings = validate_enrichment_output(value, **kwargs)
    if findings:
        raise EnrichmentOutputError(findings)
    return value
