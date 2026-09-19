"""Closed agent contract for trusted Facility Planning prototype packages."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping


FACILITY_PLANNING_PROTOTYPE_TOOL = (
    "generate_facility_planning_prototype_draft"
)
FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL = (
    "amend_facility_program_resource_batch_draft"
)
MMLE_FACILITY_PLANNING_PACKAGE_ID = "mmle-50d-facility-planning-v1"
FACILITY_PLANNING_PROTOTYPE_PACKAGE_IDS = frozenset(
    {MMLE_FACILITY_PLANNING_PACKAGE_ID}
)


class FacilityPlanningGenerationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def canonicalize_facility_planning_generation_request(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityPlanningGenerationError(
            "facility_planning_generation_request_invalid",
            "Facility planning generation arguments must be an object.",
        )
    allowed = {"planning_package_id", "execution_mode"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityPlanningGenerationError(
            "facility_planning_generation_request_invalid",
            "Facility planning generation arguments contain unsupported fields.",
            details={"unknown": unknown},
        )
    package_id = str(value.get("planning_package_id") or "").strip()
    if package_id not in FACILITY_PLANNING_PROTOTYPE_PACKAGE_IDS:
        raise FacilityPlanningGenerationError(
            "facility_planning_package_unavailable",
            "The requested Facility Planning prototype package is unavailable.",
            details={"planningPackageId": package_id},
        )
    if value.get("execution_mode") != "authorized_draft_run":
        raise FacilityPlanningGenerationError(
            "facility_planning_generation_mode_invalid",
            "Facility Planning packages can create only an authorized unsaved draft.",
        )
    return {
        "planning_package_id": package_id,
        "execution_mode": "authorized_draft_run",
    }


def is_facility_planning_prototype_request(message: str) -> bool:
    """Recognize an explicit request to execute the reviewed MMLE prototype."""

    text = re.sub(r"\s+", " ", str(message or "").strip()).casefold()
    if "mmle-50d" not in text:
        return False
    has_factory = bool(re.search(r"\b(?:factory|facility|plant|layout)\b", text))
    has_create = bool(
        re.search(r"\b(?:build|create|generate|lay\s*out|reproduce)\b", text)
    )
    has_trusted_selector = bool(
        re.search(
            r"\b(?:planning\s+package|reviewed\s+prototype|"
            r"reference[- ]quality|trusted\s+prototype)\b",
            text,
        )
    )
    return has_factory and has_create and has_trusted_selector


def canonicalize_facility_program_resource_amendment_request(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one coordinate-free follow-up against an active program run."""

    if not isinstance(value, Mapping):
        raise FacilityPlanningGenerationError(
            "facility_program_local_amendment_invalid",
            "FacilityProgram amendment arguments must be an object.",
        )
    allowed = {
        "resource_batch_id",
        "quantity",
        "placement_pattern",
        "semantic_orientation",
        "authored_spacing_meters",
        "execution_mode",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityPlanningGenerationError(
            "facility_program_local_amendment_invalid",
            "FacilityProgram amendment contains unsupported fields.",
            details={"unknown": unknown},
        )
    batch_id = str(value.get("resource_batch_id") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", batch_id) is None:
        raise FacilityPlanningGenerationError(
            "facility_program_local_amendment_invalid",
            "resource_batch_id must be an exact stable batch identifier.",
        )
    if value.get("execution_mode") != "authorized_draft_run":
        raise FacilityPlanningGenerationError(
            "facility_program_local_amendment_mode_invalid",
            "FacilityProgram amendments can modify only the active unsaved draft.",
        )
    patch: dict[str, Any] = {}
    quantity = value.get("quantity")
    if quantity is not None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 900:
            raise FacilityPlanningGenerationError(
                "facility_program_local_amendment_invalid",
                "quantity must be an integer from 1 through 900.",
            )
        patch["quantity"] = quantity
    for source, target in (
        ("placement_pattern", "placement_pattern"),
        ("semantic_orientation", "semantic_orientation"),
    ):
        raw = value.get(source)
        if raw is None:
            continue
        normalized = str(raw).strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", normalized) is None:
            raise FacilityPlanningGenerationError(
                "facility_program_local_amendment_invalid",
                f"{source} must be a stable semantic identifier.",
            )
        patch[target] = normalized
    spacing = value.get("authored_spacing_meters")
    if spacing is not None:
        if (
            isinstance(spacing, bool)
            or not isinstance(spacing, (int, float))
            or not 0 <= float(spacing) <= 10_000
        ):
            raise FacilityPlanningGenerationError(
                "facility_program_local_amendment_invalid",
                "authored_spacing_meters must be a non-negative number.",
            )
        patch["authored_spacing"] = {
            "value": float(spacing),
            "unit": "m",
            "evidence_ref": "user-authored-facility-program-amendment",
        }
    if not patch:
        raise FacilityPlanningGenerationError(
            "facility_program_local_amendment_invalid",
            "Specify at least one quantity, pattern, orientation, or spacing change.",
        )
    return {
        "resource_batch_id": batch_id,
        "patch": patch,
        "execution_mode": "authorized_draft_run",
    }


def is_facility_program_resource_amendment_request(message: str) -> bool:
    text = re.sub(r"\s+", " ", str(message or "").strip()).casefold()
    has_resource = bool(
        re.search(
            r"\b(?:asset|equipment|machine|rack|bench|workstation|forklift|"
            r"resource|batch)\b",
            text,
        )
    )
    if not has_resource:
        return False

    # Keep this predicate narrower than the cell and circulation routers. A
    # request such as "arrange Assembly ... with 1 m spacing" names a cell
    # strategy, while "make this aisle safe for any forklift" is a guarded
    # circulation question. Neither authorizes a FacilityProgram batch edit.
    if re.search(
        r"\b(?:increase|decrease|reduce|add|remove|reorient|rotate|space|arrange)\b",
        text,
    ):
        return True
    if not re.search(r"\b(?:change|update|set|make)\b", text):
        return False
    return bool(
        re.search(r"\b(?:quantity|count|spacing|orientation|pattern)\b", text)
        or re.search(r"\b\d+(?:\.\d+)?\b", text)
    )


def facility_planning_prototype_tool_spec() -> dict[str, Any]:
    return {
        "name": FACILITY_PLANNING_PROTOTYPE_TOOL,
        "description": (
            "Create one complete unsaved prototype factory from a trusted, "
            "revision-bound Facility Planning package. Select only the package "
            "ID; InspectorPro resolves the package, catalog revisions, geometry, "
            "routing, patterns, validation, and durable ten-stage execution. "
            "Never use this tool to claim production, safety, capacity, or "
            "regulatory approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "planning_package_id": {
                    "type": "string",
                    "enum": sorted(FACILITY_PLANNING_PROTOTYPE_PACKAGE_IDS),
                },
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": ["planning_package_id", "execution_mode"],
            "additionalProperties": False,
        },
    }


def facility_program_resource_amendment_tool_spec() -> dict[str, Any]:
    return {
        "name": FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "description": (
            "Amend exactly one dependency-independent resource batch in the "
            "active unsaved FacilityProgram prototype. Use the batch's exact "
            "stable ID and only user-requested quantity, placement pattern, "
            "semantic orientation, or spacing. InspectorPro owns geometry, "
            "collision validation, receipt chaining, and exact Undo. Never "
            "supply coordinates or claim Save, safety, capacity, or approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_batch_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                },
                "quantity": {
                    "anyOf": [
                        {"type": "integer", "minimum": 1, "maximum": 900},
                        {"type": "null"},
                    ]
                },
                "placement_pattern": {
                    "anyOf": [
                        {"type": "string", "minLength": 1, "maxLength": 160},
                        {"type": "null"},
                    ]
                },
                "semantic_orientation": {
                    "anyOf": [
                        {"type": "string", "minLength": 1, "maxLength": 160},
                        {"type": "null"},
                    ]
                },
                "authored_spacing_meters": {
                    "anyOf": [
                        {"type": "number", "minimum": 0, "maximum": 10000},
                        {"type": "null"},
                    ]
                },
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "resource_batch_id",
                "quantity",
                "placement_pattern",
                "semantic_orientation",
                "authored_spacing_meters",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


__all__ = [
    "FACILITY_PLANNING_PROTOTYPE_PACKAGE_IDS",
    "FACILITY_PLANNING_PROTOTYPE_TOOL",
    "FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL",
    "MMLE_FACILITY_PLANNING_PACKAGE_ID",
    "FacilityPlanningGenerationError",
    "canonicalize_facility_planning_generation_request",
    "canonicalize_facility_program_resource_amendment_request",
    "facility_program_resource_amendment_tool_spec",
    "facility_planning_prototype_tool_spec",
    "is_facility_planning_prototype_request",
    "is_facility_program_resource_amendment_request",
]
