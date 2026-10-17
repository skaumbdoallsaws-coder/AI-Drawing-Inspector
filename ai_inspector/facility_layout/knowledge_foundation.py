"""Canonical knowledge contracts for Sage Facility Layout orchestration.

This module adapts the established runtime registries into one strict,
versioned contract. It does not calculate geometry and it does not persist a
Facility Layout. Those responsibilities remain with the existing planner,
operation kernel, validators, and repository.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .feature_flags import (
    FACILITY_ALL_CAPABILITY_DEPENDENCIES,
    FACILITY_ALL_CAPABILITY_FLAGS,
    FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES,
    FACILITY_LAYOUT_CAPABILITY_FLAGS,
    FACILITY_LAYOUT_FEATURE_FLAGS,
)
from .semantic_model import (
    AGENT_TOOL_SEMANTICS,
    CELL_LAYOUT_STRATEGIES,
    FACILITY_COMMAND_SEMANTICS,
)


FACILITY_KNOWLEDGE_SCHEMA_VERSION = 1
FACILITY_GENERATION_RUN_SCHEMA_VERSION = 1
FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES = 8_192
FACILITY_CONTEXT_TARGET_ESTIMATED_TOKENS = 9_600
FACILITY_CONTEXT_MAXIMUM_ESTIMATED_TOKENS = 12_000
FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES = 16_384
FACILITY_SOURCE_UNITS = ("m", "mm", "ft", "in")
FACILITY_COMMAND_EFFECTS = (
    "read",
    "viewport",
    "draft_edit",
    "persistent_save",
    "viewport_capture",
)
FACILITY_AGENT_EFFECTS = (
    "read",
    "preview",
    "design_state_edit",
    "draft_edit",
)
FACILITY_STAGE_STATUSES = (
    "pending",
    "ready",
    "running",
    "blocked",
    "complete",
    "invalidated",
    "cancelled",
)
FACILITY_RUN_STATUSES = (
    "active",
    "blocked",
    "complete",
    "cancelled",
    "expired",
    "stale",
    "saved",
)
FACILITY_SAVE_ELIGIBILITY = ("blocked", "eligible", "saved")
FACILITY_EVIDENCE_STATUSES = ("authored", "derived", "inferred", "unknown")
FACILITY_LIFECYCLE_STATES = (
    "proposed",
    "draft",
    "active",
    "superseded",
    "archived",
)
FACILITY_INTENT_MODES = ("greenfield", "brownfield", "scoped_modification")
FACILITY_EXECUTION_MODES = (
    "preview_only",
    "guided_draft",
    "authorized_draft_run",
)
FACILITY_SAVE_POLICIES = ("explicit_user_command",)
FACILITY_SUBSTAGE_STATUSES = FACILITY_STAGE_STATUSES
FACILITY_INVALIDATION_REASONS = (
    "upstream_dependency_changed",
    "base_layout_revision_changed",
    "source_revision_changed",
    "provider_configuration_changed",
    "user_cancelled",
)
FACILITY_MAXIMUM_OPERATION_BATCH = 500
FACILITY_MAXIMUM_PLANNED_INSTANCES = 500
FACILITY_STAGE_RECEIPT_STATUSES = ("valid", "failed")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RUN_ID_RE = re.compile(r"^fgr-[A-Za-z0-9][A-Za-z0-9._:-]{0,124}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FacilityKnowledgeContractError(ValueError):
    """Stable fail-closed error for Facility knowledge contracts."""

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


def canonical_facility_knowledge_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityKnowledgeContractError(
            "facility_contract_not_canonical",
            "Facility knowledge content is not canonical JSON.",
        ) from exc


def facility_knowledge_revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def bytes4_estimate(canonical_byte_count: int) -> int:
    if isinstance(canonical_byte_count, bool) or not isinstance(
        canonical_byte_count, int
    ):
        raise FacilityKnowledgeContractError(
            "invalid_byte_count",
            "Canonical byte count must be an integer.",
        )
    if canonical_byte_count < 0:
        raise FacilityKnowledgeContractError(
            "invalid_byte_count",
            "Canonical byte count cannot be negative.",
        )
    return (canonical_byte_count + 3) // 4


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise FacilityKnowledgeContractError(
            "invalid_identifier",
            f"{field} must be a stable identifier.",
            details={"field": field},
        )
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise FacilityKnowledgeContractError(
            "invalid_sha256",
            f"{field} must be a lowercase SHA-256 digest.",
            details={"field": field},
        )
    return value


def _finite_positive(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise FacilityKnowledgeContractError(
            "invalid_dimension",
            f"{field} must be a finite positive number.",
            details={"field": field},
        )
    return float(value)


FACILITY_GENERATION_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stageId": "facility_envelope",
        "sequence": 1,
        "label": "Facility envelope and plan settings",
        "dependsOn": [],
        "capabilityTags": ["plan_settings", "facility_envelope"],
    },
    {
        "stageId": "macro_departments",
        "sequence": 2,
        "label": "Macro departments",
        "dependsOn": ["facility_envelope"],
        "capabilityTags": ["zones", "department_partition"],
    },
    {
        "stageId": "primary_circulation",
        "sequence": 3,
        "label": "Primary circulation and crossings",
        "dependsOn": ["macro_departments"],
        "capabilityTags": ["routes", "aisles", "crossings"],
    },
    {
        "stageId": "department_subdivisions",
        "sequence": 4,
        "label": "Department subdivisions",
        "dependsOn": ["macro_departments", "primary_circulation"],
        "capabilityTags": ["zones", "hierarchy"],
    },
    {
        "stageId": "department_resources",
        "sequence": 5,
        "label": "Department resources and staging",
        "dependsOn": ["department_subdivisions"],
        "capabilityTags": ["assets", "staging"],
    },
    {
        "stageId": "seed_cells",
        "sequence": 6,
        "label": "Seed manufacturing cells",
        "dependsOn": ["department_resources"],
        "capabilityTags": ["cell_strategy", "workcell"],
    },
    {
        "stageId": "repeated_modules",
        "sequence": 7,
        "label": "Repeated cells, rows, and modules",
        "dependsOn": ["seed_cells"],
        "capabilityTags": ["patterns", "modules"],
    },
    {
        "stageId": "floor_communication",
        "sequence": 8,
        "label": "Floor communication and support details",
        "dependsOn": ["primary_circulation", "repeated_modules"],
        "capabilityTags": ["floor_markings", "support"],
    },
    {
        "stageId": "deterministic_validation",
        "sequence": 9,
        "label": "Full deterministic validation",
        "dependsOn": ["floor_communication"],
        "capabilityTags": ["validation", "findings"],
    },
    {
        "stageId": "review_and_save",
        "sequence": 10,
        "label": "Review and explicit save",
        "dependsOn": ["deterministic_validation"],
        "capabilityTags": ["review", "save"],
    },
)


FACILITY_ENTITY_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "entityType": "facility_envelope",
        "stableIdField": "facilityId",
        "parentTypes": [],
        "allowedRelationships": ["contains", "constrained_by"],
    },
    {
        "entityType": "department",
        "stableIdField": "zoneId",
        "parentTypes": ["facility_envelope"],
        "allowedRelationships": [
            "contained_by",
            "contains",
            "adjacent_to",
            "separated_from",
            "served_by",
            "flows_to",
            "constrained_by",
        ],
    },
    {
        "entityType": "subzone",
        "stableIdField": "zoneId",
        "parentTypes": ["department", "subzone"],
        "allowedRelationships": [
            "contained_by",
            "contains",
            "adjacent_to",
            "served_by",
            "constrained_by",
        ],
    },
    {
        "entityType": "route",
        "stableIdField": "routeId",
        "parentTypes": ["facility_envelope", "department", "subzone"],
        "allowedRelationships": ["connects", "serves", "crosses", "constrained_by"],
    },
    {
        "entityType": "manufacturing_cell",
        "stableIdField": "cellId",
        "parentTypes": ["department", "subzone"],
        "allowedRelationships": [
            "contained_by",
            "contains",
            "performs",
            "served_by",
            "flows_to",
            "constrained_by",
        ],
    },
    {
        "entityType": "asset_definition",
        "stableIdField": "assetId",
        "parentTypes": [],
        "allowedRelationships": ["instantiated_as", "supports", "constrained_by"],
    },
    {
        "entityType": "placement_occurrence",
        "stableIdField": "placementId",
        "parentTypes": ["department", "subzone", "manufacturing_cell"],
        "allowedRelationships": [
            "instance_of",
            "contained_by",
            "member_of",
            "supports",
            "served_by",
            "performs",
            "constrained_by",
        ],
    },
    {
        "entityType": "floor_marking",
        "stableIdField": "markingId",
        "parentTypes": ["facility_envelope", "department", "subzone"],
        "allowedRelationships": ["contained_by", "communicates", "constrained_by"],
    },
    {
        "entityType": "utility_network",
        "stableIdField": "networkId",
        "parentTypes": ["facility_envelope"],
        "allowedRelationships": ["serves", "connects", "constrained_by"],
    },
    {
        "entityType": "process_binding",
        "stableIdField": "bindingId",
        "parentTypes": ["facility_envelope"],
        "allowedRelationships": ["binds", "precedes", "flows_to"],
    },
    {
        "entityType": "constraint",
        "stableIdField": "constraintId",
        "parentTypes": [
            "facility_envelope",
            "department",
            "subzone",
            "route",
            "manufacturing_cell",
            "asset_definition",
            "placement_occurrence",
            "floor_marking",
            "utility_network",
        ],
        "allowedRelationships": ["constrains", "derived_from"],
    },
    {
        "entityType": "execution_receipt",
        "stableIdField": "receiptId",
        "parentTypes": [],
        "allowedRelationships": ["proves", "supersedes", "bound_to_revision"],
    },
)

FACILITY_RELATIONSHIP_CONTRACTS: tuple[dict[str, Any], ...] = tuple(
    {
        "relationshipType": relationship,
        "directed": relationship
        not in {"adjacent_to", "separated_from", "crosses"},
        "requiresEvidenceStatus": True,
    }
    for relationship in (
        "contains",
        "contained_by",
        "adjacent_to",
        "separated_from",
        "connects",
        "crosses",
        "serves",
        "served_by",
        "member_of",
        "supports",
        "instantiated_as",
        "instance_of",
        "performs",
        "binds",
        "precedes",
        "flows_to",
        "communicates",
        "constrained_by",
        "constrains",
        "derived_from",
        "proves",
        "supersedes",
        "bound_to_revision",
    )
)

FACILITY_RESPONSIBILITY_CONTRACT: Mapping[str, Any] = {
    "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
    "recordKind": "facility_sage_responsibility_contract",
    "sageMay": [
        "interpret user intent and resolve semantic scope",
        "separate hard constraints, preferences, assumptions, and unknowns",
        "select registered semantic commands",
        "plan dependency-ordered stages",
        "rank deterministically feasible alternatives",
        "report progress, assumptions, blockers, and required decisions",
    ],
    "sageMustInspect": [
        "current revision-bound facility digest",
        "stage-appropriate command and strategy contracts",
        "relevant asset, process, policy, and authority evidence",
        "current generation-stage state and prior immutable receipts",
        "deterministic validation findings before claiming success",
    ],
    "deterministicCodeOwns": [
        "unit conversion",
        "coordinates and transforms",
        "polygon construction and partitioning",
        "footprint, clearance, route, containment, and collision geometry",
        "pattern and cell member placement",
        "operation batches, diffs, preview, undo, and save receipts",
        "revision, authorization, and stale-state enforcement",
    ],
    "userOwns": [
        "business intent and priorities",
        "authored dimensions, quantities, sequence, and adjacency",
        "acceptance of disclosed assumptions and tradeoffs",
        "explicit authorization of the cumulative save diff",
        "approval of safety, compliance, and production evidence",
    ],
    "defaultPolicy": {
        "labelsOnlyDepartmentRequest": "equal_area_partition_with_disclosed_assumption",
        "inventCorridor": False,
        "inventSafetySeparation": False,
        "inventExpansionReserve": False,
        "inferWorldCoordinatesFromModelText": False,
    },
    "clarificationRequiredWhen": [
        "two valid interpretations change a hard constraint",
        "an authored dimension, count, identity, or authority binding is ambiguous",
        "no deterministic candidate satisfies all hard constraints",
        "a requested persistent action lacks exact cumulative approval",
    ],
    "receiptClaims": {
        "previewRequiresReceipt": True,
        "mutationRequiresReceipt": True,
        "saveRequiresReceipt": True,
        "modelTextAloneProvesExecution": False,
    },
    "authorityBoundary": {
        "modelMayGrantHumanAuthority": False,
        "modelMayApproveOrRelease": False,
        "prototypeModeRequiresExplicitFlag": True,
        "finalSaveRequiresExplicitUserCommand": True,
    },
}

FACILITY_CELL_RECIPES: tuple[dict[str, Any], ...] = (
    {
        "recipeId": "guarded_robot_cell",
        "label": "Guarded Robot Cell",
        "strategyIds": ["u", "cluster"],
        "processFit": ["robotic processing", "guarded automation"],
        "requiredEvidence": ["asset footprints", "guard envelope", "material interfaces"],
    },
    {
        "recipeId": "assembly_cell",
        "label": "Assembly Cell",
        "strategyIds": ["u", "l", "cluster"],
        "processFit": ["manual assembly", "mixed manual and assisted assembly"],
        "requiredEvidence": ["asset footprints", "operator access", "material interfaces"],
    },
    {
        "recipeId": "straight_assembly_line",
        "label": "Straight Assembly Line",
        "strategyIds": ["line"],
        "processFit": ["ordered serial assembly"],
        "requiredEvidence": ["process order", "asset footprints", "material entry and exit"],
    },
    {
        "recipeId": "kitting_island",
        "label": "Kitting Island",
        "strategyIds": ["cluster", "u"],
        "processFit": ["parts staging", "kit preparation"],
        "requiredEvidence": ["asset footprints", "material interfaces"],
    },
    {
        "recipeId": "inspection_station",
        "label": "Inspection Station",
        "strategyIds": ["line", "cluster"],
        "processFit": ["in-process inspection", "final inspection"],
        "requiredEvidence": ["gage footprints", "operator access", "process binding"],
    },
    {
        "recipeId": "packaging_station",
        "label": "Packaging Station",
        "strategyIds": ["line", "l", "u"],
        "processFit": ["packing", "labeling", "finished-product transfer"],
        "requiredEvidence": ["asset footprints", "material entry and exit"],
    },
    {
        "recipeId": "rack_row",
        "label": "Rack Row",
        "strategyIds": ["line", "parallel", "grid"],
        "processFit": ["material storage", "finished-goods storage"],
        "requiredEvidence": ["rack footprint", "route interfaces"],
    },
    {
        "recipeId": "equipment_parking_module",
        "label": "Equipment Parking Module",
        "strategyIds": ["line", "grid"],
        "processFit": ["mobile-equipment parking", "support equipment staging"],
        "requiredEvidence": ["equipment footprint", "entry and exit interface"],
    },
)


_NON_RIBBON_SURFACES: Mapping[str, tuple[str, ...]] = {
    "assets": ("asset_browser",),
    "fit-layout": ("plan_navigation", "3d_navigation"),
    "top-view": ("plan_navigation", "3d_navigation"),
    "orbit": ("3d_navigation",),
    "walkthrough": ("3d_navigation",),
    "drone": ("3d_navigation",),
    "record": ("3d_capture",),
}

_CONSTRUCTION_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "static" / "contracts"
     / "facility-construction-commands-v1.json").read_text(encoding="utf-8")
)

_INPUTS: Mapping[str, tuple[str, ...]] = {
    "assets": ("query", "capabilityTags"),
    "select": ("entityIds",),
    "pan": ("viewportDelta",),
    "rectangle-zone": ("label", "zoneType", "width", "depth", "sourceUnit"),
    "polygon-zone": ("label", "zoneType", "vertices", "sourceUnit"),
    "bulk-zones": ("zones", "sourceUnit"),
    "aisle": ("label", "routeKind", "width", "centerline", "sourceUnit"),
    "floor-marking": ("markingKind", "geometry", "label"),
    "motion-path": ("actorPlacementId", "authoringMode"),
    "rotate": ("selectionIds", "quarterTurns"),
    "duplicate": ("selectionIds", "offset", "sourceUnit"),
    "delete": ("selectionIds",),
    "clear-all": ("confirmed",),
    "lock": ("selectionIds", "positionMode"),
    "align": ("selectionIds", "axis", "anchor"),
    "distribute": ("selectionIds", "axis", "spacingMode"),
    "relative": ("movingIds", "referenceId", "relationship", "distance", "sourceUnit"),
    "distance": ("firstId", "secondId", "measurementMode", "requestedDistance", "sourceUnit"),
    "offset": ("selectionIds", "delta", "sourceUnit", "copy"),
    "linear-pattern": ("seedIds", "count", "direction", "spacing", "sourceUnit"),
    "circular-pattern": ("seedIds", "count", "center", "arcDegrees", "sourceUnit"),
    "perimeter-pattern": ("seedIds", "width", "depth", "clearGap", "sourceUnit"),
    "cell-layout": ("selectionIds", "strategyId", "targetBounds", "sourceUnit", "gap", "rows", "orientation", "angleDegrees", "invertU"),
    "create-cell-group": ("selectionIds", "label", "envelopePadding", "sourceUnit"),
    "ungroup-cell": ("cellId",),
    "vertical-stack": ("selectionIds", "count", "gap", "sourceUnit"),
    "surface-stack": ("supportId", "childIds", "surfaceId", "side", "gap", "sourceUnit", "itemGap", "inset"),
    "mirror": ("selectionIds", "axisStart", "axisEnd", "sourceUnit"),
    "swap": ("firstId", "secondId"),
    "undo": (),
    "redo": (),
    "fit": (),
    "fit-layout": (),
    "top-view": (),
    "auto-arrange": ("selectionIds", "strategyId", "preferences"),
    "save": ("expectedBaseRevision", "approvedCumulativeDiffHash"),
    "orbit": (),
    "walkthrough": ("placementId",),
    "drone": ("placementId", "altitudeMeters"),
    "record": ("captureSettings",),
}

_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    "rotate": {"quarterTurns": 1},
    "duplicate": {"offset": {"x": 1.0, "y": 0.0, "z": 1.0}, "sourceUnit": "m"},
    "lock": {"positionMode": "locked"},
    "offset": {"copy": False, "sourceUnit": "m"},
    "circular-pattern": {"arcDegrees": 360.0, "sourceUnit": "m"},
    "create-cell-group": {"envelopePadding": 0.0, "sourceUnit": "m"},
    "vertical-stack": {"gap": 0.0, "sourceUnit": "m"},
    "surface-stack": {"side": "top", "gap": 0.0, "sourceUnit": "m"},
    "motion-path": {"authoringMode": "plan_pointer"},
}

_OPTIONAL_INPUTS: Mapping[str, frozenset[str]] = {
    "assets": frozenset({"query", "capabilityTags"}),
    "rotate": frozenset({"quarterTurns"}),
    "duplicate": frozenset({"offset", "sourceUnit"}),
    "lock": frozenset({"positionMode"}),
    "distance": frozenset({"requestedDistance", "sourceUnit"}),
    "offset": frozenset({"sourceUnit", "copy"}),
    "circular-pattern": frozenset({"arcDegrees", "sourceUnit"}),
    "create-cell-group": frozenset({"envelopePadding", "sourceUnit"}),
    "vertical-stack": frozenset({"gap", "sourceUnit"}),
    "surface-stack": frozenset({"side", "gap", "sourceUnit"}),
    "motion-path": frozenset({"authoringMode"}),
    "mirror": frozenset({"sourceUnit"}),
    "auto-arrange": frozenset({"selectionIds", "preferences"}),
    "drone": frozenset({"placementId", "altitudeMeters"}),
    "record": frozenset({"captureSettings"}),
}

_ALL_GENERATION_STAGE_IDS = tuple(
    item["stageId"] for item in FACILITY_GENERATION_STAGES
)

_COMMAND_STAGE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "assets": ("department_resources", "seed_cells", "repeated_modules"),
    "rectangle-zone": ("macro_departments", "department_subdivisions"),
    "polygon-zone": ("macro_departments", "department_subdivisions"),
    "bulk-zones": ("macro_departments", "department_subdivisions"),
    "aisle": ("primary_circulation", "floor_communication"),
    "floor-marking": ("primary_circulation", "floor_communication"),
    "motion-path": ("floor_communication",),
    "rotate": ("department_resources", "seed_cells", "repeated_modules"),
    "duplicate": (
        "department_subdivisions",
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "floor_communication",
    ),
    "lock": ("department_resources", "seed_cells", "repeated_modules"),
    "align": ("department_resources", "seed_cells", "repeated_modules"),
    "distribute": ("department_resources", "seed_cells", "repeated_modules"),
    "relative": ("department_resources", "seed_cells", "repeated_modules"),
    "distance": ("department_resources", "seed_cells", "repeated_modules"),
    "offset": ("department_resources", "seed_cells", "repeated_modules"),
    "linear-pattern": ("repeated_modules",),
    "circular-pattern": ("repeated_modules",),
    "perimeter-pattern": ("repeated_modules",),
    "cell-layout": ("seed_cells", "repeated_modules"),
    "create-cell-group": ("seed_cells", "repeated_modules"),
    "ungroup-cell": ("seed_cells", "repeated_modules"),
    "vertical-stack": ("department_resources", "seed_cells", "repeated_modules"),
    "surface-stack": ("department_resources", "seed_cells", "repeated_modules"),
    "mirror": ("department_resources", "seed_cells", "repeated_modules"),
    "swap": ("department_resources", "seed_cells", "repeated_modules"),
    "auto-arrange": ("department_resources", "seed_cells", "repeated_modules"),
    "save": ("review_and_save",),
    "record": ("review_and_save",),
}

_READ_ONLY_OR_NAVIGATION_COMMANDS = frozenset(
    {
        "select",
        "pan",
        "undo",
        "redo",
        "fit",
        "fit-layout",
        "top-view",
        "orbit",
        "walkthrough",
        "drone",
    }
)

_DESTRUCTIVE_COMMANDS = frozenset({"delete", "clear-all"})

_FIELD_TYPE_OVERRIDES: Mapping[str, Mapping[str, Any]] = {
    "query": {"type": "string", "maxLength": 120},
    "capabilityTags": {"type": "array", "maxItems": 48, "uniqueItems": True,
                       "items": {"type": "string", "minLength": 1}},
    "sourceUnit": {"type": "string", "enum": list(FACILITY_SOURCE_UNITS)},
    "count": {"type": "integer", "minimum": 1},
    "quarterTurns": {"type": "integer"},
    "arcDegrees": {"type": "number"},
    "width": {"type": "number", "exclusiveMinimum": 0},
    "depth": {"type": "number", "exclusiveMinimum": 0},
    "distance": {"type": "number", "minimum": 0},
    "requestedDistance": {"type": "number", "minimum": 0},
    "spacing": {"type": "number", "minimum": 0},
    "gap": {"type": "number", "minimum": 0},
    "clearGap": {"type": "number", "minimum": 0},
    "altitudeMeters": {"type": "number", "minimum": 0},
    "authoringMode": {"type": "string", "enum": ["plan_pointer"]},
    "copy": {"type": "boolean"},
    "confirmed": {"type": "boolean", "const": True},
}


def _command_supported_stages(command_id: str) -> list[str]:
    if command_id in _COMMAND_STAGE_GROUPS:
        return list(_COMMAND_STAGE_GROUPS[command_id])
    if command_id in _READ_ONLY_OR_NAVIGATION_COMMANDS:
        return list(_ALL_GENERATION_STAGE_IDS)
    if command_id == "clear-all":
        # A complete brownfield G1 request clears only the unsaved working
        # copy before the new envelope is compiled. Save remains a separate,
        # cumulative approval action.
        return list(_ALL_GENERATION_STAGE_IDS[:8])
    if command_id in _DESTRUCTIVE_COMMANDS:
        return list(_ALL_GENERATION_STAGE_IDS[1:8])
    return list(_ALL_GENERATION_STAGE_IDS)


def _input_property_schema(field: str) -> dict[str, Any]:
    if field in _FIELD_TYPE_OVERRIDES:
        return deepcopy(dict(_FIELD_TYPE_OVERRIDES[field]))
    if field.endswith("Ids"):
        return {"type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1}}
    if field in {"zones", "vertices", "preferences"}:
        return {"type": "array"}
    if field.endswith("Id") or field in {
        "label",
        "zoneType",
        "routeKind",
        "markingKind",
        "axis",
        "anchor",
        "relationship",
        "measurementMode",
        "direction",
        "strategyId",
        "positionMode",
        "side",
        "expectedBaseRevision",
        "approvedCumulativeDiffHash",
    }:
        return {"type": "string"}
    return {"type": "object"}


def _command_input_schema(command_id: str) -> dict[str, Any]:
    if command_id in _CONSTRUCTION_CONTRACT["commands"]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **deepcopy(_CONSTRUCTION_CONTRACT["commands"][command_id]),
        }
    fields = list(_INPUTS[command_id])
    optional = _OPTIONAL_INPUTS.get(command_id, frozenset())
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            field: _input_property_schema(field)
            for field in fields
        },
        "required": [field for field in fields if field not in optional],
        "additionalProperties": False,
    }


def _command_required_context(command: Mapping[str, Any]) -> list[str]:
    effect = command["effect"]
    context = ["active_workspace", "feature_flag_snapshot"]
    if effect in {"draft_edit", "persistent_save"}:
        context.extend(["base_layout_revision", "current_draft_revision"])
    if command["commandId"] not in {"assets", "fit", "fit-layout", "top-view"}:
        context.append("current_layout_digest")
    if command["commandId"] == "save":
        context.extend(["valid_receipt_chain", "explicit_cumulative_diff_approval"])
    return context


def _command_validation_rules(command: Mapping[str, Any]) -> list[str]:
    rules = [str(item) for item in command.get("preconditions", ())]
    if command["effect"] == "viewport":
        rules.append("viewport state never changes document geometry")
    if command["effect"] in {"draft_edit", "persistent_save"}:
        rules.extend(
            [
                "validate against the exact base and draft revisions",
                "execute only through the deterministic owner",
                "return a revision-bound receipt",
            ]
        )
    if command["commandId"] == "save":
        rules.append("approval hash must match the complete cumulative diff")
    return list(dict.fromkeys(rules))


def _compatible_next_commands(command: Mapping[str, Any]) -> list[str]:
    if command["commandId"] == "save":
        return []
    if command["effect"] == "draft_edit":
        return ["fit-layout", "undo", "save"]
    if command["effect"] == "read":
        return ["select", "fit-layout"]
    return ["select", "fit-layout"]


def _incompatible_commands(command: Mapping[str, Any]) -> list[str]:
    if command["commandId"] == "clear-all":
        return ["save"]
    if command["effect"] == "viewport":
        return []
    return ["save"] if command["effect"] == "draft_edit" else []

_COMMAND_CAPABILITIES: Mapping[str, tuple[str, ...]] = {
    "assets": ("asset_library",),
    "aisle": ("manual_edit", "routing"),
    "auto-arrange": ("agent_preview",),
    "motion-path": ("manual_edit", "routing"),
}

_COMMAND_OWNERS: Mapping[str, str] = {
    "read": "facility.asset_catalog",
    "viewport": "facility.workspace_renderer",
    "draft_edit": "facility.operation_kernel",
    "persistent_save": "facility.repository",
    "viewport_capture": "facility.recorder",
}

_AGENT_TOOL_OWNERS: Mapping[str, str] = {
    "preview_facility_cell_layout": "facility.construction_service",
    "preview_facility_surface_stack": "facility.construction_service",
    "preview_facility_create_cell_group": "facility.construction_service",
    "preview_facility_linear_pattern": "facility.construction_service",
    "search_industrial_assets": "facility.observation.asset_catalog",
    "inspect_facility_entities": "facility.observation.entities",
    "inspect_facility_region": "facility.observation.region",
    "inspect_facility_findings": "facility.observation.findings",
    "inspect_process_bindings": "facility.observation.process_bindings",
    "inspect_facility_semantics": "facility.semantic_model",
    "inspect_pattern_provenance": "facility.observation.pattern_provenance",
    "inspect_cell_layout_provenance": "facility.observation.cell_provenance",
    "analyze_facility_spatial": "facility.spatial",
    "analyze_facility_fit": "facility.fit_analysis",
    "preview_facility_move": "facility.agent_runtime.exact_move",
    "build_facility_layout_preview": "facility.semantic_plan",
    "generate_facility_departments_draft": "facility.generation_coordinator",
    "inspect_facility_design_brief": "facility.design_repository",
    "update_facility_design_brief": "facility.design_brief",
    "run_facility_design_preview": "facility.design_runtime",
    "apply_facility_design_proposal_draft": "facility.design_transaction",
    "present_chat_visualization": "facility.chat_content.visualization",
    "present_chat_table": "facility.chat_content.table",
}


def _default_capabilities(command: Mapping[str, Any]) -> list[str]:
    command_id = str(command["commandId"])
    if command_id in _COMMAND_CAPABILITIES:
        return list(_COMMAND_CAPABILITIES[command_id])
    if command["effect"] in {"draft_edit", "persistent_save"}:
        return ["manual_edit"]
    return ["viewer_v2"]


def _prohibited_uses(command: Mapping[str, Any]) -> list[str]:
    effect = command["effect"]
    rules = []
    if effect == "read":
        rules.append("mutate or persist the Facility Layout")
    elif effect == "viewport":
        rules.append("treat camera or screen coordinates as document geometry")
    elif effect == "viewport_capture":
        rules.append("treat a recording as a geometry or approval receipt")
    elif effect == "draft_edit":
        rules.extend(
            [
                "accept model-authored screen coordinates or transforms",
                "skip deterministic validation or write directly to storage",
                "claim the unsaved draft is approved or persisted",
            ]
        )
    elif effect == "persistent_save":
        rules.extend(
            [
                "run without an explicit user approval bound to the exact diff",
                "save a stale, invalidated, or partially valid receipt chain",
            ]
        )
    if command["commandId"] == "clear-all":
        rules.append("execute without explicit destructive confirmation")
    if command["commandId"] == "auto-arrange":
        rules.append("persist a generated proposal without later cumulative approval")
    if command["commandId"] == "motion-path":
        rules.extend(
            [
                "accept path coordinates authored by model text",
                "treat an authored path as proof of clearance, reachability, safety, or timing",
            ]
        )
    return rules


def _failure_codes(command: Mapping[str, Any]) -> list[str]:
    codes = ["facility_feature_disabled", "invalid_command_input"]
    if command["effect"] in {"draft_edit", "persistent_save"}:
        codes.extend(
            [
                "facility_layout_revision_conflict",
                "facility_layout_validation_failed",
            ]
        )
    if command["effect"] == "persistent_save":
        codes.extend(["explicit_approval_required", "receipt_chain_invalid"])
    return codes


def canonical_facility_command_registry() -> tuple[dict[str, Any], ...]:
    records = []
    source_ids = {item["commandId"] for item in FACILITY_COMMAND_SEMANTICS}
    if source_ids != set(_INPUTS):
        raise FacilityKnowledgeContractError(
            "command_contract_coverage_mismatch",
            "Every Facility semantic command must have one input contract.",
            details={
                "missing": sorted(source_ids - set(_INPUTS)),
                "unknown": sorted(set(_INPUTS) - source_ids),
            },
        )
    for source in FACILITY_COMMAND_SEMANTICS:
        command = deepcopy(dict(source))
        command_id = command["commandId"]
        effect = command["effect"]
        surfaces = list(_NON_RIBBON_SURFACES.get(command_id, ("ribbon",)))
        mutates = effect in {"draft_edit", "persistent_save"}
        capabilities = _default_capabilities(command)
        prohibited = _prohibited_uses(command)
        source_semantic_use = str(command.get("semanticUse") or "").strip()
        record = {
            "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
            **command,
            "semanticIntent": source_semantic_use,
            "correctUseCases": [source_semantic_use] if source_semantic_use else [],
            "incorrectUseCases": prohibited,
            "supportedStages": _command_supported_stages(command_id),
            "entityScope": command["scope"],
            "requiredContext": _command_required_context(command),
            "inputSchema": _command_input_schema(command_id),
            "defaultPolicy": (
                "registered_defaults_only"
                if command_id in _DEFAULTS
                else "no_implicit_default"
            ),
            "deterministicOwner": _COMMAND_OWNERS[effect],
            "uiSurfaces": surfaces,
            "uiCommandId": command_id,
            "requiredCapabilities": capabilities,
            "requiredFeatureFlags": [
                FACILITY_LAYOUT_CAPABILITY_FLAGS[item]
                for item in capabilities
            ],
            "featureFlagDependencies": {
                item: list(FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES[item])
                for item in capabilities
            },
            "inputContract": {
                "fields": list(_INPUTS[command_id]),
                "sourceCoordinatesAllowed": effect == "viewport",
                "modelAuthoredWorldCoordinatesAllowed": False,
            },
            "defaults": deepcopy(dict(_DEFAULTS.get(command_id, {}))),
            "prohibitedUses": prohibited,
            "validationRules": _command_validation_rules(command),
            "failureCodes": _failure_codes(command),
            "receiptShape": {
                "required": mutates or effect == "viewport_capture",
                "revisionBound": mutates,
                "recordsBeforeAndAfterRevision": mutates,
                "recordsDeterministicOwner": True,
            },
            "undoSemantics": (
                "reversible_draft_operation"
                if effect == "draft_edit"
                else "not_document_mutation"
                if not mutates
                else "new_saved_revision_required"
            ),
            "compatibleNextCommands": _compatible_next_commands(command),
            "incompatibleCommands": _incompatible_commands(command),
            "executionContract": {
                "previewRequired": mutates and effect != "persistent_save",
                "validationRequired": mutates,
                "receiptRequired": mutates,
                "undoRequired": effect == "draft_edit",
                "explicitUserApprovalRequired": effect == "persistent_save",
                "persistentWriteAllowed": effect == "persistent_save",
            },
        }
        records.append(record)
    validate_canonical_command_registry(records)
    return tuple(records)


def canonical_facility_agent_tool_registry() -> tuple[dict[str, Any], ...]:
    records = []
    for source in AGENT_TOOL_SEMANTICS:
        command = deepcopy(dict(source))
        tool_id = command["commandId"]
        owner = _AGENT_TOOL_OWNERS.get(tool_id)
        if owner is None:
            raise FacilityKnowledgeContractError(
                "agent_tool_owner_missing",
                f"Facility agent tool {tool_id} has no deterministic owner.",
            )
        effect = command["effect"]
        if effect not in FACILITY_AGENT_EFFECTS:
            raise FacilityKnowledgeContractError(
                "unknown_agent_tool_effect",
                f"Facility agent tool {tool_id} has an unknown effect.",
            )
        capability_by_tool = {
            "preview_facility_cell_layout": "construction_sage",
            "preview_facility_surface_stack": "construction_sage",
            "preview_facility_create_cell_group": "construction_sage",
            "preview_facility_linear_pattern": "construction_sage",
            "inspect_facility_design_brief": "design_loop_preview",
            "update_facility_design_brief": "design_loop_preview",
            "run_facility_design_preview": "design_loop_preview",
            "apply_facility_design_proposal_draft": "design_loop_apply",
        }
        capability = capability_by_tool.get(
            tool_id,
            "agent_preview" if effect == "preview" else "viewer_v2",
        )
        required_capabilities = [capability]
        if tool_id == "apply_facility_design_proposal_draft":
            required_capabilities.append("agent_write")
        records.append(
            {
                "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
                **command,
                "deterministicOwner": owner,
                "requiredCapabilities": required_capabilities,
                "requiredFeatureFlags": [
                    FACILITY_ALL_CAPABILITY_FLAGS[item]
                    for item in required_capabilities
                ],
                "featureFlagDependencies": {
                    item: list(FACILITY_ALL_CAPABILITY_DEPENDENCIES[item])
                    for item in required_capabilities
                },
                "executionContract": {
                    "modelCalculatesGeometry": False,
                    "mutatesSavedLayout": False,
                    "returnsRevisionBoundEvidence": True,
                    "requiresExplicitUserRequest": effect
                    in {"preview", "design_state_edit", "draft_edit"},
                    "mutatesDesignState": effect == "design_state_edit",
                    "mutatesEditorDraft": effect == "draft_edit",
                    "persistentWriteAllowed": False,
                },
            }
        )
    identifiers = [item["commandId"] for item in records]
    if len(records) != 23 or len(identifiers) != len(set(identifiers)):
        raise FacilityKnowledgeContractError(
            "agent_tool_registry_invalid",
            "Facility agent tool IDs must be 23 unique values.",
        )
    return tuple(records)


def _strategy_space_model(strategy_id: str) -> dict[str, Any]:
    return {
        "geometryEngine": "facility_layout_patterns",
        "strategyId": strategy_id,
        "requiresExactTargetPolygon": True,
        "requiresExactPhysicalFootprints": True,
        "inventedClearanceAllowed": False,
        "serverFeasibilityStatus": "implemented",
    }


def canonical_cell_strategy_registry() -> tuple[dict[str, Any], ...]:
    records = []
    for source in CELL_LAYOUT_STRATEGIES:
        record = deepcopy(dict(source))
        strategy_id = record["strategyId"]
        record.update(
            {
                "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
                "spaceModel": _strategy_space_model(strategy_id),
                "interfaces": {
                    "required": [
                        "materialEntry",
                        "materialExit",
                        "operatorAccess",
                        "serviceAccess",
                    ],
                    "unknownInterfacesRemainUnknown": True,
                },
                "accessAssumptions": {
                    "authoritativeClearanceRequired": True,
                    "lockedAndManualMembersPreserved": True,
                    "routeConnectivityValidatedWhenAuthored": True,
                    "ergonomicComplianceInferred": False,
                },
                "resultMetrics": [
                    "requiredWidth",
                    "requiredDepth",
                    "physicalFootprintArea",
                    "envelopeArea",
                    "minimumPhysicalGap",
                    "contiguousFreeArea",
                    "routeConnectivity",
                    "operatorTravelProxy",
                    "totalMovement",
                    "accessStatus",
                    "accessEvidenceCompleteness",
                    "expansionReserve",
                ],
            }
        )
        records.append(record)
    if len(records) != 10 or len({x["strategyId"] for x in records}) != 10:
        raise FacilityKnowledgeContractError(
            "cell_strategy_registry_invalid",
            "Cell strategy registry must contain ten unique strategies.",
        )
    return tuple(records)


def facility_domain_ontology() -> dict[str, Any]:
    entities = deepcopy(list(FACILITY_ENTITY_CONTRACTS))
    relationships = deepcopy(list(FACILITY_RELATIONSHIP_CONTRACTS))
    entity_ids = [item["entityType"] for item in entities]
    relationship_ids = [item["relationshipType"] for item in relationships]
    if len(entity_ids) != len(set(entity_ids)) or len(relationship_ids) != len(
        set(relationship_ids)
    ):
        raise FacilityKnowledgeContractError(
            "facility_ontology_duplicate_identifier",
            "Facility ontology identifiers must be unique.",
        )
    known_relationships = set(relationship_ids)
    known_entities = set(entity_ids)
    for entity in entities:
        unknown_parents = sorted(set(entity["parentTypes"]) - known_entities)
        unknown_relationships = sorted(
            set(entity["allowedRelationships"]) - known_relationships
        )
        if unknown_parents or unknown_relationships:
            raise FacilityKnowledgeContractError(
                "facility_ontology_reference_invalid",
                "Facility ontology contains unresolved references.",
                details={
                    "entityType": entity["entityType"],
                    "unknownParents": unknown_parents,
                    "unknownRelationships": unknown_relationships,
                },
            )
        entity["evidenceStatuses"] = list(FACILITY_EVIDENCE_STATUSES)
        entity["lifecycleStates"] = list(FACILITY_LIFECYCLE_STATES)
        entity["labelMaySubstituteForIdentity"] = False
    payload = {
        "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
        "recordKind": "facility_domain_ontology",
        "entities": entities,
        "relationships": relationships,
        "evidenceStatuses": list(FACILITY_EVIDENCE_STATUSES),
        "lifecycleStates": list(FACILITY_LIFECYCLE_STATES),
    }
    payload["ontologyRevision"] = facility_knowledge_revision(payload)
    return payload


def facility_sage_responsibility_contract() -> dict[str, Any]:
    payload = deepcopy(dict(FACILITY_RESPONSIBILITY_CONTRACT))
    payload["contractRevision"] = facility_knowledge_revision(payload)
    return payload


def canonical_cell_recipe_registry() -> tuple[dict[str, Any], ...]:
    strategy_ids = {item["strategyId"] for item in CELL_LAYOUT_STRATEGIES}
    command_ids = {
        item["commandId"] for item in canonical_facility_command_registry()
    }
    records = []
    for source in FACILITY_CELL_RECIPES:
        record = deepcopy(dict(source))
        recipe_id = _identifier(record.get("recipeId"), "recipeId")
        unknown = sorted(set(record.get("strategyIds") or ()) - strategy_ids)
        if unknown:
            raise FacilityKnowledgeContractError(
                "cell_recipe_strategy_unknown",
                f"Cell recipe {recipe_id} references unknown strategies.",
                details={"unknown": unknown},
            )
        record.update(
            {
                "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
                "commandIds": [
                    "assets",
                    "cell-layout",
                    "create-cell-group",
                    "relative",
                    "align",
                ],
                "variants": [],
                "prohibitedConditions": [
                    "target geometry is infeasible under deterministic analysis",
                    "required physical footprint evidence is missing",
                    "locked or manual placements would be overwritten",
                ],
                "deterministicValidators": [
                    "target containment",
                    "physical footprint overlap",
                    "known access and service envelopes",
                    "route connectivity when authored",
                ],
                "geometryEngineBypassAllowed": False,
            }
        )
        unknown_commands = sorted(set(record["commandIds"]) - command_ids)
        if unknown_commands:
            raise FacilityKnowledgeContractError(
                "cell_recipe_command_unknown",
                f"Cell recipe {recipe_id} references unknown commands.",
                details={"unknown": unknown_commands},
            )
        records.append(record)
    identifiers = [item["recipeId"] for item in records]
    if len(identifiers) != len(set(identifiers)):
        raise FacilityKnowledgeContractError(
            "cell_recipe_registry_invalid",
            "Cell recipe IDs must be unique.",
        )
    return tuple(records)


def validate_canonical_command_registry(records: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise FacilityKnowledgeContractError(
            "command_registry_invalid",
            "Command registry must be an array.",
        )
    identifiers = []
    owners: dict[str, str] = {}
    required = {
        "schemaVersion",
        "commandId",
        "label",
        "semanticIntent",
        "correctUseCases",
        "incorrectUseCases",
        "supportedStages",
        "entityScope",
        "effect",
        "requiredContext",
        "inputSchema",
        "defaultPolicy",
        "preconditions",
        "deterministicOwner",
        "requiredCapabilities",
        "inputContract",
        "defaults",
        "prohibitedUses",
        "validationRules",
        "failureCodes",
        "receiptShape",
        "undoSemantics",
        "compatibleNextCommands",
        "incompatibleCommands",
        "agentAvailability",
        "uiCommandId",
        "executionContract",
    }
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise FacilityKnowledgeContractError(
                "command_registry_invalid",
                f"Command record {index} must be an object.",
            )
        missing = required - set(record)
        if missing:
            raise FacilityKnowledgeContractError(
                "command_contract_incomplete",
                f"Command record {index} is incomplete.",
                details={"missing": sorted(missing)},
            )
        if record["schemaVersion"] != FACILITY_KNOWLEDGE_SCHEMA_VERSION:
            raise FacilityKnowledgeContractError(
                "unsupported_schema_version",
                "Facility command schema version is unsupported.",
            )
        command_id = _identifier(record["commandId"], "commandId")
        effect = record["effect"]
        if effect not in FACILITY_COMMAND_EFFECTS:
            raise FacilityKnowledgeContractError(
                "unknown_command_effect",
                f"Command {command_id} has an unknown effect.",
            )
        owner = _identifier(record["deterministicOwner"], "deterministicOwner")
        if command_id in owners and owners[command_id] != owner:
            raise FacilityKnowledgeContractError(
                "multiple_deterministic_owners",
                f"Command {command_id} has more than one deterministic owner.",
            )
        owners[command_id] = owner
        identifiers.append(command_id)
    if len(identifiers) != len(set(identifiers)):
        raise FacilityKnowledgeContractError(
            "duplicate_command_id",
            "Facility command IDs must be unique.",
        )
    expected = {item["commandId"] for item in FACILITY_COMMAND_SEMANTICS}
    if set(identifiers) != expected:
        raise FacilityKnowledgeContractError(
            "command_contract_coverage_mismatch",
            "Canonical command registry does not match the runtime surface.",
            details={
                "missing": sorted(expected - set(identifiers)),
                "unknown": sorted(set(identifiers) - expected),
            },
        )


def validate_facility_envelope_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_facility_envelope",
            "Facility envelope request must be an object.",
        )
    allowed = {"width", "depth", "sourceUnit", "displayName", "gridSize"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityKnowledgeContractError(
            "unknown_facility_envelope_field",
            "Facility envelope request contains unknown fields.",
            details={"unknown": unknown},
        )
    width = _finite_positive(value.get("width"), "width")
    depth = _finite_positive(value.get("depth"), "depth")
    unit = str(value.get("sourceUnit") or "").strip().lower()
    if unit not in FACILITY_SOURCE_UNITS:
        raise FacilityKnowledgeContractError(
            "unsupported_source_unit",
            "Facility source unit is unsupported.",
            details={"supported": list(FACILITY_SOURCE_UNITS)},
        )
    factors = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
    width_m = width * factors[unit]
    depth_m = depth * factors[unit]
    if not 0.5 <= width_m <= 10_000.0 or not 0.5 <= depth_m <= 10_000.0:
        raise FacilityKnowledgeContractError(
            "facility_dimension_out_of_bounds",
            "Facility width and depth must each normalize to 0.5 through 10,000 meters.",
        )
    display_name = value.get("displayName", "Facility Layout")
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 120:
        raise FacilityKnowledgeContractError(
            "invalid_facility_display_name",
            "Facility displayName must be 1 through 120 characters.",
        )
    normalized = {
        "widthMeters": width_m,
        "depthMeters": depth_m,
        "source": {"width": width, "depth": depth, "unit": unit},
        "displayName": display_name.strip(),
    }
    if "gridSize" in value:
        grid = _finite_positive(value["gridSize"], "gridSize") * factors[unit]
        normalized["gridSizeMeters"] = grid
    return normalized


def validate_department_partition_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_department_partition",
            "Department partition request must be an object.",
        )
    allowed = {
        "labels",
        "count",
        "proportions",
        "arrangement",
        "orientation",
        "rows",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityKnowledgeContractError(
            "unknown_department_partition_field",
            "Department partition request contains unknown fields.",
            details={"unknown": unknown},
        )
    labels = value.get("labels")
    if labels is None:
        labels = []
    if not isinstance(labels, list) or any(
        not isinstance(item, str) or not item.strip() or len(item) > 120
        for item in labels
    ):
        raise FacilityKnowledgeContractError(
            "invalid_department_labels",
            "Department labels must be non-empty strings of at most 120 characters.",
        )
    count = value.get("count", len(labels))
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
        raise FacilityKnowledgeContractError(
            "department_count_out_of_bounds",
            "Department count must be an integer from 1 through 50.",
        )
    if labels and len(labels) != count:
        raise FacilityKnowledgeContractError(
            "department_label_count_mismatch",
            "Department labels must match the requested count.",
        )
    normalized_labels = [item.strip() for item in labels]
    raw_proportions = value.get("proportions")
    proportions_authored = raw_proportions is not None
    if raw_proportions is not None and (
        not isinstance(raw_proportions, list)
        or len(raw_proportions) != count
    ):
        raise FacilityKnowledgeContractError(
            "invalid_department_proportions",
            "Department proportions must match the department count.",
        )
    normalized_proportions = (
        [
            _finite_positive(proportion, f"proportions[{index}]")
            for index, proportion in enumerate(raw_proportions)
        ]
        if raw_proportions is not None
        else []
    )
    if normalized_proportions:
        total = sum(normalized_proportions)
        normalized_proportions = [
            item / total for item in normalized_proportions
        ]
    arrangement = str(value.get("arrangement") or "deterministic_grid").strip()
    orientation = str(value.get("orientation") or "auto").strip()
    if arrangement not in {
        "deterministic_grid",
        "rows",
        "columns",
        "row_stack",
    }:
        raise FacilityKnowledgeContractError(
            "unsupported_department_arrangement",
            "Department arrangement is unsupported.",
        )
    if orientation not in {"auto", "horizontal", "vertical"}:
        raise FacilityKnowledgeContractError(
            "unsupported_department_orientation",
            "Department orientation is unsupported.",
        )

    raw_rows = value.get("rows")
    normalized_rows: list[dict[str, Any]] | None = None
    assumptions: list[str] = []
    if raw_rows is not None:
        if arrangement != "row_stack":
            raise FacilityKnowledgeContractError(
                "department_rows_require_row_stack",
                "Authored rows require the row_stack arrangement.",
            )
        if orientation not in {"auto", "horizontal"}:
            raise FacilityKnowledgeContractError(
                "department_row_orientation_invalid",
                "Authored rows run west to east and stack north to south.",
            )
        if not normalized_labels:
            raise FacilityKnowledgeContractError(
                "department_rows_require_labels",
                "Authored rows require explicit department labels.",
            )
        label_keys = [item.casefold() for item in normalized_labels]
        if len(label_keys) != len(set(label_keys)):
            raise FacilityKnowledgeContractError(
                "duplicate_department_label",
                "Authored row labels must be unique.",
            )
        if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= count:
            raise FacilityKnowledgeContractError(
                "invalid_department_rows",
                "Rows must contain one through the requested department count.",
            )
        canonical_by_key = dict(zip(label_keys, normalized_labels, strict=True))
        normalized_rows = []
        flattened_keys: list[str] = []
        row_proportion_presence: list[bool] = []
        for row_index, row in enumerate(raw_rows):
            if not isinstance(row, Mapping):
                raise FacilityKnowledgeContractError(
                    "invalid_department_row",
                    "Each authored row must be an object.",
                    details={"rowIndex": row_index},
                )
            unknown_row_fields = sorted(set(row) - {"labels", "proportion"})
            if unknown_row_fields:
                raise FacilityKnowledgeContractError(
                    "unknown_department_row_field",
                    "Authored rows contain unsupported fields.",
                    details={
                        "rowIndex": row_index,
                        "unknown": unknown_row_fields,
                    },
                )
            row_labels = row.get("labels")
            if not isinstance(row_labels, list) or not row_labels:
                raise FacilityKnowledgeContractError(
                    "invalid_department_row_labels",
                    "Each authored row requires at least one department label.",
                    details={"rowIndex": row_index},
                )
            canonical_row_labels = []
            for label in row_labels:
                if not isinstance(label, str) or not label.strip():
                    raise FacilityKnowledgeContractError(
                        "invalid_department_row_labels",
                        "Row labels must be non-empty strings.",
                        details={"rowIndex": row_index},
                    )
                key = label.strip().casefold()
                if key not in canonical_by_key:
                    raise FacilityKnowledgeContractError(
                        "department_row_label_unknown",
                        "Every row label must resolve to a requested department.",
                        details={"rowIndex": row_index, "label": label.strip()},
                    )
                canonical_row_labels.append(canonical_by_key[key])
                flattened_keys.append(key)
            row_proportion = row.get("proportion")
            row_proportion_presence.append(row_proportion is not None)
            normalized_rows.append(
                {
                    "labels": canonical_row_labels,
                    "proportion": (
                        _finite_positive(
                            row_proportion,
                            f"rows[{row_index}].proportion",
                        )
                        if row_proportion is not None
                        else None
                    ),
                }
            )
        if len(flattened_keys) != count or set(flattened_keys) != set(label_keys):
            raise FacilityKnowledgeContractError(
                "department_row_coverage_invalid",
                "Rows must contain every requested department exactly once.",
            )
        if len(flattened_keys) != len(set(flattened_keys)):
            raise FacilityKnowledgeContractError(
                "department_row_label_duplicate",
                "A department cannot appear in more than one row.",
            )
        if any(row_proportion_presence) and not all(row_proportion_presence):
            raise FacilityKnowledgeContractError(
                "incomplete_department_row_proportions",
                "Row proportions must be supplied for every row or none.",
            )

        index_by_key = {key: index for index, key in enumerate(label_keys)}
        if all(row_proportion_presence):
            row_total = sum(float(row["proportion"]) for row in normalized_rows)
            for row in normalized_rows:
                row["proportion"] = float(row["proportion"]) / row_total
            if proportions_authored:
                for row_index, row in enumerate(normalized_rows):
                    requested_share = sum(
                        normalized_proportions[index_by_key[label.casefold()]]
                        for label in row["labels"]
                    )
                    if not math.isclose(
                        requested_share,
                        float(row["proportion"]),
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    ):
                        raise FacilityKnowledgeContractError(
                            "department_row_area_conflict",
                            "Row proportions conflict with department area proportions.",
                            details={"rowIndex": row_index},
                        )
            else:
                normalized_proportions = [0.0] * count
                for row in normalized_rows:
                    per_department = float(row["proportion"]) / len(row["labels"])
                    for label in row["labels"]:
                        normalized_proportions[index_by_key[label.casefold()]] = (
                            per_department
                        )
                assumptions.append("equal_width_within_authored_rows")
        else:
            if not proportions_authored:
                normalized_proportions = [1.0 / count] * count
                assumptions.append("equal_area_partition")
            for row in normalized_rows:
                row["proportion"] = sum(
                    normalized_proportions[index_by_key[label.casefold()]]
                    for label in row["labels"]
                )
    else:
        if arrangement == "row_stack":
            raise FacilityKnowledgeContractError(
                "department_rows_required",
                "The row_stack arrangement requires authored rows.",
            )
        if not proportions_authored:
            normalized_proportions = [1.0 / count] * count
            assumptions.append("equal_area_partition")

    area_sizing = (
        "authored_department_proportions"
        if proportions_authored
        else (
            "authored_row_proportions"
            if normalized_rows is not None
            and any(item.get("proportion") is not None for item in raw_rows)
            else "equal_area"
        )
    )
    return {
        "count": count,
        "labels": normalized_labels,
        "proportions": normalized_proportions,
        "arrangement": arrangement,
        "orientation": orientation,
        "rows": normalized_rows,
        "rowOrder": "north_to_south" if normalized_rows is not None else None,
        "areaSizing": area_sizing,
        "assumptions": assumptions,
        "inventedCorridor": False,
        "inventedSafetySeparation": False,
        "inventedExpansionReserve": False,
    }


def _validate_intent_facility_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept authored or already-normalized envelope content idempotently."""

    if set(value) <= {"width", "depth", "sourceUnit", "displayName", "gridSize"}:
        return validate_facility_envelope_request(value)
    required = {"widthMeters", "depthMeters", "source", "displayName"}
    allowed = required | {"gridSizeMeters"}
    if not required <= set(value) or set(value) - allowed:
        raise FacilityKnowledgeContractError(
            "invalid_facility_envelope",
            "Normalized Facility envelope fields are invalid.",
        )
    source = value.get("source")
    if not isinstance(source, Mapping) or set(source) != {"width", "depth", "unit"}:
        raise FacilityKnowledgeContractError(
            "invalid_facility_envelope",
            "Normalized Facility envelope source is invalid.",
        )
    request = {
        "width": source["width"],
        "depth": source["depth"],
        "sourceUnit": source["unit"],
        "displayName": value["displayName"],
    }
    if "gridSizeMeters" in value:
        factors = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
        unit = str(source["unit"]).strip().lower()
        if unit not in factors:
            raise FacilityKnowledgeContractError(
                "unsupported_source_unit",
                "Facility source unit is unsupported.",
            )
        request["gridSize"] = float(value["gridSizeMeters"]) / factors[unit]
    normalized = validate_facility_envelope_request(request)
    if normalized != dict(value):
        raise FacilityKnowledgeContractError(
            "facility_envelope_normalization_mismatch",
            "Normalized Facility envelope does not match its source values.",
        )
    return normalized


def facility_intent_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:inspectorp:facility-layout:intent:v1",
        "title": "Facility Layout Intent",
        "type": "object",
        "required": [
            "schemaVersion",
            "intentId",
            "mode",
            "facilityEnvelope",
            "originConvention",
            "departments",
            "circulation",
            "cells",
            "resources",
            "staging",
            "floorCommunication",
            "utilities",
            "expansion",
            "hardConstraints",
            "preferences",
            "assumptions",
            "unresolvedItems",
            "sourceRevisionBindings",
            "authorityBindings",
            "executionMode",
            "savePolicy",
            "prototypeMode",
        ],
        "additionalProperties": False,
        "properties": {
            "schemaVersion": {"const": FACILITY_KNOWLEDGE_SCHEMA_VERSION},
            "intentId": {"type": "string"},
            "mode": {"enum": list(FACILITY_INTENT_MODES)},
            "facilityEnvelope": {"type": ["object", "null"]},
            "originConvention": {"type": "object"},
            "departments": {"type": "array", "maxItems": 50},
            "circulation": {"type": "array"},
            "cells": {"type": "array"},
            "resources": {"type": "array"},
            "staging": {"type": "array"},
            "floorCommunication": {"type": "array"},
            "utilities": {"type": "array"},
            "expansion": {"type": ["object", "null"]},
            "hardConstraints": {"type": "array"},
            "preferences": {"type": "array"},
            "assumptions": {"type": "array"},
            "unresolvedItems": {"type": "array"},
            "sourceRevisionBindings": {"type": "array"},
            "authorityBindings": {"type": "array"},
            "executionMode": {"enum": list(FACILITY_EXECUTION_MODES)},
            "savePolicy": {"enum": list(FACILITY_SAVE_POLICIES)},
            "prototypeMode": {"type": "boolean"},
        },
    }


_FACILITY_INTENT_FIELDS = frozenset(facility_intent_schema()["properties"])
_FORBIDDEN_INTENT_COORDINATE_FIELDS = frozenset(
    {
        "x",
        "y",
        "z",
        "worldX",
        "worldY",
        "worldZ",
        "screenX",
        "screenY",
        "transform",
        "position",
        "quaternion",
        "vertices",
        "centerline",
    }
)


def _reject_model_authored_coordinates(value: Any, path: str = "intent") -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_INTENT_COORDINATE_FIELDS)
        if forbidden:
            raise FacilityKnowledgeContractError(
                "model_authored_geometry_forbidden",
                "Facility intent cannot contain model-authored coordinates or transforms.",
                details={"path": path, "fields": forbidden},
            )
        for key, nested in value.items():
            _reject_model_authored_coordinates(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_model_authored_coordinates(nested, f"{path}[{index}]")


def _intent_semantic_record(
    value: Any,
    *,
    field: str,
    required_fields: Sequence[str],
    optional_fields: Sequence[str] = (),
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_facility_intent_record",
            f"{field} entries must be objects.",
        )
    allowed = set(required_fields) | set(optional_fields)
    missing = sorted(set(required_fields) - set(value))
    unknown = sorted(set(value) - allowed)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "invalid_facility_intent_record",
            f"{field} entry fields are invalid.",
            details={"field": field, "missing": missing, "unknown": unknown},
        )
    return deepcopy(dict(value))


def validate_facility_intent(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_facility_intent",
            "Facility intent must be an object.",
        )
    missing = sorted(_FACILITY_INTENT_FIELDS - set(value))
    unknown = sorted(set(value) - _FACILITY_INTENT_FIELDS)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "facility_intent_shape_invalid",
            "Facility intent fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    if value["schemaVersion"] != FACILITY_KNOWLEDGE_SCHEMA_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Facility intent schema version is unsupported.",
        )
    _identifier(value["intentId"], "intentId")
    if value["mode"] not in FACILITY_INTENT_MODES:
        raise FacilityKnowledgeContractError(
            "unsupported_facility_intent_mode",
            "Facility intent mode is unsupported.",
        )
    if value["executionMode"] not in FACILITY_EXECUTION_MODES:
        raise FacilityKnowledgeContractError(
            "unsupported_facility_execution_mode",
            "Facility execution mode is unsupported.",
        )
    if value["savePolicy"] not in FACILITY_SAVE_POLICIES:
        raise FacilityKnowledgeContractError(
            "unsupported_facility_save_policy",
            "Facility save policy must require a separate explicit user command.",
        )
    if not isinstance(value["prototypeMode"], bool):
        raise FacilityKnowledgeContractError(
            "invalid_prototype_mode",
            "prototypeMode must be a boolean.",
        )
    if value["mode"] == "greenfield" and value["facilityEnvelope"] is None:
        raise FacilityKnowledgeContractError(
            "facility_envelope_required",
            "Greenfield Facility intent requires an authored envelope.",
        )
    result = deepcopy(dict(value))
    if result["facilityEnvelope"] is not None:
        result["facilityEnvelope"] = _validate_intent_facility_envelope(
            result["facilityEnvelope"]
        )
    origin = _intent_semantic_record(
        result["originConvention"],
        field="originConvention",
        required_fields=("origin", "northDirection"),
        optional_fields=("source",),
    )
    if origin["origin"] not in {
        "southwest_floor_corner",
        "northwest_floor_corner",
        "existing_layout_frame",
    } or origin["northDirection"] not in {"positive_x", "positive_z"}:
        raise FacilityKnowledgeContractError(
            "unsupported_origin_convention",
            "Facility origin or north-direction convention is unsupported.",
        )
    result["originConvention"] = origin
    list_fields = (
        "departments",
        "circulation",
        "cells",
        "resources",
        "staging",
        "floorCommunication",
        "utilities",
        "hardConstraints",
        "preferences",
        "assumptions",
        "unresolvedItems",
        "sourceRevisionBindings",
        "authorityBindings",
    )
    for field in list_fields:
        if not isinstance(result[field], list):
            raise FacilityKnowledgeContractError(
                "invalid_facility_intent_collection",
                f"{field} must be an array.",
            )
    if not 1 <= len(result["departments"]) <= 50:
        raise FacilityKnowledgeContractError(
            "department_count_out_of_bounds",
            "Facility intent must contain 1 through 50 departments.",
        )
    normalized_departments = []
    for department in result["departments"]:
        record = _intent_semantic_record(
            department,
            field="departments",
            required_fields=("requestId", "label", "semanticType", "quantity"),
            optional_fields=(
                "proportion",
                "minimumArea",
                "maximumArea",
                "adjacentTo",
                "separatedFrom",
                "flowDirection",
            ),
        )
        _identifier(record["requestId"], "departments.requestId")
        if not isinstance(record["label"], str) or not record["label"].strip():
            raise FacilityKnowledgeContractError(
                "invalid_department_labels",
                "Department label must be non-empty.",
            )
        _identifier(record["semanticType"], "departments.semanticType")
        if (
            isinstance(record["quantity"], bool)
            or not isinstance(record["quantity"], int)
            or record["quantity"] < 1
        ):
            raise FacilityKnowledgeContractError(
                "invalid_department_quantity",
                "Department quantity must be a positive integer.",
            )
        for field in ("proportion", "minimumArea", "maximumArea"):
            if field in record:
                record[field] = _finite_positive(
                    record[field], f"departments.{field}"
                )
        normalized_departments.append(record)
    total_department_quantity = sum(
        record["quantity"] for record in normalized_departments
    )
    if total_department_quantity > 50:
        raise FacilityKnowledgeContractError(
            "department_count_out_of_bounds",
            "Total requested department quantity cannot exceed 50.",
        )
    request_ids = [record["requestId"] for record in normalized_departments]
    if len(request_ids) != len(set(request_ids)):
        raise FacilityKnowledgeContractError(
            "duplicate_department_request_id",
            "Department request IDs must be unique.",
        )
    proportion_presence = [
        "proportion" in record for record in normalized_departments
    ]
    if any(proportion_presence) and not all(proportion_presence):
        raise FacilityKnowledgeContractError(
            "incomplete_department_proportions",
            "Department proportions must be supplied for every department or none.",
        )
    if all(proportion_presence):
        total_proportion = sum(
            record["proportion"] for record in normalized_departments
        )
        for record in normalized_departments:
            record["proportion"] /= total_proportion
    else:
        equal_proportion = 1.0 / len(normalized_departments)
        for record in normalized_departments:
            record["proportion"] = equal_proportion
        result["assumptions"].append("equal_area_partition")
    result["departments"] = normalized_departments
    for binding in result["sourceRevisionBindings"]:
        record = _intent_semantic_record(
            binding,
            field="sourceRevisionBindings",
            required_fields=("sourceId", "revision", "evidenceStatus"),
        )
        _identifier(record["sourceId"], "sourceId")
        if record["evidenceStatus"] not in FACILITY_EVIDENCE_STATUSES:
            raise FacilityKnowledgeContractError(
                "invalid_evidence_status",
                "Source binding evidence status is unsupported.",
            )
    for binding in result["authorityBindings"]:
        record = _intent_semantic_record(
            binding,
            field="authorityBindings",
            required_fields=("authorityId", "status", "source"),
        )
        _identifier(record["authorityId"], "authorityId")
        if record["status"] not in {"pending", "reviewed", "approved"}:
            raise FacilityKnowledgeContractError(
                "invalid_authority_status",
                "Authority binding status is unsupported.",
            )
        if record["status"] == "approved" and record["source"] != "human":
            raise FacilityKnowledgeContractError(
                "human_authority_required",
                "Only a human-authored binding may carry approved authority.",
            )
    _reject_model_authored_coordinates(result)
    canonical_facility_knowledge_bytes(result)
    return result


def validate_generation_substage(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_substage",
            "Generation substage must be an object.",
        )
    required = {
        "substageId",
        "sequence",
        "status",
        "operationCount",
        "plannedInstanceCount",
        "operationReceiptIds",
        "validation",
        "affectedStableIds",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_substage_shape_invalid",
            "Generation substage fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    _identifier(result["substageId"], "substageId")
    if result["status"] not in FACILITY_SUBSTAGE_STATUSES:
        raise FacilityKnowledgeContractError(
            "invalid_generation_substage_status",
            "Generation substage status is unsupported.",
        )
    if (
        isinstance(result["sequence"], bool)
        or not isinstance(result["sequence"], int)
        or result["sequence"] < 1
    ):
        raise FacilityKnowledgeContractError(
            "invalid_generation_substage_sequence",
            "Generation substage sequence must be a positive integer.",
        )
    for field, maximum in (
        ("operationCount", FACILITY_MAXIMUM_OPERATION_BATCH),
        ("plannedInstanceCount", FACILITY_MAXIMUM_PLANNED_INSTANCES),
    ):
        count = result[field]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= maximum
        ):
            raise FacilityKnowledgeContractError(
                "generation_substage_budget_exceeded",
                f"{field} must be between zero and {maximum}.",
                details={"field": field, "maximum": maximum},
            )
    for field in ("operationReceiptIds", "affectedStableIds"):
        if not isinstance(result[field], list) or any(
            not isinstance(item, str) or not item for item in result[field]
        ):
            raise FacilityKnowledgeContractError(
                "invalid_generation_substage_field",
                f"{field} must be an array of stable IDs.",
            )
    if not isinstance(result["validation"], Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_substage_validation",
            "Generation substage validation must be an object.",
        )
    return result


def validate_generation_invalidation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_invalidation",
            "Generation invalidation must be an object.",
        )
    required = {
        "invalidationId",
        "upstreamStageId",
        "affectedStageIds",
        "reason",
        "dependencyFingerprintBefore",
        "dependencyFingerprintAfter",
        "createdAt",
        "resolved",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_invalidation_shape_invalid",
            "Generation invalidation fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    _identifier(result["invalidationId"], "invalidationId")
    valid_stage_ids = {item["stageId"] for item in FACILITY_GENERATION_STAGES}
    if result["upstreamStageId"] not in valid_stage_ids:
        raise FacilityKnowledgeContractError(
            "unknown_generation_stage",
            "Invalidation upstream stage is unknown.",
        )
    if not isinstance(result["affectedStageIds"], list) or not result[
        "affectedStageIds"
    ]:
        raise FacilityKnowledgeContractError(
            "invalid_invalidation_targets",
            "Invalidation must name at least one affected stage.",
        )
    if set(result["affectedStageIds"]) - valid_stage_ids:
        raise FacilityKnowledgeContractError(
            "unknown_generation_stage",
            "Invalidation contains an unknown affected stage.",
        )
    if result["reason"] not in FACILITY_INVALIDATION_REASONS:
        raise FacilityKnowledgeContractError(
            "invalid_invalidation_reason",
            "Generation invalidation reason is unsupported.",
        )
    _sha256(result["dependencyFingerprintBefore"], "dependencyFingerprintBefore")
    _sha256(result["dependencyFingerprintAfter"], "dependencyFingerprintAfter")
    if not isinstance(result["createdAt"], str) or not result["createdAt"].endswith("Z"):
        raise FacilityKnowledgeContractError(
            "invalid_generation_timestamp",
            "Invalidation createdAt must be a UTC timestamp ending in Z.",
        )
    if not isinstance(result["resolved"], bool):
        raise FacilityKnowledgeContractError(
            "invalid_invalidation_resolution",
            "Invalidation resolved must be a boolean.",
        )
    return result


def validate_generation_stage(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage",
            "Generation stage must be an object.",
        )
    required = {
        "stageId",
        "sequence",
        "dependsOn",
        "status",
        "inputs",
        "selectedCommandIds",
        "previewId",
        "substageGraph",
        "operationReceiptIds",
        "validation",
        "affectedStableIds",
        "assumptions",
        "unresolvedFindings",
        "invalidationEdges",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_stage_incomplete",
            "Generation stage fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    stage_id = _identifier(value["stageId"], "stageId")
    valid_stage_ids = {item["stageId"] for item in FACILITY_GENERATION_STAGES}
    if stage_id not in valid_stage_ids:
        raise FacilityKnowledgeContractError(
            "unknown_generation_stage",
            f"Unknown generation stage: {stage_id}.",
        )
    if value["status"] not in FACILITY_STAGE_STATUSES:
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_status",
            "Generation stage status is unsupported.",
        )
    if isinstance(value["sequence"], bool) or not isinstance(value["sequence"], int):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_sequence",
            "Generation stage sequence must be an integer.",
        )
    stage_definition = next(
        item for item in FACILITY_GENERATION_STAGES if item["stageId"] == stage_id
    )
    if value["sequence"] != stage_definition["sequence"] or value[
        "dependsOn"
    ] != list(stage_definition["dependsOn"]):
        raise FacilityKnowledgeContractError(
            "generation_stage_dependency_mismatch",
            "Generation stage sequence and dependencies must match the frozen graph.",
            details={"stageId": stage_id},
        )
    result = deepcopy(dict(value))
    if not isinstance(result["inputs"], Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_field",
            "inputs must be an object.",
        )
    for field in (
        "dependsOn",
        "selectedCommandIds",
        "operationReceiptIds",
        "affectedStableIds",
        "assumptions",
        "unresolvedFindings",
    ):
        if not isinstance(result[field], list):
            raise FacilityKnowledgeContractError(
                "invalid_generation_stage_field",
                f"{field} must be an array.",
            )
    known_command_ids = {item["commandId"] for item in FACILITY_COMMAND_SEMANTICS}
    unknown_commands = sorted(set(result["selectedCommandIds"]) - known_command_ids)
    if unknown_commands:
        raise FacilityKnowledgeContractError(
            "unknown_registry_identifier",
            "Generation stage selected unknown semantic commands.",
            details={"collection": "commands", "unknown": unknown_commands},
        )
    command_by_id = {
        item["commandId"]: item for item in canonical_facility_command_registry()
    }
    unsupported = sorted(
        command_id
        for command_id in result["selectedCommandIds"]
        if stage_id not in command_by_id[command_id]["supportedStages"]
    )
    if unsupported:
        raise FacilityKnowledgeContractError(
            "command_not_supported_for_stage",
            "Generation stage selected commands outside their supported stages.",
            details={"stageId": stage_id, "commandIds": unsupported},
        )
    if not isinstance(result["substageGraph"], list):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_field",
            "substageGraph must be an array.",
        )
    substages = [validate_generation_substage(item) for item in result["substageGraph"]]
    if [item["sequence"] for item in substages] != list(
        range(1, len(substages) + 1)
    ):
        raise FacilityKnowledgeContractError(
            "generation_substage_order_invalid",
            "Generation substages must use contiguous one-based sequence values.",
        )
    if len({item["substageId"] for item in substages}) != len(substages):
        raise FacilityKnowledgeContractError(
            "generation_substage_duplicate",
            "Generation substage IDs must be unique within a stage.",
        )
    if not isinstance(result["invalidationEdges"], list) or any(
        not isinstance(item, str) or not item for item in result["invalidationEdges"]
    ):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_field",
            "invalidationEdges must be an array of stable IDs.",
        )
    if not isinstance(result["validation"], Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_validation",
            "Generation stage validation must be an object.",
        )
    return result


def default_generation_stage_graph() -> list[dict[str, Any]]:
    records = []
    for stage in FACILITY_GENERATION_STAGES:
        records.append(
            {
                "stageId": stage["stageId"],
                "sequence": stage["sequence"],
                "dependsOn": list(stage["dependsOn"]),
                "status": "ready" if stage["sequence"] == 1 else "pending",
                "inputs": {},
                "selectedCommandIds": [],
                "previewId": None,
                "substageGraph": [],
                "operationReceiptIds": [],
                "validation": {"status": "pending", "findingIds": []},
                "affectedStableIds": [],
                "assumptions": [],
                "unresolvedFindings": [],
                "invalidationEdges": [],
            }
        )
    return records


def validate_generation_stage_receipt(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_stage_receipt",
            "Generation stage receipt must be an object.",
        )
    required = {
        "schemaVersion",
        "receiptId",
        "runId",
        "stageId",
        "substageId",
        "stageSequence",
        "turnSequence",
        "baseDraftRevision",
        "resultDraftRevision",
        "dependencyFingerprint",
        "selectedCommandIds",
        "operationCount",
        "plannedInstanceCount",
        "operationsHash",
        "affectedStableIds",
        "validation",
        "status",
        "createdAt",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_shape_invalid",
            "Generation stage receipt fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    if result["schemaVersion"] != FACILITY_GENERATION_RUN_SCHEMA_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Generation stage receipt schema version is unsupported.",
        )
    _identifier(result["receiptId"], "receiptId")
    if not isinstance(result["runId"], str) or _RUN_ID_RE.fullmatch(result["runId"]) is None:
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_id",
            "Generation stage receipt run ID is invalid.",
        )
    stage_id = _identifier(result["stageId"], "stageId")
    stage = next(
        (item for item in FACILITY_GENERATION_STAGES if item["stageId"] == stage_id),
        None,
    )
    if stage is None or result["stageSequence"] != stage["sequence"]:
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_stage_invalid",
            "Generation stage receipt does not match the frozen stage graph.",
        )
    if result["substageId"] is not None:
        _identifier(result["substageId"], "substageId")
    for field in ("turnSequence", "operationCount", "plannedInstanceCount"):
        number = result[field]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise FacilityKnowledgeContractError(
                "generation_stage_receipt_count_invalid",
                f"{field} must be a non-negative integer.",
            )
    if (
        result["operationCount"] > FACILITY_MAXIMUM_OPERATION_BATCH
        or result["plannedInstanceCount"] > FACILITY_MAXIMUM_PLANNED_INSTANCES
    ):
        raise FacilityKnowledgeContractError(
            "generation_substage_budget_exceeded",
            "Generation stage receipt exceeds the 500-item substage budget.",
        )
    for field in (
        "baseDraftRevision",
        "resultDraftRevision",
        "dependencyFingerprint",
        "operationsHash",
    ):
        _sha256(result[field], field)
    if not isinstance(result["selectedCommandIds"], list):
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_commands_invalid",
            "selectedCommandIds must be an array.",
        )
    commands = {item["commandId"]: item for item in canonical_facility_command_registry()}
    unknown_commands = sorted(set(result["selectedCommandIds"]) - set(commands))
    unsupported = sorted(
        command_id
        for command_id in result["selectedCommandIds"]
        if command_id in commands and stage_id not in commands[command_id]["supportedStages"]
    )
    if unknown_commands or unsupported:
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_commands_invalid",
            "Generation stage receipt contains unknown or unsupported commands.",
            details={"unknown": unknown_commands, "unsupported": unsupported},
        )
    if not isinstance(result["affectedStableIds"], list) or any(
        not isinstance(item, str) or not item for item in result["affectedStableIds"]
    ):
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_affected_ids_invalid",
            "affectedStableIds must contain stable non-empty IDs.",
        )
    if not isinstance(result["validation"], Mapping):
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_validation_invalid",
            "Generation stage receipt validation must be an object.",
        )
    if result["status"] not in FACILITY_STAGE_RECEIPT_STATUSES:
        raise FacilityKnowledgeContractError(
            "generation_stage_receipt_status_invalid",
            "Generation stage receipt status is unsupported.",
        )
    if not isinstance(result["createdAt"], str) or not result["createdAt"].endswith("Z"):
        raise FacilityKnowledgeContractError(
            "invalid_generation_timestamp",
            "Generation stage receipt createdAt must be UTC and end in Z.",
        )
    return result


def validate_generation_cumulative_proposal(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_cumulative_proposal",
            "Cumulative proposal must be an object.",
        )
    required = {
        "proposalId",
        "runId",
        "baseLayoutRevision",
        "draftLayoutRevision",
        "receiptChain",
        "dependencyFingerprint",
        "cumulativeDiffHash",
        "validation",
        "saveEligibility",
        "generatedAt",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "cumulative_proposal_shape_invalid",
            "Cumulative proposal fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    _identifier(result["proposalId"], "proposalId")
    if not isinstance(result["runId"], str) or _RUN_ID_RE.fullmatch(result["runId"]) is None:
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_id",
            "Cumulative proposal run ID is invalid.",
        )
    for field in (
        "baseLayoutRevision",
        "draftLayoutRevision",
        "dependencyFingerprint",
        "cumulativeDiffHash",
    ):
        _sha256(result[field], field)
    if not isinstance(result["receiptChain"], list) or any(
        not isinstance(item, str) or not item for item in result["receiptChain"]
    ):
        raise FacilityKnowledgeContractError(
            "invalid_receipt_chain",
            "Cumulative proposal receiptChain must be an array of stable IDs.",
        )
    if not isinstance(result["validation"], Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_cumulative_proposal_validation",
            "Cumulative proposal validation must be an object.",
        )
    if result["saveEligibility"] not in FACILITY_SAVE_ELIGIBILITY:
        raise FacilityKnowledgeContractError(
            "invalid_save_eligibility",
            "Cumulative proposal save eligibility is unsupported.",
        )
    if not isinstance(result["generatedAt"], str) or not result["generatedAt"].endswith("Z"):
        raise FacilityKnowledgeContractError(
            "invalid_generation_timestamp",
            "Cumulative proposal generatedAt must be a UTC timestamp ending in Z.",
        )
    return result


def validate_generation_save_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_save_receipt",
            "Generation save receipt must be an object.",
        )
    required = {
        "schemaVersion",
        "saveReceiptId",
        "runId",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "baseLayoutRevision",
        "savedLayoutRevision",
        "cumulativeDiffHash",
        "dependencyFingerprint",
        "receiptChain",
        "approvedBy",
        "approvedAt",
        "persistedAt",
        "approvalSource",
    }
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_save_receipt_shape_invalid",
            "Generation save receipt fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    result = deepcopy(dict(value))
    if result["schemaVersion"] != FACILITY_GENERATION_RUN_SCHEMA_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Generation save receipt schema version is unsupported.",
        )
    _identifier(result["saveReceiptId"], "saveReceiptId")
    if not isinstance(result["runId"], str) or _RUN_ID_RE.fullmatch(result["runId"]) is None:
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_id",
            "Generation save receipt run ID is invalid.",
        )
    for field in (
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "approvedBy",
    ):
        _identifier(result[field], field)
    for field in (
        "baseLayoutRevision",
        "savedLayoutRevision",
        "cumulativeDiffHash",
        "dependencyFingerprint",
    ):
        _sha256(result[field], field)
    if not isinstance(result["receiptChain"], list) or not result["receiptChain"]:
        raise FacilityKnowledgeContractError(
            "invalid_receipt_chain",
            "Generation save receipt must bind the complete non-empty receipt chain.",
        )
    if result["approvalSource"] != "explicit_user_command":
        raise FacilityKnowledgeContractError(
            "explicit_approval_required",
            "Generation save receipt requires explicit user approval.",
        )
    for field in ("approvedAt", "persistedAt"):
        if not isinstance(result[field], str) or not result[field].endswith("Z"):
            raise FacilityKnowledgeContractError(
                "invalid_generation_timestamp",
                f"{field} must be a UTC timestamp ending in Z.",
            )
    return result


def validate_generation_run(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "invalid_generation_run",
            "Generation run must be an object.",
        )
    required = {
        "schemaVersion",
        "runId",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "userId",
        "sessionId",
        "baseLayoutRevision",
        "effectiveProvider",
        "effectiveModel",
        "reasoningEffort",
        "intentHash",
        "dependencyFingerprint",
        "stageGraph",
        "currentStageId",
        "resumePoint",
        "receiptChain",
        "invalidations",
        "status",
        "writable",
        "writableLease",
        "prototypeMode",
        "createdAt",
        "updatedAt",
        "lastActivityAt",
        "expiresAt",
        "cumulativeDiffHash",
        "cumulativeProposal",
        "saveEligibility",
        "terminalReason",
    }
    unknown = sorted(set(value) - required - {"gatewayRevision"})
    missing = sorted(required - set(value))
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            "generation_run_shape_invalid",
            "Generation run fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )
    if value["schemaVersion"] != FACILITY_GENERATION_RUN_SCHEMA_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Generation run schema version is unsupported.",
        )
    run_id = value["runId"]
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_id",
            "Generation run ID is invalid.",
        )
    for field in (
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "userId",
        "sessionId",
    ):
        _identifier(value[field], field)
    for field in ("baseLayoutRevision", "intentHash", "dependencyFingerprint"):
        _sha256(value[field], field)
    if value["cumulativeDiffHash"] is not None:
        _sha256(value["cumulativeDiffHash"], "cumulativeDiffHash")
    if value["status"] not in FACILITY_RUN_STATUSES:
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_status",
            "Generation run status is unsupported.",
        )
    if value["saveEligibility"] not in FACILITY_SAVE_ELIGIBILITY:
        raise FacilityKnowledgeContractError(
            "invalid_save_eligibility",
            "Generation run save eligibility is unsupported.",
        )
    if not isinstance(value["writable"], bool) or not isinstance(
        value["prototypeMode"], bool
    ):
        raise FacilityKnowledgeContractError(
            "invalid_generation_run_boolean",
            "writable and prototypeMode must be booleans.",
        )
    if not isinstance(value["stageGraph"], list) or len(value["stageGraph"]) != 10:
        raise FacilityKnowledgeContractError(
            "generation_stage_graph_invalid",
            "Generation run must contain all ten stages.",
        )
    stages = [validate_generation_stage(item) for item in value["stageGraph"]]
    expected_ids = [item["stageId"] for item in FACILITY_GENERATION_STAGES]
    if [item["stageId"] for item in stages] != expected_ids:
        raise FacilityKnowledgeContractError(
            "generation_stage_graph_invalid",
            "Generation stages must use the frozen order.",
        )
    if value["currentStageId"] is not None and value["currentStageId"] not in expected_ids:
        raise FacilityKnowledgeContractError(
            "unknown_generation_stage",
            "currentStageId is not in the generation graph.",
        )
    if not isinstance(value["receiptChain"], list) or any(
        not isinstance(item, str) or not item for item in value["receiptChain"]
    ):
        raise FacilityKnowledgeContractError(
            "invalid_receipt_chain",
            "receiptChain must be an array.",
        )
    if not isinstance(value["invalidations"], list):
        raise FacilityKnowledgeContractError(
            "invalid_generation_invalidations",
            "invalidations must be an array.",
        )
    invalidations = [
        validate_generation_invalidation(item) for item in value["invalidations"]
    ]
    invalidation_ids = [item["invalidationId"] for item in invalidations]
    if len(invalidation_ids) != len(set(invalidation_ids)):
        raise FacilityKnowledgeContractError(
            "duplicate_generation_invalidation",
            "Generation invalidation IDs must be unique.",
        )
    unknown_invalidation_edges = sorted(
        {
            edge
            for stage in stages
            for edge in stage["invalidationEdges"]
            if edge not in set(invalidation_ids)
        }
    )
    if unknown_invalidation_edges:
        raise FacilityKnowledgeContractError(
            "generation_invalidation_reference_invalid",
            "Generation stage references an unknown invalidation.",
            details={"unknown": unknown_invalidation_edges},
        )
    if value["resumePoint"] is not None:
        if not isinstance(value["resumePoint"], Mapping):
            raise FacilityKnowledgeContractError(
                "invalid_generation_resume_point",
                "resumePoint must be an object or null.",
            )
        allowed_resume = {"stageId", "substageId", "turnSequence"}
        if set(value["resumePoint"]) != allowed_resume:
            raise FacilityKnowledgeContractError(
                "invalid_generation_resume_point",
                "resumePoint fields are invalid.",
            )
        if value["resumePoint"]["stageId"] not in expected_ids:
            raise FacilityKnowledgeContractError(
                "unknown_generation_stage",
                "resumePoint stageId is unknown.",
            )
        if value["resumePoint"]["substageId"] is not None:
            _identifier(value["resumePoint"]["substageId"], "substageId")
        if (
            isinstance(value["resumePoint"]["turnSequence"], bool)
            or not isinstance(value["resumePoint"]["turnSequence"], int)
            or value["resumePoint"]["turnSequence"] < 0
        ):
            raise FacilityKnowledgeContractError(
                "invalid_generation_resume_point",
                "resumePoint turnSequence must be a non-negative integer.",
            )
    if value["writableLease"] is not None:
        if not isinstance(value["writableLease"], Mapping):
            raise FacilityKnowledgeContractError(
                "invalid_generation_writable_lease",
                "writableLease must be an object or null.",
            )
        lease_required = {
            "layoutId",
            "runId",
            "ownerToken",
            "leaseRevision",
            "acquiredAt",
            "updatedAt",
            "expiresAt",
        }
        if set(value["writableLease"]) != lease_required:
            raise FacilityKnowledgeContractError(
                "invalid_generation_writable_lease",
                "writableLease fields are invalid.",
            )
        if value["writableLease"]["runId"] != value["runId"] or value[
            "writableLease"
        ]["layoutId"] != value["layoutId"]:
            raise FacilityKnowledgeContractError(
                "invalid_generation_writable_lease",
                "writableLease does not match its generation run.",
            )
        _identifier(value["writableLease"]["ownerToken"], "ownerToken")
        _sha256(value["writableLease"]["leaseRevision"], "leaseRevision")
        for field in ("acquiredAt", "updatedAt", "expiresAt"):
            timestamp = value["writableLease"][field]
            if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
                raise FacilityKnowledgeContractError(
                    "invalid_generation_timestamp",
                    f"writableLease.{field} must be a UTC timestamp ending in Z.",
                )
    if value["writable"] != (value["writableLease"] is not None):
        raise FacilityKnowledgeContractError(
            "generation_writable_lease_mismatch",
            "writable must match writableLease presence.",
        )
    if value["cumulativeProposal"] is not None:
        proposal = validate_generation_cumulative_proposal(
            value["cumulativeProposal"]
        )
        if proposal["runId"] != value["runId"]:
            raise FacilityKnowledgeContractError(
                "cumulative_proposal_run_mismatch",
                "Cumulative proposal does not belong to its generation run.",
            )
        if proposal["cumulativeDiffHash"] != value["cumulativeDiffHash"]:
            raise FacilityKnowledgeContractError(
                "cumulative_proposal_diff_mismatch",
                "Cumulative proposal hash does not match its generation run.",
            )
    if value["terminalReason"] is not None and (
        not isinstance(value["terminalReason"], str)
        or not value["terminalReason"].strip()
    ):
        raise FacilityKnowledgeContractError(
            "invalid_generation_terminal_reason",
            "terminalReason must be a non-empty string or null.",
        )
    for field in ("effectiveProvider", "effectiveModel"):
        _identifier(value[field], field)
    if "gatewayRevision" in value:
        _sha256(value["gatewayRevision"], "gatewayRevision")
    if value["reasoningEffort"] is not None:
        _identifier(value["reasoningEffort"], "reasoningEffort")
    for field in ("createdAt", "updatedAt", "lastActivityAt", "expiresAt"):
        if not isinstance(value[field], str) or not value[field].endswith("Z"):
            raise FacilityKnowledgeContractError(
                "invalid_generation_timestamp",
                f"{field} must be a UTC timestamp ending in Z.",
            )
    return deepcopy(dict(value))


def facility_knowledge_registry() -> dict[str, Any]:
    commands = list(canonical_facility_command_registry())
    tools = list(canonical_facility_agent_tool_registry())
    strategies = list(canonical_cell_strategy_registry())
    recipes = list(canonical_cell_recipe_registry())
    payload = {
        "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
        "recordKind": "facility_knowledge_registry",
        "ontology": facility_domain_ontology(),
        "responsibilityContract": facility_sage_responsibility_contract(),
        "intentSchema": facility_intent_schema(),
        "commands": commands,
        "agentTools": tools,
        "cellStrategies": strategies,
        "cellRecipes": recipes,
        "stages": deepcopy(list(FACILITY_GENERATION_STAGES)),
        "effects": list(FACILITY_COMMAND_EFFECTS),
        "featureFlags": list(FACILITY_LAYOUT_FEATURE_FLAGS),
        "capabilityFlags": dict(FACILITY_LAYOUT_CAPABILITY_FLAGS),
        "capabilityDependencies": {
            key: list(value)
            for key, value in FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES.items()
        },
    }
    payload["registryRevision"] = facility_knowledge_revision(payload)
    return payload


def query_facility_knowledge(
    *,
    command_ids: Iterable[str] = (),
    agent_tool_ids: Iterable[str] = (),
    strategy_ids: Iterable[str] = (),
    recipe_ids: Iterable[str] = (),
    stage_ids: Iterable[str] = (),
    capability_tags: Iterable[str] = (),
    entity_scopes: Iterable[str] = (),
    include_ontology: bool = False,
    include_responsibility_contract: bool = False,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes < 256:
        raise FacilityKnowledgeContractError(
            "invalid_registry_slice_budget",
            "Registry slice maximum_bytes must be an integer of at least 256.",
        )
    registry = facility_knowledge_registry()

    def select(
        collection: str,
        key: str,
        requested: Iterable[str],
    ) -> list[dict[str, Any]]:
        requested_ids = list(dict.fromkeys(str(item) for item in requested))
        if not requested_ids:
            return []
        by_id = {item[key]: item for item in registry[collection]}
        unknown = sorted(set(requested_ids) - set(by_id))
        if unknown:
            raise FacilityKnowledgeContractError(
                "unknown_registry_identifier",
                "Registry query contains unknown identifiers.",
                details={"collection": collection, "unknown": unknown},
            )
        return [deepcopy(by_id[item]) for item in requested_ids]

    requested_stage_ids = list(dict.fromkeys(str(item) for item in stage_ids))
    requested_capabilities = list(
        dict.fromkeys(str(item) for item in capability_tags)
    )
    requested_scopes = list(dict.fromkeys(str(item) for item in entity_scopes))
    unknown_capabilities = sorted(
        set(requested_capabilities) - set(FACILITY_LAYOUT_CAPABILITY_FLAGS)
    )
    if unknown_capabilities:
        raise FacilityKnowledgeContractError(
            "unknown_registry_identifier",
            "Registry query contains unknown capability identifiers.",
            details={
                "collection": "capabilities",
                "unknown": unknown_capabilities,
            },
        )
    selected_stages = select("stages", "stageId", requested_stage_ids)
    selected_commands = select("commands", "commandId", command_ids)
    if not selected_commands and (
        requested_stage_ids or requested_capabilities or requested_scopes
    ):
        selected_commands = deepcopy(registry["commands"])
    if requested_stage_ids:
        selected_commands = [
            item
            for item in selected_commands
            if set(item["supportedStages"]) & set(requested_stage_ids)
        ]
    if requested_capabilities:
        selected_commands = [
            item
            for item in selected_commands
            if set(item["requiredCapabilities"]) & set(requested_capabilities)
        ]
    if requested_scopes:
        selected_commands = [
            item for item in selected_commands if item["entityScope"] in requested_scopes
        ]
    result = {
        "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
        "recordKind": "facility_knowledge_slice",
        "registryRevision": registry["registryRevision"],
        "commands": selected_commands,
        "agentTools": select("agentTools", "commandId", agent_tool_ids),
        "cellStrategies": select("cellStrategies", "strategyId", strategy_ids),
        "cellRecipes": select("cellRecipes", "recipeId", recipe_ids),
        "stages": selected_stages,
        "ontology": deepcopy(registry["ontology"]) if include_ontology else None,
        "responsibilityContract": (
            deepcopy(registry["responsibilityContract"])
            if include_responsibility_contract
            else None
        ),
        "query": {
            "stageIds": requested_stage_ids,
            "capabilityTags": requested_capabilities,
            "entityScopes": requested_scopes,
        },
        "measurement": {
            "canonicalBytes": 0,
            "estimatedTokens": 0,
            "estimatorId": "bytes4-v1",
            "maximumBytes": maximum_bytes,
        },
    }
    for _ in range(8):
        payload = canonical_facility_knowledge_bytes(result)
        measurement = {
            "canonicalBytes": len(payload),
            "estimatedTokens": bytes4_estimate(len(payload)),
            "estimatorId": "bytes4-v1",
            "maximumBytes": maximum_bytes,
        }
        if result["measurement"] == measurement:
            break
        result["measurement"] = measurement
    payload = canonical_facility_knowledge_bytes(result)
    if result["measurement"]["canonicalBytes"] != len(payload):
        result["measurement"]["canonicalBytes"] = len(payload)
        result["measurement"]["estimatedTokens"] = bytes4_estimate(len(payload))
        payload = canonical_facility_knowledge_bytes(result)
    if len(payload) > maximum_bytes:
        raise FacilityKnowledgeContractError(
            "registry_slice_too_large",
            "Facility registry slice exceeds the canonical byte limit.",
            details={
                "canonicalBytes": len(payload),
                "maximumBytes": maximum_bytes,
                "estimatedTokens": bytes4_estimate(len(payload)),
            },
        )
    return result


__all__ = [
    "FACILITY_AGENT_EFFECTS",
    "FACILITY_COMMAND_EFFECTS",
    "FACILITY_CONTEXT_MAXIMUM_ESTIMATED_TOKENS",
    "FACILITY_CONTEXT_TARGET_ESTIMATED_TOKENS",
    "FACILITY_GENERATION_RUN_SCHEMA_VERSION",
    "FACILITY_GENERATION_STAGES",
    "FACILITY_STAGE_RECEIPT_STATUSES",
    "FACILITY_KNOWLEDGE_SCHEMA_VERSION",
    "FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES",
    "FACILITY_RUN_STATUSES",
    "FACILITY_SAVE_ELIGIBILITY",
    "FACILITY_SOURCE_UNITS",
    "FACILITY_STAGE_STATUSES",
    "FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES",
    "FacilityKnowledgeContractError",
    "bytes4_estimate",
    "canonical_cell_strategy_registry",
    "canonical_facility_agent_tool_registry",
    "canonical_facility_command_registry",
    "canonical_facility_knowledge_bytes",
    "default_generation_stage_graph",
    "facility_knowledge_registry",
    "facility_knowledge_revision",
    "query_facility_knowledge",
    "validate_canonical_command_registry",
    "validate_department_partition_request",
    "validate_facility_envelope_request",
    "validate_generation_run",
    "validate_generation_stage_receipt",
    "validate_generation_stage",
]
