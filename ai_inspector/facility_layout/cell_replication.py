"""G6 deterministic replication and conformance of qualified cells."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import re
from typing import Any, Mapping, Sequence

from .canonical import (
    canonicalize_layout,
    layout_revision,
    trusted_canonical_layout_revision,
)
from .knowledge_foundation import (
    FacilityKnowledgeContractError,
    canonical_facility_knowledge_bytes,
)
from .operations import (
    apply_facility_layout_operations,
    apply_prevalidated_facility_layout_operations,
)
from .spatial import (
    diagnose_layout,
    placement_spatial_records,
    polygon_contains_polygon,
)


G6_CELL_REPLICATION_SCOPE = "repeated_modules"
G6_FACILITY_CELL_REPLICATION_TOOL = "generate_facility_cell_replication_draft"
G6_MAXIMUM_TARGET_AREAS = 20
G6_MAXIMUM_COPIED_PLACEMENTS = 900
G6_CANONICAL_COORDINATE_TOLERANCE_METERS = 1.0e-6

_INTENT = re.compile(
    r"\b(?:replicat(?:e|ed|ion)|duplicat(?:e|ed|ion)|copy|copies|repeat(?:ed)?|"
    r"reusable\s+(?:cell|module)|cell\s+module|module\s+pattern|"
    r"still\s+match|matches?\s+(?:the\s+)?(?:source|module)|drift(?:ed)?|"
    r"diverg(?:e|ed|ence)|conform(?:s|ance)?)\b",
    re.IGNORECASE,
)
_BUILD = re.compile(
    r"\b(?:replicate|duplicate|copy|repeat|create|build|apply)\b",
    re.IGNORECASE,
)
_READ = re.compile(
    r"\b(?:inspect|check|compare|report|show|still\s+match|drift|diverg|"
    r"conform|identical|consistent|same\s+as)\b",
    re.IGNORECASE,
)
_COORDINATE = re.compile(
    r"(?:\b(?:x|z)\s*=\s*-?\d|\bcoordinates?\b|\bworld\s+point\b|"
    r"\b-?\d+(?:\.\d+)?\s*(?:degrees?|deg)\b)",
    re.IGNORECASE,
)
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:safe|safety|compliant|compliance|osha|fire\s+code|building\s+code|"
    r"regulatory|throughput|capacity|ergonomic|ergonomics|optimal)\b",
    re.IGNORECASE,
)
_CURRENT_EDITED_STATE = re.compile(
    r"\b(?:current(?:ly)?\s+(?:edited\s+)?state|as\s+it\s+is\s+now|"
    r"including\s+(?:the\s+)?manual\s+edits?|copy\s+the\s+edits?)\b",
    re.IGNORECASE,
)
_MODULE_CONTEXT = re.compile(
    r"\b(?:cell|module|replica|replication|conformance|drift|divergence)\b",
    re.IGNORECASE,
)


class FacilityCellReplicationError(FacilityKnowledgeContractError):
    """A G6 replication request is ambiguous, unsupported, or infeasible."""


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _collection_revision(layout: Mapping[str, Any], field: str) -> str:
    return _revision(layout.get(field, []))


def _zone_index(layout: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("zoneId") or ""): deepcopy(dict(item))
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }


def _placement_index(layout: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("placementId") or ""): deepcopy(dict(item))
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }


def _zone_extensions(zone: Mapping[str, Any]) -> dict[str, Any]:
    value = zone.get("extensions")
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _layout_provenance(value: Mapping[str, Any]) -> dict[str, Any] | None:
    for container_name in ("metadata", "extensions"):
        container = value.get(container_name)
        if not isinstance(container, Mapping):
            continue
        provenance = container.get("layoutProvenance")
        if isinstance(provenance, Mapping):
            return deepcopy(dict(provenance))
    return None


def _current_geometry(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("placementId"):
        return {
            "kind": "placement",
            "transform": deepcopy(value.get("transform")),
        }
    return {
        "kind": "zone",
        "boundary": deepcopy(value.get("boundary")),
    }


def _geometry_state(value: Mapping[str, Any]) -> dict[str, Any]:
    provenance = _layout_provenance(value)
    if provenance is None:
        return {
            "status": "incomplete",
            "authoredGeometryAvailable": False,
            "matchesAuthoredGeometry": None,
            "manuallyEditedSinceCreation": False,
        }
    authored = provenance.get("authoredGeometry")
    available = isinstance(authored, Mapping)
    matches = authored == _current_geometry(value) if available else None
    edited = (
        provenance.get("manuallyEditedSinceCreation") is True
        or provenance.get("geometryEditedSinceCreation") is True
        or matches is False
    )
    return {
        "status": (
            "incomplete" if not available else ("modified" if edited else "consistent")
        ),
        "authoredGeometryAvailable": available,
        "matchesAuthoredGeometry": matches,
        "manuallyEditedSinceCreation": (
            provenance.get("manuallyEditedSinceCreation") is True
        ),
    }


def _is_qualified_source_zone(zone: Mapping[str, Any]) -> bool:
    extensions = _zone_extensions(zone)
    cell_group = extensions.get("cellGroup")
    provenance = extensions.get("layoutProvenance")
    command = provenance.get("command") if isinstance(provenance, Mapping) else None
    program_source = bool(
        command == "industrial_pattern_module_source"
        and provenance.get("generatedBy") == "facility_program_operation_plan_v1"
        and isinstance(provenance.get("programRevision"), str)
        and len(provenance.get("programRevision")) == 64
    ) if isinstance(provenance, Mapping) else False
    return bool(
        isinstance(cell_group, Mapping)
        and cell_group.get("groupKind") == "manufacturing_cell"
        and isinstance(provenance, Mapping)
        and (command == "cell_layout" or program_source)
        and provenance.get("authoredStrategy")
        and isinstance(provenance.get("seedEntityIds"), list)
        and provenance.get("seedEntityIds")
    )


def _qualified_source_zones(layout: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            deepcopy(dict(item))
            for item in layout.get("zones", [])
            if isinstance(item, Mapping) and _is_qualified_source_zone(item)
        ],
        key=lambda item: str(item.get("zoneId") or ""),
    )


def _resolve_zone(layout: Mapping[str, Any], value: str) -> dict[str, Any]:
    requested = str(value or "").strip()
    if not requested:
        raise FacilityCellReplicationError(
            "facility_cell_module_zone_required",
            "Name one existing Facility area.",
        )
    zones = [
        item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping)
        and (
            str(item.get("zoneId") or "") == requested
            or str(item.get("label") or "").strip().casefold()
            == requested.casefold()
        )
    ]
    if len(zones) != 1:
        raise FacilityCellReplicationError(
            (
                "facility_cell_module_zone_ambiguous"
                if zones
                else "facility_cell_module_zone_unknown"
            ),
            (
                f"Facility area '{requested}' is ambiguous."
                if zones
                else f"Facility area '{requested}' does not exist."
            ),
        )
    return deepcopy(dict(zones[0]))


def _source_members(
    layout: Mapping[str, Any], source_zone: Mapping[str, Any]
) -> list[dict[str, Any]]:
    provenance = _layout_provenance(source_zone) or {}
    member_ids = [str(item) for item in provenance.get("seedEntityIds", [])]
    placements = _placement_index(layout)
    missing = [item for item in member_ids if item not in placements]
    if missing:
        raise FacilityCellReplicationError(
            "facility_cell_module_source_member_missing",
            "The source cell no longer resolves to every authored member.",
            details={"missingPlacementIds": missing},
        )
    return [placements[item] for item in member_ids]


def _zone_member_ids(layout: Mapping[str, Any], zone_id: str) -> list[str]:
    result = []
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        zone_ids = placement.get("zoneIds")
        bound = (
            str(metadata.get("targetZoneId") or "") == zone_id
            or (isinstance(zone_ids, list) and zone_id in map(str, zone_ids))
        )
        if bound and placement.get("placementId"):
            result.append(str(placement["placementId"]))
    return sorted(result)


def _polygon_centroid(boundary: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in boundary
        if isinstance(item, Mapping) and "x" in item and "z" in item
    ]
    if len(points) < 3:
        raise FacilityCellReplicationError(
            "facility_cell_module_zone_geometry_invalid",
            "Cell replication requires a valid target boundary.",
        )
    twice_area = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if abs(twice_area) <= 1e-9:
        return (
            sum(item[0] for item in points) / len(points),
            sum(item[1] for item in points) / len(points),
        )
    factor = 1.0 / (3.0 * twice_area)
    x = 0.0
    z = 0.0
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        cross = current[0] * following[1] - following[0] * current[1]
        x += (current[0] + following[0]) * cross
        z += (current[1] + following[1]) * cross
    return x * factor, z * factor


def _relative_module_definition(
    source_zone: Mapping[str, Any], members: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    center_x, center_z = _polygon_centroid(source_zone.get("boundary", []))
    provenance = _layout_provenance(source_zone) or {}
    member_records = []
    member_ids = {str(item.get("placementId") or "") for item in members}
    for placement in members:
        transform = placement.get("transform")
        transform = transform if isinstance(transform, Mapping) else {}
        position = transform.get("position")
        position = position if isinstance(position, Mapping) else {}
        relationship = placement.get("snapRelationship")
        if isinstance(relationship, Mapping):
            support_id = str(relationship.get("supportPlacementId") or "")
            if support_id and support_id not in member_ids:
                raise FacilityCellReplicationError(
                    "facility_cell_module_external_dependency",
                    "The source cell has a placement relationship outside its authored member set.",
                    details={
                        "placementId": placement.get("placementId"),
                        "supportPlacementId": support_id,
                    },
                )
        member_records.append(
            {
                "sourcePlacementId": str(placement.get("placementId") or ""),
                "assetId": str(placement.get("assetId") or ""),
                "assetDefinitionRevision": str(
                    placement.get("assetDefinitionRevision") or ""
                ),
                "relativePosition": {
                    "x": float(position.get("x") or 0.0) - center_x,
                    "y": float(position.get("y") or 0.0),
                    "z": float(position.get("z") or 0.0) - center_z,
                },
                "quaternion": deepcopy(transform.get("quaternion")),
                "snapRelationship": deepcopy(relationship),
            }
        )
    return {
        "schemaVersion": 1,
        "sourceCellZoneId": str(source_zone.get("zoneId") or ""),
        "sourceCellLabel": str(source_zone.get("label") or ""),
        "authoredStrategy": provenance.get("authoredStrategy"),
        "strategyParameters": deepcopy(provenance.get("parameters") or {}),
        "members": member_records,
    }


def analyze_cell_replication_state(
    layout: Mapping[str, Any], source_cell: str | None = None
) -> dict[str, Any]:
    current = canonicalize_layout(deepcopy(dict(layout)))
    sources = _qualified_source_zones(current)
    if source_cell:
        source = _resolve_zone(current, source_cell)
        if not _is_qualified_source_zone(source):
            raise FacilityCellReplicationError(
                "facility_cell_module_source_unqualified",
                f"'{source.get('label')}' is not a qualified G5 source cell.",
            )
        sources = [source]
    if not sources:
        raise FacilityCellReplicationError(
            "facility_cell_module_source_required",
            "No qualified G5 source cell is present in the active draft.",
        )
    source_records = []
    all_zones = _zone_index(current)
    placements = _placement_index(current)
    for source in sources:
        members = _source_members(current, source)
        member_states = [
            {
                "placementId": str(item.get("placementId") or ""),
                **_geometry_state(item),
            }
            for item in members
        ]
        source_zone_state = _geometry_state(source)
        source_status = (
            "incomplete"
            if source_zone_state["status"] == "incomplete"
            or any(item["status"] == "incomplete" for item in member_states)
            else (
                "modified"
                if source_zone_state["status"] == "modified"
                or any(item["status"] == "modified" for item in member_states)
                else "consistent"
            )
        )
        definition = _relative_module_definition(source, members)
        module_revision = _revision(definition)
        replicas = []
        for target in all_zones.values():
            module = _zone_extensions(target).get("cellModule")
            if not isinstance(module, Mapping) or str(
                module.get("sourceCellZoneId") or ""
            ) != str(source.get("zoneId") or ""):
                continue
            copied_ids = [str(item) for item in module.get("copiedPlacementIds", [])]
            missing = [item for item in copied_ids if item not in placements]
            copied_states = [
                {
                    "placementId": item,
                    **_geometry_state(placements[item]),
                }
                for item in copied_ids
                if item in placements
            ]
            stale_source = str(module.get("moduleRevision") or "") != module_revision
            status = (
                "incomplete"
                if missing or any(item["status"] == "incomplete" for item in copied_states)
                else (
                    "modified"
                    if any(item["status"] == "modified" for item in copied_states)
                    else ("stale_source" if stale_source else "consistent")
                )
            )
            replicas.append(
                {
                    "targetZoneId": str(target.get("zoneId") or ""),
                    "targetArea": str(target.get("label") or ""),
                    "moduleId": str(module.get("moduleId") or ""),
                    "moduleRevision": str(module.get("moduleRevision") or ""),
                    "currentSourceModuleRevision": module_revision,
                    "status": status,
                    "missingPlacementIds": missing,
                    "modifiedPlacementIds": [
                        item["placementId"]
                        for item in copied_states
                        if item["status"] == "modified"
                    ],
                    "memberCount": len(copied_ids),
                }
            )
        source_records.append(
            {
                "sourceCellZoneId": str(source.get("zoneId") or ""),
                "sourceCellLabel": str(source.get("label") or ""),
                "authoredStrategy": definition["authoredStrategy"],
                "sourceStatus": source_status,
                "moduleRevision": module_revision,
                "memberCount": len(members),
                "modifiedMemberIds": [
                    item["placementId"]
                    for item in member_states
                    if item["status"] == "modified"
                ],
                "replicaCount": len(replicas),
                "replicas": sorted(replicas, key=lambda item: item["targetZoneId"]),
            }
        )
    return {
        "scope": G6_CELL_REPLICATION_SCOPE,
        "sourceCount": len(source_records),
        "sources": source_records,
        "saved": False,
        "qualification": (
            "Conformance compares current deterministic geometry with persisted "
            "authored snapshots; it does not establish process, safety, capacity, "
            "or compliance equivalence."
        ),
    }


def _closed_request(request: Mapping[str, Any]) -> None:
    allowed = {
        "request_id",
        "source_cell",
        "target_areas",
        "copy_current_edited_state",
        "preserve_departments",
        "preserve_routes",
        "preserve_markings",
        "preserve_source_cell",
        "preserve_manual_and_locked",
        "execution_mode",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise FacilityCellReplicationError(
            "facility_cell_module_model_geometry_refused",
            "G6 accepts source and target cell intent only; InspectorPro owns geometry.",
            details={"fields": unknown},
        )


def normalize_cell_replication_request(
    request: Mapping[str, Any], layout: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise FacilityCellReplicationError(
            "facility_cell_module_request_invalid",
            "G6 cell replication intent must be an object.",
        )
    _closed_request(request)
    for field in (
        "preserve_departments",
        "preserve_routes",
        "preserve_markings",
        "preserve_source_cell",
        "preserve_manual_and_locked",
    ):
        if request.get(field) is not True:
            raise FacilityCellReplicationError(
                "facility_cell_module_preservation_required",
                "G6 must preserve upstream geometry, source cells, and manual work.",
                details={"field": field},
            )
    if str(request.get("execution_mode") or "") != "authorized_draft_run":
        raise FacilityCellReplicationError(
            "facility_cell_module_execution_mode_invalid",
            "G6 requires authorized_draft_run mode.",
        )
    source = _resolve_zone(layout, str(request.get("source_cell") or ""))
    if not _is_qualified_source_zone(source):
        raise FacilityCellReplicationError(
            "facility_cell_module_source_unqualified",
            f"'{source.get('label')}' is not a qualified source cell.",
        )
    raw_targets = request.get("target_areas")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise FacilityCellReplicationError(
            "facility_cell_module_targets_required",
            "Name one or more empty target areas for the replicas.",
        )
    if len(raw_targets) > G6_MAXIMUM_TARGET_AREAS:
        raise FacilityCellReplicationError(
            "facility_cell_module_target_limit_exceeded",
            f"G6 supports at most {G6_MAXIMUM_TARGET_AREAS} target areas per request.",
        )
    targets = [_resolve_zone(layout, str(item or "")) for item in raw_targets]
    target_ids = [str(item.get("zoneId") or "") for item in targets]
    if len(target_ids) != len(set(target_ids)):
        raise FacilityCellReplicationError(
            "facility_cell_module_duplicate_target",
            "Each target area may appear only once.",
        )
    if str(source.get("zoneId") or "") in target_ids:
        raise FacilityCellReplicationError(
            "facility_cell_module_source_is_target",
            "The source cell cannot also be a replication target.",
        )
    occupied = {
        str(target.get("label") or ""): _zone_member_ids(
            layout, str(target.get("zoneId") or "")
        )
        for target in targets
    }
    occupied = {key: value for key, value in occupied.items() if value}
    if occupied:
        raise FacilityCellReplicationError(
            "facility_cell_module_target_occupied",
            "G6 will not overwrite or relocate resources already bound to a target area.",
            details={"occupiedTargets": occupied},
        )
    already_cells = [
        str(target.get("label") or "")
        for target in targets
        if isinstance(_zone_extensions(target).get("cellGroup"), Mapping)
        or isinstance(_zone_extensions(target).get("cellModule"), Mapping)
    ]
    if already_cells:
        raise FacilityCellReplicationError(
            "facility_cell_module_target_already_defined",
            "G6 will not replace an existing cell or module without a scoped update contract.",
            details={"targetAreas": already_cells},
        )
    analysis = analyze_cell_replication_state(
        layout, str(source.get("zoneId") or "")
    )["sources"][0]
    copy_current = request.get("copy_current_edited_state") is True
    if analysis["sourceStatus"] != "consistent" and not copy_current:
        raise FacilityCellReplicationError(
            "facility_cell_module_source_diverged",
            "The source cell differs from its authored G5 snapshot. Explicitly request the current edited state or restore the source first.",
            details={
                "sourceStatus": analysis["sourceStatus"],
                "modifiedMemberIds": analysis["modifiedMemberIds"],
            },
        )
    members = _source_members(layout, source)
    copied_count = len(members) * len(targets)
    if copied_count > G6_MAXIMUM_COPIED_PLACEMENTS:
        raise FacilityCellReplicationError(
            "facility_cell_module_operation_budget_exceeded",
            "The requested module copies exceed the bounded G6 placement budget.",
            details={"copiedPlacementCount": copied_count},
        )
    identity = {
        "sourceCellZoneId": source.get("zoneId"),
        "targetZoneIds": target_ids,
        "sourceModuleRevision": analysis["moduleRevision"],
        "copyCurrentEditedState": copy_current,
    }
    return {
        "scope": G6_CELL_REPLICATION_SCOPE,
        "requestId": str(request.get("request_id") or "").strip()
        or _stable_id("g6-request", identity),
        "sourceCell": str(source.get("label") or ""),
        "sourceCellZoneId": str(source.get("zoneId") or ""),
        "sourceStatus": analysis["sourceStatus"],
        "sourceModuleRevision": analysis["moduleRevision"],
        "sourceMemberPlacementIds": [
            str(item.get("placementId") or "") for item in members
        ],
        "targetAreas": [str(item.get("label") or "") for item in targets],
        "targetZoneIds": target_ids,
        "copyCurrentEditedState": copy_current,
        "sourceStateAuthority": (
            "explicit_current_edited_state" if copy_current else "authored_g5_snapshot"
        ),
        "preserveDepartments": True,
        "preserveRoutes": True,
        "preserveMarkings": True,
        "preserveSourceCell": True,
        "preserveManualAndLocked": True,
        "executionMode": "authorized_draft_run",
    }


def cell_replication_tool_spec() -> dict[str, Any]:
    return {
        "name": G6_FACILITY_CELL_REPLICATION_TOOL,
        "description": (
            "Replicate one qualified G5 manufacturing cell into one or more "
            "uniquely named empty target areas. Preserve exact asset revisions, "
            "relative transforms, orientations, internal relationships, source "
            "geometry, departments, routes, markings, and manual work. Supply no "
            "coordinates, transforms, inferred spacing, safety conclusions, or approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_cell": {"type": "string", "minLength": 1},
                "target_areas": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": G6_MAXIMUM_TARGET_AREAS,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "copy_current_edited_state": {"type": "boolean"},
                "preserve_departments": {"type": "boolean", "const": True},
                "preserve_routes": {"type": "boolean", "const": True},
                "preserve_markings": {"type": "boolean", "const": True},
                "preserve_source_cell": {"type": "boolean", "const": True},
                "preserve_manual_and_locked": {"type": "boolean", "const": True},
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "source_cell",
                "target_areas",
                "copy_current_edited_state",
                "preserve_departments",
                "preserve_routes",
                "preserve_markings",
                "preserve_source_cell",
                "preserve_manual_and_locked",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def _mentioned_zones(message: str, layout: Mapping[str, Any]) -> list[dict[str, Any]]:
    matches = []
    occupied: list[tuple[int, int]] = []
    candidates = sorted(
        [item for item in layout.get("zones", []) if isinstance(item, Mapping)],
        key=lambda item: len(str(item.get("label") or "")),
        reverse=True,
    )
    for zone in candidates:
        label = str(zone.get("label") or "").strip()
        if not label:
            continue
        for found in re.finditer(
            r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])",
            message,
            re.IGNORECASE,
        ):
            span = found.span()
            if any(not (span[1] <= left or span[0] >= right) for left, right in occupied):
                continue
            occupied.append(span)
            matches.append((span[0], deepcopy(dict(zone))))
            break
    return [item for _, item in sorted(matches, key=lambda pair: pair[0])]


def _unresolved_target_clause(
    message: str,
    zones: Sequence[Mapping[str, Any]],
) -> str:
    separator = re.search(r"\b(?:into|to)\b", message, re.IGNORECASE)
    if separator is None:
        return ""
    clause = message[separator.end():]
    for zone in sorted(
        zones,
        key=lambda item: len(str(item.get("label") or "")),
        reverse=True,
    ):
        label = str(zone.get("label") or "").strip()
        if label:
            clause = re.sub(
                r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])",
                " ",
                clause,
                flags=re.IGNORECASE,
            )
    clause = _CURRENT_EDITED_STATE.sub(" ", clause)
    clause = re.sub(
        r"\b(?:the|an?|and|or|empty|named|target|targets|area|areas|"
        r"department|departments|cell|cells|as|exact|replica|replicas|"
        r"copy|copies|please|using|with|from|of|current|edited|state|"
        r"manual|edits?)\b",
        " ",
        clause,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^A-Za-z0-9]+", " ", clause).strip()


def parse_cell_replication_turn(
    message: str, layout: Mapping[str, Any]
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if _INTENT.search(text) is None:
        return {"kind": "not_applicable"}
    mentioned = _mentioned_zones(text, layout)
    sources = [item for item in mentioned if _is_qualified_source_zone(item)]
    if not sources and _MODULE_CONTEXT.search(text) is None:
        return {"kind": "not_applicable"}
    if _COORDINATE.search(text):
        return {
            "kind": "refuse",
            "code": "facility_cell_module_coordinate_ownership",
            "response": (
                "**I cannot accept cell-copy coordinates, transforms, or angles from chat.** "
                "Name the qualified source cell and empty target areas; InspectorPro will compute and validate every transform."
            ),
        }
    if _UNSUPPORTED_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_cell_module_unsupported_engineering_claim",
            "response": (
                "**I cannot claim that repeated cells are safe, compliant, ergonomic, optimal, or capacity-equivalent from geometry alone.** "
                "Bind controlled requirements and acceptance criteria; nothing changed."
            ),
        }
    intent_text = text
    for zone in mentioned:
        label = str(zone.get("label") or "").strip()
        if label:
            intent_text = re.sub(
                r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])",
                " ",
                intent_text,
                flags=re.IGNORECASE,
            )
    build = _BUILD.search(intent_text) is not None
    read = _READ.search(intent_text) is not None
    if not build and read:
        if len(sources) > 1:
            return {
                "kind": "ask",
                "code": "facility_cell_module_source_ambiguous",
                "response": "**Name one source cell whose module family should be checked.** Nothing changed.",
            }
        try:
            analysis = analyze_cell_replication_state(
                layout,
                str(sources[0].get("zoneId") or "") if sources else None,
            )
        except FacilityCellReplicationError as exc:
            return {
                "kind": "ask",
                "code": exc.code,
                "response": f"**I could not inspect cell-module conformance.** {exc} Nothing changed.",
            }
        return {"kind": "read_only", "analysis": analysis}
    if not build:
        return {"kind": "not_applicable"}
    if len(sources) != 1:
        return {
            "kind": "ask",
            "code": (
                "facility_cell_module_source_ambiguous"
                if sources
                else "facility_cell_module_source_required"
            ),
            "response": (
                "**Name exactly one qualified G5 source cell.** "
                "InspectorPro will not guess which cell defines the reusable module."
            ),
        }
    source_id = str(sources[0].get("zoneId") or "")
    targets = [
        item for item in mentioned if str(item.get("zoneId") or "") != source_id
    ]
    unresolved = _unresolved_target_clause(text, mentioned)
    if unresolved:
        return {
            "kind": "ask",
            "code": "facility_cell_module_target_unknown",
            "response": (
                "**One or more requested target areas do not resolve in the active layout.** "
                f"Unresolved target text: {unresolved}. Name existing empty target areas; nothing changed."
            ),
        }
    if not targets:
        return {
            "kind": "ask",
            "code": "facility_cell_module_targets_required",
            "response": "**Name one or more empty target areas for the replicas.** Nothing changed.",
        }
    request = {
        "source_cell": str(sources[0].get("label") or ""),
        "target_areas": [str(item.get("label") or "") for item in targets],
        "copy_current_edited_state": _CURRENT_EDITED_STATE.search(text) is not None,
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_source_cell": True,
        "preserve_manual_and_locked": True,
        "execution_mode": "authorized_draft_run",
    }
    try:
        normalized = normalize_cell_replication_request(request, layout)
    except FacilityCellReplicationError as exc:
        return {
            "kind": "ask",
            "code": exc.code,
            "response": f"**I could not prepare that cell replication.** {exc} Nothing changed.",
        }
    return {"kind": "build", "request": normalized}


def _catalog_index(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for raw in asset_catalog:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get("definition")
        definition = deepcopy(dict(nested if isinstance(nested, Mapping) else raw))
        asset_id = str(raw.get("assetId") or definition.get("assetId") or "")
        revision = str(
            raw.get("assetDefinitionRevision")
            or definition.get("assetDefinitionRevision")
            or ""
        )
        if asset_id and revision:
            definition["assetId"] = asset_id
            definition["assetDefinitionRevision"] = revision
            result[(asset_id, revision)] = definition
    return result


def _remapped_zone_ids(
    source: Mapping[str, Any], source_zone_id: str, target_zone_id: str
) -> list[str]:
    raw = source.get("zoneIds")
    values = [str(item) for item in raw] if isinstance(raw, list) else []
    values = [target_zone_id if item == source_zone_id else item for item in values]
    if target_zone_id not in values:
        values.append(target_zone_id)
    return list(dict.fromkeys(values))


def _target_extensions(
    target: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    module_id: str,
    module_revision: str,
    request_id: str,
    source_state_authority: str,
    instance_index: int,
    id_map: Mapping[str, str],
) -> dict[str, Any]:
    extensions = _zone_extensions(target)
    source_extensions = _zone_extensions(source)
    cell_group = deepcopy(dict(source_extensions.get("cellGroup") or {}))
    auto_number = cell_group.get("autoNumber")
    if isinstance(auto_number, Mapping):
        auto_number = deepcopy(dict(auto_number))
        auto_number["seriesId"] = module_id
        auto_number["baseName"] = str(target.get("label") or "")[:80]
        auto_number["sequence"] = instance_index
        cell_group["autoNumber"] = auto_number
    extensions["cellGroup"] = cell_group
    extensions["cellModule"] = {
        "schemaVersion": 1,
        "moduleId": module_id,
        "moduleRevision": module_revision,
        "requestId": request_id,
        "sourceCellZoneId": str(source.get("zoneId") or ""),
        "sourceCellLabel": str(source.get("label") or ""),
        "targetZoneId": str(target.get("zoneId") or ""),
        "targetArea": str(target.get("label") or ""),
        "instanceIndex": instance_index,
        "sourceStateAuthority": source_state_authority,
        "sourcePlacementIds": list(id_map),
        "copiedPlacementIds": list(id_map.values()),
        "placementIdMap": [
            {"sourcePlacementId": key, "copiedPlacementId": value}
            for key, value in id_map.items()
        ],
    }
    return extensions


def compile_cell_replication_program(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    defer_spatial_validation: bool = False,
    defer_post_validation: bool = False,
    include_compiled_document: bool = False,
) -> dict[str, Any]:
    base = canonicalize_layout(deepcopy(dict(layout)))
    normalized = normalize_cell_replication_request(request, base)
    zones = _zone_index(base)
    placements = _placement_index(base)
    source = zones[normalized["sourceCellZoneId"]]
    members = [placements[item] for item in normalized["sourceMemberPlacementIds"]]
    definition = _relative_module_definition(source, members)
    module_revision = _revision(definition)
    if module_revision != normalized["sourceModuleRevision"]:
        raise FacilityCellReplicationError(
            "facility_cell_module_source_revision_changed",
            "The source cell changed while the replication request was being prepared.",
        )
    assets = _catalog_index(asset_catalog)
    missing_assets = [
        {
            "assetId": item.get("assetId"),
            "assetDefinitionRevision": item.get("assetDefinitionRevision"),
        }
        for item in members
        if (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        )
        not in assets
    ]
    if missing_assets:
        raise FacilityCellReplicationError(
            "facility_cell_module_asset_revision_unavailable",
            "Every source member requires its exact authoritative asset revision.",
            details={"missingAssets": missing_assets},
        )
    source_center = _polygon_centroid(source.get("boundary", []))
    module_id = _stable_id(
        "cell-module",
        {
            "sourceCellZoneId": normalized["sourceCellZoneId"],
            "moduleRevision": module_revision,
        },
    )
    operations: list[dict[str, Any]] = []
    replicas = []
    for target_index, target_zone_id in enumerate(
        normalized["targetZoneIds"], start=1
    ):
        target = zones[target_zone_id]
        target_center = _polygon_centroid(target.get("boundary", []))
        delta_x = round(target_center[0] - source_center[0], 6)
        delta_z = round(target_center[1] - source_center[1], 6)
        id_map = {
            str(item.get("placementId") or ""): _stable_id(
                "pl-g6",
                {
                    "requestId": normalized["requestId"],
                    "sourcePlacementId": item.get("placementId"),
                    "targetZoneId": target_zone_id,
                },
            )
            for item in members
        }
        provenance_id = _stable_id(
            "layout-module",
            {
                "moduleId": module_id,
                "targetZoneId": target_zone_id,
                "requestId": normalized["requestId"],
            },
        )
        provenance = {
            "schemaVersion": 1,
            "provenanceId": provenance_id,
            "command": "duplicate",
            "authoredStrategy": definition["authoredStrategy"],
            "seedEntityIds": list(normalized["sourceMemberPlacementIds"]),
            "parameters": {
                "requestId": normalized["requestId"],
                "moduleId": module_id,
                "moduleRevision": module_revision,
                "sourceCellZoneId": normalized["sourceCellZoneId"],
                "targetZoneId": target_zone_id,
                "sourceStateAuthority": normalized["sourceStateAuthority"],
                "translation": {"x": delta_x, "z": delta_z},
            },
            "instanceIndex": target_index,
            "manuallyEditedSinceCreation": False,
        }
        operations.append(
            {
                "op": "edit_zone",
                "zoneId": target_zone_id,
                "patch": {
                    "extensions": _target_extensions(
                        target,
                        source,
                        module_id=module_id,
                        module_revision=module_revision,
                        request_id=normalized["requestId"],
                        source_state_authority=normalized["sourceStateAuthority"],
                        instance_index=target_index,
                        id_map=id_map,
                    )
                },
                "layoutProvenance": deepcopy(provenance),
            }
        )
        copied = []
        for source_member in members:
            source_id = str(source_member.get("placementId") or "")
            copy = deepcopy(source_member)
            copy["placementId"] = id_map[source_id]
            transform = deepcopy(dict(copy.get("transform") or {}))
            position = deepcopy(dict(transform.get("position") or {}))
            position["x"] = round(
                float(position.get("x") or 0.0) + delta_x, 6
            )
            position["z"] = round(
                float(position.get("z") or 0.0) + delta_z, 6
            )
            transform["position"] = position
            copy["transform"] = transform
            copy["positionMode"] = "auto"
            copy["zoneIds"] = _remapped_zone_ids(
                source_member,
                normalized["sourceCellZoneId"],
                target_zone_id,
            )
            relationship = copy.get("snapRelationship")
            if isinstance(relationship, Mapping):
                relationship = deepcopy(dict(relationship))
                support_id = str(relationship.get("supportPlacementId") or "")
                if support_id:
                    relationship["supportPlacementId"] = id_map[support_id]
                copy["snapRelationship"] = relationship
            metadata = deepcopy(dict(copy.get("metadata") or {}))
            metadata.update(
                {
                    "generatedBy": "facility_cell_replication_g6",
                    "gate": "G6",
                    "requestId": normalized["requestId"],
                    "sourceRequestId": metadata.get("requestId"),
                    "sourcePlacementId": source_id,
                    "sourceCellZoneId": normalized["sourceCellZoneId"],
                    "targetZoneId": target_zone_id,
                    "targetArea": str(target.get("label") or ""),
                    "moduleId": module_id,
                    "moduleRevision": module_revision,
                    "moduleInstanceIndex": target_index,
                    "layoutProvenance": deepcopy(provenance),
                }
            )
            copy["metadata"] = metadata
            operations.append({"op": "place_asset", "placement": copy})
            copied.append(
                {
                    "sourcePlacementId": source_id,
                    "copiedPlacementId": id_map[source_id],
                    "assetId": str(copy.get("assetId") or ""),
                    "assetDefinitionRevision": str(
                        copy.get("assetDefinitionRevision") or ""
                    ),
                    "transform": deepcopy(copy["transform"]),
                    "snapRelationship": deepcopy(copy.get("snapRelationship")),
                }
            )
        replicas.append(
            {
                "targetArea": str(target.get("label") or ""),
                "targetZoneId": target_zone_id,
                "instanceIndex": target_index,
                "translation": {"x": delta_x, "z": delta_z},
                "placementIdMap": [
                    {"sourcePlacementId": key, "copiedPlacementId": value}
                    for key, value in id_map.items()
                ],
                "copiedPlacements": copied,
            }
        )
    if defer_post_validation:
        result = apply_prevalidated_facility_layout_operations(
            base,
            operations,
            base_revision=trusted_canonical_layout_revision(base),
        )
    else:
        result = apply_facility_layout_operations(
            base, operations, base_revision=layout_revision(base)
        )
    expected = {
        "scope": G6_CELL_REPLICATION_SCOPE,
        "requestId": normalized["requestId"],
        "sourceCell": normalized["sourceCell"],
        "sourceCellZoneId": normalized["sourceCellZoneId"],
        "sourceStatus": normalized["sourceStatus"],
        "sourceStateAuthority": normalized["sourceStateAuthority"],
        "sourceModuleRevision": module_revision,
        "moduleId": module_id,
        "sourceMemberPlacementIds": list(
            normalized["sourceMemberPlacementIds"]
        ),
        "targetAreas": list(normalized["targetAreas"]),
        "targetZoneIds": list(normalized["targetZoneIds"]),
        "replicas": replicas,
        "replicaCount": len(replicas),
        "copiedPlacementCount": sum(
            len(item["copiedPlacements"]) for item in replicas
        ),
        "authoredStrategy": definition["authoredStrategy"],
        "preservedCollectionRevisions": {
            field: _collection_revision(base, field)
            for field in (
                "routes",
                "floorMarkings",
                "utilityNetworks",
                "processBindings",
            )
        },
        "saved": False,
    }
    if not defer_post_validation:
        validation = validate_cell_replication_result(
            result["document"],
            expected,
            asset_catalog,
            base_layout=base,
            validate_spatial=not defer_spatial_validation,
        )
        if validation["status"] != "valid":
            raise FacilityCellReplicationError(
                "facility_cell_module_program_validation_failed",
                "Compiled G6 cell replication failed deterministic post-validation.",
                details={"errors": validation["errors"]},
            )
    replay_input = {
        "scope": G6_CELL_REPLICATION_SCOPE,
        "request": {
            "request_id": normalized["requestId"],
            "source_cell": normalized["sourceCell"],
            "target_areas": list(normalized["targetAreas"]),
            "copy_current_edited_state": normalized["copyCurrentEditedState"],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_source_cell": True,
            "preserve_manual_and_locked": True,
            "execution_mode": "authorized_draft_run",
        },
        "assetCatalog": [deepcopy(dict(item)) for item in asset_catalog],
    }
    compiled_result = {
        "stageId": G6_CELL_REPLICATION_SCOPE,
        "selectedCommandIds": ["duplicate", "create-cell-group"],
        "operations": operations,
        "plannedInstanceCount": expected["copiedPlacementCount"],
        "normalizedRequest": replay_input,
        "assumptions": [],
        "validationPlan": [
            "qualified_g5_source",
            "source_snapshot_conformance",
            "exact_asset_revision_preservation",
            "deterministic_identity_remapping",
            "relative_transform_and_rotation_preservation",
            "internal_relationship_remapping",
            "target_zone_containment",
            "physical_collision_and_route_obstruction_rejection",
            "department_geometry_preservation",
            "source_and_manual_state_preservation",
            "pattern_provenance_and_drift_snapshot",
        ],
        "expectedSummary": expected,
    }
    if include_compiled_document:
        compiled_result["_compiledDocument"] = result["document"]
    return compiled_result


def validate_cell_replication_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    base_layout: Mapping[str, Any],
    validate_spatial: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    current = canonicalize_layout(deepcopy(dict(layout)))
    base = canonicalize_layout(deepcopy(dict(base_layout)))
    current_zones = _zone_index(current)
    base_zones = _zone_index(base)
    target_ids = set(expected.get("targetZoneIds") or [])
    if set(current_zones) != set(base_zones):
        errors.append("zone_identity_changed")
    for zone_id, before in base_zones.items():
        after = current_zones.get(zone_id)
        if after is None:
            continue
        if before.get("boundary") != after.get("boundary"):
            errors.append(f"department_boundary_changed:{zone_id}")
        if zone_id not in target_ids and before != after:
            errors.append(f"unrelated_zone_changed:{zone_id}")
    for field, revision in expected.get("preservedCollectionRevisions", {}).items():
        if _collection_revision(current, str(field)) != revision:
            errors.append(f"preserved_collection_changed:{field}")
    base_placements = _placement_index(base)
    current_placements = _placement_index(current)
    copied_records = [
        item
        for replica in expected.get("replicas", [])
        for item in replica.get("copiedPlacements", [])
    ]
    copied_ids = {str(item.get("copiedPlacementId") or "") for item in copied_records}
    if set(current_placements) != set(base_placements) | copied_ids:
        errors.append("placement_identity_set_mismatch")
    for placement_id, before in base_placements.items():
        if current_placements.get(placement_id) != before:
            errors.append(f"existing_placement_changed:{placement_id}")
    assets = _catalog_index(asset_catalog)
    replica_by_target = {
        str(item.get("targetZoneId") or ""): item
        for item in expected.get("replicas", [])
    }
    new_physical: dict[str, list[Any]] = {}
    for item in copied_records:
        placement_id = str(item.get("copiedPlacementId") or "")
        placement = current_placements.get(placement_id)
        if placement is None:
            errors.append(f"copied_placement_missing:{placement_id}")
            continue
        if (
            placement.get("assetId") != item.get("assetId")
            or placement.get("assetDefinitionRevision")
            != item.get("assetDefinitionRevision")
            or placement.get("transform") != item.get("transform")
            or placement.get("snapRelationship") != item.get("snapRelationship")
        ):
            errors.append(f"copied_placement_mismatch:{placement_id}")
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        target_id = str(metadata.get("targetZoneId") or "")
        replica = replica_by_target.get(target_id)
        if replica is None:
            errors.append(f"copied_target_binding_invalid:{placement_id}")
            continue
        if (
            metadata.get("generatedBy") != "facility_cell_replication_g6"
            or metadata.get("moduleId") != expected.get("moduleId")
            or metadata.get("moduleRevision")
            != expected.get("sourceModuleRevision")
        ):
            errors.append(f"copied_provenance_invalid:{placement_id}")
        target = current_zones.get(target_id)
        asset = assets.get(
            (
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            )
        )
        if target is None or asset is None:
            errors.append(f"copied_target_or_asset_missing:{placement_id}")
            continue
        try:
            records = list(placement_spatial_records(placement, asset))
        except (TypeError, ValueError):
            records = []
        boundary = tuple(
            (float(point["x"]), float(point["z"]))
            for point in target.get("boundary", [])
            if isinstance(point, Mapping)
        )
        if not records or not all(
            polygon_contains_polygon(
                boundary,
                record.polygon,
                tolerance=G6_CANONICAL_COORDINATE_TOLERANCE_METERS,
            )
            for record in records
        ):
            errors.append(
                "copied_placement_outside_target:"
                f"{placement_id}:"
                f"{metadata.get('sourcePlacementId')}:"
                f"{metadata.get('targetArea')}:"
                f"{placement.get('assetId')}:"
                f"{placement.get('transform')}:"
                f"{target.get('boundary')}"
            )
        new_physical[placement_id] = records
    guard_ids_by_target: dict[str, list[str]] = {}
    for placement_id in copied_ids:
        placement = current_placements.get(placement_id) or {}
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if (
            placement.get("assetId")
            == "asset-5987t55-wire-mesh-machine-guard-panel"
            and metadata.get("spacingAuthority") == "panel_abutment_geometry"
        ):
            guard_ids_by_target.setdefault(
                str(metadata.get("targetZoneId") or ""), []
            ).append(placement_id)
    allowed_guard_contacts = {
        tuple(sorted(pair))
        for values in guard_ids_by_target.values()
        for pair in combinations(sorted(values), 2)
    }
    spatial = {"findings": []}
    if validate_spatial:
        try:
            spatial = diagnose_layout(
                current,
                list(assets.values()),
                allowed_contact_pairs=allowed_guard_contacts,
            )
        except (TypeError, ValueError):
            errors.append("spatial_validation_failed")
    blocking_codes = {
        "placement_collision",
        "shell_obstacle_collision",
        "zone_containment_violation",
        "exclusion_zone_violation",
        "zone_kind_incompatible",
    }
    for finding in spatial.get("findings", []):
        refs = {str(item) for item in finding.get("subjectRefs", [])}
        copied_refs = refs & copied_ids
        if finding.get("code") == "placement_collision" and len(copied_refs) == 2:
            left, right = (current_placements[item] for item in sorted(copied_refs))
            left_metadata = left.get("metadata")
            right_metadata = right.get("metadata")
            left_metadata = left_metadata if isinstance(left_metadata, Mapping) else {}
            right_metadata = right_metadata if isinstance(right_metadata, Mapping) else {}
            same_guard_module = (
                left.get("assetId")
                == right.get("assetId")
                == "asset-5987t55-wire-mesh-machine-guard-panel"
                and left_metadata.get("spacingAuthority")
                == right_metadata.get("spacingAuthority")
                == "panel_abutment_geometry"
                and left_metadata.get("targetZoneId")
                == right_metadata.get("targetZoneId")
            )
            left_relationship = left.get("snapRelationship")
            right_relationship = right.get("snapRelationship")
            authored_support = (
                isinstance(left_relationship, Mapping)
                and left_relationship.get("supportPlacementId") == right.get("placementId")
            ) or (
                isinstance(right_relationship, Mapping)
                and right_relationship.get("supportPlacementId") == left.get("placementId")
            )
            if same_guard_module or authored_support:
                continue
        if copied_refs and (
            finding.get("severity") == "error"
            or finding.get("code") in blocking_codes
        ):
            errors.append(
                f"spatial_blocker:{finding.get('code')}:"
                + ":".join(sorted(copied_refs))
            )
    for target_id in target_ids:
        target = current_zones.get(target_id) or {}
        module = _zone_extensions(target).get("cellModule")
        if not isinstance(module, Mapping):
            errors.append(f"cell_module_metadata_missing:{target_id}")
            continue
        if (
            module.get("moduleId") != expected.get("moduleId")
            or module.get("moduleRevision")
            != expected.get("sourceModuleRevision")
        ):
            errors.append(f"cell_module_metadata_invalid:{target_id}")
    return {
        "status": "valid" if not errors else "invalid",
        "sourceCellZoneId": expected.get("sourceCellZoneId"),
        "replicaCount": len(expected.get("replicas", [])),
        "copiedPlacementCount": len(copied_ids),
        "validatedPlacementCount": len(new_physical),
        "spatialValidationDeferred": not validate_spatial,
        "departmentGeometryPreserved": not any(
            item.startswith("department_boundary_changed") for item in errors
        ),
        "sourceCellPreserved": not any(
            item.startswith("existing_placement_changed") for item in errors
        ),
        "errors": sorted(set(errors)),
    }


__all__ = [
    "G6_CELL_REPLICATION_SCOPE",
    "G6_FACILITY_CELL_REPLICATION_TOOL",
    "G6_MAXIMUM_COPIED_PLACEMENTS",
    "G6_MAXIMUM_TARGET_AREAS",
    "FacilityCellReplicationError",
    "analyze_cell_replication_state",
    "cell_replication_tool_spec",
    "compile_cell_replication_program",
    "normalize_cell_replication_request",
    "parse_cell_replication_turn",
    "validate_cell_replication_result",
]
