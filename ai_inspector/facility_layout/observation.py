"""Trusted, revision-bound Facility Layout observation primitives.

The browser may report a small set of ephemeral editor facts. Layout geometry,
asset evidence, policy, revisions, proposals, and receipts must arrive through
typed server sources so a browser-authored mapping cannot masquerade as trusted
context.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .canonical import layout_revision
from .semantic_model import CELL_FEASIBILITY_STRATEGIES
from .spatial import (
    SpatialRecord,
    placement_clearance_records,
    placement_spatial_records,
)


FACILITY_LAYOUT_STATE_CONTRACT_VERSION = 1
FACILITY_LAYOUT_EVIDENCE_CONTRACT_VERSION = 1
FACILITY_LAYOUT_OBSERVATION_TOOL_VERSION = 1
MAXIMUM_SELECTION_IDS = 50
MAXIMUM_RECENT_RECEIPTS = 6
MAXIMUM_READ_IDS = 50
MAXIMUM_READ_PAGE_SIZE = 50

_REVISION_KINDS = frozenset(
    {
        "facility_layout",
        "industrial_asset_catalog",
        "facility_shell",
        "facility_policy",
        "vehicle_profiles",
        "process_maps",
        "facility_evidence",
        "facility_diagnostics",
        "facility_capabilities",
        "facility_proposal",
        "facility_receipts",
    }
)
_VIEWPORT_MODES = frozenset({"plan", "three", "split"})
_READ_TOOL_NAMES = (
    "search_industrial_assets",
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_findings",
    "inspect_process_bindings",
    "inspect_facility_semantics",
    "inspect_pattern_provenance",
    "inspect_cell_layout_provenance",
    "analyze_facility_spatial",
    "analyze_facility_fit",
)


class FacilityObservationError(ValueError):
    """Typed observation-boundary rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TrustedFacilityContext(dict):
    """JSON-compatible mapping carrying an in-process trust marker.

    The marker is intentionally lost when browser JSON is parsed. Consumers
    therefore reject a browser object even if it copies the visible
    ``origin.kind = server`` fields.
    """

    def __init__(self, context_kind: str, value: Mapping[str, Any]) -> None:
        super().__init__(deepcopy(dict(value)))
        self._trusted_facility_context_kind = context_kind


@dataclass(frozen=True)
class TrustedFacilitySource:
    """One server-loaded authority source.

    Callers cannot substitute a JSON mapping for this type. The source revision
    is an envelope/CAS revision and is not trusted from the source document.
    """

    source_kind: str
    revision: str
    document: Any
    provider: str
    origin_kind: str = "server"


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
        raise FacilityObservationError(
            "invalid_trusted_source",
            "Trusted Facility Layout sources must contain finite JSON values.",
        ) from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_text(value: Any, maximum: int = 240) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _clean_id(value: Any) -> str:
    text = _clean_text(value, 128)
    return text if text else ""


def _is_revision(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def trusted_facility_source(
    source_kind: str,
    document: Any,
    *,
    revision: str | None = None,
    provider: str = "facility-layout-server",
) -> TrustedFacilitySource:
    """Construct a detached server source with an exact revision."""

    if source_kind not in _REVISION_KINDS:
        raise FacilityObservationError(
            "unsupported_trusted_source_kind",
            f"Unsupported Facility Layout source kind '{source_kind}'.",
        )
    detached = json.loads(_canonical_bytes(document).decode("ascii"))
    effective_revision = revision or _fingerprint(detached)
    if not _is_revision(effective_revision):
        raise FacilityObservationError(
            "invalid_trusted_source_revision",
            f"{source_kind} requires a lowercase SHA-256 revision.",
        )
    provider_name = _clean_id(provider)
    if not provider_name:
        raise FacilityObservationError(
            "invalid_trusted_source_provider",
            "Trusted Facility Layout sources require a provider.",
        )
    return TrustedFacilitySource(
        source_kind=source_kind,
        revision=effective_revision,
        document=detached,
        provider=provider_name,
    )


def _require_source(
    value: Any,
    source_kind: str,
    *,
    optional: bool = False,
) -> TrustedFacilitySource | None:
    if value is None and optional:
        return None
    if not isinstance(value, TrustedFacilitySource):
        raise FacilityObservationError(
            "untrusted_facility_source",
            (
                f"{source_kind} must be loaded by the server. Browser mappings "
                "are not accepted as trusted geometry or evidence."
            ),
        )
    if value.origin_kind != "server" or value.source_kind != source_kind:
        raise FacilityObservationError(
            "trusted_source_origin_mismatch",
            f"Expected a server-origin {source_kind} source.",
        )
    if not _is_revision(value.revision):
        raise FacilityObservationError(
            "invalid_trusted_source_revision",
            f"{source_kind} has an invalid revision.",
        )
    return value


def assert_trusted_facility_context(
    value: Any,
    context_kind: str,
) -> TrustedFacilityContext:
    if (
        not isinstance(value, TrustedFacilityContext)
        or getattr(value, "_trusted_facility_context_kind", None) != context_kind
        or not isinstance(value.get("origin"), Mapping)
        or value["origin"].get("kind") != "server"
    ):
        raise FacilityObservationError(
            "untrusted_facility_context",
            f"{context_kind} must be compiled from typed server sources.",
        )
    return value


def _records(value: Any, *, plural_key: str) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        raw = value.get(plural_key)
        if isinstance(raw, list):
            values = raw
        elif plural_key == "assets":
            values = [
                item for _, item in sorted(value.items())
                if isinstance(item, Mapping)
            ]
        else:
            values = []
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return [
        deepcopy(dict(item))
        for item in values
        if isinstance(item, Mapping)
    ]


def _asset_document(value: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    raw_document = value.get("document")
    document = (
        deepcopy(dict(raw_document))
        if isinstance(raw_document, Mapping)
        else deepcopy(dict(value))
    )
    revision = value.get("revision") or value.get("assetDefinitionRevision")
    if not _is_revision(revision):
        revision = _fingerprint(document)
    return document, str(revision)


def _capability_ids(asset: Mapping[str, Any]) -> list[str]:
    result: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and _clean_id(value):
            result.add(_clean_id(value))
        elif isinstance(value, Mapping):
            for key in ("capabilityId", "processType", "id", "name"):
                if isinstance(value.get(key), str) and _clean_id(value[key]):
                    result.add(_clean_id(value[key]))
                    break
        elif isinstance(value, list):
            for item in value:
                add(item)

    capabilities = asset.get("capabilities")
    if isinstance(capabilities, Mapping):
        for key in (
            "items",
            "processTypes",
            "supportedProcesses",
            "capabilityIds",
        ):
            add(capabilities.get(key))
        for key, enabled in capabilities.items():
            if enabled is True and _clean_id(key):
                result.add(_clean_id(key))
    else:
        add(capabilities)
    return sorted(result)


def _connector_records(asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in asset.get("connectors", []):
        if not isinstance(raw, Mapping):
            continue
        connector_id = _clean_id(raw.get("connectorId"))
        if not connector_id:
            continue
        result.append(
            {
                "connectorId": connector_id,
                "connectorKind": _clean_text(
                    raw.get("connectorKind")
                    or raw.get("serviceType")
                    or "unknown",
                    80,
                ),
                "role": _clean_text(raw.get("role") or "unknown", 40),
                "allowedRouteKinds": sorted(
                    {
                        _clean_id(item)
                        for item in raw.get("allowedRouteKinds", [])
                        if _clean_id(item)
                    }
                ),
                "evidenceStatus": (
                    raw.get("evidenceStatus")
                    if raw.get("evidenceStatus")
                    in {"authored", "derived", "inferred", "unknown"}
                    else "unknown"
                ),
                "evidenceIds": sorted(
                    {
                        _clean_id(item)
                        for item in raw.get("evidence", [])
                        if _clean_id(item)
                    }
                ),
            }
        )
    return sorted(result, key=lambda item: item["connectorId"])


def _asset_dimensions(asset: Mapping[str, Any]) -> dict[str, float] | None:
    geometry = asset.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    aabb = geometry.get("aabb") or geometry.get("AABB")
    if isinstance(aabb, Mapping):
        minimum = aabb.get("minimum")
        maximum = aabb.get("maximum")
        if isinstance(minimum, Mapping) and isinstance(maximum, Mapping):
            try:
                return {
                    axis: round(
                        float(maximum[axis]) - float(minimum[axis]),
                        6,
                    )
                    for axis in ("x", "y", "z")
                }
            except (KeyError, TypeError, ValueError):
                pass
    polygons = geometry.get("footprintPolygons")
    interval = geometry.get("heightInterval")
    if isinstance(polygons, list) and polygons and isinstance(polygons[0], list):
        points = [
            point for point in polygons[0]
            if isinstance(point, Mapping)
            and isinstance(point.get("x"), (int, float))
            and not isinstance(point.get("x"), bool)
            and isinstance(point.get("z"), (int, float))
            and not isinstance(point.get("z"), bool)
        ]
        if points:
            xs = [float(item["x"]) for item in points]
            zs = [float(item["z"]) for item in points]
            height = 0.0
            if isinstance(interval, Mapping):
                try:
                    height = float(interval.get("maximumY", 0.0)) - float(
                        interval.get("minimumY", 0.0)
                    )
                except (TypeError, ValueError):
                    height = 0.0
            return {
                "x": round(max(xs) - min(xs), 6),
                "y": round(max(0.0, height), 6),
                "z": round(max(zs) - min(zs), 6),
            }
    return None


def _asset_footprint(asset: Mapping[str, Any]) -> dict[str, Any] | None:
    geometry = asset.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    polygons = geometry.get("footprintPolygons")
    polygon_areas = []
    if isinstance(polygons, list):
        for raw_polygon in polygons:
            if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                continue
            points = []
            try:
                for point in raw_polygon:
                    if not isinstance(point, Mapping):
                        raise TypeError
                    points.append((float(point["x"]), float(point["z"])))
            except (KeyError, TypeError, ValueError):
                continue
            area = abs(
                0.5
                * sum(
                    points[index][0]
                    * points[(index + 1) % len(points)][1]
                    - points[(index + 1) % len(points)][0]
                    * points[index][1]
                    for index in range(len(points))
                )
            )
            if area > 0:
                polygon_areas.append(area)
    if polygon_areas:
        return {
            "areaSquareMeters": round(sum(polygon_areas), 6),
            "polygonCount": len(polygon_areas),
            "method": "sum_geometry_footprint_polygons",
            "evidenceStatus": "derived",
            "qualification": (
                "Gross footprint area; overlapping source polygons are not "
                "unioned."
            ),
        }
    dimensions = _asset_dimensions(asset)
    if dimensions and dimensions["x"] > 0 and dimensions["z"] > 0:
        return {
            "areaSquareMeters": round(
                dimensions["x"] * dimensions["z"],
                6,
            ),
            "polygonCount": 0,
            "method": "geometry_aabb_rectangle",
            "evidenceStatus": "derived",
            "qualification": "Conservative rectangular AABB footprint.",
        }
    return None


def _asset_facility_semantics(asset: Mapping[str, Any]) -> dict[str, Any]:
    value = asset.get("facilitySemantics")
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    semantic_type = _clean_id(value.get("semanticType"))
    if semantic_type:
        result["semanticType"] = semantic_type
    roles = sorted(
        {
            _clean_id(item)
            for item in value.get("operationalRoles", [])
            if _clean_id(item)
        }
    )
    if roles:
        result["operationalRoles"] = roles
    functional_sides = value.get("functionalSides")
    if isinstance(functional_sides, Mapping):
        normalized_sides = {}
        for role, raw in functional_sides.items():
            role_id = _clean_id(role)
            if role_id not in {
                "operator", "service", "material_input", "material_output",
                "loading", "gate", "front", "rear",
            }:
                continue
            record = raw if isinstance(raw, Mapping) else {"side": raw}
            side = _clean_id(record.get("side"))
            if side not in {"north", "east", "south", "west", "top", "bottom"}:
                continue
            evidence_status = record.get("evidenceStatus")
            if evidence_status not in {
                "authored", "derived", "inferred", "unknown",
            }:
                evidence_status = "authored"
            normalized_sides[role_id] = {
                "side": side,
                "evidenceStatus": evidence_status,
            }
        if normalized_sides:
            result["functionalSides"] = dict(sorted(normalized_sides.items()))
    evidence_status = value.get("evidenceStatus")
    if evidence_status in {
        "authored",
        "derived",
        "inferred",
        "unknown",
    }:
        result["evidenceStatus"] = evidence_status
    return result


def _asset_mounting_surfaces(asset: Mapping[str, Any]) -> list[str]:
    coordinate_frame = asset.get("coordinateFrame")
    if not isinstance(coordinate_frame, Mapping):
        return []
    return sorted(
        {
            _clean_id(item)
            for item in coordinate_frame.get("allowedMountingSurfaces", [])
            if _clean_id(item)
        }
    )


def _asset_utility_kinds(asset: Mapping[str, Any]) -> list[str]:
    utilities = asset.get("utilities")
    if not isinstance(utilities, Mapping):
        return []
    return sorted(
        _clean_id(key)
        for key, value in utilities.items()
        if _clean_id(key) and value not in (None, False, [], {})
    )


def _readiness_gate(
    readiness: Mapping[str, Any],
    *names: str,
) -> tuple[bool, list[str]]:
    raw = None
    for name in names:
        if name in readiness:
            raw = readiness[name]
            break
    if isinstance(raw, Mapping):
        blockers = sorted(
            {
                _clean_id(item)
                for item in raw.get("blockers", [])
                if _clean_id(item)
            }
        )
        return raw.get("value") is True and not blockers, blockers
    if isinstance(raw, bool):
        return raw, [] if raw else ["planning_readiness_false"]
    return False, ["planning_readiness_missing"]


def _asset_catalog(source: TrustedFacilitySource) -> list[dict[str, Any]]:
    values = _records(source.document, plural_key="assets")
    result = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        document, revision = _asset_document(value)
        asset_id = _clean_id(document.get("assetId"))
        if not asset_id:
            continue
        key = (asset_id, revision)
        if key in seen:
            raise FacilityObservationError(
                "duplicate_trusted_asset_revision",
                f"Asset '{asset_id}' has a duplicate trusted revision.",
            )
        seen.add(key)
        readiness = document.get("readiness")
        readiness = readiness if isinstance(readiness, Mapping) else {}
        nested_definition = document.get("definition")
        nested_definition = (
            nested_definition
            if isinstance(nested_definition, Mapping)
            else {}
        )
        nested_readiness = nested_definition.get("readiness")
        nested_readiness = (
            nested_readiness
            if isinstance(nested_readiness, Mapping)
            else {}
        )
        if readiness:
            planning_evidence_complete, planning_blockers = _readiness_gate(
                readiness,
                "planningReady",
                "planning_ready",
            )
        else:
            planning_evidence_complete, planning_blockers = _readiness_gate(
                nested_readiness,
                "planningReady",
                "planning_ready",
            )
        preview_planning_eligible = (
            value.get("previewPlanningEligible") is True
        )
        planning_ready = (
            planning_evidence_complete or preview_planning_eligible
        )
        result.append(
            {
                "assetId": asset_id,
                "assetDefinitionRevision": revision,
                "displayName": _clean_text(
                    document.get("displayName") or asset_id,
                    160,
                ),
                "category": _clean_text(
                    document.get("category") or "unknown",
                    80,
                ),
                "description": _clean_text(
                    document.get("description"),
                    320,
                ),
                "tags": sorted(
                    {
                        _clean_id(item)
                        for item in document.get("tags", [])
                        if _clean_id(item)
                    }
                )[:32],
                "familyId": _clean_id(document.get("familyId")),
                "variantId": _clean_id(document.get("variantId")),
                "capabilityIds": _capability_ids(document),
                "connectors": _connector_records(document),
                "dimensions": _asset_dimensions(document),
                "footprint": _asset_footprint(document),
                "mobilityClassification": _clean_id(
                    document.get("mobility", {}).get("classification")
                    if isinstance(document.get("mobility"), Mapping)
                    else None
                ),
                "allowedMountingSurfaces": _asset_mounting_surfaces(
                    document
                ),
                "utilityKinds": _asset_utility_kinds(document),
                "facilitySemantics": _asset_facility_semantics(document),
                "clearanceRecordCount": len(
                    document.get("clearances", [])
                    if isinstance(document.get("clearances"), list)
                    else []
                ),
                "planningReady": planning_ready,
                "previewPlanningEligible": preview_planning_eligible,
                "planningReadinessEvidenceComplete": (
                    planning_evidence_complete
                ),
                "planningReadinessBlockers": planning_blockers,
                "evidenceIds": sorted(
                    {
                        _clean_id(item)
                        for item in document.get("evidence", [])
                        if _clean_id(item)
                    }
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["assetId"],
            item["assetDefinitionRevision"],
        ),
    )


def _asset_document_index(
    source: TrustedFacilitySource,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return exact revisioned definitions for server-side geometry work."""

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for value in _records(source.document, plural_key="assets"):
        document, revision = _asset_document(value)
        asset_id = _clean_id(document.get("assetId"))
        if asset_id:
            result[(asset_id, revision)] = document
    return result


def _spatial_record_projection(record: SpatialRecord) -> dict[str, Any]:
    return {
        "recordId": record.record_id,
        "polygon": [
            {"x": round(point[0], 9), "z": round(point[1], 9)}
            for point in record.polygon
        ],
        "minimumY": round(record.minimum_y, 9),
        "maximumY": round(record.maximum_y, 9),
        "recordKind": record.record_kind,
        "clearanceId": record.clearance_id,
        "clearanceKind": record.clearance_kind,
        "enforcement": record.enforcement,
        "evidenceStatus": record.evidence_status,
        "authoritative": record.authoritative,
    }


def _evidence_refs_authoritative(
    evidence_ids: Any,
    evidence_authority: Mapping[str, Mapping[str, Any]],
) -> bool:
    return bool(
        isinstance(evidence_ids, list)
        and evidence_ids
        and all(
            evidence_authority.get(str(evidence_id), {}).get("current") is True
            and evidence_authority.get(str(evidence_id), {}).get(
                "authoritative"
            ) is True
            and not evidence_authority.get(str(evidence_id), {}).get(
                "blockers"
            )
            for evidence_id in evidence_ids
        )
    )


def _shell_semantic_projection(
    source: TrustedFacilitySource,
    evidence_authority: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    document = source.document
    document = document if isinstance(document, Mapping) else {}
    floor_surfaces = []
    obstacle_count = 0
    for feature in document.get("features", []):
        if not isinstance(feature, Mapping):
            continue
        kind = _clean_id(feature.get("featureKind"))
        if kind == "floor_surface":
            geometry = feature.get("geometry")
            geometry = geometry if isinstance(geometry, Mapping) else {}
            boundary = geometry.get("boundary")
            if isinstance(boundary, list):
                evidence_ids = sorted(
                    _clean_id(item)
                    for item in feature.get("evidence", [])
                    if _clean_id(item)
                )
                floor_surfaces.append({
                    "featureId": _clean_id(feature.get("featureId")),
                    "boundary": deepcopy(boundary),
                    "elevation": geometry.get("elevation"),
                    "evidenceIds": evidence_ids,
                    "evidenceAuthoritative": _evidence_refs_authoritative(
                        evidence_ids,
                        evidence_authority,
                    ),
                })
        elif kind:
            obstacle_count += 1
    return {
        "shellId": _clean_id(document.get("shellId")),
        "shellRevision": source.revision,
        "status": _clean_id(document.get("status")),
        "floorSurfaces": sorted(
            floor_surfaces,
            key=lambda item: item["featureId"],
        ),
        "obstacleFeatureCount": obstacle_count,
        "floorGeometryAuthoritative": bool(
            floor_surfaces
            and all(
                item["evidenceAuthoritative"] for item in floor_surfaces
            )
        ),
        "unresolvedItems": deepcopy(
            document.get("unresolvedItems", [])
            if isinstance(document.get("unresolvedItems"), list)
            else []
        ),
    }


def _policy_semantic_projection(
    source: TrustedFacilitySource,
    evidence_authority: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    document = source.document
    document = document if isinstance(document, Mapping) else {}
    rules = []
    for raw in document.get("deterministicRules", []):
        if not isinstance(raw, Mapping):
            continue
        evidence_ids = sorted(
            _clean_id(item)
            for item in raw.get("evidence", [])
            if _clean_id(item)
        )
        rules.append({
            "ruleId": _clean_id(raw.get("ruleId")),
            "ruleType": _clean_id(raw.get("ruleType")),
            "severity": _clean_id(raw.get("severity")),
            "applicability": deepcopy(raw.get("applicability")),
            "parameters": deepcopy(raw.get("parameters")),
            "evidenceIds": evidence_ids,
            "evidenceAuthoritative": _evidence_refs_authoritative(
                evidence_ids,
                evidence_authority,
            ),
        })
    return {
        "policySetId": _clean_id(document.get("policySetId")),
        "policySetRevision": source.revision,
        "status": _clean_id(document.get("status")),
        "deterministicRules": sorted(
            rules,
            key=lambda item: (item["ruleType"], item["ruleId"]),
        ),
        "rulesAuthoritative": all(
            item["evidenceAuthoritative"] for item in rules
        ),
        "unresolvedItems": deepcopy(
            document.get("unresolvedItems", [])
            if isinstance(document.get("unresolvedItems"), list)
            else []
        ),
    }


def _vehicle_catalog(
    source: TrustedFacilitySource | None,
) -> list[dict[str, Any]]:
    if source is None:
        return []
    values = _records(source.document, plural_key="vehicles")
    result = []
    for value in values:
        document = (
            value.get("document")
            if isinstance(value.get("document"), Mapping)
            else value
        )
        vehicle_id = _clean_id(document.get("vehicleProfileId"))
        revision = (
            value.get("revision")
            or document.get("vehicleProfileRevision")
        )
        if vehicle_id and _is_revision(revision):
            result.append(
                {
                    "vehicleProfileId": vehicle_id,
                    "vehicleProfileRevision": str(revision),
                    "displayName": _clean_text(
                        document.get("displayName") or vehicle_id,
                        160,
                    ),
                    "reversePolicy": _clean_text(
                        document.get("reversePolicy") or "unknown",
                        40,
                    ),
                    "evidenceIds": sorted(
                        {
                            _clean_id(item)
                            for item in document.get("evidence", [])
                            if _clean_id(item)
                        }
                    ),
                }
            )
    return sorted(
        result,
        key=lambda item: (
            item["vehicleProfileId"],
            item["vehicleProfileRevision"],
        ),
    )


def _process_catalog(
    source: TrustedFacilitySource | None,
) -> list[dict[str, Any]]:
    if source is None:
        return []
    values = _records(source.document, plural_key="processMaps")
    result = []
    for value in values:
        process_map_id = _clean_id(
            value.get("processMapId") or value.get("mapId")
        )
        revision = value.get("processMapRevision") or value.get("revision")
        if not process_map_id or not _is_revision(revision):
            continue
        raw_edges = value.get("precedenceEdges")
        graph_topology_loaded = bool(value.get("graphTopologyLoaded")) or (
            isinstance(raw_edges, list)
        )
        precedence_edges = []
        for edge in raw_edges if isinstance(raw_edges, list) else []:
            if not isinstance(edge, Mapping):
                continue
            edge_id = _clean_id(edge.get("edgeId") or edge.get("id"))
            from_node_id = _clean_id(
                edge.get("fromNodeId") or edge.get("sourceNodeId")
            )
            to_node_id = _clean_id(
                edge.get("toNodeId") or edge.get("targetNodeId")
            )
            if not edge_id or not from_node_id or not to_node_id:
                continue
            precedence_edges.append({
                "edgeId": edge_id,
                "fromNodeId": from_node_id,
                "toNodeId": to_node_id,
                "edgeKind": _clean_text(
                    edge.get("edgeKind") or edge.get("kind") or "precedence",
                    40,
                ),
                "evidenceStatus": "authored",
            })
        result.append(
            {
                "productId": _clean_id(value.get("productId")),
                "processMapId": process_map_id,
                "processMapRevision": str(revision),
                "displayName": _clean_text(
                    value.get("displayName") or process_map_id,
                    160,
                ),
                "nodeIds": sorted(
                    {
                        _clean_id(item)
                        for item in value.get("nodeIds", [])
                        if _clean_id(item)
                    }
                ),
                "edgeIds": sorted(
                    {
                        _clean_id(item)
                        for item in value.get("edgeIds", [])
                        if _clean_id(item)
                    }
                ),
                "graphTopologyLoaded": graph_topology_loaded,
                "precedenceEdges": sorted(
                    precedence_edges,
                    key=lambda item: item["edgeId"],
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["processMapId"],
            item["processMapRevision"],
        ),
    )


def _evidence_context(
    source: TrustedFacilitySource | None,
) -> TrustedFacilityContext:
    records = []
    unresolved = []
    if source is not None:
        raw_document = source.document
        if isinstance(raw_document, Mapping):
            raw_records = raw_document.get("records")
            if not isinstance(raw_records, list):
                raw_records = raw_document.get("evidenceRecords")
            raw_unresolved = raw_document.get("unresolvedFacts", [])
        elif isinstance(raw_document, list):
            raw_records = raw_document
            raw_unresolved = []
        else:
            raw_records = []
            raw_unresolved = []
        for raw in raw_records or []:
            if not isinstance(raw, Mapping):
                continue
            evidence_id = _clean_id(raw.get("evidenceId"))
            status = raw.get("status")
            if (
                not evidence_id
                or status
                not in {"authored", "derived", "inferred", "unknown"}
            ):
                continue
            blockers = sorted(
                {
                    _clean_id(item)
                    for item in raw.get("blockers", [])
                    if _clean_id(item)
                }
            )
            source_ref = raw.get("sourceRef")
            safe_source = {}
            if isinstance(source_ref, Mapping):
                for key in (
                    "trustedSourceId",
                    "sourceRevision",
                    "locator",
                ):
                    if isinstance(source_ref.get(key), str):
                        safe_source[key] = _clean_text(
                            source_ref[key],
                            512 if key == "locator" else 128,
                        )
            records.append(
                {
                    "evidenceId": evidence_id,
                    "subjectRef": deepcopy(raw.get("subjectRef")),
                    "claimKey": _clean_text(raw.get("claimKey"), 200),
                    "status": status,
                    "current": raw.get("current") is True,
                    "authoritative": raw.get("authoritative") is True,
                    "blockers": blockers,
                    "sourceRef": safe_source,
                    "derivation": deepcopy(raw.get("derivation"))
                    if isinstance(raw.get("derivation"), Mapping)
                    else None,
                }
            )
        for raw in raw_unresolved or []:
            if not isinstance(raw, Mapping):
                continue
            unresolved.append(
                {
                    "findingId": _clean_id(
                        raw.get("findingId") or raw.get("id")
                    ),
                    "code": _clean_id(raw.get("code") or "unresolved_fact"),
                    "message": _clean_text(raw.get("message"), 600),
                    "subjectRefs": sorted(
                        {
                            _clean_id(item)
                            for item in raw.get("subjectRefs", [])
                            if _clean_id(item)
                        }
                    ),
                }
            )
    records.sort(key=lambda item: item["evidenceId"])
    unresolved.sort(
        key=lambda item: (
            item["code"],
            item["findingId"],
            item["message"],
        )
    )
    return TrustedFacilityContext(
        "facility_layout.evidence",
        {
            "evidenceContractVersion": (
                FACILITY_LAYOUT_EVIDENCE_CONTRACT_VERSION
            ),
            "origin": {
                "kind": "server",
                "provider": (
                    source.provider if source is not None else
                    "facility-layout-observation"
                ),
                "sourceRevision": (
                    source.revision if source is not None else None
                ),
            },
            "records": records,
            "unresolvedFacts": unresolved,
        },
    )


def _point_in_polygon(
    x: float,
    z: float,
    boundary: Sequence[Mapping[str, Any]],
) -> bool:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in boundary
        if isinstance(item, Mapping)
        and isinstance(item.get("x"), (int, float))
        and not isinstance(item.get("x"), bool)
        and isinstance(item.get("z"), (int, float))
        and not isinstance(item.get("z"), bool)
        and math.isfinite(float(item["x"]))
        and math.isfinite(float(item["z"]))
    ]
    if len(points) < 3:
        return False
    inside = False
    previous = points[-1]
    for current in points:
        x1, z1 = previous
        x2, z2 = current
        if ((z1 > z) != (z2 > z)) and (
            x < (x2 - x1) * (z - z1) / ((z2 - z1) or 1e-15) + x1
        ):
            inside = not inside
        previous = current
    return inside


def _known_ids(layout: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        "placementIds": {
            str(item.get("placementId"))
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        },
        "zoneIds": {
            str(item.get("zoneId"))
            for item in layout.get("zones", [])
            if isinstance(item, Mapping) and item.get("zoneId")
        },
        "floorMarkingIds": {
            str(item.get("markingId"))
            for item in layout.get("floorMarkings", [])
            if isinstance(item, Mapping) and item.get("markingId")
        },
        "routeIds": {
            str(item.get("routeId"))
            for item in layout.get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId")
        },
        "utilityNetworkIds": {
            str(item.get("utilityNetworkId"))
            for item in layout.get("utilityNetworks", [])
            if isinstance(item, Mapping) and item.get("utilityNetworkId")
        },
        "processBindingIds": {
            str(item.get("processBindingId"))
            for item in layout.get("processBindings", [])
            if isinstance(item, Mapping) and item.get("processBindingId")
        },
    }


def _selected_ids(value: Any, known: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            item
            for item in value[:MAXIMUM_SELECTION_IDS]
            if isinstance(item, str) and item in known
        }
    )


def sanitize_facility_layout_live_facts(
    value: Any,
    *,
    known_ids: Mapping[str, set[str]],
) -> dict[str, Any]:
    """Keep browser authority limited to ephemeral UI facts."""

    source = value if isinstance(value, Mapping) else {}
    selection = (
        source.get("selection")
        if isinstance(source.get("selection"), Mapping)
        else {}
    )
    viewport_mode = source.get("viewportMode")
    navigation = source.get("navigationCapabilities")
    navigation = navigation if isinstance(navigation, Mapping) else {}
    walkthrough = navigation.get("walkthrough")
    walkthrough = walkthrough if isinstance(walkthrough, Mapping) else {}
    drone = navigation.get("drone")
    drone = drone if isinstance(drone, Mapping) else {}
    render_consistency = source.get("renderConsistency")
    render_consistency = (
        render_consistency
        if isinstance(render_consistency, Mapping)
        else {}
    )
    generation_draft = source.get("generationDraft")
    generation_draft = (
        generation_draft if isinstance(generation_draft, Mapping) else {}
    )
    generation_status = str(generation_draft.get("status") or "")
    if generation_status not in {
        "pending",
        "running",
        "blocked",
        "complete",
        "saved",
        "cancelled",
        "expired",
        "stale",
    }:
        generation_status = "unknown"
    generation_stage = str(generation_draft.get("currentStageId") or "")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", generation_stage) is None:
        generation_stage = ""
    save_eligibility = str(generation_draft.get("saveEligibility") or "")
    if save_eligibility not in {"eligible", "blocked", "pending"}:
        save_eligibility = "unknown"

    def bounded_number(raw: Any, minimum: float, maximum: float) -> float | None:
        if isinstance(raw, bool):
            return None
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return min(maximum, max(minimum, parsed))

    def sanitize_transform_audit(raw: Any) -> dict[str, Any]:
        audit = raw if isinstance(raw, Mapping) else {}
        known_placements = known_ids.get("placementIds", set())
        status = audit.get("status")
        if status not in {"match", "mismatch", "incomplete", "unavailable"}:
            status = "unavailable"
        result = {
            "status": status,
            "expectedPlacementCount": bounded_number(
                audit.get("expectedPlacementCount"), 0, 1_000_000
            ),
            "auditedPlacementCount": bounded_number(
                audit.get("auditedPlacementCount"), 0, 1_000_000
            ),
            "transformMismatchIds": _selected_ids(
                audit.get("transformMismatchIds"), known_placements
            ),
            "missingPlacementIds": _selected_ids(
                audit.get("missingPlacementIds"), known_placements
            ),
            "unexpectedPlacementIds": _selected_ids(
                audit.get("unexpectedPlacementIds"), known_placements
            ),
            "unavailablePlacementIds": _selected_ids(
                audit.get("unavailablePlacementIds"), known_placements
            ),
            "visibilityOrPendingPlacementIds": _selected_ids(
                audit.get("visibilityOrPendingPlacementIds"),
                known_placements,
            ),
            "evidenceStatus": "browser_ephemeral",
        }
        result["reportedIssueCount"] = sum(
            len(result[key])
            for key in (
                "transformMismatchIds",
                "missingPlacementIds",
                "unexpectedPlacementIds",
                "unavailablePlacementIds",
            )
        )
        return result

    return {
        "dirty": bool(source.get("dirty")),
        "conflict": bool(source.get("conflict")),
        "editable": bool(source.get("editable")),
        "viewportMode": (
            viewport_mode if viewport_mode in _VIEWPORT_MODES else "plan"
        ),
        "generationDraft": {
            "active": generation_draft.get("active") is True,
            "status": generation_status,
            "currentStageId": generation_stage or None,
            "saveEligibility": save_eligibility,
            "writable": generation_draft.get("writable") is True,
            "evidenceStatus": "browser_ephemeral",
            "qualification": (
                "This reports the current editor draft lifecycle only. It is "
                "not saved layout geometry, approval, or persistence evidence."
            ),
        },
        "navigationCapabilities": {
            "activeMode": (
                navigation.get("activeMode")
                if navigation.get("activeMode") in {
                    "orbit", "walkthrough", "drone"
                }
                else "orbit"
            ),
            "walkthrough": {
                "supported": walkthrough.get("supported") is True,
                "active": walkthrough.get("active") is True,
            },
            "drone": {
                "supported": drone.get("supported") is True,
                "active": drone.get("active") is True,
                "assistedFlight": drone.get("assistedFlight") is True,
                "colliderRadiusMeters": bounded_number(
                    drone.get("colliderRadiusMeters"), 0.01, 25.0
                ),
                "obstacleCount": bounded_number(
                    drone.get("obstacleCount"), 0.0, 1_000_000.0
                ),
                "altitudeMeters": bounded_number(
                    drone.get("altitudeMeters"), -1_000.0, 100_000.0
                ),
                "nearestObstacleDistanceMeters": bounded_number(
                    drone.get("nearestObstacleDistanceMeters"), 0.0, 100_000.0
                ),
            },
            "evidenceStatus": "browser_ephemeral",
            "qualification": (
                "This reports the mounted viewer capability and current "
                "navigation state. It is not saved layout authority."
            ),
        },
        "renderConsistency": {
            "topPlan": sanitize_transform_audit(
                render_consistency.get("topPlan")
            ),
            "three": sanitize_transform_audit(
                render_consistency.get("three")
            ),
            "evidenceStatus": "browser_ephemeral",
            "qualification": (
                "Mounted renderer diagnostics are bounded ephemeral evidence. "
                "They are compared with the server-authoritative placement "
                "count but do not replace persisted layout authority."
            ),
        },
        "selection": {
            key: _selected_ids(selection.get(key), known_ids.get(key, set()))
            for key in (
                "placementIds",
                "zoneIds",
                "floorMarkingIds",
                "routeIds",
                "utilityNetworkIds",
                "processBindingIds",
            )
        },
    }


def _diagnostics(
    source: TrustedFacilitySource | None,
) -> dict[str, Any]:
    if source is None or not isinstance(source.document, Mapping):
        return {"findings": [], "metrics": {}}
    findings = [
        {
            key: deepcopy(raw[key])
            for key in (
                "findingId",
                "code",
                "severity",
                "message",
                "placementId",
                "zoneId",
                "routeId",
                "utilityNetworkId",
                "processBindingId",
                "details",
            )
            if key in raw
        }
        for raw in source.document.get("findings", [])
        if isinstance(raw, Mapping)
    ]
    findings.sort(
        key=lambda item: (
            str(item.get("severity") or ""),
            str(item.get("code") or ""),
            str(item.get("findingId") or ""),
        )
    )
    metrics = source.document.get("metrics")
    return {
        "findings": findings,
        "metrics": deepcopy(dict(metrics))
        if isinstance(metrics, Mapping)
        else {},
    }


def _proposal_summary(
    source: TrustedFacilitySource | None,
    *,
    layout_id: str,
    revision: str,
) -> dict[str, Any] | None:
    if source is None or not isinstance(source.document, Mapping):
        return None
    proposal = source.document
    if (
        proposal.get("layoutId") != layout_id
        or proposal.get("baseRevision") != revision
    ):
        return None
    return {
        "proposalId": _clean_id(proposal.get("proposalId")),
        "status": _clean_text(proposal.get("status") or "preview", 40),
        "baseRevision": revision,
        "selectedAlternativeId": _clean_id(
            proposal.get("selectedAlternativeId")
        ),
        "entityIds": sorted(
            {
                _clean_id(item)
                for item in proposal.get("entityIds", [])
                if _clean_id(item)
            }
        )[:250],
        "counts": deepcopy(proposal.get("counts"))
        if isinstance(proposal.get("counts"), Mapping)
        else {},
        "pendingApproval": proposal.get("pendingApproval") is not False,
    }


def _receipt_summaries(
    source: TrustedFacilitySource | None,
    *,
    layout_id: str,
) -> list[dict[str, Any]]:
    if source is None:
        return []
    values = _records(source.document, plural_key="receipts")
    result = []
    for value in values[-MAXIMUM_RECENT_RECEIPTS:]:
        if value.get("layoutId") != layout_id:
            continue
        record = {}
        for key in (
            "receiptId",
            "proposalId",
            "layoutId",
            "baseRevision",
            "revision",
            "diffHash",
            "dependencyFingerprint",
            "action",
        ):
            if isinstance(value.get(key), str):
                record[key] = _clean_text(value[key], 256)
        for key in (
            "createdIds",
            "movedIds",
            "removedIds",
            "warnings",
            "unresolvedItems",
            "validationSummary",
        ):
            if key in value:
                record[key] = deepcopy(value[key])
        if record:
            result.append(record)
    return result


def build_facility_layout_observation(
    layout_source: TrustedFacilitySource,
    asset_catalog_source: TrustedFacilitySource,
    *,
    shell_source: TrustedFacilitySource,
    policy_source: TrustedFacilitySource,
    evidence_source: TrustedFacilitySource | None = None,
    vehicle_source: TrustedFacilitySource | None = None,
    process_source: TrustedFacilitySource | None = None,
    diagnostics_source: TrustedFacilitySource | None = None,
    capabilities_source: TrustedFacilitySource | None = None,
    proposal_source: TrustedFacilitySource | None = None,
    receipts_source: TrustedFacilitySource | None = None,
    live_facts: Mapping[str, Any] | None = None,
) -> dict[str, TrustedFacilityContext]:
    """Compile exact saved state and evidence from typed server sources."""

    layout_source = _require_source(layout_source, "facility_layout")
    asset_catalog_source = _require_source(
        asset_catalog_source,
        "industrial_asset_catalog",
    )
    shell_source = _require_source(shell_source, "facility_shell")
    policy_source = _require_source(policy_source, "facility_policy")
    evidence_source = _require_source(
        evidence_source,
        "facility_evidence",
        optional=True,
    )
    vehicle_source = _require_source(
        vehicle_source,
        "vehicle_profiles",
        optional=True,
    )
    process_source = _require_source(
        process_source,
        "process_maps",
        optional=True,
    )
    diagnostics_source = _require_source(
        diagnostics_source,
        "facility_diagnostics",
        optional=True,
    )
    capabilities_source = _require_source(
        capabilities_source,
        "facility_capabilities",
        optional=True,
    )
    proposal_source = _require_source(
        proposal_source,
        "facility_proposal",
        optional=True,
    )
    receipts_source = _require_source(
        receipts_source,
        "facility_receipts",
        optional=True,
    )
    if not isinstance(layout_source.document, Mapping):
        raise FacilityObservationError(
            "invalid_trusted_layout",
            "The trusted Facility Layout document must be an object.",
        )
    layout = deepcopy(dict(layout_source.document))
    computed_revision = layout_revision(layout)
    if computed_revision != layout_source.revision:
        raise FacilityObservationError(
            "trusted_layout_revision_mismatch",
            "The trusted Facility Layout revision does not match its content.",
        )
    layout_id = _clean_id(layout.get("layoutId"))
    association = (
        layout.get("association")
        if isinstance(layout.get("association"), Mapping)
        else {}
    )
    site_id = _clean_id(association.get("siteId"))
    shell_ref = (
        layout.get("sourceShellRef")
        if isinstance(layout.get("sourceShellRef"), Mapping)
        else {}
    )
    policy_ref = (
        layout.get("policySetRef")
        if isinstance(layout.get("policySetRef"), Mapping)
        else {}
    )
    if shell_ref.get("shellRevision") != shell_source.revision:
        raise FacilityObservationError(
            "trusted_shell_revision_mismatch",
            "The loaded shell revision is not the layout shell revision.",
        )
    if policy_ref.get("policySetRevision") != policy_source.revision:
        raise FacilityObservationError(
            "trusted_policy_revision_mismatch",
            "The loaded policy revision is not the layout policy revision.",
        )

    assets = _asset_catalog(asset_catalog_source)
    asset_index = {
        (item["assetId"], item["assetDefinitionRevision"]): item
        for item in assets
    }
    asset_document_index = _asset_document_index(asset_catalog_source)
    evidence = _evidence_context(evidence_source)
    evidence_authority = {
        str(item.get("evidenceId")): item
        for item in evidence.get("records", [])
        if isinstance(item, Mapping) and item.get("evidenceId")
    }
    zones = sorted(
        [
            deepcopy(dict(item))
            for item in layout.get("zones", [])
            if isinstance(item, Mapping) and item.get("zoneId")
        ],
        key=lambda item: str(item.get("zoneId")),
    )
    placements = []
    stale_dependencies = []
    for raw in sorted(
        (
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        ),
        key=lambda item: str(item.get("placementId")),
    ):
        asset_key = (
            str(raw.get("assetId") or ""),
            str(raw.get("assetDefinitionRevision") or ""),
        )
        asset = asset_index.get(asset_key)
        asset_document = asset_document_index.get(asset_key)
        if asset is None:
            stale_dependencies.append(
                {
                    "kind": "asset_definition",
                    "id": asset_key[0],
                    "expectedRevision": asset_key[1],
                    "reason": "referenced_asset_revision_unavailable",
                }
            )
        transform = (
            raw.get("transform")
            if isinstance(raw.get("transform"), Mapping)
            else {}
        )
        point = (
            transform.get("position")
            if isinstance(transform.get("position"), Mapping)
            else {}
        )
        zone_ids = []
        try:
            x = float(point["x"])
            z = float(point["z"])
            zone_ids = [
                str(zone["zoneId"])
                for zone in zones
                if _point_in_polygon(x, z, zone.get("boundary", []))
            ]
        except (KeyError, TypeError, ValueError):
            pass
        physical_geometry = []
        clearance_geometry = []
        geometry_error = None
        if asset_document is not None:
            try:
                physical_geometry = [
                    _spatial_record_projection(record)
                    for record in placement_spatial_records(
                        raw,
                        asset_document,
                    )
                ]
                clearance_geometry = [
                    _spatial_record_projection(record)
                    for record in placement_clearance_records(
                        raw,
                        asset_document,
                        evidence_authority=evidence_authority,
                    )
                ]
            except (TypeError, ValueError) as exc:
                geometry_error = _clean_text(exc, 240)
        placements.append(
            {
                "placementId": str(raw["placementId"]),
                "assetId": asset_key[0],
                "assetDefinitionRevision": asset_key[1],
                "displayName": (
                    asset.get("displayName") if asset else asset_key[0]
                ),
                "category": asset.get("category") if asset else "unknown",
                "capabilityIds": (
                    deepcopy(asset.get("capabilityIds", []))
                    if asset else []
                ),
                "transform": deepcopy(raw.get("transform")),
                "positionMode": raw.get("positionMode"),
                "dimensions": deepcopy(asset.get("dimensions"))
                if asset else None,
                "footprint": deepcopy(asset.get("footprint"))
                if asset else None,
                "connectors": deepcopy(asset.get("connectors", []))
                if asset else [],
                "mobilityClassification": (
                    asset.get("mobilityClassification") if asset else None
                ),
                "allowedMountingSurfaces": (
                    deepcopy(asset.get("allowedMountingSurfaces", []))
                    if asset else []
                ),
                "utilityKinds": (
                    deepcopy(asset.get("utilityKinds", []))
                    if asset else []
                ),
                "facilitySemantics": (
                    deepcopy(asset.get("facilitySemantics", {}))
                    if asset else {}
                ),
                "clearanceRecordCount": (
                    int(asset.get("clearanceRecordCount") or 0)
                    if asset else 0
                ),
                "planningReady": (
                    asset.get("planningReady") is True
                    if asset else False
                ),
                "planningReadinessBlockers": (
                    deepcopy(asset.get("planningReadinessBlockers", []))
                    if asset else ["asset_definition_unavailable"]
                ),
                "planningReadinessEvidenceComplete": (
                    asset.get("planningReadinessEvidenceComplete") is True
                    if asset else False
                ),
                "physicalGeometry": physical_geometry,
                "clearanceGeometry": clearance_geometry,
                "geometryEvidenceStatus": (
                    "derived"
                    if physical_geometry
                    else "unknown"
                ),
                "geometryProjectionError": geometry_error,
                "zoneIds": sorted(zone_ids),
                "metadata": deepcopy(raw.get("metadata"))
                if isinstance(raw.get("metadata"), Mapping)
                else {},
            }
        )
    known_ids = _known_ids(layout)
    live = sanitize_facility_layout_live_facts(
        live_facts,
        known_ids=known_ids,
    )
    diagnostics = _diagnostics(diagnostics_source)
    vehicles = _vehicle_catalog(vehicle_source)
    process_maps = _process_catalog(process_source)
    capabilities = {}
    if (
        capabilities_source is not None
        and isinstance(capabilities_source.document, Mapping)
    ):
        capabilities = {
            str(key): bool(value)
            for key, value in sorted(capabilities_source.document.items())
            if isinstance(key, str)
        }
    proposal = _proposal_summary(
        proposal_source,
        layout_id=layout_id,
        revision=layout_source.revision,
    )
    state = TrustedFacilityContext(
        "facility_layout.state",
        {
            "stateContractVersion": FACILITY_LAYOUT_STATE_CONTRACT_VERSION,
            "origin": {
                "kind": "server",
                "provider": "facility-layout-observation",
                "sourceRevisions": {
                    "layout": layout_source.revision,
                    "catalog": asset_catalog_source.revision,
                    "shell": shell_source.revision,
                    "policy": policy_source.revision,
                    "evidence": (
                        evidence_source.revision
                        if evidence_source is not None else None
                    ),
                    "vehicles": (
                        vehicle_source.revision
                        if vehicle_source is not None else None
                    ),
                    "processMaps": (
                        process_source.revision
                        if process_source is not None else None
                    ),
                },
            },
            "identity": {
                "siteId": site_id,
                "layoutId": layout_id,
                "displayName": _clean_text(
                    layout.get("displayName") or layout_id,
                    160,
                ),
                "revision": layout_source.revision,
                "status": layout.get("status"),
            },
            "dependencyRevisions": {
                "shellId": shell_ref.get("shellId"),
                "shellRevision": shell_source.revision,
                "policySetId": policy_ref.get("policySetId"),
                "policySetRevision": policy_source.revision,
                "catalogSnapshotRevision": layout.get(
                    "catalogSnapshotRevision"
                ),
                "vehicleCatalogRevision": (
                    vehicle_source.revision
                    if vehicle_source is not None else None
                ),
                "processCatalogRevision": (
                    process_source.revision
                    if process_source is not None else None
                ),
            },
            "savedStateCurrent": not live["dirty"] and not live["conflict"],
            "editor": {
                "dirty": live["dirty"],
                "conflict": live["conflict"],
                "editable": live["editable"],
                "viewportMode": live["viewportMode"],
                "generationDraft": live["generationDraft"],
                "navigationCapabilities": live[
                    "navigationCapabilities"
                ],
                "renderConsistency": live["renderConsistency"],
            },
            "selection": live["selection"],
            "coordinateFrame": deepcopy(layout.get("coordinateFrame")),
            "facilityShell": _shell_semantic_projection(
                shell_source,
                evidence_authority,
            ),
            "facilityPolicy": _policy_semantic_projection(
                policy_source,
                evidence_authority,
            ),
            "zones": zones,
            "floorMarkings": sorted(
                [
                    {
                        **deepcopy(dict(item)),
                        "evidenceAuthoritative": bool(
                            isinstance(item.get("evidence"), list)
                            and bool(item.get("evidence"))
                            and all(
                                evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("current") is True
                                and evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("authoritative") is True
                                and not evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("blockers")
                                for evidence_id in item.get("evidence", [])
                            )
                        ),
                    }
                    for item in layout.get("floorMarkings", [])
                    if isinstance(item, Mapping) and item.get("markingId")
                ],
                key=lambda item: str(item.get("markingId")),
            ),
            "placements": placements,
            "routes": sorted(
                [
                    {
                        **deepcopy(dict(item)),
                        "clearanceAuthoritative": bool(
                            isinstance(item.get("extensions"), Mapping)
                            and isinstance(
                                item.get("extensions", {}).get(
                                    "facilityAisle"
                                ),
                                Mapping,
                            )
                            and item.get("extensions", {}).get(
                                "facilityAisle", {}
                            ).get("clearanceEvidenceStatus")
                            in {"authored", "derived"}
                            and isinstance(item.get("evidence"), list)
                            and bool(item.get("evidence"))
                            and all(
                                evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("current") is True
                                and evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("authoritative") is True
                                and not evidence_authority.get(
                                    str(evidence_id), {}
                                ).get("blockers")
                                for evidence_id in item.get("evidence", [])
                            )
                        ),
                    }
                    for item in layout.get("routes", [])
                    if isinstance(item, Mapping) and item.get("routeId")
                ],
                key=lambda item: str(item.get("routeId")),
            ),
            "utilityNetworks": sorted(
                [
                    deepcopy(dict(item))
                    for item in layout.get("utilityNetworks", [])
                    if isinstance(item, Mapping)
                    and item.get("utilityNetworkId")
                ],
                key=lambda item: str(item.get("utilityNetworkId")),
            ),
            "processBindings": sorted(
                [
                    deepcopy(dict(item))
                    for item in layout.get("processBindings", [])
                    if isinstance(item, Mapping)
                    and item.get("processBindingId")
                ],
                key=lambda item: str(item.get("processBindingId")),
            ),
            "assets": assets,
            "vehicles": vehicles,
            "processMaps": process_maps,
            "diagnostics": diagnostics,
            "capabilities": capabilities,
            "activeProposal": proposal,
            "recentReceipts": _receipt_summaries(
                receipts_source,
                layout_id=layout_id,
            ),
            "staleDependencies": sorted(
                stale_dependencies,
                key=lambda item: (
                    item["kind"],
                    item["id"],
                    item["expectedRevision"],
                ),
            ),
            "coordinateContract": {
                "persisted": "facility_world",
                "upAxis": "+Y",
                "floorAxes": ["+X", "+Z"],
                "cameraIsNotGeometry": True,
                "screenPixelsAcceptedForWrites": False,
                "modelCoordinatesAcceptedForWrites": False,
                "positionModes": ["auto", "manual", "locked"],
            },
        },
    )
    return {"state": state, "evidence": evidence}


def facility_layout_read_tool_specs() -> list[dict[str, Any]]:
    """Return the bounded, read-only P9 observation tool contracts."""

    common_response = (
        "Results are server-loaded at the active layout revision, ordered by "
        "stable ID, and bounded to 50 records. Continue only with the opaque "
        "server cursor; never supply coordinates or screen rectangles."
    )
    specs = [
        {
            "name": "search_industrial_assets",
            "description": (
                "Search authorized industrial assets by text, category, or "
                "capability. " + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "maxLength": 120,
                    },
                    "category": {
                        "type": "string",
                        "maxLength": 80,
                    },
                    "capabilityId": {
                        "type": "string",
                        "maxLength": 128,
                    },
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "inspect_facility_entities",
            "description": (
                "Inspect placements, zones, floor markings, routes, or utility networks by "
                "stable ID. " + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entityKind", "ids"],
                "properties": {
                    "entityKind": {
                        "enum": [
                            "placement",
                            "zone",
                            "floor_marking",
                            "route",
                            "utility_network",
                        ]
                    },
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                },
            },
        },
        {
            "name": "inspect_facility_region",
            "description": (
                "Inspect one named zone or shell feature by stable ID; model-"
                "authored rectangles are forbidden. " + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["regionKind", "regionId"],
                "properties": {
                    "regionKind": {"enum": ["zone", "shell_feature"]},
                    "regionId": {"type": "string", "maxLength": 128},
                },
            },
        },
        {
            "name": "inspect_facility_findings",
            "description": (
                "Inspect deterministic findings by stable ID or code. "
                + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "code": {"type": "string", "maxLength": 128},
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "inspect_process_bindings",
            "description": (
                "Inspect revision-bound Facility Layout to Process Map "
                "bindings by stable ID. " + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "processMapId": {
                        "type": "string",
                        "maxLength": 128,
                    },
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "inspect_facility_semantics",
            "description": (
                "Inspect the revision-bound semantic facility map, exact "
                "derived geometry metrics, asset operational roles, Facility "
                "Layout command meaning, or manufacturing-cell strategy "
                "knowledge. Use this before declaring a value unavailable "
                "when it may be deterministically derived. Inferred planning "
                "priors never satisfy safety or policy requirements. "
                + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["view"],
                "properties": {
                    "view": {
                        "enum": [
                            "overview",
                            "departments",
                            "department_metrics",
                            "zones",
                            "assets",
                            "placements",
                            "routes",
                            "route_crossings",
                            "floor_markings",
                            "process_bindings",
                            "layout_patterns",
                            "commands",
                            "cell_layout_strategies",
                            "derived_metrics",
                        ]
                    },
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "query": {
                        "type": "string",
                        "maxLength": 120,
                    },
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "inspect_pattern_provenance",
            "description": (
                "Inspect authored linear, circular, perimeter, or other "
                "Facility Layout pattern provenance without creating a "
                "pattern. Returns seed IDs, parameters, membership, and "
                "manual drift from the active revision. " + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "query": {"type": "string", "maxLength": 120},
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "inspect_cell_layout_provenance",
            "description": (
                "Inspect authored manufacturing-cell layout provenance and "
                "current geometric conformance without arranging or "
                "previewing a cell. Returns strategy, parameters, members, "
                "manual-edit state, and current classification. "
                + common_response
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ids": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "query": {"type": "string", "maxLength": 120},
                    "pageSize": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAXIMUM_READ_PAGE_SIZE,
                    },
                    "cursor": {"type": "string", "maxLength": 2048},
                },
            },
        },
        {
            "name": "analyze_facility_spatial",
            "description": (
                "Run one focused, bounded, read-only Facility analysis. Use "
                "resolve_entities for human labels or current selection; "
                "clearances for actual edge-to-edge distances; "
                "protected_intrusions for footprint overlap with routes, "
                "keep-clear, pedestrian, or material areas; and "
                "route_crossings for physical crossings and crosswalk "
                "coverage; route_widths for authored and narrowest known "
                "usable corridor widths after physical obstructions; "
                "free_space for exact connected open regions; "
                "layout_provenance for authored pattern/cell parameters and "
                "drift; cell_alternatives for all ten registered, validated "
                "cell-strategy comparisons; route_access for "
                "geometry-derived paths between "
                "zones; module_fit for complete authored cell-envelope fit "
                "lower bounds between a source cell and target zone; "
                "and operator_travel for authored process travel or "
                "an explicitly labelled geometric proxy; cell_access for "
                "authored gate, loading, and service interface geometry; "
                "asset_access for authored machine operator, service, "
                "loading, input, output, front, or rear approach geometry; "
                "drone_clearance for static 3D passage margins using the "
                "mounted Drone collider; render_consistency "
                "for mounted 2D/3D transform audits. Actual geometry is "
                "reported separately from "
                "policy adequacy, and the tool never mutates the layout."
                " Scopes and returned entities use stable IDs."
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["analysis"],
                "properties": {
                    "analysis": {
                        "enum": [
                            "resolve_entities",
                            "clearances",
                            "protected_intrusions",
                            "route_crossings",
                            "free_space",
                            "layout_provenance",
                            "route_access",
                            "route_widths",
                            "cell_alternatives",
                            "module_fit",
                            "operator_travel",
                            "asset_access",
                            "cell_access",
                            "drone_clearance",
                            "render_consistency",
                        ]
                    },
                    "query": {"type": "string", "maxLength": 120},
                    "entityKinds": {
                        "type": "array",
                        "maxItems": 6,
                        "uniqueItems": True,
                        "items": {
                            "enum": [
                                "placement",
                                "zone",
                                "asset",
                                "route",
                                "floor_marking",
                                "layout_pattern",
                            ]
                        },
                    },
                    "useCurrentSelection": {"type": "boolean"},
                    "scopeIds": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "unitMode": {
                        "enum": ["operational_units", "placements"]
                    },
                    "interfaceRole": {
                        "enum": [
                            "service",
                            "operator",
                            "loading",
                            "material_input",
                            "material_output",
                            "front",
                            "rear",
                        ]
                    },
                    "freeSpaceMetric": {
                        "enum": [
                            "geometric",
                            "known_planning",
                            "operational",
                        ]
                    },
                    "sourceQuery": {
                        "type": "string",
                        "maxLength": 120,
                    },
                    "targetQuery": {
                        "type": "string",
                        "maxLength": 120,
                    },
                    "sourceZoneIds": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "targetZoneIds": {
                        "type": "array",
                        "maxItems": MAXIMUM_READ_IDS,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 128},
                    },
                    "movementClass": {
                        "enum": [
                            "material",
                            "pedestrian",
                            "conveyor",
                            "any",
                        ]
                    },
                    "cellStrategies": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": len(CELL_FEASIBILITY_STRATEGIES),
                        "uniqueItems": True,
                        "items": {
                            "enum": list(CELL_FEASIBILITY_STRATEGIES)
                        },
                    },
                    "preferredGapMeters": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 20,
                    },
                    "invertU": {"type": "boolean"},
                    "orientationsDegrees": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "uniqueItems": True,
                        "items": {"enum": [0, 90, 180, 270]},
                    },
                    "moduleGapMeters": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "altitudeMeters": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100000,
                    },
                    "maximumResults": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
            },
        },
        {
            "name": "analyze_facility_fit",
            "description": (
                "Run a bounded, read-only deterministic fit search for one "
                "current asset inside one authored zone. Resolve the asset "
                "from an existing placement, current selection, human name, "
                "or an exact internal asset/revision pair; resolve the target "
                "zone by stable ID or human label. The server "
                "chooses probe coordinates and validates footprint, named "
                "clearance, protected-route, marking, shell, and policy "
                "constraints. Use this for 'can this asset fit?' questions. "
                "It does not estimate maximum quantity or production "
                "capacity, and it never mutates the layout."
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "assetId": {"type": "string", "maxLength": 128},
                    "assetDefinitionRevision": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "assetQuery": {"type": "string", "maxLength": 120},
                    "sourcePlacementId": {
                        "type": "string",
                        "maxLength": 128,
                    },
                    "useSelectedPlacement": {"type": "boolean"},
                    "zoneId": {"type": "string", "maxLength": 128},
                    "zoneQuery": {"type": "string", "maxLength": 120},
                    "orientationsDegrees": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "uniqueItems": True,
                        "items": {"enum": [0, 90, 180, 270]},
                    },
                    "maximumResults": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
            },
        },
    ]
    assert tuple(item["name"] for item in specs) == _READ_TOOL_NAMES
    return specs


__all__ = [
    "FACILITY_LAYOUT_EVIDENCE_CONTRACT_VERSION",
    "FACILITY_LAYOUT_OBSERVATION_TOOL_VERSION",
    "FACILITY_LAYOUT_STATE_CONTRACT_VERSION",
    "FacilityObservationError",
    "TrustedFacilityContext",
    "TrustedFacilitySource",
    "assert_trusted_facility_context",
    "build_facility_layout_observation",
    "facility_layout_read_tool_specs",
    "sanitize_facility_layout_live_facts",
    "trusted_facility_source",
]
