"""Closed, coordinate-free contract for reference-quality Facility generation."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping, Sequence

from .full_factory import compile_full_factory_program
from .g1_planner import G1_ZONE_TYPES
from .knowledge_foundation import (
    canonical_facility_knowledge_bytes,
    facility_knowledge_revision,
)
from .industrial_patterns import select_industrial_pattern


FACILITY_PROGRAM_SCHEMA = "facility-program-v1"
FACILITY_PROGRAM_MODES = frozenset(
    {"reference_reproduction", "intent_driven_prototype", "edit_current_draft"}
)
FACILITY_PROGRAM_EVIDENCE_STATUSES = frozenset(
    {"authored", "derived", "inferred", "unknown"}
)
FACILITY_PROGRAM_REVIEW_STATUSES = frozenset(
    {"pending", "confirmed", "rejected"}
)
FACILITY_PROGRAM_MAX_RESOURCE_BATCHES = 160
FACILITY_PROGRAM_MAX_CELL_RECIPES = 24
FACILITY_PROGRAM_MAX_MODULE_FAMILIES = 24
FACILITY_PROGRAM_MAX_FLOOR_COMMUNICATION = 100
FACILITY_PROGRAM_MAX_TOTAL_ASSETS = 900
FACILITY_PROGRAM_TOOL_RESPONSE_BYTES = 16_384
FACILITY_PROGRAM_STAGE_SLICE_BYTES = 8_192

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNITS = frozenset({"m", "mm", "ft", "in"})
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


class FacilityProgramError(RuntimeError):
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


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must be an object.",
            details={"field": field},
        )
    return deepcopy(dict(value))


def _closed(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityProgramError(
            "facility_program_unknown_field",
            f"{field} contains unsupported fields.",
            details={"field": field, "unknown": unknown},
        )


def _array(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must be an array.",
            details={"field": field},
        )
    if len(value) > maximum:
        raise FacilityProgramError(
            "facility_program_budget_exceeded",
            f"{field} cannot contain more than {maximum} entries.",
            details={"field": field, "maximum": maximum, "actual": len(value)},
        )
    return deepcopy(value)


def _text(value: Any, field: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must be text.",
            details={"field": field},
        )
    result = re.sub(r"\s+", " ", value.strip())
    if not result or len(result) > maximum:
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must contain 1-{maximum} characters.",
            details={"field": field},
        )
    return result


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field)
    if _IDENTIFIER.fullmatch(result) is None:
        raise FacilityProgramError(
            "facility_program_identifier_invalid",
            f"{field} must be a stable identifier.",
            details={"field": field},
        )
    return result


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field)
    if _SHA256.fullmatch(result) is None:
        raise FacilityProgramError(
            "facility_program_revision_invalid",
            f"{field} must be a lowercase SHA-256 digest.",
            details={"field": field},
        )
    return result


def _number(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must be numeric.",
            details={"field": field},
        )
    result = float(value)
    if result < 0 if allow_zero else result <= 0:
        raise FacilityProgramError(
            "facility_program_invalid",
            f"{field} must be {'non-negative' if allow_zero else 'positive'}.",
            details={"field": field},
        )
    return result


def _refs(value: Any, field: str, *, maximum: int = 64) -> list[str]:
    values = _array(value, field, maximum)
    result = [_identifier(item, field) for item in values]
    if len(set(result)) != len(result):
        raise FacilityProgramError(
            "facility_program_duplicate_reference",
            f"{field} contains duplicate references.",
            details={"field": field},
        )
    return result


def _reject_coordinates(value: Any, field: str = "facility_program") -> None:
    if isinstance(value, Mapping):
        prohibited = sorted(str(key) for key in value if key in _COORDINATE_FIELDS)
        if prohibited:
            raise FacilityProgramError(
                "facility_program_model_geometry_forbidden",
                "FacilityProgram intent cannot contain authored coordinates or transforms.",
                details={"field": field, "prohibited": prohibited},
            )
        for key, child in value.items():
            _reject_coordinates(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_coordinates(child, f"{field}[{index}]")


def _canonical_authority(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "authority_and_mode")
    _closed(
        raw,
        {
            "mode",
            "evidence_status",
            "review_status",
            "production_eligible",
            "prototype_assumptions_allowed",
        },
        "authority_and_mode",
    )
    mode = str(raw.get("mode") or "")
    evidence = str(raw.get("evidence_status") or "")
    review = str(raw.get("review_status") or "")
    if mode not in FACILITY_PROGRAM_MODES:
        raise FacilityProgramError("facility_program_mode_invalid", "FacilityProgram mode is invalid.")
    if evidence not in FACILITY_PROGRAM_EVIDENCE_STATUSES:
        raise FacilityProgramError(
            "facility_program_authority_invalid", "FacilityProgram evidence status is invalid."
        )
    if review not in FACILITY_PROGRAM_REVIEW_STATUSES:
        raise FacilityProgramError(
            "facility_program_review_invalid", "FacilityProgram review status is invalid."
        )
    production = raw.get("production_eligible")
    assumptions = raw.get("prototype_assumptions_allowed")
    if not isinstance(production, bool) or not isinstance(assumptions, bool):
        raise FacilityProgramError(
            "facility_program_authority_invalid",
            "FacilityProgram authority flags must be boolean.",
        )
    if mode != "reference_reproduction" and production and review != "confirmed":
        raise FacilityProgramError(
            "facility_program_authority_invalid",
            "An unreviewed program cannot be production eligible.",
        )
    return {
        "mode": mode,
        "evidence_status": evidence,
        "review_status": review,
        "production_eligible": production,
        "prototype_assumptions_allowed": assumptions,
    }


def _canonical_envelope(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "facility_envelope")
    _closed(
        raw,
        {
            "width",
            "depth",
            "source_unit",
            "display_name",
            "grid_size",
            "dimension_evidence_refs",
        },
        "facility_envelope",
    )
    unit = str(raw.get("source_unit") or "")
    if unit not in _UNITS:
        raise FacilityProgramError("facility_program_unit_invalid", "Envelope unit is invalid.")
    grid = raw.get("grid_size")
    return {
        "width": _number(raw.get("width"), "facility_envelope.width"),
        "depth": _number(raw.get("depth"), "facility_envelope.depth"),
        "source_unit": unit,
        "display_name": _text(raw.get("display_name"), "facility_envelope.display_name"),
        "grid_size": (
            None
            if grid is None
            else _number(grid, "facility_envelope.grid_size")
        ),
        "dimension_evidence_refs": _refs(
            raw.get("dimension_evidence_refs", []),
            "facility_envelope.dimension_evidence_refs",
        ),
    }


def _canonical_catalog_identity(value: Any, field: str) -> dict[str, str]:
    raw = _mapping(value, field)
    _closed(raw, {"asset_id", "asset_definition_revision", "display_name"}, field)
    return {
        "asset_id": _identifier(raw.get("asset_id"), f"{field}.asset_id"),
        "asset_definition_revision": _sha256(
            raw.get("asset_definition_revision"),
            f"{field}.asset_definition_revision",
        ),
        "display_name": _text(raw.get("display_name"), f"{field}.display_name"),
    }


def _canonical_resource_batch(value: Any, index: int) -> dict[str, Any]:
    field = f"resource_batches[{index}]"
    raw = _mapping(value, field)
    _closed(
        raw,
        {
            "batch_id",
            "exact_catalog_identity",
            "quantity",
            "target_area",
            "placement_pattern",
            "semantic_orientation",
            "resource_role",
            "authored_spacing",
            "ordering_or_grouping",
            "required_relationships",
            "placement_dependencies",
            "evidence_refs",
            "reference_entity_ids",
        },
        field,
    )
    quantity = raw.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise FacilityProgramError(
            "facility_program_quantity_invalid", f"{field}.quantity must be a positive integer."
        )
    spacing_raw = raw.get("authored_spacing")
    spacing = None
    if spacing_raw is not None:
        spacing_value = _mapping(spacing_raw, f"{field}.authored_spacing")
        _closed(spacing_value, {"value", "unit", "evidence_ref"}, f"{field}.authored_spacing")
        if spacing_value.get("unit") not in _UNITS:
            raise FacilityProgramError(
                "facility_program_unit_invalid", f"{field}.authored_spacing unit is invalid."
            )
        spacing = {
            "value": _number(
                spacing_value.get("value"),
                f"{field}.authored_spacing.value",
                allow_zero=True,
            ),
            "unit": spacing_value["unit"],
            "evidence_ref": _identifier(
                spacing_value.get("evidence_ref"),
                f"{field}.authored_spacing.evidence_ref",
            ),
        }
    relationships = _array(raw.get("required_relationships", []), f"{field}.required_relationships", 64)
    normalized_relationships = []
    for rel_index, item in enumerate(relationships):
        rel_field = f"{field}.required_relationships[{rel_index}]"
        relation = _mapping(item, rel_field)
        _closed(relation, {"kind", "target_batch_id", "evidence_ref"}, rel_field)
        normalized_relationships.append(
            {
                "kind": _identifier(relation.get("kind"), f"{rel_field}.kind"),
                "target_batch_id": _identifier(
                    relation.get("target_batch_id"), f"{rel_field}.target_batch_id"
                ),
                "evidence_ref": _identifier(
                    relation.get("evidence_ref"), f"{rel_field}.evidence_ref"
                ),
            }
        )
    return {
        "batch_id": _identifier(raw.get("batch_id"), f"{field}.batch_id"),
        "exact_catalog_identity": _canonical_catalog_identity(
            raw.get("exact_catalog_identity"), f"{field}.exact_catalog_identity"
        ),
        "quantity": quantity,
        "target_area": _text(raw.get("target_area"), f"{field}.target_area"),
        "placement_pattern": _identifier(
            raw.get("placement_pattern"), f"{field}.placement_pattern"
        ),
        "semantic_orientation": _identifier(
            raw.get("semantic_orientation"), f"{field}.semantic_orientation"
        ),
        "resource_role": _identifier(raw.get("resource_role"), f"{field}.resource_role"),
        "authored_spacing": spacing,
        "ordering_or_grouping": (
            None
            if raw.get("ordering_or_grouping") is None
            else _identifier(raw.get("ordering_or_grouping"), f"{field}.ordering_or_grouping")
        ),
        "required_relationships": normalized_relationships,
        "placement_dependencies": _refs(
            raw.get("placement_dependencies", []), f"{field}.placement_dependencies"
        ),
        "evidence_refs": _refs(raw.get("evidence_refs", []), f"{field}.evidence_refs"),
        "reference_entity_ids": _refs(
            raw.get("reference_entity_ids", []),
            f"{field}.reference_entity_ids",
            maximum=FACILITY_PROGRAM_MAX_TOTAL_ASSETS,
        ),
    }


def _canonical_cell_recipe(value: Any, index: int) -> dict[str, Any]:
    field = f"cell_recipes[{index}]"
    raw = _mapping(value, field)
    _closed(
        raw,
        {
            "recipe_id",
            "target_area",
            "member_batches",
            "candidate_strategies",
            "selected_strategy_or_objective",
            "authored_spacing",
            "process_order",
            "interfaces",
            "evidence_refs",
        },
        field,
    )
    strategies = _refs(raw.get("candidate_strategies", []), f"{field}.candidate_strategies")
    if not strategies:
        raise FacilityProgramError(
            "facility_program_cell_strategy_invalid", f"{field} needs a candidate strategy."
        )
    return {
        "recipe_id": _identifier(raw.get("recipe_id"), f"{field}.recipe_id"),
        "target_area": _text(raw.get("target_area"), f"{field}.target_area"),
        "member_batches": _refs(raw.get("member_batches", []), f"{field}.member_batches"),
        "candidate_strategies": strategies,
        "selected_strategy_or_objective": _identifier(
            raw.get("selected_strategy_or_objective"),
            f"{field}.selected_strategy_or_objective",
        ),
        "authored_spacing": deepcopy(raw.get("authored_spacing")),
        "process_order": _refs(raw.get("process_order", []), f"{field}.process_order"),
        "interfaces": deepcopy(_array(raw.get("interfaces", []), f"{field}.interfaces", 64)),
        "evidence_refs": _refs(raw.get("evidence_refs", []), f"{field}.evidence_refs"),
    }


def _canonical_module_family(value: Any, index: int) -> dict[str, Any]:
    field = f"module_families[{index}]"
    raw = _mapping(value, field)
    _closed(
        raw,
        {
            "family_id",
            "source_recipe_or_cell",
            "target_areas",
            "allowed_transform_mode",
            "preserve_source",
            "conformance_requirements",
            "composable_with",
            "evidence_refs",
        },
        field,
    )
    preserve = raw.get("preserve_source")
    if not isinstance(preserve, bool):
        raise FacilityProgramError(
            "facility_program_module_invalid", f"{field}.preserve_source must be boolean."
        )
    transform_mode = str(raw.get("allowed_transform_mode") or "")
    if transform_mode != "translate_exact":
        raise FacilityProgramError(
            "facility_program_module_transform_unsupported",
            "Initial module-family scope supports exact translation only.",
        )
    return {
        "family_id": _identifier(raw.get("family_id"), f"{field}.family_id"),
        "source_recipe_or_cell": _text(
            raw.get("source_recipe_or_cell"), f"{field}.source_recipe_or_cell"
        ),
        "target_areas": [
            _text(item, f"{field}.target_areas")
            for item in _array(
                raw.get("target_areas", []), f"{field}.target_areas", 100
            )
        ],
        "allowed_transform_mode": transform_mode,
        "preserve_source": preserve,
        "conformance_requirements": _refs(
            raw.get("conformance_requirements", []),
            f"{field}.conformance_requirements",
        ),
        "composable_with": _refs(raw.get("composable_with", []), f"{field}.composable_with"),
        "evidence_refs": _refs(raw.get("evidence_refs", []), f"{field}.evidence_refs"),
    }


def _closed_records(
    value: Any,
    field: str,
    maximum: int,
    variants: Sequence[set[str]],
) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(_array(value, field, maximum)):
        record_field = f"{field}[{index}]"
        record = _mapping(item, record_field)
        matching = [allowed for allowed in variants if set(record) <= allowed]
        if not matching:
            supported = sorted(set().union(*variants))
            unknown = sorted(set(record) - set(supported))
            raise FacilityProgramError(
                "facility_program_unknown_field",
                f"{record_field} contains unsupported fields.",
                details={"field": record_field, "unknown": unknown},
            )
        result.append(record)
    return result


def _canonical_macro_departments(value: Any) -> list[dict[str, Any]]:
    records = _closed_records(
        value,
        "macro_departments",
        50,
        (
            {"count", "labels", "proportions", "arrangement", "orientation", "rows"},
            {
                "department_id",
                "label",
                "zone_type",
                "reference_entity_id",
                "evidence_refs",
            },
        ),
    )
    for index, record in enumerate(records):
        rows = record.get("rows")
        if rows is not None:
            for row_index, row in enumerate(_array(rows, f"macro_departments[{index}].rows", 50)):
                _closed(
                    _mapping(row, f"macro_departments[{index}].rows[{row_index}]"),
                    {"labels", "proportion"},
                    f"macro_departments[{index}].rows[{row_index}]",
                )
    return records


def _canonical_area_hierarchy(value: Any) -> list[dict[str, Any]]:
    records = _closed_records(
        value,
        "area_hierarchy",
        200,
        (
            {
                "parent_department",
                "count",
                "labels",
                "zone_types",
                "zone_type_evidence_status",
                "proportions",
                "arrangement",
                "orientation",
                "rows",
            },
            {
                "parent_area",
                "child_area",
                "reference_entity_id",
                "evidence_refs",
            },
        ),
    )
    for index, record in enumerate(records):
        labels = record.get("labels")
        zone_types = record.get("zone_types")
        if zone_types is not None:
            values = _array(zone_types, f"area_hierarchy[{index}].zone_types", 50)
            if not isinstance(labels, list) or len(values) != len(labels):
                raise FacilityProgramError(
                    "facility_program_area_zone_types_invalid",
                    "Area-hierarchy zone types must align one-for-one with child labels.",
                )
            normalized_types = [
                _identifier(item, f"area_hierarchy[{index}].zone_types")
                for item in values
            ]
            if any(item not in G1_ZONE_TYPES for item in normalized_types):
                raise FacilityProgramError(
                    "facility_program_area_zone_types_invalid",
                    "Area-hierarchy zone types must use the Facility Layout vocabulary.",
                )
            record["zone_types"] = normalized_types
        evidence_status = record.get("zone_type_evidence_status")
        if evidence_status is not None and evidence_status not in FACILITY_PROGRAM_EVIDENCE_STATUSES:
            raise FacilityProgramError(
                "facility_program_area_zone_type_authority_invalid",
                "Area-hierarchy zone-type evidence status is invalid.",
            )
        rows = record.get("rows")
        if rows is not None:
            for row_index, row in enumerate(_array(rows, f"area_hierarchy[{index}].rows", 50)):
                _closed(
                    _mapping(row, f"area_hierarchy[{index}].rows[{row_index}]"),
                    {"labels", "proportion"},
                    f"area_hierarchy[{index}].rows[{row_index}]",
                )
    return records


def _canonical_route_network(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "route_network")
    _closed(raw, {"primary_routes", "local_routes"}, "route_network")
    variants = (
        {
            "route_kind",
            "width",
            "source_unit",
            "source_department",
            "target_department",
            "via_departments",
            "direction",
            "label",
        },
        {
            "route_id",
            "label",
            "route_kind",
            "width",
            "dimension_authority",
            "reference_entity_id",
            "evidence_refs",
        },
        {
            "route_id",
            "route_kind",
            "width",
            "source_unit",
            "source_area",
            "target_area",
            "via_areas",
            "direction",
            "label",
            "clearance",
            "vehicle_profile_ref",
            "evidence_refs",
        },
    )
    return {
        "primary_routes": _closed_records(
            raw.get("primary_routes", []), "route_network.primary_routes", 100, variants
        ),
        "local_routes": _closed_records(
            raw.get("local_routes", []), "route_network.local_routes", 200, variants
        ),
    }


def _canonical_floor_communication(value: Any) -> list[dict[str, Any]]:
    records = _closed_records(
        value,
        "floor_communication",
        FACILITY_PROGRAM_MAX_FLOOR_COMMUNICATION,
        (
            {"route_labels", "width", "depth", "source_unit", "label"},
            {
                "communication_id",
                "marking_type",
                "pattern",
                "reference_entity_ids",
                "dimension_authority",
                "evidence_refs",
            },
            {
                "communication_id",
                "marking_type",
                "label",
                "anchor_relationship",
                "count",
                "rows",
                "columns",
                "pitch",
                "semantic_orientation",
                "width",
                "depth",
                "source_unit",
                "dimension_evidence_refs",
            },
        ),
    )
    for index, record in enumerate(records):
        if "anchor_relationship" not in record:
            continue
        anchor = _mapping(
            record.get("anchor_relationship"),
            f"floor_communication[{index}].anchor_relationship",
        )
        _closed(
            anchor,
            {"kind", "target_area", "route_label", "placement_id"},
            f"floor_communication[{index}].anchor_relationship",
        )
        pitch = _mapping(
            record.get("pitch"), f"floor_communication[{index}].pitch"
        )
        _closed(
            pitch,
            {"along", "across"},
            f"floor_communication[{index}].pitch",
        )
    return records


def _canonical_presentation_intent(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "presentation_intent")
    _closed(
        raw,
        {
            "fit_to_occupied_content",
            "semantic_zoom",
            "overview_label_priority",
            "plan_layers",
            "three_d_layers",
        },
        "presentation_intent",
    )
    return raw


def _canonical_unresolved(value: Any) -> list[dict[str, Any]]:
    return _closed_records(
        value,
        "unresolved_requirements",
        200,
        (
            {
                "finding_id",
                "code",
                "issue",
                "risk",
                "required_action",
                "release_impact",
                "evidence_refs",
            },
            {
                "code",
                "placementId",
                "zoneId",
                "candidateTargetZoneIds",
                "candidateParentZoneIds",
                "assetId",
                "assetDefinitionRevision",
                "supportPlacementId",
                "leftPlacementId",
                "rightPlacementId",
            },
        ),
    )


def canonicalize_facility_program(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one resolved program and reject model-authored geometry."""

    _reject_coordinates(value)
    raw = _mapping(value, "facility_program")
    _closed(
        raw,
        {
            "schema_version",
            "identity",
            "authority_and_mode",
            "facility_envelope",
            "macro_departments",
            "area_hierarchy",
            "flow_requirements",
            "route_network",
            "resource_batches",
            "cell_recipes",
            "module_families",
            "floor_communication",
            "presentation_intent",
            "unresolved_requirements",
            "reference_manifest_ref",
        },
        "facility_program",
    )
    if raw.get("schema_version") != FACILITY_PROGRAM_SCHEMA:
        raise FacilityProgramError(
            "facility_program_schema_invalid", "FacilityProgram schema version is unsupported."
        )
    identity = _mapping(raw.get("identity"), "identity")
    _closed(identity, {"program_id", "display_name", "source_revision_refs"}, "identity")
    resources = [
        _canonical_resource_batch(item, index)
        for index, item in enumerate(
            _array(
                raw.get("resource_batches"),
                "resource_batches",
                FACILITY_PROGRAM_MAX_RESOURCE_BATCHES,
            )
        )
    ]
    total_assets = sum(item["quantity"] for item in resources)
    if total_assets > FACILITY_PROGRAM_MAX_TOTAL_ASSETS:
        raise FacilityProgramError(
            "facility_program_asset_budget_exceeded",
            f"FacilityProgram cannot request more than {FACILITY_PROGRAM_MAX_TOTAL_ASSETS} assets.",
            details={"actual": total_assets, "maximum": FACILITY_PROGRAM_MAX_TOTAL_ASSETS},
        )
    batch_ids = [item["batch_id"] for item in resources]
    if len(set(batch_ids)) != len(batch_ids):
        raise FacilityProgramError("facility_program_batch_duplicate", "Resource batch IDs must be unique.")
    batch_set = set(batch_ids)
    for item in resources:
        unknown = sorted(set(item["placement_dependencies"]) - batch_set)
        unknown.extend(
            sorted(
                relation["target_batch_id"]
                for relation in item["required_relationships"]
                if relation["target_batch_id"] not in batch_set
            )
        )
        if unknown:
            raise FacilityProgramError(
                "facility_program_batch_dependency_unknown",
                "Resource relationships must reference a batch in the same program.",
                details={"batchId": item["batch_id"], "unknown": sorted(set(unknown))},
            )
    recipes = [
        _canonical_cell_recipe(item, index)
        for index, item in enumerate(
            _array(raw.get("cell_recipes"), "cell_recipes", FACILITY_PROGRAM_MAX_CELL_RECIPES)
        )
    ]
    recipe_ids = [item["recipe_id"] for item in recipes]
    if len(set(recipe_ids)) != len(recipe_ids):
        raise FacilityProgramError("facility_program_recipe_duplicate", "Cell recipe IDs must be unique.")
    for recipe in recipes:
        unknown = sorted(set(recipe["member_batches"]) - batch_set)
        if unknown:
            raise FacilityProgramError(
                "facility_program_recipe_batch_unknown",
                "Cell recipes must reference resource batches in the same program.",
                details={"recipeId": recipe["recipe_id"], "unknown": unknown},
            )
    families = [
        _canonical_module_family(item, index)
        for index, item in enumerate(
            _array(
                raw.get("module_families"),
                "module_families",
                FACILITY_PROGRAM_MAX_MODULE_FAMILIES,
            )
        )
    ]
    family_ids = [item["family_id"] for item in families]
    if len(set(family_ids)) != len(family_ids):
        raise FacilityProgramError("facility_program_family_duplicate", "Module family IDs must be unique.")
    family_set = set(family_ids)
    for family in families:
        unknown = sorted(set(family["composable_with"]) - family_set)
        if unknown:
            raise FacilityProgramError(
                "facility_program_family_unknown",
                "composable_with must reference a family in the same program.",
                details={"familyId": family["family_id"], "unknown": unknown},
            )
    reference = raw.get("reference_manifest_ref")
    if reference is not None:
        reference = _mapping(reference, "reference_manifest_ref")
        _closed(
            reference,
            {"manifest_id", "manifest_revision", "source_layout_revision"},
            "reference_manifest_ref",
        )
        reference = {
            "manifest_id": _identifier(reference.get("manifest_id"), "reference_manifest_ref.manifest_id"),
            "manifest_revision": _sha256(
                reference.get("manifest_revision"), "reference_manifest_ref.manifest_revision"
            ),
            "source_layout_revision": _sha256(
                reference.get("source_layout_revision"),
                "reference_manifest_ref.source_layout_revision",
            ),
        }
    canonical = {
        "schema_version": FACILITY_PROGRAM_SCHEMA,
        "identity": {
            "program_id": _identifier(identity.get("program_id"), "identity.program_id"),
            "display_name": _text(identity.get("display_name"), "identity.display_name"),
            "source_revision_refs": _refs(
                identity.get("source_revision_refs", []), "identity.source_revision_refs"
            ),
        },
        "authority_and_mode": _canonical_authority(raw.get("authority_and_mode")),
        "facility_envelope": _canonical_envelope(raw.get("facility_envelope")),
        "macro_departments": _canonical_macro_departments(raw.get("macro_departments")),
        "area_hierarchy": _canonical_area_hierarchy(raw.get("area_hierarchy")),
        "flow_requirements": _closed_records(
            raw.get("flow_requirements"),
            "flow_requirements",
            100,
            (
                {
                    "flow_id",
                    "source_area",
                    "target_area",
                    "via_areas",
                    "material_or_people_class",
                    "direction",
                    "evidence_refs",
                },
            ),
        ),
        "route_network": _canonical_route_network(raw.get("route_network")),
        "resource_batches": resources,
        "cell_recipes": sorted(recipes, key=lambda item: item["recipe_id"]),
        "module_families": sorted(families, key=lambda item: item["family_id"]),
        "floor_communication": _canonical_floor_communication(
            raw.get("floor_communication")
        ),
        "presentation_intent": _canonical_presentation_intent(
            raw.get("presentation_intent")
        ),
        "unresolved_requirements": _canonical_unresolved(
            raw.get("unresolved_requirements")
        ),
        "reference_manifest_ref": reference,
    }
    _reject_coordinates(canonical)
    return canonical


def facility_program_from_full_factory(
    request: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Adapt the shipped singular G1-G6 request into the canonical array contract."""

    compiled = compile_full_factory_program(request, asset_catalog)
    canonical = compiled["canonicalRequest"]
    resolved_by_request = {
        item["requestId"]: item for item in compiled["resolvedAssets"]
    }
    catalog_by_identity = {
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        ): item
        for item in asset_catalog
        if isinstance(item, Mapping)
    }
    resource_batches = []
    aggregate_index: dict[tuple[str, ...], int] = {}
    for index, item in enumerate(canonical["asset_placements"], start=1):
        request_id = f"full-factory-asset-{index:03d}"
        resolved = resolved_by_request[request_id]
        batch = {
                "batch_id": request_id,
                "exact_catalog_identity": {
                    "asset_id": resolved["assetId"],
                    "asset_definition_revision": resolved["assetDefinitionRevision"],
                    "display_name": resolved["assetName"],
                },
                "quantity": item["quantity"],
                "target_area": item["target_area"],
                "placement_pattern": select_industrial_pattern(
                    catalog_by_identity[
                        (resolved["assetId"], resolved["assetDefinitionRevision"])
                    ]
                ),
                "semantic_orientation": (
                    "catalog_default"
                    if item["orientation_mode"] == "auto"
                    else item["orientation_mode"]
                ),
                "resource_role": item["resource_role"],
                "authored_spacing": None,
                "ordering_or_grouping": None,
                "required_relationships": [],
                "placement_dependencies": [],
                "evidence_refs": [resolved["assetDefinitionRevision"]],
                "reference_entity_ids": [],
            }
        aggregate_key = (
            batch["exact_catalog_identity"]["asset_id"],
            batch["exact_catalog_identity"]["asset_definition_revision"],
            batch["target_area"].casefold(),
            batch["placement_pattern"],
            batch["semantic_orientation"],
            batch["resource_role"],
        )
        existing_index = aggregate_index.get(aggregate_key)
        if existing_index is None:
            aggregate_index[aggregate_key] = len(resource_batches)
            resource_batches.append(batch)
        else:
            resource_batches[existing_index]["quantity"] += batch["quantity"]
    recipes = []
    recipe_id_by_target: dict[str, str] = {}
    for recipe_index, seed in enumerate(canonical["cell_recipes"], start=1):
        members = [
            item["batch_id"]
            for item in resource_batches
            if item["target_area"].casefold() == seed["target_area"].casefold()
        ]
        selected = seed["selected_strategy"] or seed["objective"]
        recipe_id = f"recipe-{recipe_index:03d}"
        recipe_id_by_target[seed["target_area"].casefold()] = recipe_id
        recipes.append(
            {
                "recipe_id": recipe_id,
                "target_area": seed["target_area"],
                "member_batches": members,
                "candidate_strategies": list(seed["candidate_strategies"]),
                "selected_strategy_or_objective": selected,
                "authored_spacing": (
                    None
                    if seed["preferred_gap_meters"] is None
                    else {
                        "value": seed["preferred_gap_meters"],
                        "unit": "m",
                        "evidence_ref": "user-authored-cell-gap",
                    }
                ),
                "process_order": [],
                "interfaces": [],
                "evidence_refs": [],
            }
        )
    families = []
    for family_index, replication in enumerate(
        canonical["module_families"], start=1
    ):
        families.append(
            {
                "family_id": f"family-{family_index:03d}",
                "source_recipe_or_cell": recipe_id_by_target.get(
                    replication["source_cell"].casefold(),
                    replication["source_cell"],
                ),
                "target_areas": list(replication["target_areas"]),
                "allowed_transform_mode": "translate_exact",
                "preserve_source": True,
                "conformance_requirements": ["exact_relative_geometry"],
                "composable_with": [],
                "evidence_refs": [],
            }
        )
    program = {
        "schema_version": FACILITY_PROGRAM_SCHEMA,
        "identity": {
            "program_id": f"facility-program-{compiled['programRevision'][:24]}",
            "display_name": canonical["facility_envelope"]["display_name"],
            "source_revision_refs": [compiled["programRevision"]],
        },
        "authority_and_mode": {
            "mode": "intent_driven_prototype",
            "evidence_status": "authored",
            "review_status": "pending",
            "production_eligible": False,
            "prototype_assumptions_allowed": True,
        },
        "facility_envelope": {
            **canonical["facility_envelope"],
            "dimension_evidence_refs": ["user-authored-envelope"],
        },
        "macro_departments": [deepcopy(canonical["departments"])],
        "area_hierarchy": deepcopy(canonical["subdivisions"]),
        "flow_requirements": [],
        "route_network": {
            "primary_routes": deepcopy(canonical["circulation"]["routes"]),
            "local_routes": [],
        },
        "resource_batches": resource_batches,
        "cell_recipes": recipes,
        "module_families": families,
        "floor_communication": deepcopy(canonical["circulation"]["crossings"]),
        "presentation_intent": {
            "fit_to_occupied_content": True,
            "semantic_zoom": True,
        },
        "unresolved_requirements": [],
        "reference_manifest_ref": None,
    }
    return canonicalize_facility_program(program)


def facility_program_stage_slice(
    program: Mapping[str, Any], stage_id: str, *, cursor: int = 0
) -> dict[str, Any]:
    """Return the bounded semantic slice available to one deterministic stage."""

    canonical = canonicalize_facility_program(program)
    common = {
        "schemaVersion": FACILITY_PROGRAM_SCHEMA,
        "programId": canonical["identity"]["program_id"],
        "programRevision": facility_knowledge_revision(canonical),
        "mode": canonical["authority_and_mode"]["mode"],
        "stageId": _identifier(stage_id, "stage_id"),
    }
    mapping = {
        "facility_envelope": {"facilityEnvelope": canonical["facility_envelope"]},
        "macro_departments": {"macroDepartments": canonical["macro_departments"]},
        "primary_circulation": {
            "flowRequirements": canonical["flow_requirements"],
            "primaryRoutes": canonical["route_network"].get("primary_routes", []),
        },
        "department_subdivisions": {"areaHierarchy": canonical["area_hierarchy"]},
        "department_resources": {"resourceBatches": canonical["resource_batches"]},
        "seed_cells": {"cellRecipes": canonical["cell_recipes"]},
        "repeated_modules": {"moduleFamilies": canonical["module_families"]},
        "floor_communication": {
            "localRoutes": canonical["route_network"].get("local_routes", []),
            "floorCommunication": canonical["floor_communication"],
        },
        "deterministic_validation": {
            "unresolvedRequirements": canonical["unresolved_requirements"]
        },
        "review_and_save": {
            "authority": canonical["authority_and_mode"],
            "presentationIntent": canonical["presentation_intent"],
        },
    }
    if stage_id not in mapping:
        raise FacilityProgramError(
            "facility_program_stage_unknown", "FacilityProgram stage is unknown."
        )
    payload = deepcopy(mapping[stage_id])
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        raise FacilityProgramError(
            "facility_program_slice_cursor_invalid",
            "FacilityProgram stage cursor must be a non-negative integer.",
        )
    list_fields = [key for key, value in payload.items() if isinstance(value, list)]
    if not list_fields:
        result = {**common, **payload, "cursor": 0, "nextCursor": None}
        if len(canonical_facility_knowledge_bytes(result)) > FACILITY_PROGRAM_STAGE_SLICE_BYTES:
            raise FacilityProgramError(
                "facility_program_stage_slice_too_large",
                "The indivisible stage slice exceeds the runtime semantic byte budget.",
                details={"stageId": stage_id, "maximum": FACILITY_PROGRAM_STAGE_SLICE_BYTES},
            )
        return result

    flattened: list[dict[str, Any]] = []
    for key in list_fields:
        flattened.extend({"collection": key, "value": item} for item in payload[key])
    if cursor > len(flattened):
        raise FacilityProgramError(
            "facility_program_slice_cursor_invalid",
            "FacilityProgram stage cursor is past the end of the stage.",
        )
    fixed = {key: value for key, value in payload.items() if key not in list_fields}
    selected: list[dict[str, Any]] = []
    next_cursor: int | None = None
    for index in range(cursor, len(flattened)):
        candidate = selected + [flattened[index]]
        candidate_result = {
            **common,
            **fixed,
            "items": candidate,
            "cursor": cursor,
            "nextCursor": index + 1 if index + 1 < len(flattened) else None,
        }
        if len(canonical_facility_knowledge_bytes(candidate_result)) > FACILITY_PROGRAM_STAGE_SLICE_BYTES:
            if not selected:
                raise FacilityProgramError(
                    "facility_program_stage_item_too_large",
                    "One FacilityProgram stage item exceeds the runtime semantic byte budget.",
                    details={"stageId": stage_id, "itemIndex": index},
                )
            next_cursor = index
            break
        selected = candidate
        next_cursor = index + 1 if index + 1 < len(flattened) else None
    result = {
        **common,
        **fixed,
        "items": selected,
        "cursor": cursor,
        "nextCursor": next_cursor,
    }
    return result


def facility_program_model_summary(program: Mapping[str, Any]) -> dict[str, Any]:
    """Return a provider-safe receipt rather than the full resolved artifact."""

    canonical = canonicalize_facility_program(program)
    result = {
        "programId": canonical["identity"]["program_id"],
        "programRevision": facility_knowledge_revision(canonical),
        "displayName": canonical["identity"]["display_name"],
        "mode": canonical["authority_and_mode"]["mode"],
        "reviewStatus": canonical["authority_and_mode"]["review_status"],
        "productionEligible": canonical["authority_and_mode"]["production_eligible"],
        "counts": {
            "macroDepartmentGroups": len(canonical["macro_departments"]),
            "areaHierarchyGroups": len(canonical["area_hierarchy"]),
            "resourceBatches": len(canonical["resource_batches"]),
            "requestedAssets": sum(
                item["quantity"] for item in canonical["resource_batches"]
            ),
            "cellRecipes": len(canonical["cell_recipes"]),
            "moduleFamilies": len(canonical["module_families"]),
            "floorCommunication": len(canonical["floor_communication"]),
            "unresolvedRequirements": len(canonical["unresolved_requirements"]),
        },
    }
    byte_count = len(canonical_facility_knowledge_bytes(result))
    if byte_count > FACILITY_PROGRAM_TOOL_RESPONSE_BYTES:
        raise FacilityProgramError(
            "facility_program_tool_response_too_large",
            "FacilityProgram provider receipt exceeds the tool-response budget.",
        )
    return result


__all__ = [
    "FACILITY_PROGRAM_MAX_TOTAL_ASSETS",
    "FACILITY_PROGRAM_SCHEMA",
    "FACILITY_PROGRAM_STAGE_SLICE_BYTES",
    "FACILITY_PROGRAM_TOOL_RESPONSE_BYTES",
    "FacilityProgramError",
    "canonicalize_facility_program",
    "facility_program_from_full_factory",
    "facility_program_model_summary",
    "facility_program_stage_slice",
]
