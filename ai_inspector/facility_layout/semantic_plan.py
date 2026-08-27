"""Semantic Facility Layout Plan v1.

Sage describes operational intent, resources, evidence, and relationships. The
compiler emits only the existing P8 declarative planner request; deterministic
placement and routing retain sole ownership of coordinates and geometry.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .observation import (
    FacilityObservationError,
    TrustedFacilityContext,
    assert_trusted_facility_context,
)
from .planner import (
    FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION,
    validate_layout_request,
)


SEMANTIC_FACILITY_PLAN_VERSION = 1
SEMANTIC_FACILITY_PREVIEW_TOOL = "build_facility_layout_preview"
SEMANTIC_FACILITY_MOVE_TOOL = "preview_facility_move"
MAXIMUM_SEMANTIC_ASSET_ITEMS = 500
MAXIMUM_SEMANTIC_RECORDS = 1000

EVIDENCE_STATUSES = frozenset(
    {"authored", "derived", "inferred", "unknown"}
)
_OBJECTIVES = frozenset(
    {"place_asset_set", "cleanup_layout", "place_and_cleanup"}
)
_RESOURCE_ROLES = frozenset(
    {
        "machine",
        "workstation",
        "storage",
        "material_handling",
        "inspection",
        "operator_support",
        "safety",
        "utility",
        "fixture",
        "tooling",
    }
)
_ZONE_TYPES = frozenset(
    {
        "workcell",
        "storage",
        "staging",
        "receiving",
        "shipping",
        "inspection",
        "aisle",
        "dock",
        "charging",
        "safety",
        "exclusion",
        "utility",
        "service",
        "operator",
    }
)
_RELATIONSHIP_TYPES = frozenset(
    {
        "adjacent_to",
        "near",
        "upstream_of",
        "aligned_with",
        "grouped_with",
        "face_toward",
        "separate_from",
    }
)
_FLOW_KINDS = frozenset(
    {
        "material",
        "operator",
        "forklift",
        "conveyor",
        "utility",
    }
)
_UTILITY_KINDS = frozenset(
    {
        "electrical",
        "compressed_air",
        "water",
        "exhaust",
        "network",
        "gas",
        "drain",
    }
)
_BINDING_ROLES = frozenset(
    {
        "resource",
        "material_flow",
        "operator_flow",
        "inspection",
        "storage",
        "staging",
    }
)
_STRATEGIES = frozenset(
    {"compact_rows", "balanced_grid", "flow_lanes"}
)
_DENSITY_SPACING = {
    "compact": 0.75,
    "balanced": 1.0,
    "spacious": 1.5,
}
_ZONE_PADDING = {
    "compact": 0.5,
    "standard": 0.75,
    "generous": 1.25,
}
_HIGH_RISK_CLAIM_TYPES = frozenset(
    {"safety", "capacity", "clearance", "utility"}
)
_CLAIM_TYPES = _HIGH_RISK_CLAIM_TYPES | frozenset(
    {
        "process_capability",
        "asset_selection",
        "adjacency",
        "orientation",
        "process_binding",
    }
)
_AUTHORITATIVE_VERDICTS = frozenset(
    {
        "approved",
        "compliant",
        "meets_requirement",
        "safe",
        "sufficient",
        "validated",
    }
)
_FORBIDDEN_GEOMETRY_KEYS = frozenset(
    {
        "angle",
        "camera",
        "centerline",
        "clientx",
        "clienty",
        "coordinate",
        "coordinates",
        "matrix",
        "matrices",
        "offsetx",
        "offsety",
        "pan",
        "pagex",
        "pagey",
        "pixel",
        "pixels",
        "port",
        "ports",
        "position",
        "positions",
        "quaternion",
        "rotation",
        "routepoint",
        "routepoints",
        "scale",
        "screen",
        "screencoordinate",
        "screencoordinates",
        "screenpixel",
        "screenpixels",
        "screenrectangle",
        "transform",
        "transforms",
        "translation",
        "viewport",
        "waypoint",
        "waypoints",
        "worldcoordinate",
        "worldcoordinates",
        "x",
        "y",
        "yaw",
        "z",
        "zoom",
    }
)
_FORBIDDEN_APPROVAL_KEYS = frozenset(
    {
        "approval",
        "approvalclaim",
        "approved",
        "commit",
        "committed",
        "receipt",
        "successfullyapplied",
    }
)
_RISK_CLAIM_TERMS = {
    "safety": ("safety", "guard", "egress", "hazard"),
    "capacity": ("capacity", "load", "throughput"),
    "clearance": ("clearance", "separation", "setback"),
    "utility": (
        "utility",
        "electrical",
        "air",
        "water",
        "exhaust",
        "network",
        "gas",
        "drain",
    ),
}


class SemanticFacilityPlanError(ValueError):
    """Typed semantic-plan validation rejection."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        findings: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.findings = [deepcopy(dict(item)) for item in findings]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise SemanticFacilityPlanError(
            "invalid_semantic_facility_plan",
            "Semantic Facility Layout Plan must contain finite JSON values.",
        ) from exc


def semantic_facility_plan_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, maximum: int = 240) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 128:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", cleaned):
        return ""
    return cleaned


def _revision(value: Any) -> str:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return ""


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    ref: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    result = {"severity": severity, "code": code, "message": message}
    if ref:
        result["ref"] = ref
    if path:
        result["path"] = path
    return result


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _key_tokens(value: Any) -> set[str]:
    separated = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        str(value),
    )
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", separated.lower())
        if token
    }


def _reject_forbidden_fields(
    value: Any,
    path: str,
    findings: list[dict[str, Any]],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalized_key(key)
            tokens = _key_tokens(key)
            if (
                normalized in _FORBIDDEN_GEOMETRY_KEYS
                or bool(tokens & _FORBIDDEN_GEOMETRY_KEYS)
            ):
                findings.append(
                    _finding(
                        "error",
                        "semantic_plan_contains_raw_geometry",
                        (
                            f"{path}.{key} is forbidden. Sage describes "
                            "facility intent; deterministic systems own world "
                            "coordinates, routing, ports, and camera state."
                        ),
                        path=f"{path}.{key}",
                    )
                )
            if (
                normalized in _FORBIDDEN_APPROVAL_KEYS
                or bool(tokens & _FORBIDDEN_APPROVAL_KEYS)
            ):
                findings.append(
                    _finding(
                        "error",
                        "semantic_plan_contains_approval_claim",
                        (
                            f"{path}.{key} is forbidden. A semantic plan is a "
                            "proposal and cannot claim approval or commit."
                        ),
                        path=f"{path}.{key}",
                    )
                )
            _reject_forbidden_fields(child, f"{path}.{key}", findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(
                child,
                f"{path}[{index}]",
                findings,
            )


def _unique_records(
    values: Any,
    *,
    field: str,
    identifier_field: str,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        findings.append(
            _finding(
                "error",
                "semantic_collection_not_array",
                f"{field} must be an array.",
                path=field,
            )
        )
        return []
    if len(values) > MAXIMUM_SEMANTIC_RECORDS:
        findings.append(
            _finding(
                "error",
                "semantic_plan_limit_exceeded",
                f"{field} exceeds the semantic-plan record limit.",
                path=field,
            )
        )
    result = []
    seen: set[str] = set()
    for index, raw in enumerate(values[:MAXIMUM_SEMANTIC_RECORDS]):
        if not isinstance(raw, Mapping):
            findings.append(
                _finding(
                    "error",
                    "semantic_record_not_object",
                    f"{field}[{index}] must be an object.",
                    path=f"{field}[{index}]",
                )
            )
            continue
        item = deepcopy(dict(raw))
        identifier = _identifier(item.get(identifier_field))
        if not identifier:
            findings.append(
                _finding(
                    "error",
                    "semantic_identifier_invalid",
                    (
                        f"{field}[{index}].{identifier_field} requires a "
                        "stable ID."
                    ),
                    path=f"{field}[{index}].{identifier_field}",
                )
            )
            continue
        if identifier in seen:
            findings.append(
                _finding(
                    "error",
                    "semantic_identifier_duplicate",
                    f"{field} contains duplicate ID '{identifier}'.",
                    ref=identifier,
                )
            )
            continue
        seen.add(identifier)
        item[identifier_field] = identifier
        result.append(item)
    return result


def _context_indexes(
    state: TrustedFacilityContext,
    evidence: TrustedFacilityContext,
) -> dict[str, Any]:
    assets = {
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        ): item
        for item in state.get("assets", [])
        if isinstance(item, Mapping)
        and item.get("assetId")
        and item.get("assetDefinitionRevision")
    }
    placements = {
        str(item.get("placementId")): item
        for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    zones = {
        str(item.get("zoneId")): item
        for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    vehicles = {
        (
            str(item.get("vehicleProfileId") or ""),
            str(item.get("vehicleProfileRevision") or ""),
        ): item
        for item in state.get("vehicles", [])
        if isinstance(item, Mapping)
        and item.get("vehicleProfileId")
        and item.get("vehicleProfileRevision")
    }
    process_maps = {
        (
            str(item.get("processMapId") or ""),
            str(item.get("processMapRevision") or ""),
        ): item
        for item in state.get("processMaps", [])
        if isinstance(item, Mapping)
        and item.get("processMapId")
        and item.get("processMapRevision")
    }
    evidence_records = {
        str(item.get("evidenceId")): item
        for item in evidence.get("records", [])
        if isinstance(item, Mapping) and item.get("evidenceId")
    }
    return {
        "assets": assets,
        "placements": placements,
        "zones": zones,
        "vehicles": vehicles,
        "processMaps": process_maps,
        "evidence": evidence_records,
    }


def _semantic_status(
    record: Mapping[str, Any],
    *,
    ref: str,
    evidence_index: Mapping[str, Mapping[str, Any]],
    known_assumptions: set[str],
    unresolved_subjects: set[str],
    findings: list[dict[str, Any]],
    claim_type: str | None = None,
) -> tuple[str, list[str], list[str]]:
    status = record.get("knowledgeStatus")
    if status not in EVIDENCE_STATUSES:
        findings.append(
            _finding(
                "error",
                "invalid_semantic_evidence_status",
                f"'{ref}' requires an authored, derived, inferred, or unknown status.",
                ref=ref,
            )
        )
        status = "unknown"
    evidence_ids = sorted(
        {
            _identifier(item)
            for item in record.get("evidenceIds", [])
            if _identifier(item)
        }
    ) if isinstance(record.get("evidenceIds", []), list) else []
    assumption_ids = sorted(
        {
            _identifier(item)
            for item in record.get("assumptionIds", [])
            if _identifier(item)
        }
    ) if isinstance(record.get("assumptionIds", []), list) else []
    unknown_evidence = [
        item for item in evidence_ids if item not in evidence_index
    ]
    if unknown_evidence:
        findings.append(
            _finding(
                "error",
                "semantic_evidence_unknown",
                (
                    f"'{ref}' references evidence outside the trusted context: "
                    + ", ".join(unknown_evidence)
                ),
                ref=ref,
            )
        )
    unknown_assumptions = [
        item for item in assumption_ids if item not in known_assumptions
    ]
    if unknown_assumptions:
        findings.append(
            _finding(
                "error",
                "semantic_assumption_unknown",
                (
                    f"'{ref}' references unknown assumptions: "
                    + ", ".join(unknown_assumptions)
                ),
                ref=ref,
            )
        )
    trusted = [
        evidence_index[item]
        for item in evidence_ids
        if item in evidence_index
    ]
    if status in {"authored", "derived"}:
        required_status = status
        valid = [
            item
            for item in trusted
            if item.get("status") == required_status
            and item.get("current") is True
            and item.get("authoritative") is True
            and not item.get("blockers")
        ]
        if not valid:
            findings.append(
                _finding(
                    "error",
                    "authoritative_facility_evidence_required",
                    (
                        f"'{ref}' cannot be {status} without a current trusted "
                        f"{status} evidence record."
                    ),
                    ref=ref,
                )
            )
        if claim_type in _HIGH_RISK_CLAIM_TYPES and valid:
            terms = _RISK_CLAIM_TERMS[claim_type]
            if not any(
                any(term in str(item.get("claimKey") or "").lower()
                    for term in terms)
                for item in valid
            ):
                findings.append(
                    _finding(
                        "error",
                        "authoritative_evidence_scope_mismatch",
                        (
                            f"'{ref}' cites evidence that does not authorize "
                            f"the {claim_type} claim."
                        ),
                        ref=ref,
                    )
                )
    elif status == "inferred":
        if record.get("hardRequirement") is True:
            findings.append(
                _finding(
                    "error",
                    "inferred_hard_requirement_forbidden",
                    (
                        f"'{ref}' is inferred and cannot satisfy a hard "
                        "facility requirement."
                    ),
                    ref=ref,
                )
            )
        if not evidence_ids and not assumption_ids:
            findings.append(
                _finding(
                    "error",
                    "inferred_claim_requires_basis",
                    (
                        f"'{ref}' is inferred and requires evidence or an "
                        "explicit assumption."
                    ),
                    ref=ref,
                )
            )
    elif status == "unknown" and ref not in unresolved_subjects:
        findings.append(
            _finding(
                "error",
                "unknown_claim_must_remain_unresolved",
                (
                    f"'{ref}' is unknown and must be represented by an "
                    "unresolved item."
                ),
                ref=ref,
            )
        )
    return str(status), evidence_ids, assumption_ids


def _endpoint(
    raw: Any,
    *,
    path: str,
    item_index: Mapping[str, Mapping[str, Any]],
    placement_index: Mapping[str, Mapping[str, Any]],
    zone_index: Mapping[str, Mapping[str, Any]],
    asset_index: Mapping[tuple[str, str], Mapping[str, Any]],
    shell_id: str,
    shell_revision: str,
    flow_kind: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        findings.append(
            _finding(
                "error",
                "semantic_flow_endpoint_invalid",
                f"{path} must be an endpoint object.",
                path=path,
            )
        )
        return None
    endpoint = deepcopy(dict(raw))
    kind = endpoint.get("kind")
    connector_id = _identifier(endpoint.get("connectorId"))
    asset = None
    if kind == "planned_asset_connector":
        item_id = _identifier(endpoint.get("itemId"))
        item = item_index.get(item_id)
        occurrence_index = endpoint.get("occurrenceIndex", 0)
        if (
            item is None
            or isinstance(occurrence_index, bool)
            or not isinstance(occurrence_index, int)
            or occurrence_index < 0
            or occurrence_index >= int(item.get("quantity", 0))
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_endpoint_unresolved",
                    f"{path} references an unavailable planned occurrence.",
                    path=path,
                )
            )
            return None
        asset = asset_index.get(
            (item["assetId"], item["assetDefinitionRevision"])
        )
        result = {
            "kind": kind,
            "itemId": item_id,
            "occurrenceIndex": occurrence_index,
            "connectorId": connector_id,
        }
    elif kind == "placement_connector":
        placement_id = _identifier(endpoint.get("placementId"))
        placement = placement_index.get(placement_id)
        if placement is None:
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_endpoint_unresolved",
                    f"{path} references an unavailable placement.",
                    path=path,
                )
            )
            return None
        asset = asset_index.get(
            (
                str(placement.get("assetId")),
                str(placement.get("assetDefinitionRevision")),
            )
        )
        result = {
            "kind": kind,
            "placementId": placement_id,
            "connectorId": connector_id,
        }
    elif kind == "zone_anchor":
        zone_id = _identifier(endpoint.get("zoneId"))
        anchor_id = _identifier(endpoint.get("anchorId"))
        zone = zone_index.get(zone_id)
        anchors = {
            str(item.get("anchorId")): item
            for item in (zone or {}).get("anchors", [])
            if isinstance(item, Mapping) and item.get("anchorId")
        }
        if anchor_id not in anchors:
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_endpoint_unresolved",
                    f"{path} references an unavailable zone anchor.",
                    path=path,
                )
            )
            return None
        allowed = anchors[anchor_id].get("allowedRouteKinds", [])
        if flow_kind != "utility" and flow_kind not in allowed:
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_endpoint_incompatible",
                    f"{path} does not allow {flow_kind} routes.",
                    path=path,
                )
            )
        return {
            "kind": kind,
            "zoneId": zone_id,
            "anchorId": anchor_id,
        }
    elif kind == "shell_connector":
        if (
            endpoint.get("shellId") != shell_id
            or endpoint.get("shellRevision") != shell_revision
            or not connector_id
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_endpoint_unresolved",
                    f"{path} references an unavailable shell connector.",
                    path=path,
                )
            )
            return None
        return {
            "kind": kind,
            "shellId": shell_id,
            "shellRevision": shell_revision,
            "connectorId": connector_id,
        }
    else:
        findings.append(
            _finding(
                "error",
                "semantic_flow_endpoint_invalid",
                f"{path} has an unsupported endpoint kind.",
                path=path,
            )
        )
        return None
    if not connector_id or asset is None:
        findings.append(
            _finding(
                "error",
                "semantic_flow_endpoint_unresolved",
                f"{path} has no trusted occurrence-qualified connector.",
                path=path,
            )
        )
        return None
    connectors = {
        str(item.get("connectorId")): item
        for item in asset.get("connectors", [])
        if isinstance(item, Mapping) and item.get("connectorId")
    }
    connector = connectors.get(connector_id)
    if connector is None:
        findings.append(
            _finding(
                "error",
                "semantic_flow_endpoint_unresolved",
                f"{path} references an unavailable asset connector.",
                path=path,
            )
        )
    elif (
        flow_kind != "utility"
        and flow_kind not in connector.get("allowedRouteKinds", [])
    ):
        findings.append(
            _finding(
                "error",
                "semantic_flow_endpoint_incompatible",
                f"{path} connector does not allow {flow_kind} routes.",
                path=path,
            )
        )
    return result


def _facility_layout_semantic_plan_schema() -> dict[str, Any]:
    """Return the exact model-facing Semantic Facility Layout Plan v1 schema.

    Keeping this schema explicit is important: a generic ``object`` schema lets
    a capable model invent a reasonable but incompatible planning vocabulary.
    The deterministic validator remains authoritative, while this contract
    makes valid first-pass tool calls substantially more likely.
    """

    identifier = {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    }
    revision = {
        "type": "string",
        "pattern": r"^[0-9a-f]{64}$",
    }
    id_array = {
        "type": "array",
        "items": deepcopy(identifier),
        "maxItems": MAXIMUM_SEMANTIC_RECORDS,
    }
    status_properties = {
        "knowledgeStatus": {
            "type": "string",
            "enum": sorted(EVIDENCE_STATUSES),
        },
        "evidenceIds": deepcopy(id_array),
        "assumptionIds": deepcopy(id_array),
    }
    status_required = [
        "knowledgeStatus",
        "evidenceIds",
        "assumptionIds",
    ]

    def nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "anyOf": [
                deepcopy(dict(schema)),
                {"type": "null"},
            ]
        }

    endpoint = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {
                "type": "string",
                "enum": [
                    "planned_asset_connector",
                    "placement_connector",
                    "zone_anchor",
                    "shell_connector",
                ],
            },
            "itemId": nullable(identifier),
            "occurrenceIndex": nullable({
                "type": "integer",
                "minimum": 0,
                "maximum": MAXIMUM_SEMANTIC_ASSET_ITEMS - 1,
            }),
            "placementId": nullable(identifier),
            "zoneId": nullable(identifier),
            "anchorId": nullable(identifier),
            "shellId": nullable(identifier),
            "shellRevision": nullable(revision),
            "connectorId": nullable(identifier),
        },
        "description": (
            "Occurrence-qualified trusted endpoint. Include only the fields "
            "required by its kind and copy every ID from trusted context."
        ),
    }
    endpoint["required"] = list(endpoint["properties"])

    def record(
        required: Sequence[str],
        properties: Mapping[str, Any],
    ) -> dict[str, Any]:
        del required
        return {
            "type": "object",
            "additionalProperties": False,
            # OpenAI strict function schemas require every declared property.
            # Semantically optional fields use an explicit null branch.
            "required": list(properties),
            "properties": deepcopy(dict(properties)),
        }

    plan = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "planId",
            "scope",
            "objective",
            "sourceRevisions",
            "requiredCapabilities",
            "selectedAssets",
            "requiredZones",
            "placementRelationships",
            "processBindings",
            "flows",
            "evidence",
            "assumptions",
            "unresolvedItems",
            "alternatives",
            "layoutHints",
        ],
        "properties": {
            "schemaVersion": {"type": "integer", "const": 1},
            "planId": deepcopy(identifier),
            "scope": record(
                ["siteId", "layoutId", "label"],
                {
                    "siteId": deepcopy(identifier),
                    "layoutId": deepcopy(identifier),
                    "label": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 160,
                    },
                },
            ),
            "objective": {
                "type": "string",
                "enum": sorted(_OBJECTIVES),
            },
            "sourceRevisions": record(
                ["layout", "shell", "policy"],
                {
                    "layout": deepcopy(revision),
                    "shell": deepcopy(revision),
                    "policy": deepcopy(revision),
                },
            ),
            "requiredCapabilities": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "requirementId",
                        "capabilityId",
                        "quantity",
                        "assignedItemIds",
                        *status_required,
                    ],
                    {
                        "requirementId": deepcopy(identifier),
                        "capabilityId": deepcopy(identifier),
                        "quantity": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAXIMUM_SEMANTIC_ASSET_ITEMS,
                        },
                        "assignedItemIds": deepcopy(id_array),
                        **status_properties,
                    },
                ),
            },
            "selectedAssets": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAXIMUM_SEMANTIC_ASSET_ITEMS,
                "items": record(
                    [
                        "itemId",
                        "assetId",
                        "assetDefinitionRevision",
                        "quantity",
                        "resourceRole",
                        "stage",
                        *status_required,
                    ],
                    {
                        "itemId": deepcopy(identifier),
                        "assetId": deepcopy(identifier),
                        "assetDefinitionRevision": deepcopy(revision),
                        "quantity": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAXIMUM_SEMANTIC_ASSET_ITEMS,
                        },
                        "resourceRole": {
                            "type": "string",
                            "enum": sorted(_RESOURCE_ROLES),
                        },
                        "stage": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "targetZoneRef": nullable(identifier),
                        "existingPlacementId": nullable(identifier),
                        **status_properties,
                    },
                ),
            },
            "requiredZones": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "zoneRequestId",
                        "zoneType",
                        "label",
                        "memberItemIds",
                        "paddingClass",
                        *status_required,
                    ],
                    {
                        "zoneRequestId": deepcopy(identifier),
                        "zoneType": {
                            "type": "string",
                            "enum": sorted(_ZONE_TYPES),
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 160,
                        },
                        "existingZoneId": nullable(identifier),
                        "memberItemIds": deepcopy(id_array),
                        "paddingClass": {
                            "type": "string",
                            "enum": sorted(_ZONE_PADDING),
                        },
                        **status_properties,
                    },
                ),
            },
            "placementRelationships": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "relationshipId",
                        "relationshipType",
                        "sourceRef",
                        "targetRef",
                        *status_required,
                    ],
                    {
                        "relationshipId": deepcopy(identifier),
                        "relationshipType": {
                            "type": "string",
                            "enum": sorted(_RELATIONSHIP_TYPES),
                        },
                        "sourceRef": deepcopy(identifier),
                        "targetRef": deepcopy(identifier),
                        **status_properties,
                    },
                ),
            },
            "processBindings": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "bindingIntentId",
                        "productId",
                        "processMapId",
                        "processMapRevision",
                        "processNodeIds",
                        "processEdgeIds",
                        "resourceItemIds",
                        "flowIds",
                        "bindingRole",
                        *status_required,
                    ],
                    {
                        "bindingIntentId": deepcopy(identifier),
                        "productId": deepcopy(identifier),
                        "processMapId": deepcopy(identifier),
                        "processMapRevision": deepcopy(revision),
                        "processNodeIds": deepcopy(id_array),
                        "processEdgeIds": deepcopy(id_array),
                        "resourceItemIds": deepcopy(id_array),
                        "flowIds": deepcopy(id_array),
                        "bindingRole": {
                            "type": "string",
                            "enum": sorted(_BINDING_ROLES),
                        },
                        **status_properties,
                    },
                ),
            },
            "flows": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "flowId",
                        "flowKind",
                        "sourceEndpoint",
                        "targetEndpoint",
                        *status_required,
                    ],
                    {
                        "flowId": deepcopy(identifier),
                        "flowKind": {
                            "type": "string",
                            "enum": sorted(_FLOW_KINDS),
                        },
                        "utilityKind": nullable({
                            "type": "string",
                            "enum": sorted(_UTILITY_KINDS),
                        }),
                        "vehicleProfileId": nullable(identifier),
                        "vehicleProfileRevision": nullable(revision),
                        "sourceEndpoint": deepcopy(endpoint),
                        "targetEndpoint": deepcopy(endpoint),
                        **status_properties,
                    },
                ),
            },
            "evidence": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    [
                        "claimId",
                        "claimType",
                        "subjectRef",
                        "statement",
                        "verdict",
                        "hardRequirement",
                        *status_required,
                    ],
                    {
                        "claimId": deepcopy(identifier),
                        "claimType": {
                            "type": "string",
                            "enum": sorted(_CLAIM_TYPES),
                        },
                        "subjectRef": deepcopy(identifier),
                        "statement": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 600,
                        },
                        "verdict": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                        },
                        "hardRequirement": {"type": "boolean"},
                        **status_properties,
                    },
                ),
            },
            "assumptions": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    ["assumptionId", "text", "subjectRefs"],
                    {
                        "assumptionId": deepcopy(identifier),
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 600,
                        },
                        "subjectRefs": deepcopy(id_array),
                    },
                ),
            },
            "unresolvedItems": {
                "type": "array",
                "maxItems": MAXIMUM_SEMANTIC_RECORDS,
                "items": record(
                    ["unresolvedId", "code", "message", "subjectRefs"],
                    {
                        "unresolvedId": deepcopy(identifier),
                        "code": deepcopy(identifier),
                        "message": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 600,
                        },
                        "subjectRefs": deepcopy(id_array),
                    },
                ),
            },
            "alternatives": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": record(
                    ["alternativeId", "strategy", "label"],
                    {
                        "alternativeId": deepcopy(identifier),
                        "strategy": {
                            "type": "string",
                            "enum": sorted(_STRATEGIES),
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                        },
                    },
                ),
            },
            "layoutHints": record(
                ["density", "preserveManual", "preserveLocked"],
                {
                    "density": {
                        "type": "string",
                        "enum": sorted(_DENSITY_SPACING),
                    },
                    "preserveManual": {"type": "boolean", "const": True},
                    "preserveLocked": {"type": "boolean", "const": True},
                    "replaceExistingContents": {"type": "boolean"},
                    "primaryFlow": nullable({
                        "type": "string",
                        "maxLength": 120,
                    }),
                },
            ),
        },
    }
    return plan


def facility_layout_preview_tool_spec() -> dict[str, Any]:
    """Return the only Sage-exposed Facility Layout mutation tool."""

    return {
        "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
        "description": (
            "Build one complete, review-only 2D/3D Facility Layout ghost "
            "preview from Semantic Facility Layout Plan v1. Supply operational "
            "intent, stable IDs, evidence, assumptions, and layout preferences; "
            "never supply coordinates, transforms, ports, waypoints, camera "
            "state, low-level operations, or approval claims. The deterministic "
            "server validates, places, routes, and binds the proposal to exact "
            "revisions. This tool does not commit the layout."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["semantic_plan"],
            "properties": {
                "semantic_plan": {
                    "description": (
                        "Exact Semantic Facility Layout Plan v1. Copy trusted "
                        "IDs and revisions exactly. Cover every requested "
                        "resource and quantity before calling this tool."
                    ),
                    **_facility_layout_semantic_plan_schema(),
                }
            },
        },
    }


def facility_layout_move_tool_spec() -> dict[str, Any]:
    """Return the bounded Sage tool for one exact draft translation.

    The model never supplies a destination coordinate or rotation. It names a
    cardinal world direction and distance, while the browser resolves current
    placement positions and the existing authoritative preview endpoint
    validates the resulting unsaved transaction.
    """

    return {
        "name": SEMANTIC_FACILITY_MOVE_TOOL,
        "description": (
            "Translate current Facility Layout placement selection or exact "
            "resolved placement IDs by one cardinal world-space distance. "
            "Use only for a direct request such as 'move the selected machine "
            "10 ft east'. Direction maps to facility axes: east/west are "
            "+X/-X, north/south are +Z/-Z, and up/down are +Y/-Y. Never "
            "supply coordinates, screen pixels, camera actions, or rotation. "
            "Rotation is preserved by construction. The result is a "
            "server-validated unsaved draft edit with Undo available; it does "
            "not save or approve the layout."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "direction",
                "distance",
                "unit",
                "preserve_rotation",
            ],
            "properties": {
                "use_current_selection": {
                    "type": "boolean",
                    "description": (
                        "True when the user explicitly refers to the current "
                        "selection."
                    ),
                },
                "placement_ids": {
                    "type": "array",
                    "maxItems": 50,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 128},
                    "description": (
                        "Exact IDs returned by resolve_entities. Omit when "
                        "using the current selection."
                    ),
                },
                "direction": {
                    "enum": ["east", "west", "north", "south", "up", "down"],
                },
                "distance": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 1000000,
                },
                "unit": {"enum": ["mm", "cm", "m", "in", "ft"]},
                "preserve_rotation": {"const": True},
            },
        },
    }


def validate_semantic_facility_plan(
    plan: Mapping[str, Any],
    *,
    state: TrustedFacilityContext,
    evidence: TrustedFacilityContext,
) -> dict[str, Any]:
    """Validate semantic meaning and exact trusted references."""

    try:
        state = assert_trusted_facility_context(
            state,
            "facility_layout.state",
        )
        evidence = assert_trusted_facility_context(
            evidence,
            "facility_layout.evidence",
        )
    except FacilityObservationError as exc:
        raise SemanticFacilityPlanError(exc.code, str(exc)) from exc
    if not isinstance(plan, Mapping):
        raise SemanticFacilityPlanError(
            "invalid_semantic_facility_plan",
            "Semantic Facility Layout Plan must be an object.",
        )
    normalized = json.loads(_canonical_bytes(plan).decode("ascii"))
    findings: list[dict[str, Any]] = []
    _reject_forbidden_fields(normalized, "$", findings)
    required_fields = {
        "schemaVersion",
        "planId",
        "scope",
        "objective",
        "sourceRevisions",
        "requiredCapabilities",
        "selectedAssets",
        "requiredZones",
        "placementRelationships",
        "processBindings",
        "flows",
        "evidence",
        "assumptions",
        "unresolvedItems",
        "alternatives",
        "layoutHints",
    }
    missing = sorted(required_fields - set(normalized))
    if missing:
        findings.append(
            _finding(
                "error",
                "semantic_plan_fields_missing",
                f"Semantic Facility Layout Plan is missing: {', '.join(missing)}.",
            )
        )
    if normalized.get("schemaVersion") != SEMANTIC_FACILITY_PLAN_VERSION:
        findings.append(
            _finding(
                "error",
                "unsupported_semantic_facility_plan_version",
                "Semantic Facility Layout Plan schemaVersion must equal 1.",
            )
        )
    plan_id = _identifier(normalized.get("planId"))
    if not plan_id:
        findings.append(
            _finding(
                "error",
                "semantic_plan_id_invalid",
                "Semantic Facility Layout Plan requires a stable planId.",
            )
        )
    scope = (
        normalized.get("scope")
        if isinstance(normalized.get("scope"), Mapping)
        else {}
    )
    identity = state.get("identity", {})
    if (
        scope.get("siteId") != identity.get("siteId")
        or scope.get("layoutId") != identity.get("layoutId")
    ):
        findings.append(
            _finding(
                "error",
                "semantic_scope_mismatch",
                "Semantic scope does not match the trusted active layout.",
            )
        )
    objective = normalized.get("objective")
    if objective not in _OBJECTIVES:
        findings.append(
            _finding(
                "error",
                "semantic_objective_invalid",
                "Semantic objective is unsupported.",
            )
        )
    source_revisions = (
        normalized.get("sourceRevisions")
        if isinstance(normalized.get("sourceRevisions"), Mapping)
        else {}
    )
    dependencies = state.get("dependencyRevisions", {})
    expected_revisions = {
        "layout": identity.get("revision"),
        "shell": dependencies.get("shellRevision"),
        "policy": dependencies.get("policySetRevision"),
    }
    for key, expected in expected_revisions.items():
        if source_revisions.get(key) != expected or not _revision(expected):
            findings.append(
                _finding(
                    "error",
                    "semantic_source_revision_stale",
                    f"Semantic source revision '{key}' is not current.",
                    ref=key,
                )
            )

    indexes = _context_indexes(state, evidence)
    assumptions = _unique_records(
        normalized.get("assumptions", []),
        field="assumptions",
        identifier_field="assumptionId",
        findings=findings,
    )
    assumption_ids = {item["assumptionId"] for item in assumptions}
    unresolved = _unique_records(
        normalized.get("unresolvedItems", []),
        field="unresolvedItems",
        identifier_field="unresolvedId",
        findings=findings,
    )
    unresolved_subjects = {
        _identifier(subject)
        for item in unresolved
        for subject in item.get("subjectRefs", [])
        if _identifier(subject)
    }

    selected_assets = _unique_records(
        normalized.get("selectedAssets", []),
        field="selectedAssets",
        identifier_field="itemId",
        findings=findings,
    )
    if len(selected_assets) > MAXIMUM_SEMANTIC_ASSET_ITEMS:
        findings.append(
            _finding(
                "error",
                "semantic_asset_limit_exceeded",
                "A semantic plan can select at most 500 asset items.",
            )
        )
    selected_index: dict[str, dict[str, Any]] = {}
    selected_total = 0
    for item in selected_assets[:MAXIMUM_SEMANTIC_ASSET_ITEMS]:
        item_id = item["itemId"]
        asset_id = _identifier(item.get("assetId"))
        asset_revision = _revision(item.get("assetDefinitionRevision"))
        trusted_asset = indexes["assets"].get((asset_id, asset_revision))
        if trusted_asset is None:
            findings.append(
                _finding(
                    "error",
                    "trusted_asset_revision_unavailable",
                    (
                        f"Selected item '{item_id}' references an unavailable "
                        "asset definition revision."
                    ),
                    ref=item_id,
                )
            )
        elif trusted_asset.get("planningReady") is not True:
            findings.append(
                _finding(
                    "error",
                    "asset_not_planning_ready",
                    f"Selected asset '{asset_id}' is not planning-ready.",
                    ref=item_id,
                )
            )
        quantity = item.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= MAXIMUM_SEMANTIC_ASSET_ITEMS
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_quantity_invalid",
                    f"Selected item '{item_id}' has an invalid quantity.",
                    ref=item_id,
                )
            )
            quantity = 0
        selected_total += int(quantity)
        if item.get("resourceRole") not in _RESOURCE_ROLES:
            findings.append(
                _finding(
                    "error",
                    "semantic_resource_role_invalid",
                    f"Selected item '{item_id}' has an unsupported resource role.",
                    ref=item_id,
                )
            )
        stage = item.get("stage", 0)
        if isinstance(stage, bool) or not isinstance(stage, int) or stage < 0:
            findings.append(
                _finding(
                    "error",
                    "semantic_stage_invalid",
                    f"Selected item '{item_id}' requires a non-negative stage.",
                    ref=item_id,
                )
            )
        existing = item.get("existingPlacementId")
        if existing is not None:
            placement = indexes["placements"].get(_identifier(existing))
            if (
                quantity != 1
                or placement is None
                or placement.get("assetId") != asset_id
                or placement.get("assetDefinitionRevision") != asset_revision
            ):
                findings.append(
                    _finding(
                        "error",
                        "existing_placement_reference_invalid",
                        (
                            f"Selected item '{item_id}' does not match one "
                            "trusted existing placement."
                        ),
                        ref=item_id,
                    )
                )
        _semantic_status(
            item,
            ref=item_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
        )
        item["assetId"] = asset_id
        item["assetDefinitionRevision"] = asset_revision
        item["quantity"] = quantity
        item["stage"] = stage
        selected_index[item_id] = item
    if selected_total > MAXIMUM_SEMANTIC_ASSET_ITEMS:
        findings.append(
            _finding(
                "error",
                "semantic_quantity_limit_exceeded",
                "Selected asset quantities exceed the P8 planner limit of 500.",
            )
        )
    if objective != "cleanup_layout" and not selected_assets:
        findings.append(
            _finding(
                "error",
                "semantic_assets_required",
                "Asset selections are required for this objective.",
            )
        )

    required_capabilities = _unique_records(
        normalized.get("requiredCapabilities", []),
        field="requiredCapabilities",
        identifier_field="requirementId",
        findings=findings,
    )
    for requirement in required_capabilities:
        requirement_id = requirement["requirementId"]
        capability_id = _identifier(requirement.get("capabilityId"))
        quantity = requirement.get("quantity")
        assigned_ids = (
            sorted(
                {
                    _identifier(item)
                    for item in requirement.get("assignedItemIds", [])
                    if _identifier(item)
                }
            )
            if isinstance(requirement.get("assignedItemIds"), list)
            else []
        )
        if (
            not capability_id
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            findings.append(
                _finding(
                    "error",
                    "required_capability_invalid",
                    f"Capability requirement '{requirement_id}' is invalid.",
                    ref=requirement_id,
                )
            )
            continue
        resolved_quantity = 0
        for item_id in assigned_ids:
            item = selected_index.get(item_id)
            if item is None:
                findings.append(
                    _finding(
                        "error",
                        "required_capability_assignment_unknown",
                        (
                            f"Capability requirement '{requirement_id}' "
                            f"references unknown selected item '{item_id}'."
                        ),
                        ref=requirement_id,
                    )
                )
                continue
            asset = indexes["assets"].get(
                (item["assetId"], item["assetDefinitionRevision"])
            )
            if (
                asset is None
                or capability_id not in asset.get("capabilityIds", [])
            ):
                findings.append(
                    _finding(
                        "error",
                        "required_capability_not_supported",
                        (
                            f"Selected item '{item_id}' does not provide "
                            f"capability '{capability_id}'."
                        ),
                        ref=requirement_id,
                    )
                )
                continue
            resolved_quantity += int(item["quantity"])
        if resolved_quantity < quantity:
            findings.append(
                _finding(
                    "error",
                    "required_capability_quantity_incomplete",
                    (
                        f"Capability '{capability_id}' requires {quantity}; "
                        f"the plan resolves {resolved_quantity}."
                    ),
                    ref=requirement_id,
                )
            )
        _semantic_status(
            requirement,
            ref=requirement_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
            claim_type="process_capability",
        )

    required_zones = _unique_records(
        normalized.get("requiredZones", []),
        field="requiredZones",
        identifier_field="zoneRequestId",
        findings=findings,
    )
    zone_request_index = {}
    for item in required_zones:
        request_id = item["zoneRequestId"]
        zone_type = item.get("zoneType")
        if zone_type not in _ZONE_TYPES:
            findings.append(
                _finding(
                    "error",
                    "semantic_zone_type_invalid",
                    f"Zone request '{request_id}' has an unsupported type.",
                    ref=request_id,
                )
            )
        existing_zone_id = item.get("existingZoneId")
        if existing_zone_id is not None:
            existing_zone_id = _identifier(existing_zone_id)
            zone = indexes["zones"].get(existing_zone_id)
            if zone is None or (
                zone_type is not None and zone.get("zoneType") != zone_type
            ):
                findings.append(
                    _finding(
                        "error",
                        "trusted_zone_reference_invalid",
                        f"Zone request '{request_id}' does not match a trusted zone.",
                        ref=request_id,
                    )
                )
        member_ids = sorted(
            {
                _identifier(member)
                for member in item.get("memberItemIds", [])
                if _identifier(member)
            }
        ) if isinstance(item.get("memberItemIds"), list) else []
        unknown_members = [
            member for member in member_ids if member not in selected_index
        ]
        if not member_ids or unknown_members:
            findings.append(
                _finding(
                    "error",
                    "semantic_zone_members_invalid",
                    (
                        f"Zone request '{request_id}' requires known selected "
                        "asset items."
                    ),
                    ref=request_id,
                )
            )
        if item.get("paddingClass", "standard") not in _ZONE_PADDING:
            findings.append(
                _finding(
                    "error",
                    "semantic_zone_padding_invalid",
                    f"Zone request '{request_id}' has an invalid padding class.",
                    ref=request_id,
                )
            )
        _semantic_status(
            item,
            ref=request_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
        )
        item["memberItemIds"] = member_ids
        if existing_zone_id is not None:
            item["existingZoneId"] = existing_zone_id
        zone_request_index[request_id] = item
    for item in selected_assets:
        target_ref = item.get("targetZoneRef")
        if target_ref is not None and _identifier(target_ref) not in zone_request_index:
            findings.append(
                _finding(
                    "error",
                    "semantic_target_zone_unknown",
                    (
                        f"Selected item '{item['itemId']}' references an "
                        "unknown semantic zone."
                    ),
                    ref=item["itemId"],
                )
            )

    relationships = _unique_records(
        normalized.get("placementRelationships", []),
        field="placementRelationships",
        identifier_field="relationshipId",
        findings=findings,
    )
    relationship_refs = set(selected_index) | set(zone_request_index)
    for item in relationships:
        relationship_id = item["relationshipId"]
        if item.get("relationshipType") not in _RELATIONSHIP_TYPES:
            findings.append(
                _finding(
                    "error",
                    "semantic_relationship_type_invalid",
                    f"Relationship '{relationship_id}' has an unsupported type.",
                    ref=relationship_id,
                )
            )
        if (
            _identifier(item.get("sourceRef")) not in relationship_refs
            or _identifier(item.get("targetRef")) not in relationship_refs
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_relationship_reference_invalid",
                    f"Relationship '{relationship_id}' has unresolved references.",
                    ref=relationship_id,
                )
            )
        _semantic_status(
            item,
            ref=relationship_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
            claim_type="adjacency",
        )

    process_bindings = _unique_records(
        normalized.get("processBindings", []),
        field="processBindings",
        identifier_field="bindingIntentId",
        findings=findings,
    )
    for item in process_bindings:
        binding_id = item["bindingIntentId"]
        process_key = (
            _identifier(item.get("processMapId")),
            _revision(item.get("processMapRevision")),
        )
        process_map = indexes["processMaps"].get(process_key)
        if process_map is None:
            findings.append(
                _finding(
                    "error",
                    "trusted_process_map_revision_unavailable",
                    f"Process binding '{binding_id}' is stale or unavailable.",
                    ref=binding_id,
                )
            )
            continue
        if item.get("productId") != process_map.get("productId"):
            findings.append(
                _finding(
                    "error",
                    "semantic_process_product_mismatch",
                    f"Process binding '{binding_id}' has the wrong product.",
                    ref=binding_id,
                )
            )
        node_ids = sorted(
            {
                _identifier(node_id)
                for node_id in item.get("processNodeIds", [])
                if _identifier(node_id)
            }
        )
        edge_ids = sorted(
            {
                _identifier(edge_id)
                for edge_id in item.get("processEdgeIds", [])
                if _identifier(edge_id)
            }
        )
        if (
            not set(node_ids).issubset(set(process_map.get("nodeIds", [])))
            or not set(edge_ids).issubset(set(process_map.get("edgeIds", [])))
        ):
            findings.append(
                _finding(
                    "error",
                    "semantic_process_entity_unknown",
                    f"Process binding '{binding_id}' references unknown entities.",
                    ref=binding_id,
                )
            )
        if item.get("bindingRole") not in _BINDING_ROLES:
            findings.append(
                _finding(
                    "error",
                    "semantic_binding_role_invalid",
                    f"Process binding '{binding_id}' has an invalid role.",
                    ref=binding_id,
                )
            )
        unknown_items = [
            value for value in item.get("resourceItemIds", [])
            if _identifier(value) not in selected_index
        ]
        if unknown_items:
            findings.append(
                _finding(
                    "error",
                    "semantic_binding_resource_unknown",
                    f"Process binding '{binding_id}' has unknown resources.",
                    ref=binding_id,
                )
            )
        _semantic_status(
            item,
            ref=binding_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
            claim_type="process_binding",
        )

    shell_id = str(dependencies.get("shellId") or "")
    shell_revision = str(dependencies.get("shellRevision") or "")
    flows = _unique_records(
        normalized.get("flows", []),
        field="flows",
        identifier_field="flowId",
        findings=findings,
    )
    for item in flows:
        flow_id = item["flowId"]
        flow_kind = item.get("flowKind")
        if flow_kind not in _FLOW_KINDS:
            findings.append(
                _finding(
                    "error",
                    "semantic_flow_kind_invalid",
                    f"Flow '{flow_id}' has an unsupported kind.",
                    ref=flow_id,
                )
            )
            continue
        item["_sourceEndpoint"] = _endpoint(
            item.get("sourceEndpoint"),
            path=f"flows.{flow_id}.sourceEndpoint",
            item_index=selected_index,
            placement_index=indexes["placements"],
            zone_index=indexes["zones"],
            asset_index=indexes["assets"],
            shell_id=shell_id,
            shell_revision=shell_revision,
            flow_kind=flow_kind,
            findings=findings,
        )
        item["_targetEndpoint"] = _endpoint(
            item.get("targetEndpoint"),
            path=f"flows.{flow_id}.targetEndpoint",
            item_index=selected_index,
            placement_index=indexes["placements"],
            zone_index=indexes["zones"],
            asset_index=indexes["assets"],
            shell_id=shell_id,
            shell_revision=shell_revision,
            flow_kind=flow_kind,
            findings=findings,
        )
        if flow_kind == "forklift":
            vehicle_key = (
                _identifier(item.get("vehicleProfileId")),
                _revision(item.get("vehicleProfileRevision")),
            )
            if vehicle_key not in indexes["vehicles"]:
                findings.append(
                    _finding(
                        "error",
                        "trusted_vehicle_revision_unavailable",
                        f"Flow '{flow_id}' has no current trusted vehicle profile.",
                        ref=flow_id,
                    )
                )
        if flow_kind == "utility":
            if item.get("utilityKind") not in _UTILITY_KINDS:
                findings.append(
                    _finding(
                        "error",
                        "semantic_utility_kind_invalid",
                        f"Utility flow '{flow_id}' has an unsupported service.",
                        ref=flow_id,
                    )
                )
        _semantic_status(
            item,
            ref=flow_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
            claim_type=("utility" if flow_kind == "utility" else None),
        )

    claims = _unique_records(
        normalized.get("evidence", []),
        field="evidence",
        identifier_field="claimId",
        findings=findings,
    )
    for item in claims:
        claim_id = item["claimId"]
        claim_type = item.get("claimType")
        if claim_type not in _CLAIM_TYPES:
            findings.append(
                _finding(
                    "error",
                    "semantic_claim_type_invalid",
                    f"Claim '{claim_id}' has an unsupported type.",
                    ref=claim_id,
                )
            )
            continue
        status, _, _ = _semantic_status(
            item,
            ref=claim_id,
            evidence_index=indexes["evidence"],
            known_assumptions=assumption_ids,
            unresolved_subjects=unresolved_subjects,
            findings=findings,
            claim_type=claim_type,
        )
        verdict = _normalized_key(item.get("verdict"))
        has_authoritative_value = (
            "value" in item
            or verdict in {
                _normalized_key(value)
                for value in _AUTHORITATIVE_VERDICTS
            }
        )
        if (
            claim_type in _HIGH_RISK_CLAIM_TYPES
            and has_authoritative_value
            and status not in {"authored", "derived"}
        ):
            findings.append(
                _finding(
                    "error",
                    "unsupported_authoritative_facility_claim",
                    (
                        f"Claim '{claim_id}' cannot present an inferred or "
                        f"unknown {claim_type} value or verdict as authoritative."
                    ),
                    ref=claim_id,
                )
            )

    alternatives = _unique_records(
        normalized.get("alternatives", []),
        field="alternatives",
        identifier_field="alternativeId",
        findings=findings,
    )
    strategies = []
    for item in alternatives:
        strategy = item.get("strategy")
        if strategy not in _STRATEGIES:
            findings.append(
                _finding(
                    "error",
                    "semantic_strategy_invalid",
                    f"Alternative '{item['alternativeId']}' has an invalid strategy.",
                    ref=item["alternativeId"],
                )
            )
        elif strategy not in strategies:
            strategies.append(strategy)
    if not strategies:
        findings.append(
            _finding(
                "error",
                "semantic_alternative_required",
                "At least one deterministic layout strategy is required.",
            )
        )
    if len(strategies) > 4:
        findings.append(
            _finding(
                "error",
                "semantic_alternative_limit_exceeded",
                "At most four layout strategies are supported.",
            )
        )
    layout_hints = (
        normalized.get("layoutHints")
        if isinstance(normalized.get("layoutHints"), Mapping)
        else {}
    )
    if layout_hints.get("density") not in _DENSITY_SPACING:
        findings.append(
            _finding(
                "error",
                "semantic_density_invalid",
                "layoutHints.density must be compact, balanced, or spacious.",
            )
        )
    if layout_hints.get("preserveManual") is not True:
        findings.append(
            _finding(
                "error",
                "manual_position_preservation_required",
                "Semantic planning must preserve manual positions by default.",
            )
        )
    if layout_hints.get("preserveLocked") is not True:
        findings.append(
            _finding(
                "error",
                "locked_position_preservation_required",
                "Semantic planning must preserve locked positions.",
            )
        )
    replace_existing = layout_hints.get("replaceExistingContents", False)
    if not isinstance(replace_existing, bool):
        findings.append(
            _finding(
                "error",
                "semantic_replacement_policy_invalid",
                "layoutHints.replaceExistingContents must be boolean.",
            )
        )
    elif replace_existing and objective != "place_and_cleanup":
        findings.append(
            _finding(
                "error",
                "semantic_replacement_objective_invalid",
                (
                    "Replacing existing contents requires the explicit "
                    "place_and_cleanup objective."
                ),
            )
        )
    if state.get("staleDependencies"):
        findings.append(
            _finding(
                "error",
                "trusted_facility_dependencies_stale",
                "The trusted state has stale dependencies.",
            )
        )

    normalized.update(
        {
            "planId": plan_id,
            "requiredCapabilities": required_capabilities,
            "selectedAssets": selected_assets,
            "requiredZones": required_zones,
            "placementRelationships": relationships,
            "processBindings": process_bindings,
            "flows": flows,
            "evidence": claims,
            "assumptions": assumptions,
            "unresolvedItems": unresolved,
            "alternatives": alternatives,
            "layoutHints": deepcopy(dict(layout_hints)),
        }
    )
    errors = [item for item in findings if item["severity"] == "error"]
    if errors:
        raise SemanticFacilityPlanError(
            errors[0]["code"],
            errors[0]["message"],
            findings=findings,
        )
    return {
        "plan": normalized,
        "findings": findings,
        "context": indexes,
    }


_GENERIC_ASSET_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "asset",
        "equipment",
        "facility",
        "for",
        "layout",
        "machine",
        "of",
        "one",
        "the",
        "with",
    }
)
_QUANTITY_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_COMPLETE_FACTORY_MAXIMUM_INSTANCES = 120
_COMPLETE_FACTORY_ZONE_TEMPLATES = (
    {
        "zoneRequestId": "zone-receiving-raw-material",
        "zoneType": "receiving",
        "label": "Receiving + Raw Material",
        "stage": 0,
        "selectors": (
            {
                "categories": ("storage",),
                "preferredNames": ("pallet rack", "rack", "storage"),
                "quantity": 6,
            },
            {
                "categories": ("material handling",),
                "preferredNames": ("forklift", "pallet truck", "cart"),
                "quantity": 2,
            },
            {
                "categories": ("storage",),
                "preferredNames": ("pallet", "shipping container", "box"),
                "quantity": 4,
            },
        ),
    },
    {
        "zoneRequestId": "zone-machining-hall",
        "zoneType": "workcell",
        "label": "Machining Hall",
        "stage": 1,
        "selectors": (
            {
                "categories": ("machines",),
                "preferredNames": ("cnc milling", "cnc", "milling"),
                "quantity": 6,
            },
            {
                "categories": ("machines",),
                "preferredNames": ("lathe", "turning", "edm"),
                "quantity": 4,
            },
            {
                "categories": ("machines",),
                "preferredNames": ("band saw", "grinder", "saw"),
                "quantity": 3,
            },
            {
                "categories": ("workstations",),
                "preferredNames": ("workbench", "workstation"),
                "quantity": 3,
            },
        ),
    },
    {
        "zoneRequestId": "zone-automation-robot-cells",
        "zoneType": "workcell",
        "label": "Automation + Robot Cells",
        "stage": 2,
        "selectors": (
            {
                "categories": ("automation",),
                "fallbackCategories": ("machines",),
                "preferredNames": ("robot", "cnc"),
                "quantity": 6,
            },
            {
                "categories": ("conveyors",),
                "fallbackCategories": ("material handling",),
                "preferredNames": ("conveyor", "forklift", "cart"),
                "quantity": 4,
            },
            {
                "categories": ("safety",),
                "fallbackCategories": ("storage",),
                "preferredNames": ("machine guard", "guard", "rack"),
                "quantity": 6,
            },
            {
                "categories": ("people",),
                "fallbackCategories": ("workstations",),
                "preferredNames": ("operator", "workbench"),
                "quantity": 4,
            },
        ),
    },
    {
        "zoneRequestId": "zone-material-handling-maintenance",
        # A Facility Layout service zone is an exclusion envelope, not an
        # equipment-bearing maintenance department. Use an operational
        # workcell so the planned support assets can legally occupy it.
        "zoneType": "workcell",
        "label": "Material Handling + Maintenance",
        "stage": 3,
        "selectors": (
            {
                "categories": ("material handling",),
                "preferredNames": ("forklift", "pallet truck", "cart"),
                "quantity": 4,
            },
            {
                "categories": ("storage",),
                "preferredNames": ("tooling", "cabinet", "shelves", "rack"),
                "quantity": 4,
            },
            {
                "categories": ("workstations",),
                "preferredNames": ("workbench", "workstation"),
                "quantity": 3,
            },
        ),
    },
    {
        "zoneRequestId": "zone-assembly-kitting",
        "zoneType": "workcell",
        "label": "Assembly + Kitting",
        "stage": 4,
        "selectors": (
            {
                "categories": ("workstations",),
                "preferredNames": ("assembly workbench", "workbench"),
                "quantity": 8,
            },
            {
                "categories": ("people",),
                "fallbackCategories": ("storage",),
                "preferredNames": ("operator", "cabinet", "rack"),
                "quantity": 6,
            },
            {
                "categories": ("storage",),
                "preferredNames": ("tooling", "drawer", "cabinet", "rack"),
                "quantity": 4,
            },
            {
                "categories": ("material handling",),
                "preferredNames": ("mobile cart", "pallet truck", "forklift"),
                "quantity": 3,
            },
        ),
    },
    {
        "zoneRequestId": "zone-inspection-packing-shipping",
        "zoneType": "inspection",
        "label": "Inspection + Packing + Finished Goods",
        "stage": 5,
        "selectors": (
            {
                "categories": ("laboratory",),
                "fallbackCategories": ("workstations",),
                "preferredNames": ("laboratory workstation", "workbench"),
                "quantity": 4,
            },
            {
                "categories": ("packaging",),
                "fallbackCategories": ("machines",),
                "preferredNames": ("filler", "packaging", "cnc"),
                "quantity": 3,
            },
            {
                "categories": ("storage",),
                "preferredNames": ("pallet rack", "shipping container", "rack"),
                "quantity": 6,
            },
            {
                "categories": ("material handling",),
                "preferredNames": ("pallet truck", "forklift", "cart"),
                "quantity": 2,
            },
        ),
    },
)


def _intent_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if token
    }


def _intent_asset_phrases(raw_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract coordinate-free resource intent from common model shapes."""

    collections = []
    for key in ("selectedAssets", "assets", "entities", "resources"):
        value = raw_plan.get(key)
        if isinstance(value, list):
            collections.extend(value)
    result = []
    for index, raw in enumerate(collections[:MAXIMUM_SEMANTIC_ASSET_ITEMS]):
        if isinstance(raw, str):
            phrase = raw
            quantity = 1
        elif isinstance(raw, Mapping):
            phrase = " ".join(
                str(raw.get(key) or "")
                for key in (
                    "assetId",
                    "asset_type",
                    "assetType",
                    "type",
                    "kind",
                    "label",
                    "name",
                    "description",
                    "role",
                )
            )
            quantity = raw.get("quantity", raw.get("count", 1))
        else:
            continue
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 1
        result.append(
            {
                "phrase": _text(phrase, 300),
                "quantity": max(
                    1,
                    min(quantity, MAXIMUM_SEMANTIC_ASSET_ITEMS),
                ),
                "sourceIndex": index,
            }
        )
    return result


def _asset_match_score(
    phrase_tokens: set[str],
    asset: Mapping[str, Any],
) -> tuple[int, int, str]:
    identity_tokens = _intent_tokens(
        " ".join(
            (
                str(asset.get("assetId") or ""),
                str(asset.get("displayName") or ""),
                str(asset.get("category") or ""),
                " ".join(
                    str(item)
                    for item in asset.get("capabilityIds", [])
                ),
            )
        )
    )
    significant = identity_tokens - _GENERIC_ASSET_WORDS
    overlap = phrase_tokens & significant
    return (
        len(overlap),
        len(phrase_tokens & identity_tokens),
        str(asset.get("assetId") or ""),
    )


def _quantity_near_asset(message: str, asset: Mapping[str, Any]) -> int:
    normalized = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(message or "").lower(),
    ).strip()
    significant = sorted(
        _intent_tokens(asset.get("displayName")) - _GENERIC_ASSET_WORDS,
        key=lambda token: (-len(token), token),
    )
    for token in significant:
        match = re.search(
            rf"\b(?P<count>[0-9]{{1,3}}|{'|'.join(_QUANTITY_WORDS)})"
            rf"\b(?:\s+\w+){{0,4}}\s+\w*{re.escape(token)}\w*\b",
            normalized,
        )
        if not match:
            continue
        raw = match.group("count")
        quantity = (
            _QUANTITY_WORDS.get(raw)
            if raw in _QUANTITY_WORDS
            else int(raw)
        )
        return max(
            1,
            min(int(quantity), MAXIMUM_SEMANTIC_ASSET_ITEMS),
        )
    return 1


def _resource_role(asset: Mapping[str, Any]) -> str:
    tokens = _intent_tokens(
        f"{asset.get('category', '')} {asset.get('displayName', '')}"
    )
    rules = (
        ("workstation", {"workbench", "workstation", "bench"}),
        ("storage", {"rack", "storage", "shelf", "shelving"}),
        (
            "material_handling",
            {"forklift", "vehicle", "conveyor", "cart", "tugger"},
        ),
        ("inspection", {"inspection", "metrology", "cmm"}),
        ("fixture", {"fixture", "jig"}),
        ("tooling", {"tool", "tooling"}),
        ("utility", {"utility", "compressor", "transformer"}),
        ("safety", {"guard", "barrier", "safety"}),
        ("operator_support", {"operator", "ergonomic"}),
    )
    for role, candidates in rules:
        if tokens & candidates:
            return role
    return "machine"


def _requests_complete_blank_factory(
    raw_plan: Mapping[str, Any],
    user_message: str,
    state: TrustedFacilityContext,
) -> bool:
    """Return whether the user explicitly requested a full factory rebuild."""

    # Unsaved browser geometry is intentionally not a trusted planning source.
    # An explicit from-scratch request therefore compiles to a replacement
    # ghost transaction against the saved revision, regardless of saved content.
    has_saved_contents = any(
        state.get(key)
        for key in ("placements", "zones", "floorMarkings", "routes")
    )
    intent = " ".join(
        value
        for value in (
            _text(raw_plan.get("intent"), 240),
            _text(raw_plan.get("label"), 160),
            _text(raw_plan.get("objective"), 80),
            _text(user_message, 1000),
        )
        if value
    ).lower()
    tokens = _intent_tokens(intent)
    creation_requested = bool(
        tokens & {"build", "create", "design", "generate", "populate"}
    )
    facility_scope = bool(tokens & {"facility", "factory", "plant"})
    complete_scope = bool(tokens & {"complete", "full"})
    from_scratch = "from scratch" in intent or bool(
        tokens & {"blank", "empty"}
    )
    return (
        creation_requested
        and facility_scope
        and (from_scratch or (complete_scope and not has_saved_contents))
    )


def _factory_asset_rank(
    asset: Mapping[str, Any],
    selector: Mapping[str, Any],
) -> tuple[int, int, int, str] | None:
    category = str(asset.get("category") or "").strip().lower()
    primary = tuple(selector.get("categories", ()))
    fallback = tuple(selector.get("fallbackCategories", ()))
    if category in primary:
        category_tier = 0
        category_rank = primary.index(category)
    elif category in fallback:
        category_tier = 1
        category_rank = fallback.index(category)
    else:
        return None
    name_tokens = _intent_tokens(asset.get("displayName"))
    preferred = tuple(selector.get("preferredNames", ()))
    phrase_rank = len(preferred)
    for index, phrase in enumerate(preferred):
        phrase_tokens = _intent_tokens(phrase)
        if phrase_tokens and phrase_tokens <= name_tokens:
            phrase_rank = index
            break
    return (
        category_tier,
        category_rank,
        phrase_rank,
        str(asset.get("assetId") or ""),
    )


def _select_factory_asset(
    assets: Sequence[Mapping[str, Any]],
    selector: Mapping[str, Any],
    *,
    used_asset_ids: set[str],
) -> Mapping[str, Any] | None:
    ranked = []
    for asset in assets:
        asset_id = str(asset.get("assetId") or "")
        if not asset_id or asset_id in used_asset_ids:
            continue
        rank = _factory_asset_rank(asset, selector)
        if rank is not None:
            ranked.append((rank, asset))
    if not ranked:
        return None
    return min(ranked, key=lambda item: item[0])[1]


def _canonical_complete_factory_plan(
    raw_plan: Mapping[str, Any],
    *,
    user_message: str,
    state: TrustedFacilityContext,
) -> dict[str, Any]:
    """Build one bounded, catalog-driven starter factory semantic plan."""

    assets = sorted(
        (
            item
            for item in state.get("assets", [])
            if isinstance(item, Mapping)
            and item.get("planningReady") is True
        ),
        key=lambda item: (
            str(item.get("category") or ""),
            str(item.get("displayName") or ""),
            str(item.get("assetId") or ""),
        ),
    )
    if not assets:
        raise SemanticFacilityPlanError(
            "trusted_planning_assets_unavailable",
            "No trusted planning-ready Facility Layout assets are available.",
        )

    identity = state["identity"]
    dependencies = state["dependencyRevisions"]
    assumption_id = "assumption-generic-factory-program"
    selected_assets = []
    required_zones = []
    total_instances = 0
    for template in _COMPLETE_FACTORY_ZONE_TEMPLATES:
        member_ids = []
        used_asset_ids: set[str] = set()
        for selector_index, selector in enumerate(template["selectors"]):
            asset = _select_factory_asset(
                assets,
                selector,
                used_asset_ids=used_asset_ids,
            )
            if asset is None:
                continue
            quantity = int(selector["quantity"])
            if (
                total_instances + quantity
                > _COMPLETE_FACTORY_MAXIMUM_INSTANCES
            ):
                continue
            asset_id = str(asset["assetId"])
            digest = hashlib.sha256(
                asset_id.encode("utf-8")
            ).hexdigest()[:10]
            item_id = (
                f"factory-resource-{int(template['stage']) + 1}-"
                f"{selector_index + 1}-{digest}"
            )
            member_ids.append(item_id)
            used_asset_ids.add(asset_id)
            total_instances += quantity
            selected_assets.append(
                {
                    "itemId": item_id,
                    "assetId": asset_id,
                    "assetDefinitionRevision": asset[
                        "assetDefinitionRevision"
                    ],
                    "quantity": quantity,
                    "resourceRole": _resource_role(asset),
                    "stage": int(template["stage"]),
                    "targetZoneRef": template["zoneRequestId"],
                    "existingPlacementId": None,
                    "knowledgeStatus": "inferred",
                    "evidenceIds": [],
                    "assumptionIds": [assumption_id],
                }
            )
        if not member_ids:
            continue
        required_zones.append(
            {
                "zoneRequestId": template["zoneRequestId"],
                "zoneType": template["zoneType"],
                "label": template["label"],
                "existingZoneId": None,
                "memberItemIds": member_ids,
                "paddingClass": "generous",
                "knowledgeStatus": "inferred",
                "evidenceIds": [],
                "assumptionIds": [assumption_id],
            }
        )

    if not selected_assets or not required_zones:
        raise SemanticFacilityPlanError(
            "factory_program_assets_unavailable",
            "The trusted catalog cannot support a starter factory program.",
        )
    if total_instances > _COMPLETE_FACTORY_MAXIMUM_INSTANCES:
        raise SemanticFacilityPlanError(
            "factory_program_limit_exceeded",
            "The starter factory program exceeded its bounded instance limit.",
        )

    plan_seed = {
        "siteId": identity["siteId"],
        "layoutId": identity["layoutId"],
        "revision": identity["revision"],
        "message": _text(user_message, 1000),
        "zones": [
            {
                "zoneRequestId": item["zoneRequestId"],
                "memberItemIds": item["memberItemIds"],
            }
            for item in required_zones
        ],
        "assets": [
            {
                "itemId": item["itemId"],
                "assetId": item["assetId"],
                "assetDefinitionRevision": item[
                    "assetDefinitionRevision"
                ],
                "quantity": item["quantity"],
            }
            for item in selected_assets
        ],
    }
    plan_id = (
        "facility-plan-"
        + semantic_facility_plan_fingerprint(plan_seed)[:20]
    )
    zone_ids = [item["zoneRequestId"] for item in required_zones]
    relationships = [
        {
            "relationshipId": f"factory-flow-{index + 1}",
            "relationshipType": "upstream_of",
            "sourceRef": zone_ids[index],
            "targetRef": zone_ids[index + 1],
            "knowledgeStatus": "inferred",
            "evidenceIds": [],
            "assumptionIds": [assumption_id],
        }
        for index in range(len(zone_ids) - 1)
    ]
    subject_refs = [
        item["itemId"] for item in selected_assets
    ] + zone_ids
    return {
        "schemaVersion": SEMANTIC_FACILITY_PLAN_VERSION,
        "planId": plan_id,
        "scope": {
            "siteId": identity["siteId"],
            "layoutId": identity["layoutId"],
            "label": _text(
                raw_plan.get("intent")
                or raw_plan.get("objective")
                or user_message,
                160,
            ),
        },
        "objective": "place_and_cleanup",
        "sourceRevisions": {
            "layout": identity["revision"],
            "shell": dependencies["shellRevision"],
            "policy": dependencies["policySetRevision"],
        },
        "requiredCapabilities": [],
        "selectedAssets": selected_assets,
        "requiredZones": required_zones,
        "placementRelationships": relationships,
        "processBindings": [],
        "flows": [],
        "evidence": [],
        "assumptions": [
            {
                "assumptionId": assumption_id,
                "text": (
                    "This is a generic departmental factory program derived "
                    "from the available trusted asset catalog; operating "
                    "constraints require engineering review."
                ),
                "subjectRefs": subject_refs,
            }
        ],
        "unresolvedItems": [
            {
                "unresolvedId": "unresolved-floor-marking-review",
                "code": "detailed_floor_markings_require_review",
                "message": (
                    "The deterministic preview provides inferred macro aisle "
                    "markings; detailed departmental markings, labels, and "
                    "paint standards still require engineering review."
                ),
                "subjectRefs": zone_ids,
            },
            {
                "unresolvedId": "unresolved-safety-clearance-authority",
                "code": "safety_clearances_require_review",
                "message": (
                    "Authoritative machine, guarding, pedestrian, and "
                    "maintenance clearances require engineering review."
                ),
                "subjectRefs": zone_ids,
            },
            {
                "unresolvedId": "unresolved-material-flow-endpoints",
                "code": "material_flow_endpoints_require_review",
                "message": (
                    "Material-flow endpoints and route widths require "
                    "authoritative process and vehicle evidence."
                ),
                "subjectRefs": zone_ids,
            },
        ],
        "alternatives": [
            {
                "alternativeId": "alternative-flow",
                "strategy": "flow_lanes",
                "label": "Flow lanes",
            },
            {
                "alternativeId": "alternative-balanced",
                "strategy": "balanced_grid",
                "label": "Balanced",
            },
        ],
        "layoutHints": {
            "density": "spacious",
            "preserveManual": True,
            "preserveLocked": True,
            "replaceExistingContents": True,
            "primaryFlow": "west_to_east_department_sequence",
        },
    }


def _requests_existing_layout_cleanup(
    raw_plan: Mapping[str, Any],
    user_message: str,
) -> bool:
    objective = _text(raw_plan.get("objective"), 80).lower()
    if objective in {"cleanup_layout", "place_and_cleanup"}:
        return True
    intent_text = " ".join(
        value
        for value in (
            _text(raw_plan.get("intent"), 240),
            _text(raw_plan.get("label"), 160),
            _text(user_message, 1000),
        )
        if value
    )
    tokens = _intent_tokens(intent_text)
    cleanup_actions = {
        "cleanup",
        "improve",
        "optimize",
        "rearrange",
        "review",
        "validate",
    }
    existing_scope = {
        "cell",
        "current",
        "department",
        "existing",
        "facility",
        "layout",
        "workcell",
    }
    return bool(tokens & cleanup_actions) and bool(tokens & existing_scope)


def _requests_asset_addition(user_message: str) -> bool:
    """Return whether the user explicitly requested new layout resources."""

    tokens = _intent_tokens(user_message)
    return bool(
        tokens
        & {
            "add",
            "build",
            "create",
            "fill",
            "include",
            "insert",
            "introduce",
            "place",
            "populate",
        }
    )


def _canonical_cleanup_plan(
    raw_plan: Mapping[str, Any],
    *,
    user_message: str,
    state: TrustedFacilityContext,
) -> dict[str, Any]:
    identity = state["identity"]
    dependencies = state["dependencyRevisions"]
    plan_seed = {
        "siteId": identity["siteId"],
        "layoutId": identity["layoutId"],
        "revision": identity["revision"],
        "message": _text(user_message, 1000),
        "objective": "cleanup_layout",
    }
    plan_id = (
        "facility-plan-"
        + semantic_facility_plan_fingerprint(plan_seed)[:20]
    )
    return {
        "schemaVersion": SEMANTIC_FACILITY_PLAN_VERSION,
        "planId": plan_id,
        "scope": {
            "siteId": identity["siteId"],
            "layoutId": identity["layoutId"],
            "label": _text(
                raw_plan.get("intent")
                or raw_plan.get("objective")
                or user_message,
                160,
            ),
        },
        "objective": "cleanup_layout",
        "sourceRevisions": {
            "layout": identity["revision"],
            "shell": dependencies["shellRevision"],
            "policy": dependencies["policySetRevision"],
        },
        "requiredCapabilities": [],
        "selectedAssets": [],
        "requiredZones": [],
        "placementRelationships": [],
        "processBindings": [],
        "flows": [],
        "evidence": [],
        "assumptions": [],
        "unresolvedItems": [],
        "alternatives": [
            {
                "alternativeId": "alternative-balanced",
                "strategy": "balanced_grid",
                "label": "Balanced",
            },
            {
                "alternativeId": "alternative-flow",
                "strategy": "flow_lanes",
                "label": "Flow lanes",
            },
        ],
        "layoutHints": {
            "density": "balanced",
            "preserveManual": True,
            "preserveLocked": True,
            "primaryFlow": None,
        },
    }


def _canonical_plan_from_facility_intent(
    raw_plan: Mapping[str, Any],
    *,
    user_message: str,
    state: TrustedFacilityContext,
) -> dict[str, Any]:
    """Resolve loose model intent into exact trusted Plan v1 references.

    This adapter never trusts model-authored geometry, revisions, evidence, or
    approvals. It only performs unique text-to-catalog resolution; ambiguity
    fails closed instead of selecting a plausible resource.
    """

    forbidden: list[dict[str, Any]] = []
    _reject_forbidden_fields(raw_plan, "$.modelIntent", forbidden)
    if forbidden:
        raise SemanticFacilityPlanError(
            forbidden[0]["code"],
            forbidden[0]["message"],
            findings=forbidden,
        )
    assets = [
        item
        for item in state.get("assets", [])
        if isinstance(item, Mapping) and item.get("planningReady") is True
    ]
    if not assets:
        raise SemanticFacilityPlanError(
            "trusted_planning_assets_unavailable",
            "No trusted planning-ready Facility Layout assets are available.",
        )
    requests = _intent_asset_phrases(raw_plan)
    message_tokens = _intent_tokens(user_message)
    cleanup_requested = _requests_existing_layout_cleanup(
        raw_plan,
        user_message,
    )
    resolved: dict[tuple[str, str], dict[str, Any]] = {}

    def resolve_phrase(
        phrase: str,
        quantity: int,
        *,
        require_distinctive: bool,
    ) -> None:
        tokens = _intent_tokens(phrase)
        scored = sorted(
            (
                (_asset_match_score(tokens, asset), asset)
                for asset in assets
            ),
            key=lambda value: (
                -value[0][0],
                -value[0][1],
                value[0][2],
            ),
        )
        if not scored or scored[0][0][0] < (1 if require_distinctive else 2):
            return
        best = scored[0][0][:2]
        tied = [
            asset for score, asset in scored
            if score[:2] == best
        ]
        if len(tied) != 1:
            phrase_identity = tokens - _GENERIC_ASSET_WORDS
            exact_display_matches = [
                asset
                for asset in tied
                if (
                    _intent_tokens(asset.get("displayName"))
                    - _GENERIC_ASSET_WORDS
                ) == phrase_identity
            ]
            if len(exact_display_matches) == 1:
                tied = exact_display_matches
        if len(tied) != 1:
            raise SemanticFacilityPlanError(
                "semantic_asset_intent_ambiguous",
                f"Resource intent '{_text(phrase)}' matches multiple assets.",
            )
        asset = tied[0]
        key = (
            str(asset["assetId"]),
            str(asset["assetDefinitionRevision"]),
        )
        if key in resolved:
            resolved[key]["quantity"] = max(
                resolved[key]["quantity"],
                quantity,
            )
        else:
            resolved[key] = {
                "asset": asset,
                "quantity": quantity,
            }

    for request in requests:
        resolve_phrase(
            request["phrase"],
            request["quantity"],
            require_distinctive=True,
        )
    # Explicit model resource intent is the bounded selection authority. A
    # second free-text catalog sweep would add every similarly named variant
    # (for example, all workbench sizes) and can turn one requested resource
    # into hundreds of unintended instances.
    if not requests:
        for asset in assets:
            score = _asset_match_score(message_tokens, asset)
            if score[0] < 1 or score[1] < 2:
                continue
            key = (
                str(asset["assetId"]),
                str(asset["assetDefinitionRevision"]),
            )
            if key not in resolved:
                resolved[key] = {
                    "asset": asset,
                    "quantity": _quantity_near_asset(user_message, asset),
                }
    if not resolved and cleanup_requested:
        return _canonical_cleanup_plan(
            raw_plan,
            user_message=user_message,
            state=state,
        )
    if not resolved:
        raise SemanticFacilityPlanError(
            "semantic_asset_intent_unresolved",
            (
                "The requested resources do not resolve uniquely to trusted "
                "planning-ready assets."
            ),
        )

    ordered = sorted(
        resolved.values(),
        key=lambda item: (
            _resource_role(item["asset"]),
            str(item["asset"].get("assetId") or ""),
        ),
    )
    identity = state["identity"]
    dependencies = state["dependencyRevisions"]
    plan_seed = {
        "siteId": identity["siteId"],
        "layoutId": identity["layoutId"],
        "revision": identity["revision"],
        "message": _text(user_message, 1000),
        "assets": [
            {
                "assetId": item["asset"]["assetId"],
                "assetDefinitionRevision": item["asset"][
                    "assetDefinitionRevision"
                ],
                "quantity": item["quantity"],
            }
            for item in ordered
        ],
    }
    plan_id = (
        "facility-plan-"
        + semantic_facility_plan_fingerprint(plan_seed)[:20]
    )
    assumption_id = "assumption-review-operating-intent"
    item_ids = [
        f"resource-{index + 1}-{_identifier(item['asset']['assetId'])}"
        for index, item in enumerate(ordered)
    ]
    selected_assets = []
    for index, (item_id, resolved_item) in enumerate(
        zip(item_ids, ordered, strict=True)
    ):
        asset = resolved_item["asset"]
        selected_assets.append(
            {
                "itemId": item_id,
                "assetId": asset["assetId"],
                "assetDefinitionRevision": asset[
                    "assetDefinitionRevision"
                ],
                "quantity": resolved_item["quantity"],
                "resourceRole": _resource_role(asset),
                "stage": index,
                "targetZoneRef": None,
                "existingPlacementId": None,
                "knowledgeStatus": "inferred",
                "evidenceIds": [],
                "assumptionIds": [assumption_id],
            }
        )
    relationships = [
        {
            "relationshipId": f"relationship-{index + 1}",
            "relationshipType": "upstream_of",
            "sourceRef": item_ids[index],
            "targetRef": item_ids[index + 1],
            "knowledgeStatus": "inferred",
            "evidenceIds": [],
            "assumptionIds": [assumption_id],
        }
        for index in range(len(item_ids) - 1)
    ]
    unresolved_subjects = list(item_ids)
    plan = {
        "schemaVersion": SEMANTIC_FACILITY_PLAN_VERSION,
        "planId": plan_id,
        "scope": {
            "siteId": identity["siteId"],
            "layoutId": identity["layoutId"],
            "label": _text(
                raw_plan.get("intent")
                or raw_plan.get("objective")
                or user_message,
                160,
            ),
        },
        "objective": (
            "place_and_cleanup"
            if cleanup_requested
            else "place_asset_set"
        ),
        "sourceRevisions": {
            "layout": identity["revision"],
            "shell": dependencies["shellRevision"],
            "policy": dependencies["policySetRevision"],
        },
        "requiredCapabilities": [],
        "selectedAssets": selected_assets,
        # Generic intent does not create or resize a zone implicitly. Adding
        # the first workcell zone to a previously unzoned layout would make
        # unrelated existing placements fail containment. Workflow packages
        # may request zones explicitly when their membership is complete.
        "requiredZones": [],
        "placementRelationships": relationships,
        "processBindings": [],
        "flows": [],
        "evidence": [],
        "assumptions": [
            {
                "assumptionId": assumption_id,
                "text": (
                    "Review the inferred resource order, operating access, "
                    "clearances, utilities, and material handoff."
                ),
                "subjectRefs": list(item_ids),
            }
        ],
        "unresolvedItems": [
            {
                "unresolvedId": "unresolved-operating-authority",
                "code": "operating_constraints_require_review",
                "message": (
                    "Authoritative clearances, utilities, safety controls, "
                    "and material-flow endpoints require review."
                ),
                "subjectRefs": unresolved_subjects,
            }
        ],
        "alternatives": [
            {
                "alternativeId": "alternative-balanced",
                "strategy": "balanced_grid",
                "label": "Balanced",
            },
            {
                "alternativeId": "alternative-flow",
                "strategy": "flow_lanes",
                "label": "Flow lanes",
            },
        ],
        "layoutHints": {
            "density": "balanced",
            "preserveManual": True,
            "preserveLocked": True,
            "primaryFlow": "inferred_resource_sequence",
        },
    }
    if cleanup_requested and not any(
        state.get(key)
        for key in ("placements", "zones", "floorMarkings", "routes")
    ):
        plan["layoutHints"]["replaceExistingContents"] = True
    return plan


def canonicalize_semantic_facility_plan(
    raw_plan: Mapping[str, Any],
    *,
    user_message: str,
    state: TrustedFacilityContext,
    evidence: TrustedFacilityContext,
) -> tuple[dict[str, Any], bool]:
    """Return an exact valid Plan v1 and whether intent repair was required."""

    if _requests_complete_blank_factory(raw_plan, user_message, state):
        forbidden: list[dict[str, Any]] = []
        _reject_forbidden_fields(raw_plan, "$.modelIntent", forbidden)
        if forbidden:
            raise SemanticFacilityPlanError(
                forbidden[0]["code"],
                forbidden[0]["message"],
                findings=forbidden,
            )
        canonical = _canonical_complete_factory_plan(
            raw_plan,
            user_message=user_message,
            state=state,
        )
        validated = validate_semantic_facility_plan(
            canonical,
            state=state,
            evidence=evidence,
        )
        return validated["plan"], True

    cleanup_only = (
        _requests_existing_layout_cleanup(raw_plan, user_message)
        and not _requests_asset_addition(user_message)
    )
    try:
        validated = validate_semantic_facility_plan(
            raw_plan,
            state=state,
            evidence=evidence,
        )
    except SemanticFacilityPlanError as original:
        if original.code in {
            "semantic_plan_contains_raw_geometry",
            "semantic_plan_contains_approval_claim",
        }:
            raise
    else:
        if not cleanup_only:
            return validated["plan"], False

    canonical = (
        _canonical_cleanup_plan(
            raw_plan,
            user_message=user_message,
            state=state,
        )
        if cleanup_only
        else _canonical_plan_from_facility_intent(
            raw_plan,
            user_message=user_message,
            state=state,
        )
    )
    validated = validate_semantic_facility_plan(
        canonical,
        state=state,
        evidence=evidence,
    )
    return validated["plan"], True


def _stable_zone_id(plan_id: str, request_id: str) -> str:
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        request_id.lower(),
    ).strip("-")[:28]
    digest = hashlib.sha256(
        f"{plan_id}:{request_id}".encode("ascii")
    ).hexdigest()[:12]
    return f"zn-{slug or 'planned'}-{digest}"


def compile_semantic_facility_plan(
    plan: Mapping[str, Any],
    *,
    state: TrustedFacilityContext,
    evidence: TrustedFacilityContext,
) -> dict[str, Any]:
    """Compile validated semantics into one exact P8 declarative request."""

    validated = validate_semantic_facility_plan(
        plan,
        state=state,
        evidence=evidence,
    )
    normalized = validated["plan"]
    plan_id = normalized["planId"]
    plan_hash = semantic_facility_plan_fingerprint(normalized)
    zone_index = {
        item["zoneRequestId"]: item
        for item in normalized["requiredZones"]
    }
    asset_set = []
    for item in sorted(
        normalized["selectedAssets"],
        key=lambda value: value["itemId"],
    ):
        target_zone_id = None
        target_ref = _identifier(item.get("targetZoneRef"))
        if target_ref and zone_index.get(target_ref, {}).get("existingZoneId"):
            target_zone_id = zone_index[target_ref]["existingZoneId"]
        record = {
            "itemId": item["itemId"],
            "assetId": item["assetId"],
            "assetDefinitionRevision": item["assetDefinitionRevision"],
            "quantity": item["quantity"],
            "stage": item["stage"],
        }
        if target_zone_id:
            record["targetZoneId"] = target_zone_id
        if item.get("existingPlacementId") is not None:
            record["existingPlacementId"] = item["existingPlacementId"]
        asset_set.append(record)

    zone_sizing = []
    for item in sorted(
        normalized["requiredZones"],
        key=lambda value: value["zoneRequestId"],
    ):
        record: dict[str, Any] = {
            "memberItemIds": item["memberItemIds"],
            "paddingMeters": _ZONE_PADDING[
                item.get("paddingClass", "standard")
            ],
        }
        if item.get("existingZoneId"):
            record["zoneId"] = item["existingZoneId"]
        else:
            categories = sorted(
                {
                    str(
                        validated["context"]["assets"][
                            (
                                next(
                                    selected
                                    for selected in normalized["selectedAssets"]
                                    if selected["itemId"] == member_id
                                )["assetId"],
                                next(
                                    selected
                                    for selected in normalized["selectedAssets"]
                                    if selected["itemId"] == member_id
                                )["assetDefinitionRevision"],
                            )
                        ].get("category") or ""
                    )
                    for member_id in item["memberItemIds"]
                    if any(
                        selected["itemId"] == member_id
                        for selected in normalized["selectedAssets"]
                    )
                }
            )
            record["newZone"] = {
                "zoneId": _stable_zone_id(
                    plan_id,
                    item["zoneRequestId"],
                ),
                "zoneType": item["zoneType"],
                "label": _text(
                    item.get("label") or item["zoneRequestId"],
                    120,
                ),
                # Asset catalogs currently expose some category display
                # labels (for example, "Material Handling") where the
                # Facility Layout schema requires stable identifiers. A
                # partial allowlist would reject the omitted member assets,
                # and inventing slugs would not match their trusted category.
                # Keep such generated zones unrestricted until the catalog
                # publishes canonical category IDs.
                "allowedAssetCategories": (
                    categories
                    if categories
                    and all(_identifier(category) for category in categories)
                    else []
                ),
                "evidence": sorted(
                    {
                        evidence_id
                        for evidence_id in item.get("evidenceIds", [])
                        if _identifier(evidence_id)
                    }
                ),
            }
        zone_sizing.append(record)

    routes = []
    deferred = []
    for item in sorted(
        normalized["flows"],
        key=lambda value: value["flowId"],
    ):
        if item["flowKind"] == "utility":
            deferred.append(
                {
                    "type": "utility_flow",
                    "id": item["flowId"],
                    "code": "utility_network_planning_deferred",
                    "message": (
                        "P8 does not generate utility-network topology; this "
                        "validated semantic flow remains unresolved."
                    ),
                }
            )
            continue
        route = {
            "routeRequestId": item["flowId"],
            "routeKind": item["flowKind"],
            "sourceEndpoint": item["_sourceEndpoint"],
            "targetEndpoint": item["_targetEndpoint"],
            "requirements": [],
            "evidence": sorted(
                {
                    evidence_id
                    for evidence_id in item.get("evidenceIds", [])
                    if _identifier(evidence_id)
                }
            ),
        }
        if item["flowKind"] == "forklift":
            route.update(
                {
                    "vehicleProfileId": item["vehicleProfileId"],
                    "vehicleProfileRevision": item[
                        "vehicleProfileRevision"
                    ],
                    "allowReverse": False,
                }
            )
        else:
            deferred.append(
                {
                    "type": "route",
                    "id": item["flowId"],
                    "code": "route_mutation_not_supported",
                    "message": (
                        f"P8 can inspect but does not persist "
                        f"{item['flowKind']} route proposals."
                    ),
                }
            )
        routes.append(route)

    source_revisions = {
        "shell": normalized["sourceRevisions"]["shell"],
        "policy": normalized["sourceRevisions"]["policy"],
    }
    for binding in normalized["processBindings"]:
        source_revisions[
            f"process.{binding['processMapId']}"
        ] = binding["processMapRevision"]
        deferred.append(
            {
                "type": "process_binding",
                "id": binding["bindingIntentId"],
                "code": "process_binding_application_deferred",
                "message": (
                    "The process binding is validated and revision-bound but "
                    "is applied after deterministic placement IDs exist."
                ),
            }
        )
    for relationship in normalized["placementRelationships"]:
        deferred.append(
            {
                "type": "placement_relationship",
                "id": relationship["relationshipId"],
                "code": "semantic_relationship_advisory",
                "message": (
                    "The relationship remains a semantic layout preference; "
                    "P8 retains deterministic spatial authority."
                ),
            }
        )

    strategies = []
    for alternative in normalized["alternatives"]:
        strategy = alternative["strategy"]
        if strategy not in strategies:
            strategies.append(strategy)
    cleanup = {
        "enabled": normalized["objective"]
        in {"cleanup_layout", "place_and_cleanup"},
        "moveAuto": True,
        "movableManualPlacementIds": [],
    }
    if normalized["layoutHints"].get("replaceExistingContents") is True:
        cleanup["replaceExistingContents"] = True
    planner_request = {
        "schemaVersion": FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION,
        "requestId": f"request-p9-{plan_hash[:24]}",
        "objective": normalized["objective"],
        "assetSet": asset_set,
        "strategies": strategies,
        "maximumAlternatives": min(4, len(strategies)),
        "spacingMeters": _DENSITY_SPACING[
            normalized["layoutHints"]["density"]
        ],
        "cleanup": cleanup,
        "zoneSizing": zone_sizing,
        "routes": routes,
        "sourceRevisions": source_revisions,
    }
    planner_request = validate_layout_request(planner_request)
    semantic_summary = {
        "selectedAssetItemCount": len(asset_set),
        "requestedPlacementCount": sum(
            int(item["quantity"]) for item in asset_set
        ),
        "requiredCapabilityCount": len(
            normalized["requiredCapabilities"]
        ),
        "zoneRequestCount": len(zone_sizing),
        "flowCount": len(normalized["flows"]),
        "processBindingCount": len(normalized["processBindings"]),
        "assumptionCount": len(normalized["assumptions"]),
        "unresolvedCount": (
            len(normalized["unresolvedItems"]) + len(deferred)
        ),
    }
    binding = {
        "semanticPlanVersion": SEMANTIC_FACILITY_PLAN_VERSION,
        "planId": plan_id,
        "planHash": plan_hash,
        "siteId": state["identity"]["siteId"],
        "layoutId": state["identity"]["layoutId"],
        "layoutRevision": state["identity"]["revision"],
        "shellRevision": state["dependencyRevisions"]["shellRevision"],
        "policyRevision": state["dependencyRevisions"][
            "policySetRevision"
        ],
        "referencedAssets": [
            {
                "assetId": item["assetId"],
                "assetDefinitionRevision": item[
                    "assetDefinitionRevision"
                ],
            }
            for item in asset_set
        ],
        "referencedVehicles": [
            {
                "vehicleProfileId": item["vehicleProfileId"],
                "vehicleProfileRevision": item[
                    "vehicleProfileRevision"
                ],
            }
            for item in normalized["flows"]
            if item["flowKind"] == "forklift"
        ],
        "referencedProcessMaps": [
            {
                "processMapId": item["processMapId"],
                "processMapRevision": item["processMapRevision"],
            }
            for item in normalized["processBindings"]
        ],
        "plannerRequestHash": semantic_facility_plan_fingerprint(
            planner_request
        ),
    }
    return {
        "schemaVersion": 1,
        "plan": normalized,
        "planHash": plan_hash,
        "binding": binding,
        "bindingHash": semantic_facility_plan_fingerprint(binding),
        "plannerRequest": planner_request,
        "semanticSummary": semantic_summary,
        "assumptions": deepcopy(normalized["assumptions"]),
        "unresolvedItems": [
            *deepcopy(normalized["unresolvedItems"]),
            *deferred,
        ],
        "findings": validated["findings"],
    }


__all__ = [
    "EVIDENCE_STATUSES",
    "SEMANTIC_FACILITY_PLAN_VERSION",
    "SEMANTIC_FACILITY_MOVE_TOOL",
    "SEMANTIC_FACILITY_PREVIEW_TOOL",
    "SemanticFacilityPlanError",
    "canonicalize_semantic_facility_plan",
    "compile_semantic_facility_plan",
    "facility_layout_preview_tool_spec",
    "facility_layout_move_tool_spec",
    "semantic_facility_plan_fingerprint",
    "validate_semantic_facility_plan",
]
