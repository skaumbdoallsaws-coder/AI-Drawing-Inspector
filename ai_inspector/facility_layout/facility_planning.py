"""Evidence-gated planning packages for coordinate-free facility programs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any, Mapping, Sequence

from .facility_program import (
    FACILITY_PROGRAM_SCHEMA,
    canonicalize_facility_program,
)
from .g1_planner import G1_ZONE_TYPES
from .industrial_patterns import (
    INDUSTRIAL_PATTERN_IDS,
    select_industrial_pattern,
)
from .knowledge_foundation import canonical_facility_knowledge_bytes


FACILITY_PLANNING_PACKAGE_SCHEMA = "facility-planning-package-v1"
FACILITY_PLANNING_COMPILE_SCHEMA = "facility-planning-compile-v1"
FACILITY_PLANNING_IMPACT_SCHEMA = "facility-planning-impact-v1"
FACILITY_PLANNING_MAX_PROCESS_STEPS = 200
FACILITY_PLANNING_MAX_DEPARTMENTS = 50
FACILITY_PLANNING_MAX_EQUIPMENT_REQUIREMENTS = 160
FACILITY_PLANNING_MAX_EVIDENCE = 400
FACILITY_PLANNING_TOOL_RESPONSE_BYTES = 16_384

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNITS = frozenset({"m", "mm", "ft", "in"})
_EVIDENCE_STATUSES = frozenset({"authored", "derived", "inferred", "unknown"})
_AUTHORITIES = frozenset({"illustrative", "supporting", "controlled"})
_REVIEW_STATUSES = frozenset({"pending", "confirmed", "rejected"})
_PLANNING_CLAIMS = frozenset(
    {"illustrative_prototype", "reviewed_recipe", "production_realistic"}
)
_COORDINATE_FIELDS = frozenset(
    {
        "x",
        "y",
        "z",
        "position",
        "transform",
        "boundary",
        "centerline",
        "quaternion",
        "rotationDegrees",
        "cameraPosition",
        "cameraTarget",
    }
)
_REQUIRED_REALISM_INPUT_KINDS = frozenset(
    {"process_routing", "demand_or_takt", "capability_mapping", "adjacency_or_separation"}
)


class FacilityPlanningPackageError(RuntimeError):
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


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must be an object.",
            details={"field": field},
        )
    return deepcopy(dict(value))


def _array(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must be an array.",
            details={"field": field},
        )
    if len(value) > maximum:
        raise FacilityPlanningPackageError(
            "facility_planning_package_budget_exceeded",
            f"{field} exceeds the {maximum}-item contract limit.",
            details={"field": field, "maximum": maximum, "actual": len(value)},
        )
    return deepcopy(value)


def _closed(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityPlanningPackageError(
            "facility_planning_package_unknown_field",
            f"{field} contains unsupported fields.",
            details={"field": field, "unknown": unknown},
        )


def _text(value: Any, field: str, maximum: int = 240) -> str:
    if not isinstance(value, str):
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must be text.",
            details={"field": field},
        )
    result = re.sub(r"\s+", " ", value.strip())
    if not result or len(result) > maximum:
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must contain 1-{maximum} characters.",
            details={"field": field},
        )
    return result


def _optional_text(value: Any, field: str, maximum: int = 240) -> str | None:
    return None if value is None else _text(value, field, maximum)


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field, 160)
    if _IDENTIFIER.fullmatch(result) is None:
        raise FacilityPlanningPackageError(
            "facility_planning_package_identifier_invalid",
            f"{field} must be a stable identifier.",
            details={"field": field},
        )
    return result


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field, 64)
    if _SHA256.fullmatch(result) is None:
        raise FacilityPlanningPackageError(
            "facility_planning_package_revision_invalid",
            f"{field} must be a lowercase SHA-256 digest.",
            details={"field": field},
        )
    return result


def _positive_number(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must be numeric.",
            details={"field": field},
        )
    result = float(value)
    if result < 0 if allow_zero else result <= 0:
        raise FacilityPlanningPackageError(
            "facility_planning_package_invalid",
            f"{field} must be {'non-negative' if allow_zero else 'positive'}.",
            details={"field": field},
        )
    return result


def _refs(value: Any, field: str, maximum: int = 200) -> list[str]:
    result = [_identifier(item, field) for item in _array(value, field, maximum)]
    if len(result) != len(set(result)):
        raise FacilityPlanningPackageError(
            "facility_planning_package_duplicate_reference",
            f"{field} contains duplicate references.",
            details={"field": field},
        )
    return result


def _reject_coordinates(value: Any, field: str = "planning_package") -> None:
    if isinstance(value, Mapping):
        prohibited = sorted(str(key) for key in value if key in _COORDINATE_FIELDS)
        if prohibited:
            raise FacilityPlanningPackageError(
                "facility_planning_model_geometry_forbidden",
                "Facility planning knowledge cannot own coordinates or transforms.",
                details={"field": field, "prohibited": prohibited},
            )
        for key, child in value.items():
            _reject_coordinates(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_coordinates(child, f"{field}[{index}]")


def _evidence_refs(value: Any, field: str, evidence_ids: set[str]) -> list[str]:
    result = _refs(value, field)
    unknown = sorted(set(result) - evidence_ids)
    if unknown:
        raise FacilityPlanningPackageError(
            "facility_planning_evidence_unknown",
            f"{field} references evidence not registered by the package.",
            details={"field": field, "unknown": unknown},
        )
    return result


def _canonical_evidence_register(value: Any) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(
        _array(value, "evidenceRegister", FACILITY_PLANNING_MAX_EVIDENCE)
    ):
        field = f"evidenceRegister[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "evidenceId",
                "sourceType",
                "sourceLocator",
                "sourceRevision",
                "evidenceClass",
                "authority",
                "reviewStatus",
                "synthetic",
            },
            field,
        )
        authority = str(raw.get("authority") or "")
        review_status = str(raw.get("reviewStatus") or "")
        if authority not in _AUTHORITIES or review_status not in _REVIEW_STATUSES:
            raise FacilityPlanningPackageError(
                "facility_planning_authority_invalid",
                f"{field} has an invalid authority or review status.",
            )
        synthetic = raw.get("synthetic")
        if not isinstance(synthetic, bool):
            raise FacilityPlanningPackageError(
                "facility_planning_package_invalid",
                f"{field}.synthetic must be boolean.",
            )
        if synthetic and (authority == "controlled" or review_status == "confirmed"):
            raise FacilityPlanningPackageError(
                "facility_planning_synthetic_authority_forbidden",
                "Synthetic evidence cannot be controlled or human-confirmed automatically.",
                details={"evidenceId": raw.get("evidenceId")},
            )
        result.append(
            {
                "evidenceId": _identifier(raw.get("evidenceId"), f"{field}.evidenceId"),
                "sourceType": _identifier(raw.get("sourceType"), f"{field}.sourceType"),
                "sourceLocator": _text(
                    raw.get("sourceLocator"), f"{field}.sourceLocator", 500
                ),
                "sourceRevision": _sha256(
                    raw.get("sourceRevision"), f"{field}.sourceRevision"
                ),
                "evidenceClass": _identifier(
                    raw.get("evidenceClass"), f"{field}.evidenceClass"
                ),
                "authority": authority,
                "reviewStatus": review_status,
                "synthetic": synthetic,
            }
        )
    ids = [item["evidenceId"] for item in result]
    if len(ids) != len(set(ids)):
        raise FacilityPlanningPackageError(
            "facility_planning_evidence_duplicate",
            "Evidence IDs must be unique within one package.",
        )
    return sorted(result, key=lambda item: item["evidenceId"])


def _canonical_authority(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "authority")
    _closed(
        raw,
        {
            "knowledgeStatus",
            "authority",
            "reviewStatus",
            "productionEligible",
            "planningClaim",
            "reviewReceiptId",
        },
        "authority",
    )
    knowledge = str(raw.get("knowledgeStatus") or "")
    authority = str(raw.get("authority") or "")
    review = str(raw.get("reviewStatus") or "")
    claim = str(raw.get("planningClaim") or "")
    production = raw.get("productionEligible")
    if (
        knowledge not in _EVIDENCE_STATUSES
        or authority not in _AUTHORITIES
        or review not in _REVIEW_STATUSES
        or claim not in _PLANNING_CLAIMS
        or not isinstance(production, bool)
    ):
        raise FacilityPlanningPackageError(
            "facility_planning_authority_invalid",
            "Facility planning authority fields are invalid.",
        )
    receipt_id = _optional_text(raw.get("reviewReceiptId"), "authority.reviewReceiptId", 160)
    if production and (
        authority != "controlled"
        or review != "confirmed"
        or claim != "production_realistic"
        or receipt_id is None
    ):
        raise FacilityPlanningPackageError(
            "facility_planning_production_authority_missing",
            "Production eligibility requires controlled evidence and an explicit review receipt.",
        )
    if authority == "illustrative" and (production or review == "confirmed"):
        raise FacilityPlanningPackageError(
            "facility_planning_illustrative_promotion_forbidden",
            "Illustrative planning knowledge cannot be confirmed or production eligible.",
        )
    return {
        "knowledgeStatus": knowledge,
        "authority": authority,
        "reviewStatus": review,
        "productionEligible": production,
        "planningClaim": claim,
        "reviewReceiptId": receipt_id,
    }


def _canonical_catalog_identity(value: Any, field: str) -> dict[str, str]:
    raw = _mapping(value, field)
    _closed(raw, {"assetId", "assetDefinitionRevision", "displayName"}, field)
    return {
        "assetId": _identifier(raw.get("assetId"), f"{field}.assetId"),
        "assetDefinitionRevision": _sha256(
            raw.get("assetDefinitionRevision"), f"{field}.assetDefinitionRevision"
        ),
        "displayName": _text(raw.get("displayName"), f"{field}.displayName"),
    }


def _canonical_envelope(value: Any, evidence_ids: set[str]) -> dict[str, Any]:
    raw = _mapping(value, "facilityEnvelope")
    _closed(
        raw,
        {"width", "depth", "sourceUnit", "displayName", "gridSize", "evidenceRefs"},
        "facilityEnvelope",
    )
    unit = str(raw.get("sourceUnit") or "")
    if unit not in _UNITS:
        raise FacilityPlanningPackageError(
            "facility_planning_unit_invalid", "Facility envelope unit is invalid."
        )
    grid = raw.get("gridSize")
    return {
        "width": _positive_number(raw.get("width"), "facilityEnvelope.width"),
        "depth": _positive_number(raw.get("depth"), "facilityEnvelope.depth"),
        "sourceUnit": unit,
        "displayName": _text(raw.get("displayName"), "facilityEnvelope.displayName"),
        "gridSize": (
            None
            if grid is None
            else _positive_number(grid, "facilityEnvelope.gridSize")
        ),
        "evidenceRefs": _evidence_refs(
            raw.get("evidenceRefs", []), "facilityEnvelope.evidenceRefs", evidence_ids
        ),
    }


def _canonical_process_steps(value: Any, evidence_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(
        _array(value, "processSteps", FACILITY_PLANNING_MAX_PROCESS_STEPS)
    ):
        field = f"processSteps[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "processStepId",
                "label",
                "predecessorProcessStepIds",
                "departmentId",
                "stationRef",
                "materialAndWipClasses",
                "evidenceRefs",
            },
            field,
        )
        result.append(
            {
                "processStepId": _identifier(
                    raw.get("processStepId"), f"{field}.processStepId"
                ),
                "label": _text(raw.get("label"), f"{field}.label"),
                "predecessorProcessStepIds": _refs(
                    raw.get("predecessorProcessStepIds", []),
                    f"{field}.predecessorProcessStepIds",
                ),
                "departmentId": _identifier(
                    raw.get("departmentId"), f"{field}.departmentId"
                ),
                "stationRef": _identifier(raw.get("stationRef"), f"{field}.stationRef"),
                "materialAndWipClasses": _refs(
                    raw.get("materialAndWipClasses", []),
                    f"{field}.materialAndWipClasses",
                ),
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["processStepId"] for item in result]
    if len(ids) != len(set(ids)):
        raise FacilityPlanningPackageError(
            "facility_planning_process_duplicate", "Process-step IDs must be unique."
        )
    known = set(ids)
    for item in result:
        unknown = sorted(set(item["predecessorProcessStepIds"]) - known)
        if unknown:
            raise FacilityPlanningPackageError(
                "facility_planning_process_predecessor_unknown",
                "Process predecessors must exist in the same package.",
                details={"processStepId": item["processStepId"], "unknown": unknown},
            )
    pending = {item["processStepId"]: set(item["predecessorProcessStepIds"]) for item in result}
    resolved: set[str] = set()
    while pending:
        ready = sorted(key for key, refs in pending.items() if refs <= resolved)
        if not ready:
            raise FacilityPlanningPackageError(
                "facility_planning_process_cycle",
                "Process-step precedence contains a cycle.",
            )
        for key in ready:
            resolved.add(key)
            del pending[key]
    return result


def _canonical_departments(
    value: Any, evidence_ids: set[str], process_ids: set[str]
) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(
        _array(value, "departments", FACILITY_PLANNING_MAX_DEPARTMENTS)
    ):
        field = f"departments[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "departmentId",
                "label",
                "zoneType",
                "areaShare",
                "row",
                "processStepRefs",
                "evidenceRefs",
            },
            field,
        )
        row = raw.get("row")
        if isinstance(row, bool) or not isinstance(row, int) or row < 1:
            raise FacilityPlanningPackageError(
                "facility_planning_department_row_invalid",
                f"{field}.row must be a positive integer.",
            )
        process_refs = _refs(raw.get("processStepRefs", []), f"{field}.processStepRefs")
        unknown = sorted(set(process_refs) - process_ids)
        if unknown:
            raise FacilityPlanningPackageError(
                "facility_planning_process_reference_unknown",
                "A department references an unknown process step.",
                details={"departmentId": raw.get("departmentId"), "unknown": unknown},
            )
        result.append(
            {
                "departmentId": _identifier(
                    raw.get("departmentId"), f"{field}.departmentId"
                ),
                "label": _text(raw.get("label"), f"{field}.label"),
                "zoneType": _identifier(raw.get("zoneType"), f"{field}.zoneType"),
                "areaShare": _positive_number(raw.get("areaShare"), f"{field}.areaShare"),
                "row": row,
                "processStepRefs": process_refs,
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["departmentId"] for item in result]
    labels = [item["label"].casefold() for item in result]
    if len(ids) != len(set(ids)) or len(labels) != len(set(labels)):
        raise FacilityPlanningPackageError(
            "facility_planning_department_duplicate",
            "Department IDs and labels must be unique.",
        )
    share = sum(item["areaShare"] for item in result)
    if abs(share - 1.0) > 1e-9:
        raise FacilityPlanningPackageError(
            "facility_planning_department_share_invalid",
            "Department area shares must total exactly 1.0.",
            details={"actual": share},
        )
    return result


def _canonical_area_groups(
    value: Any, evidence_ids: set[str], department_ids: set[str]
) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_array(value, "areaGroups", 100)):
        field = f"areaGroups[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "areaGroupId",
                "parentDepartmentId",
                "labels",
                "zoneTypes",
                "proportions",
                "arrangement",
                "orientation",
                "rows",
                "evidenceRefs",
            },
            field,
        )
        parent = _identifier(
            raw.get("parentDepartmentId"), f"{field}.parentDepartmentId"
        )
        if parent not in department_ids:
            raise FacilityPlanningPackageError(
                "facility_planning_parent_department_unknown",
                "An area group references an unknown parent department.",
                details={"parentDepartmentId": parent},
            )
        labels = [_text(item, f"{field}.labels") for item in _array(raw.get("labels"), f"{field}.labels", 50)]
        zone_types = [
            _identifier(item, f"{field}.zoneTypes")
            for item in _array(raw.get("zoneTypes"), f"{field}.zoneTypes", 50)
        ]
        proportions = [
            _positive_number(item, f"{field}.proportions")
            for item in _array(raw.get("proportions"), f"{field}.proportions", 50)
        ]
        if (
            not labels
            or len(labels) != len(proportions)
            or len(labels) != len(zone_types)
            or any(item not in G1_ZONE_TYPES for item in zone_types)
            or abs(sum(proportions) - 1.0) > 1e-9
        ):
            raise FacilityPlanningPackageError(
                "facility_planning_area_group_invalid",
                "Area-group labels, supported zone types, and proportions must align; proportions must total 1.0.",
                details={"areaGroupId": raw.get("areaGroupId")},
            )
        rows = deepcopy(_array(raw.get("rows", []), f"{field}.rows", 50))
        result.append(
            {
                "areaGroupId": _identifier(raw.get("areaGroupId"), f"{field}.areaGroupId"),
                "parentDepartmentId": parent,
                "labels": labels,
                "zoneTypes": zone_types,
                "proportions": proportions,
                "arrangement": _identifier(raw.get("arrangement"), f"{field}.arrangement"),
                "orientation": _identifier(raw.get("orientation"), f"{field}.orientation"),
                "rows": rows,
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["areaGroupId"] for item in result]
    child_labels = [label.casefold() for item in result for label in item["labels"]]
    if len(ids) != len(set(ids)) or len(child_labels) != len(set(child_labels)):
        raise FacilityPlanningPackageError(
            "facility_planning_area_group_duplicate",
            "Area-group IDs and child labels must be unique.",
        )
    return result


def _canonical_equipment(
    value: Any,
    evidence_ids: set[str],
    process_ids: set[str],
    area_labels: set[str],
) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(
        _array(
            value,
            "equipmentRequirements",
            FACILITY_PLANNING_MAX_EQUIPMENT_REQUIREMENTS,
        )
    ):
        field = f"equipmentRequirements[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "requirementId",
                "selectedCatalogIdentity",
                "catalogCandidates",
                "quantity",
                "targetArea",
                "targetAreaKnown",
                "placementPattern",
                "semanticOrientation",
                "resourceRole",
                "authoredSpacing",
                "processStepRefs",
                "placementDependencies",
                "evidenceRefs",
            },
            field,
        )
        selected = raw.get("selectedCatalogIdentity")
        candidates = [
            _canonical_catalog_identity(candidate, f"{field}.catalogCandidates[{candidate_index}]")
            for candidate_index, candidate in enumerate(
                _array(raw.get("catalogCandidates", []), f"{field}.catalogCandidates", 20)
            )
        ]
        selected_identity = (
            None
            if selected is None
            else _canonical_catalog_identity(selected, f"{field}.selectedCatalogIdentity")
        )
        quantity = raw.get("quantity")
        if quantity is not None and (
            isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1
        ):
            raise FacilityPlanningPackageError(
                "facility_planning_equipment_quantity_invalid",
                f"{field}.quantity must be a positive integer or null.",
            )
        target = _text(raw.get("targetArea"), f"{field}.targetArea")
        process_refs = _refs(raw.get("processStepRefs", []), f"{field}.processStepRefs")
        unknown_process = sorted(set(process_refs) - process_ids)
        if unknown_process:
            raise FacilityPlanningPackageError(
                "facility_planning_process_reference_unknown",
                "An equipment requirement references an unknown process step.",
                details={"requirementId": raw.get("requirementId"), "unknown": unknown_process},
            )
        spacing = raw.get("authoredSpacing")
        if spacing is not None:
            spacing = _mapping(spacing, f"{field}.authoredSpacing")
            _closed(spacing, {"value", "unit", "evidenceRef"}, f"{field}.authoredSpacing")
            if spacing.get("unit") not in _UNITS:
                raise FacilityPlanningPackageError(
                    "facility_planning_unit_invalid", "Equipment spacing unit is invalid."
                )
            spacing = {
                "value": _positive_number(
                    spacing.get("value"), f"{field}.authoredSpacing.value", allow_zero=True
                ),
                "unit": spacing["unit"],
                "evidenceRef": next(
                    iter(
                        _evidence_refs(
                            [spacing.get("evidenceRef")],
                            f"{field}.authoredSpacing.evidenceRef",
                            evidence_ids,
                        )
                    )
                ),
            }
        result.append(
            {
                "requirementId": _identifier(
                    raw.get("requirementId"), f"{field}.requirementId"
                ),
                "selectedCatalogIdentity": selected_identity,
                "catalogCandidates": candidates,
                "quantity": quantity,
                "targetArea": target,
                "targetAreaKnown": target.casefold() in area_labels,
                "placementPattern": _optional_text(
                    raw.get("placementPattern"), f"{field}.placementPattern", 160
                ),
                "semanticOrientation": _identifier(
                    raw.get("semanticOrientation"), f"{field}.semanticOrientation"
                ),
                "resourceRole": _identifier(raw.get("resourceRole"), f"{field}.resourceRole"),
                "authoredSpacing": spacing,
                "processStepRefs": process_refs,
                "placementDependencies": _refs(
                    raw.get("placementDependencies", []),
                    f"{field}.placementDependencies",
                ),
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["requirementId"] for item in result]
    if len(ids) != len(set(ids)):
        raise FacilityPlanningPackageError(
            "facility_planning_equipment_duplicate",
            "Equipment requirement IDs must be unique.",
        )
    known = set(ids)
    for item in result:
        unknown = sorted(set(item["placementDependencies"]) - known)
        if unknown:
            raise FacilityPlanningPackageError(
                "facility_planning_equipment_dependency_unknown",
                "Equipment dependencies must reference another requirement.",
                details={"requirementId": item["requirementId"], "unknown": unknown},
            )
    return result


def _canonical_routes(
    value: Any, evidence_ids: set[str], process_ids: set[str], area_labels: set[str]
) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_array(value, "routes", 200)):
        field = f"routes[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {
                "routeId",
                "scope",
                "label",
                "routeKind",
                "width",
                "sourceUnit",
                "sourceArea",
                "targetArea",
                "viaAreas",
                "direction",
                "processStepRefs",
                "evidenceRefs",
                "areasKnown",
                "processRefsKnown",
            },
            field,
        )
        source = _text(raw.get("sourceArea"), f"{field}.sourceArea")
        target = _text(raw.get("targetArea"), f"{field}.targetArea")
        via = [_text(item, f"{field}.viaAreas") for item in _array(raw.get("viaAreas", []), f"{field}.viaAreas", 50)]
        process_refs = _refs(raw.get("processStepRefs", []), f"{field}.processStepRefs")
        unit = str(raw.get("sourceUnit") or "")
        if unit not in _UNITS:
            raise FacilityPlanningPackageError(
                "facility_planning_unit_invalid", f"{field}.sourceUnit is invalid."
            )
        result.append(
            {
                "routeId": _identifier(raw.get("routeId"), f"{field}.routeId"),
                "scope": _identifier(raw.get("scope"), f"{field}.scope"),
                "label": _text(raw.get("label"), f"{field}.label"),
                "routeKind": _identifier(raw.get("routeKind"), f"{field}.routeKind"),
                "width": (
                    None
                    if raw.get("width") is None
                    else _positive_number(raw.get("width"), f"{field}.width")
                ),
                "sourceUnit": unit,
                "sourceArea": source,
                "targetArea": target,
                "viaAreas": via,
                "areasKnown": all(
                    name.casefold() in area_labels for name in [source, target, *via]
                ),
                "direction": _identifier(raw.get("direction"), f"{field}.direction"),
                "processStepRefs": process_refs,
                "processRefsKnown": set(process_refs) <= process_ids,
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["routeId"] for item in result]
    if len(ids) != len(set(ids)):
        raise FacilityPlanningPackageError(
            "facility_planning_route_duplicate", "Route IDs must be unique."
        )
    return result


def _canonical_planning_inputs(value: Any, evidence_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_array(value, "planningInputs", 300)):
        field = f"planningInputs[{index}]"
        raw = _mapping(item, field)
        _closed(
            raw,
            {"inputId", "kind", "statement", "value", "unit", "subjectRefs", "evidenceRefs"},
            field,
        )
        result.append(
            {
                "inputId": _identifier(raw.get("inputId"), f"{field}.inputId"),
                "kind": _identifier(raw.get("kind"), f"{field}.kind"),
                "statement": _text(raw.get("statement"), f"{field}.statement", 500),
                "value": deepcopy(raw.get("value")),
                "unit": _optional_text(raw.get("unit"), f"{field}.unit", 40),
                "subjectRefs": _refs(raw.get("subjectRefs", []), f"{field}.subjectRefs"),
                "evidenceRefs": _evidence_refs(
                    raw.get("evidenceRefs", []), f"{field}.evidenceRefs", evidence_ids
                ),
            }
        )
    ids = [item["inputId"] for item in result]
    if len(ids) != len(set(ids)):
        raise FacilityPlanningPackageError(
            "facility_planning_input_duplicate", "Planning-input IDs must be unique."
        )
    return result


def canonicalize_facility_planning_package(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one revision-bound planning package without accepting geometry."""

    _reject_coordinates(value)
    raw = _mapping(value, "planning_package")
    _closed(
        raw,
        {
            "schemaVersion",
            "packageId",
            "displayName",
            "productRef",
            "sourcePackageRefs",
            "authority",
            "evidenceRegister",
            "facilityEnvelope",
            "planningInputs",
            "processSteps",
            "departments",
            "areaGroups",
            "equipmentRequirements",
            "routes",
            "cellRecipes",
            "moduleFamilies",
            "floorCommunication",
            "presentationIntent",
            "unresolvedFindings",
        },
        "planning_package",
    )
    if raw.get("schemaVersion") != FACILITY_PLANNING_PACKAGE_SCHEMA:
        raise FacilityPlanningPackageError(
            "facility_planning_schema_invalid", "Facility planning package schema is unsupported."
        )
    product = _mapping(raw.get("productRef"), "productRef")
    _closed(product, {"productId", "productRevision", "displayName"}, "productRef")
    source_refs = []
    for index, item in enumerate(_array(raw.get("sourcePackageRefs", []), "sourcePackageRefs", 50)):
        field = f"sourcePackageRefs[{index}]"
        source = _mapping(item, field)
        _closed(source, {"sourceId", "sourceRevision", "sourceType"}, field)
        source_refs.append(
            {
                "sourceId": _identifier(source.get("sourceId"), f"{field}.sourceId"),
                "sourceRevision": _sha256(source.get("sourceRevision"), f"{field}.sourceRevision"),
                "sourceType": _identifier(source.get("sourceType"), f"{field}.sourceType"),
            }
        )
    evidence = _canonical_evidence_register(raw.get("evidenceRegister"))
    evidence_ids = {item["evidenceId"] for item in evidence}
    process_steps = _canonical_process_steps(raw.get("processSteps"), evidence_ids)
    process_ids = {item["processStepId"] for item in process_steps}
    departments = _canonical_departments(raw.get("departments"), evidence_ids, process_ids)
    department_ids = {item["departmentId"] for item in departments}
    area_groups = _canonical_area_groups(raw.get("areaGroups"), evidence_ids, department_ids)
    area_labels = {item["label"].casefold() for item in departments}
    area_labels.update(label.casefold() for item in area_groups for label in item["labels"])
    equipment = _canonical_equipment(
        raw.get("equipmentRequirements"), evidence_ids, process_ids, area_labels
    )
    routes = _canonical_routes(raw.get("routes"), evidence_ids, process_ids, area_labels)
    inputs = _canonical_planning_inputs(raw.get("planningInputs"), evidence_ids)
    cell_recipes = deepcopy(_array(raw.get("cellRecipes", []), "cellRecipes", 24))
    module_families = deepcopy(_array(raw.get("moduleFamilies", []), "moduleFamilies", 24))
    floor_communication = deepcopy(
        _array(raw.get("floorCommunication", []), "floorCommunication", 100)
    )
    unresolved = deepcopy(_array(raw.get("unresolvedFindings", []), "unresolvedFindings", 200))
    result = {
        "schemaVersion": FACILITY_PLANNING_PACKAGE_SCHEMA,
        "packageId": _identifier(raw.get("packageId"), "packageId"),
        "displayName": _text(raw.get("displayName"), "displayName"),
        "productRef": {
            "productId": _identifier(product.get("productId"), "productRef.productId"),
            "productRevision": _sha256(
                product.get("productRevision"), "productRef.productRevision"
            ),
            "displayName": _text(product.get("displayName"), "productRef.displayName"),
        },
        "sourcePackageRefs": sorted(source_refs, key=lambda item: item["sourceId"]),
        "authority": _canonical_authority(raw.get("authority")),
        "evidenceRegister": evidence,
        "facilityEnvelope": _canonical_envelope(raw.get("facilityEnvelope"), evidence_ids),
        "planningInputs": inputs,
        "processSteps": process_steps,
        "departments": departments,
        "areaGroups": area_groups,
        "equipmentRequirements": equipment,
        "routes": routes,
        "cellRecipes": cell_recipes,
        "moduleFamilies": module_families,
        "floorCommunication": floor_communication,
        "presentationIntent": deepcopy(_mapping(raw.get("presentationIntent"), "presentationIntent")),
        "unresolvedFindings": unresolved,
    }
    _reject_coordinates(result)
    return result


def _finding(
    finding_id: str,
    code: str,
    issue: str,
    risk: str,
    required_action: str,
    *,
    blocking: bool,
    evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "findingId": finding_id,
        "code": code,
        "issue": issue,
        "risk": risk,
        "requiredAction": required_action,
        "releaseImpact": "blocking" if blocking else "prototype_only",
        "blocking": bool(blocking),
        "evidenceRefs": list(evidence_refs),
    }


def _catalog_index(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        ): item
        for item in asset_catalog
        if isinstance(item, Mapping)
        and item.get("assetId")
        and item.get("assetDefinitionRevision")
    }


def compile_facility_planning_package(
    package: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    trusted_review_receipt_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Compile planning knowledge into one bounded FacilityProgram plus provenance."""

    canonical = canonicalize_facility_planning_package(package)
    package_revision = _revision(canonical)
    authority = canonical["authority"]
    trusted_receipts = {str(item) for item in trusted_review_receipt_ids}
    if authority["productionEligible"] and authority["reviewReceiptId"] not in trusted_receipts:
        raise FacilityPlanningPackageError(
            "facility_planning_review_receipt_untrusted",
            "Production planning requires a trusted human review receipt.",
        )

    findings = []
    input_kinds = {item["kind"] for item in canonical["planningInputs"]}
    for missing in sorted(_REQUIRED_REALISM_INPUT_KINDS - input_kinds):
        findings.append(
            _finding(
                f"planning-input-{missing}",
                "facility_planning_realism_input_missing",
                f"The {missing.replace('_', ' ')} planning input is unavailable.",
                "planning_fidelity",
                "Provide revision-bound planning evidence before describing this as a realistic production plan.",
                blocking=authority["planningClaim"] == "production_realistic",
            )
        )
    catalog = _catalog_index(asset_catalog)
    resource_batches = []
    provenance = []
    requirement_ids = {item["requirementId"] for item in canonical["equipmentRequirements"]}
    for item in canonical["equipmentRequirements"]:
        requirement_id = item["requirementId"]
        identity = item["selectedCatalogIdentity"]
        if item["quantity"] is None:
            findings.append(
                _finding(
                    f"equipment-quantity-{requirement_id}",
                    "facility_planning_equipment_quantity_missing",
                    f"Equipment quantity is not established for {requirement_id}.",
                    "capacity_and_fit",
                    "Provide an authored quantity or the demand/cycle-time calculation that establishes it.",
                    blocking=True,
                    evidence_refs=item["evidenceRefs"],
                )
            )
            continue
        if identity is None:
            findings.append(
                _finding(
                    f"equipment-catalog-{requirement_id}",
                    "facility_planning_catalog_selection_missing",
                    f"No exact catalog identity is selected for {requirement_id}.",
                    "identity_and_fit",
                    "Select one revision-bound catalog candidate.",
                    blocking=True,
                    evidence_refs=item["evidenceRefs"],
                )
            )
            continue
        asset = catalog.get((identity["assetId"], identity["assetDefinitionRevision"]))
        if asset is None:
            findings.append(
                _finding(
                    f"equipment-revision-{requirement_id}",
                    "facility_planning_catalog_revision_unavailable",
                    f"The selected catalog revision for {requirement_id} is unavailable.",
                    "identity_and_fit",
                    "Restore the exact catalog revision or select another reviewed candidate.",
                    blocking=True,
                    evidence_refs=item["evidenceRefs"],
                )
            )
            continue
        if not item["targetAreaKnown"]:
            findings.append(
                _finding(
                    f"equipment-area-{requirement_id}",
                    "facility_planning_target_area_unknown",
                    f"Target area {item['targetArea']} is not defined by this package.",
                    "layout_binding",
                    "Bind the requirement to a defined department or child area.",
                    blocking=True,
                    evidence_refs=item["evidenceRefs"],
                )
            )
            continue
        pattern = item["placementPattern"] or select_industrial_pattern(asset)
        if pattern not in INDUSTRIAL_PATTERN_IDS:
            findings.append(
                _finding(
                    f"equipment-pattern-{requirement_id}",
                    "facility_planning_pattern_unsupported",
                    f"Placement pattern {pattern} is not supported for {requirement_id}.",
                    "deterministic_placement",
                    "Select a supported deterministic industrial pattern.",
                    blocking=True,
                    evidence_refs=item["evidenceRefs"],
                )
            )
            continue
        resource_batches.append(
            {
                "batch_id": requirement_id,
                "exact_catalog_identity": {
                    "asset_id": identity["assetId"],
                    "asset_definition_revision": identity["assetDefinitionRevision"],
                    "display_name": identity["displayName"],
                },
                "quantity": item["quantity"],
                "target_area": item["targetArea"],
                "placement_pattern": pattern,
                "semantic_orientation": item["semanticOrientation"],
                "resource_role": item["resourceRole"],
                "authored_spacing": (
                    None
                    if item["authoredSpacing"] is None
                    else {
                        "value": item["authoredSpacing"]["value"],
                        "unit": item["authoredSpacing"]["unit"],
                        "evidence_ref": item["authoredSpacing"]["evidenceRef"],
                    }
                ),
                "ordering_or_grouping": None,
                "required_relationships": [],
                "placement_dependencies": list(item["placementDependencies"]),
                "evidence_refs": list(item["evidenceRefs"]),
                "reference_entity_ids": [],
            }
        )
        provenance.append(
            {
                "facilityEntityType": "resource_batch",
                "facilityEntityId": requirement_id,
                "planningInputs": list(item["processStepRefs"]),
                "evidenceRefs": list(item["evidenceRefs"]),
                "catalogIdentity": deepcopy(identity),
                "quantityAuthority": "package_exact_quantity",
                "patternAuthority": (
                    "package_authored" if item["placementPattern"] else "catalog_derived"
                ),
            }
        )
    unknown_dependencies = sorted(
        {
            dependency
            for item in resource_batches
            for dependency in item["placement_dependencies"]
            if dependency not in requirement_ids
        }
    )
    if unknown_dependencies:
        raise FacilityPlanningPackageError(
            "facility_planning_equipment_dependency_unknown",
            "Compiled equipment dependencies are not part of the package.",
            details={"unknown": unknown_dependencies},
        )

    for route in canonical["routes"]:
        if route["width"] is None:
            findings.append(
                _finding(
                    f"route-width-{route['routeId']}",
                    "facility_planning_route_width_missing",
                    f"Route width is not established for {route['label']}.",
                    "route_geometry",
                    "Provide an exact authored route width and source.",
                    blocking=True,
                    evidence_refs=route["evidenceRefs"],
                )
            )
        if not route["areasKnown"]:
            findings.append(
                _finding(
                    f"route-area-{route['routeId']}",
                    "facility_planning_route_area_unknown",
                    f"Route {route['label']} references an undefined area.",
                    "route_binding",
                    "Bind every route endpoint and via area to this package.",
                    blocking=True,
                    evidence_refs=route["evidenceRefs"],
                )
            )
        if not route["processRefsKnown"]:
            findings.append(
                _finding(
                    f"route-process-{route['routeId']}",
                    "facility_planning_route_process_unknown",
                    f"Route {route['label']} references an undefined process step.",
                    "process_traceability",
                    "Bind the route only to process steps in this package.",
                    blocking=True,
                    evidence_refs=route["evidenceRefs"],
                )
            )

    for existing in canonical["unresolvedFindings"]:
        raw = _mapping(existing, "unresolvedFindings")
        findings.append(
            _finding(
                _identifier(raw.get("findingId"), "unresolvedFindings.findingId"),
                _identifier(raw.get("code"), "unresolvedFindings.code"),
                _text(raw.get("issue"), "unresolvedFindings.issue", 500),
                _identifier(raw.get("risk"), "unresolvedFindings.risk"),
                _text(raw.get("requiredAction"), "unresolvedFindings.requiredAction", 500),
                blocking=bool(raw.get("blocking")),
                evidence_refs=_refs(raw.get("evidenceRefs", []), "unresolvedFindings.evidenceRefs"),
            )
        )

    department_by_id = {item["departmentId"]: item for item in canonical["departments"]}
    rows = []
    for row_number in sorted({item["row"] for item in canonical["departments"]}):
        members = [item for item in canonical["departments"] if item["row"] == row_number]
        rows.append(
            {
                "labels": [item["label"] for item in members],
                "proportion": sum(item["areaShare"] for item in members),
            }
        )
    macro = {
        "count": len(canonical["departments"]),
        "labels": [item["label"] for item in canonical["departments"]],
        "proportions": [item["areaShare"] for item in canonical["departments"]],
        "arrangement": "row_stack",
        "orientation": "horizontal",
        "rows": rows,
    }
    area_hierarchy = []
    for item in canonical["areaGroups"]:
        parent = department_by_id[item["parentDepartmentId"]]
        area_hierarchy.append(
            {
                "parent_department": parent["label"],
                "count": len(item["labels"]),
                "labels": list(item["labels"]),
                "zone_types": list(item["zoneTypes"]),
                "zone_type_evidence_status": authority["knowledgeStatus"],
                "proportions": list(item["proportions"]),
                "arrangement": item["arrangement"],
                "orientation": item["orientation"],
                "rows": (
                    deepcopy(item["rows"])
                    if item["arrangement"] == "row_stack"
                    else None
                ),
            }
        )
        provenance.append(
            {
                "facilityEntityType": "area_group",
                "facilityEntityId": item["areaGroupId"],
                "planningInputs": [item["parentDepartmentId"]],
                "evidenceRefs": list(item["evidenceRefs"]),
            }
        )
    primary_routes = []
    local_routes = []
    for item in canonical["routes"]:
        if item["width"] is None or not item["areasKnown"] or not item["processRefsKnown"]:
            continue
        route = {
            "route_id": item["routeId"],
            "route_kind": item["routeKind"],
            "width": item["width"],
            "source_unit": item["sourceUnit"],
            "source_area": item["sourceArea"],
            "target_area": item["targetArea"],
            "via_areas": list(item["viaAreas"]),
            "direction": item["direction"],
            "label": item["label"],
            "clearance": None,
            "vehicle_profile_ref": None,
            "evidence_refs": list(item["evidenceRefs"]),
        }
        if item["scope"] == "primary":
            primary_routes.append(
                {
                    "route_kind": item["routeKind"],
                    "width": item["width"],
                    "source_unit": item["sourceUnit"],
                    "source_department": item["sourceArea"],
                    "target_department": item["targetArea"],
                    "via_departments": list(item["viaAreas"]),
                    "direction": item["direction"],
                    "label": item["label"],
                }
            )
        else:
            local_routes.append(route)
        provenance.append(
            {
                "facilityEntityType": "route",
                "facilityEntityId": item["routeId"],
                "planningInputs": list(item["processStepRefs"]),
                "evidenceRefs": list(item["evidenceRefs"]),
                "dimensionAuthority": "package_exact_dimension",
            }
        )

    blocking_findings = [item for item in findings if item["blocking"]]
    compiled_batch_ids = {item["batch_id"] for item in resource_batches}
    cell_recipes = [
        deepcopy(item)
        for item in canonical["cellRecipes"]
        if set(item.get("member_batches") or []) <= compiled_batch_ids
    ]
    compiled_recipe_ids = {str(item.get("recipe_id") or "") for item in cell_recipes}
    module_families = [
        deepcopy(item)
        for item in canonical["moduleFamilies"]
        if str(item.get("source_recipe_or_cell") or "") in compiled_recipe_ids
        or str(item.get("source_recipe_or_cell") or "").casefold()
        in {
            batch["target_area"].casefold()
            for batch in resource_batches
        }
    ]
    program_findings = [
        {
            "finding_id": item["findingId"],
            "code": item["code"],
            "issue": item["issue"],
            "risk": item["risk"],
            "required_action": item["requiredAction"],
            "release_impact": item["releaseImpact"],
            "evidence_refs": item["evidenceRefs"],
        }
        for item in blocking_findings
    ]
    program = canonicalize_facility_program(
        {
            "schema_version": FACILITY_PROGRAM_SCHEMA,
            "identity": {
                "program_id": f"facility-program-{package_revision[:24]}",
                "display_name": canonical["displayName"],
                "source_revision_refs": [package_revision],
            },
            "authority_and_mode": {
                "mode": "intent_driven_prototype",
                "evidence_status": authority["knowledgeStatus"],
                "review_status": authority["reviewStatus"],
                "production_eligible": authority["productionEligible"],
                "prototype_assumptions_allowed": authority["planningClaim"]
                == "illustrative_prototype",
            },
            "facility_envelope": {
                "width": canonical["facilityEnvelope"]["width"],
                "depth": canonical["facilityEnvelope"]["depth"],
                "source_unit": canonical["facilityEnvelope"]["sourceUnit"],
                "display_name": canonical["facilityEnvelope"]["displayName"],
                "grid_size": canonical["facilityEnvelope"]["gridSize"],
                "dimension_evidence_refs": canonical["facilityEnvelope"]["evidenceRefs"],
            },
            "macro_departments": [macro],
            "area_hierarchy": area_hierarchy,
            "flow_requirements": [],
            "route_network": {
                "primary_routes": primary_routes,
                "local_routes": local_routes,
            },
            "resource_batches": resource_batches,
            "cell_recipes": cell_recipes,
            "module_families": module_families,
            "floor_communication": deepcopy(canonical["floorCommunication"]),
            "presentation_intent": deepcopy(canonical["presentationIntent"]),
            "unresolved_requirements": program_findings,
            "reference_manifest_ref": None,
        }
    )
    for item in canonical["departments"]:
        provenance.append(
            {
                "facilityEntityType": "department",
                "facilityEntityId": item["departmentId"],
                "planningInputs": list(item["processStepRefs"]),
                "evidenceRefs": list(item["evidenceRefs"]),
                "areaShareAuthority": "package_exact_share",
            }
        )
    core = {
        "schemaVersion": FACILITY_PLANNING_COMPILE_SCHEMA,
        "planningPackageId": canonical["packageId"],
        "planningPackageRevision": package_revision,
        "facilityProgram": program,
        "provenance": sorted(
            provenance,
            key=lambda item: (item["facilityEntityType"], item["facilityEntityId"]),
        ),
        "findings": sorted(findings, key=lambda item: item["findingId"]),
        "blockingFindingCount": len(blocking_findings),
        "productionEligible": bool(authority["productionEligible"]),
    }
    core["compileRevision"] = _revision(core)
    return core


def analyze_facility_planning_impact(
    package: Mapping[str, Any], changed_process_step_ids: Sequence[str]
) -> dict[str, Any]:
    """Return the smallest revision-bound planning scope affected by process changes."""

    canonical = canonicalize_facility_planning_package(package)
    changed = {_identifier(item, "changed_process_step_ids") for item in changed_process_step_ids}
    known = {item["processStepId"] for item in canonical["processSteps"]}
    unknown = sorted(changed - known)
    if unknown:
        raise FacilityPlanningPackageError(
            "facility_planning_process_reference_unknown",
            "Impact analysis received an unknown process step.",
            details={"unknown": unknown},
        )
    affected = set(changed)
    while True:
        expanded = {
            item["processStepId"]
            for item in canonical["processSteps"]
            if set(item["predecessorProcessStepIds"]) & affected
        }
        if expanded <= affected:
            break
        affected.update(expanded)
    departments = sorted(
        item["departmentId"]
        for item in canonical["departments"]
        if set(item["processStepRefs"]) & affected
    )
    equipment = sorted(
        item["requirementId"]
        for item in canonical["equipmentRequirements"]
        if set(item["processStepRefs"]) & affected
    )
    routes = sorted(
        item["routeId"]
        for item in canonical["routes"]
        if set(item["processStepRefs"]) & affected
    )
    affected_area_labels = {
        item["label"].casefold()
        for item in canonical["departments"]
        if item["departmentId"] in departments
    }
    area_groups = sorted(
        item["areaGroupId"]
        for item in canonical["areaGroups"]
        if item["parentDepartmentId"] in departments
    )
    cell_recipes = sorted(
        str(item.get("recipe_id") or "")
        for item in canonical["cellRecipes"]
        if str(item.get("target_area") or "").casefold() in affected_area_labels
    )
    stage_ids = []
    if departments:
        stage_ids.extend(["macro_departments", "department_subdivisions"])
    if routes:
        stage_ids.extend(["primary_circulation", "floor_communication"])
    if equipment:
        stage_ids.extend(["department_resources", "seed_cells", "repeated_modules"])
    result = {
        "schemaVersion": FACILITY_PLANNING_IMPACT_SCHEMA,
        "planningPackageId": canonical["packageId"],
        "planningPackageRevision": _revision(canonical),
        "changedProcessStepIds": sorted(changed),
        "affectedProcessStepIds": sorted(affected),
        "affectedDepartmentIds": departments,
        "affectedAreaGroupIds": area_groups,
        "affectedEquipmentRequirementIds": equipment,
        "affectedRouteIds": routes,
        "affectedCellRecipeIds": [item for item in cell_recipes if item],
        "affectedStageIds": sorted(set(stage_ids)),
    }
    result["impactRevision"] = _revision(result)
    return result


def facility_planning_model_summary(compiled: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded Sage-facing summary without exposing authoritative geometry."""

    if not isinstance(compiled, Mapping) or compiled.get("schemaVersion") != FACILITY_PLANNING_COMPILE_SCHEMA:
        raise FacilityPlanningPackageError(
            "facility_planning_compile_invalid", "Facility planning compile result is invalid."
        )
    program = canonicalize_facility_program(compiled.get("facilityProgram"))
    result = {
        "planningPackageId": compiled.get("planningPackageId"),
        "planningPackageRevision": compiled.get("planningPackageRevision"),
        "facilityProgramId": program["identity"]["program_id"],
        "facilityProgramRevision": _revision(program),
        "displayName": program["identity"]["display_name"],
        "status": "blocked" if compiled.get("blockingFindingCount") else "prototype_ready",
        "productionEligible": bool(compiled.get("productionEligible")),
        "counts": {
            "departments": len(program["macro_departments"][0].get("labels", [])),
            "areaGroups": len(program["area_hierarchy"]),
            "resourceBatches": len(program["resource_batches"]),
            "requestedSourceAssets": sum(
                item["quantity"] for item in program["resource_batches"]
            ),
            "routes": sum(len(program["route_network"][key]) for key in ("primary_routes", "local_routes")),
            "cellRecipes": len(program["cell_recipes"]),
            "moduleFamilies": len(program["module_families"]),
            "findings": len(compiled.get("findings") or []),
            "blockingFindings": int(compiled.get("blockingFindingCount") or 0),
        },
        "claimBoundary": (
            "This is an unsaved prototype compiled from revision-bound planning inputs. "
            "It does not establish safety, capacity, throughput, compliance, or production release."
        ),
    }
    if len(canonical_facility_knowledge_bytes(result)) > FACILITY_PLANNING_TOOL_RESPONSE_BYTES:
        raise FacilityPlanningPackageError(
            "facility_planning_tool_response_too_large",
            "Facility planning summary exceeds the provider response budget.",
        )
    return result


__all__ = [
    "FACILITY_PLANNING_COMPILE_SCHEMA",
    "FACILITY_PLANNING_IMPACT_SCHEMA",
    "FACILITY_PLANNING_PACKAGE_SCHEMA",
    "FacilityPlanningPackageError",
    "analyze_facility_planning_impact",
    "canonicalize_facility_planning_package",
    "compile_facility_planning_package",
    "facility_planning_model_summary",
]
