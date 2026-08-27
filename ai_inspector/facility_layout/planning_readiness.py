"""Revision-bound planning readiness for Facility Layout assets and zones.

This module projects existing asset definitions and zone semantics into a
compact evidence contract. It never calculates placement geometry. Bounded fit
questions delegate to :mod:`fit_analysis`, which remains the spatial owner.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .fit_analysis import analyze_facility_asset_fit
from .semantic_model import (
    classify_facility_asset_semantics,
    classify_facility_zone_semantics,
)
from .spatial import canonical_spatial_bytes


FACILITY_PLANNING_READINESS_VERSION = 1
FACILITY_PLANNING_EVIDENCE_STATUSES = (
    "authored",
    "derived",
    "inferred",
    "unknown",
)
FACILITY_DIRECTIONAL_INTERFACE_ROLES = (
    "front",
    "operator",
    "load",
    "unload",
    "input",
    "output",
    "service",
)
FACILITY_PLANNING_READINESS_LEVELS = (
    "unavailable",
    "visual_only",
    "placement_ready",
    "geometric_planning_ready",
    "controlled_planning_ready",
)

_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_SIDE_VALUES = frozenset(
    {"north", "east", "south", "west", "top", "bottom"}
)
_DIRECTION_ROLE_ALIASES = {
    "front": "front",
    "operator": "operator",
    "operator_side": "operator",
    "load": "load",
    "loading": "load",
    "load_side": "load",
    "unload": "unload",
    "unloading": "unload",
    "unload_side": "unload",
    "input": "input",
    "material_input": "input",
    "infeed": "input",
    "output": "output",
    "material_output": "output",
    "outfeed": "output",
    "service": "service",
    "maintenance": "service",
}
_ACCESS_CLEARANCE_TERMS = frozenset(
    {"access", "door", "drawer", "maintenance", "operator", "service"}
)


class FacilityPlanningReadinessError(ValueError):
    """Stable validation failure for a planning-readiness projection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityPlanningReadinessError(
            "planning_readiness_not_canonical",
            "Planning-readiness content must be canonical JSON.",
        ) from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_id(value: Any) -> str:
    return "_".join(str(value or "").strip().casefold().split())


def _status(value: Any, *, default: str = "unknown") -> str:
    normalized = _clean_id(value)
    if normalized in FACILITY_PLANNING_EVIDENCE_STATUSES:
        return normalized
    # Some private visual manifests use unverified. It is not evidence that a
    # planning rule may consume, so the canonical contract reports unknown.
    return default


def _hard_rule_eligible(evidence_status: str) -> bool:
    return evidence_status in {"authored", "derived"}


def _asset_document(asset: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    definition = asset.get("definition")
    document = (
        deepcopy(dict(definition))
        if isinstance(definition, Mapping)
        else deepcopy(dict(asset))
    )
    for key in (
        "assetId",
        "displayName",
        "category",
        "description",
        "tags",
        "capabilityIds",
        "facilitySemantics",
        "previewPlanningEligible",
    ):
        if key not in document and key in asset:
            document[key] = deepcopy(asset[key])
    asset_id = str(document.get("assetId") or asset.get("assetId") or "").strip()
    revision = str(
        asset.get("assetDefinitionRevision")
        or document.get("assetDefinitionRevision")
        or ""
    ).strip()
    return document, asset_id, revision


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _footprint_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    geometry = document.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    polygons = geometry.get("footprintPolygons")
    polygon_count = 0
    point_count = 0
    if isinstance(polygons, list):
        for polygon in polygons:
            if not isinstance(polygon, list) or len(polygon) < 3:
                continue
            valid = True
            for point in polygon:
                if not isinstance(point, Mapping):
                    valid = False
                    break
                if _finite(point.get("x")) is None or _finite(point.get("z")) is None:
                    valid = False
                    break
            if valid:
                polygon_count += 1
                point_count += len(polygon)
    if polygon_count:
        method = "revision_bound_footprint_polygons"
    else:
        aabb = geometry.get("aabb") or geometry.get("AABB")
        minimum = aabb.get("minimum") if isinstance(aabb, Mapping) else None
        maximum = aabb.get("maximum") if isinstance(aabb, Mapping) else None
        valid_aabb = bool(
            isinstance(minimum, Mapping)
            and isinstance(maximum, Mapping)
            and all(
                _finite(minimum.get(axis)) is not None
                and _finite(maximum.get(axis)) is not None
                and float(maximum[axis]) > float(minimum[axis])
                for axis in ("x", "y", "z")
            )
        )
        method = "revision_bound_aabb_envelope" if valid_aabb else None
    return {
        "available": method is not None,
        "method": method,
        "polygonCount": polygon_count,
        "pointCount": point_count,
        "evidenceStatus": "derived" if method else "unknown",
        "hardRuleEligible": method is not None,
    }


def _height_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    geometry = document.get("geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    interval = geometry.get("heightInterval")
    if isinstance(interval, Mapping):
        low = _finite(interval.get("minimumY"))
        high = _finite(interval.get("maximumY"))
        if low is not None and high is not None and high > low:
            return {
                "available": True,
                "heightMeters": round(high - low, 9),
                "evidenceStatus": "derived",
            }
    aabb = geometry.get("aabb") or geometry.get("AABB")
    minimum = aabb.get("minimum") if isinstance(aabb, Mapping) else None
    maximum = aabb.get("maximum") if isinstance(aabb, Mapping) else None
    if isinstance(minimum, Mapping) and isinstance(maximum, Mapping):
        low = _finite(minimum.get("y"))
        high = _finite(maximum.get("y"))
        if low is not None and high is not None and high > low:
            return {
                "available": True,
                "heightMeters": round(high - low, 9),
                "evidenceStatus": "derived",
            }
    return {
        "available": False,
        "heightMeters": None,
        "evidenceStatus": "unknown",
    }


def _directional_interfaces(document: Mapping[str, Any]) -> dict[str, Any]:
    semantics = document.get("facilitySemantics")
    semantics = semantics if isinstance(semantics, Mapping) else {}
    raw_sides = semantics.get("functionalSides")
    raw_sides = raw_sides if isinstance(raw_sides, Mapping) else {}
    resolved: dict[str, dict[str, Any]] = {}
    additional: dict[str, dict[str, Any]] = {}
    for raw_role, raw_record in raw_sides.items():
        source_role = _clean_id(raw_role)
        canonical_role = _DIRECTION_ROLE_ALIASES.get(source_role)
        record = raw_record if isinstance(raw_record, Mapping) else {"side": raw_record}
        side = _clean_id(record.get("side"))
        if side not in _SIDE_VALUES:
            side = None
        evidence_status = _status(
            record.get("evidenceStatus"),
            default="authored" if side else "unknown",
        )
        projected = {
            "side": side,
            "evidenceStatus": evidence_status,
            "hardRuleEligible": bool(
                side and _hard_rule_eligible(evidence_status)
            ),
            "sourceRole": source_role,
        }
        if canonical_role:
            existing = resolved.get(canonical_role)
            if existing is None or (
                not existing["hardRuleEligible"]
                and projected["hardRuleEligible"]
            ):
                resolved[canonical_role] = projected
        elif source_role:
            additional[source_role] = projected
    required = {}
    for role in FACILITY_DIRECTIONAL_INTERFACE_ROLES:
        required[role] = resolved.get(
            role,
            {
                "side": None,
                "evidenceStatus": "unknown",
                "hardRuleEligible": False,
                "sourceRole": None,
            },
        )
    return {
        "requiredRoles": required,
        "additionalRoles": dict(sorted(additional.items())),
        "qualification": (
            "An inferred or unknown side is advisory only and cannot satisfy "
            "a hard placement rule."
        ),
    }


def _evidence_ids(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("evidence") or record.get("evidenceIds") or []
    if not isinstance(raw, list):
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def _clearance_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    raw_records = document.get("clearances")
    raw_records = raw_records if isinstance(raw_records, list) else []
    records = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            continue
        evidence_status = _status(raw.get("evidenceStatus"))
        geometry = raw.get("geometry")
        geometry_available = isinstance(geometry, Mapping) and bool(geometry)
        kind = _clean_id(raw.get("clearanceKind") or raw.get("kind") or "unknown")
        records.append(
            {
                "clearanceId": str(
                    raw.get("clearanceId") or f"clearance-{index + 1:03d}"
                ),
                "kind": kind,
                "enforcement": _clean_id(raw.get("enforcement") or "unknown"),
                "evidenceStatus": evidence_status,
                "evidenceIds": _evidence_ids(raw),
                "geometryAvailable": geometry_available,
                "hardRuleEligible": bool(
                    geometry_available and _hard_rule_eligible(evidence_status)
                ),
                "accessEnvelope": any(term in kind for term in _ACCESS_CLEARANCE_TERMS),
            }
        )
    explicit_policy = document.get("clearancePolicy")
    policy = explicit_policy if isinstance(explicit_policy, Mapping) else {}
    policy_status = _clean_id(policy.get("status"))
    policy_evidence = _status(policy.get("evidenceStatus"))
    none_required = bool(
        policy_status in {"none_required", "not_required"}
        and _hard_rule_eligible(policy_evidence)
    )
    complete = bool(records) and all(item["hardRuleEligible"] for item in records)
    if none_required:
        complete = True
    return {
        "recordCount": len(records),
        "records": records,
        "accessEnvelopeCount": sum(item["accessEnvelope"] for item in records),
        "evidenceComplete": complete,
        "explicitNoneRequired": none_required,
        "policyEvidenceStatus": policy_evidence,
        "qualification": (
            "Only authored or derived clearance geometry can satisfy a hard "
            "placement rule. Missing evidence remains unresolved."
        ),
    }


def _mobility_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = document.get("mobility")
    raw = raw if isinstance(raw, Mapping) else {}
    classification = _clean_id(raw.get("classification")) or None
    evidence_status = _status(
        raw.get("evidenceStatus"),
        default="authored" if classification else "unknown",
    )
    return {
        "classification": classification,
        "evidenceStatus": evidence_status,
        "hardRuleEligible": bool(
            classification and _hard_rule_eligible(evidence_status)
        ),
    }


def _support_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    frame = document.get("coordinateFrame")
    frame = frame if isinstance(frame, Mapping) else {}
    mounting = sorted(
        {
            _clean_id(item)
            for item in frame.get("allowedMountingSurfaces", [])
            if _clean_id(item)
        }
    )
    surfaces = []
    raw_surfaces = document.get("supportSurfaces")
    raw_surfaces = raw_surfaces if isinstance(raw_surfaces, list) else []
    for raw in raw_surfaces:
        if not isinstance(raw, Mapping):
            continue
        evidence_status = _status(raw.get("evidenceStatus"))
        surfaces.append(
            {
                "surfaceId": str(raw.get("surfaceId") or ""),
                "allowedSides": sorted(
                    {
                        _clean_id(item)
                        for item in raw.get("allowedSides", [])
                        if _clean_id(item)
                    }
                ),
                "evidenceStatus": evidence_status,
                "hardRuleEligible": _hard_rule_eligible(evidence_status),
            }
        )
    return {
        "allowedMountingSurfaces": mounting,
        "mountingEvidenceStatus": "authored" if mounting else "unknown",
        "supportSurfaces": surfaces,
        "stackCompatibilityKnown": bool(
            mounting and surfaces and all(item["hardRuleEligible"] for item in surfaces)
        ),
    }


def _utility_summary(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    utilities = document.get("utilities")
    utilities = utilities if isinstance(utilities, Mapping) else {}
    result = []
    for kind, raw in utilities.items():
        if raw in (None, False, [], {}):
            continue
        record = raw if isinstance(raw, Mapping) else {"value": raw}
        evidence_status = _status(
            record.get("evidenceStatus"),
            default="authored",
        )
        result.append(
            {
                "utilityKind": _clean_id(kind),
                "evidenceStatus": evidence_status,
                "hardRuleEligible": _hard_rule_eligible(evidence_status),
            }
        )
    return sorted(result, key=lambda item: item["utilityKind"])


def _capability_ids(document: Mapping[str, Any]) -> list[str]:
    raw = document.get("capabilityIds")
    result = {
        _clean_id(item) for item in raw if _clean_id(item)
    } if isinstance(raw, list) else set()
    capabilities = document.get("capabilities")
    if isinstance(capabilities, Mapping):
        for key in ("processTypes", "supportedProcesses", "capabilityIds"):
            values = capabilities.get(key)
            if isinstance(values, list):
                result.update(_clean_id(item) for item in values if _clean_id(item))
    return sorted(result)


def _operating_envelope(document: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [
        document.get("operatingEnvelope"),
        document.get("sweptEnvelope"),
    ]
    capabilities = document.get("capabilities")
    if isinstance(capabilities, Mapping):
        candidates.extend(
            [capabilities.get("operatingEnvelope"), capabilities.get("sweptEnvelope")]
        )
    for raw in candidates:
        if not isinstance(raw, Mapping) or not raw:
            continue
        evidence_status = _status(raw.get("evidenceStatus"))
        return {
            "available": True,
            "evidenceStatus": evidence_status,
            "hardRuleEligible": _hard_rule_eligible(evidence_status),
            "envelopeKind": _clean_id(raw.get("kind") or "operating"),
        }
    return {
        "available": False,
        "evidenceStatus": "unknown",
        "hardRuleEligible": False,
        "envelopeKind": None,
    }


def _source_readiness(document: Mapping[str, Any], name: str) -> tuple[bool, list[str]]:
    readiness = document.get("readiness")
    readiness = readiness if isinstance(readiness, Mapping) else {}
    raw = readiness.get(name)
    if isinstance(raw, Mapping):
        blockers = sorted(
            {str(item) for item in raw.get("blockers", []) if str(item).strip()}
        )
        return raw.get("value") is True and not blockers, blockers
    if isinstance(raw, bool):
        return raw, [] if raw else [f"{name}_false"]
    return False, [f"{name}_missing"]


def compile_asset_planning_readiness(
    asset: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one exact asset definition into the canonical K6 projection."""

    if not isinstance(asset, Mapping):
        raise FacilityPlanningReadinessError(
            "asset_definition_invalid",
            "Asset definition must be a mapping.",
        )
    document, asset_id, revision = _asset_document(asset)
    if not asset_id:
        raise FacilityPlanningReadinessError(
            "asset_identity_missing",
            "Asset definition must provide assetId.",
        )
    revision_bound = _REVISION_RE.fullmatch(revision) is not None
    footprint = _footprint_summary(document)
    height = _height_summary(document)
    directions = _directional_interfaces(document)
    clearances = _clearance_summary(document)
    mobility = _mobility_summary(document)
    supports = _support_summary(document)
    utilities = _utility_summary(document)
    envelope = _operating_envelope(document)

    semantic_input = deepcopy(document)
    semantic_input["assetId"] = asset_id
    semantic_input["assetDefinitionRevision"] = revision
    semantic_input["capabilityIds"] = _capability_ids(document)
    semantic = classify_facility_asset_semantics(semantic_input)

    visual_ready, visual_blockers = _source_readiness(document, "visualReady")
    placement_ready, placement_blockers = _source_readiness(
        document, "placementReady"
    )
    source_planning_ready, source_planning_blockers = _source_readiness(
        document, "planningReady"
    )
    geometric_ready = revision_bound and footprint["available"] and height["available"]
    controlled_ready = bool(
        geometric_ready
        and source_planning_ready
        and clearances["evidenceComplete"]
    )
    if controlled_ready:
        readiness_level = "controlled_planning_ready"
    elif geometric_ready:
        readiness_level = "geometric_planning_ready"
    else:
        readiness_level = "unavailable"

    blockers = []
    if not revision_bound:
        blockers.append("exact_asset_revision_unavailable")
    if not footprint["available"]:
        blockers.append("revision_bound_footprint_unavailable")
    if not height["available"]:
        blockers.append("revision_bound_height_unavailable")
    blockers.extend(source_planning_blockers)
    if not clearances["evidenceComplete"]:
        blockers.append("authoritative_clearance_evidence_missing")

    unresolved = []
    for role, record in directions["requiredRoles"].items():
        if record["evidenceStatus"] in {"inferred", "unknown"}:
            unresolved.append(f"directional_interface_{role}_{record['evidenceStatus']}")
    if mobility["evidenceStatus"] in {"inferred", "unknown"}:
        unresolved.append(
            f"mobility_classification_{mobility['evidenceStatus']}"
        )
    if not supports["allowedMountingSurfaces"]:
        unresolved.append("allowed_mounting_surfaces_unknown")
    if not envelope["available"]:
        unresolved.append("operating_envelope_unknown")

    report = {
        "planningReadinessVersion": FACILITY_PLANNING_READINESS_VERSION,
        "assetId": asset_id,
        "assetDefinitionRevision": revision if revision_bound else None,
        "revisionBound": revision_bound,
        "displayName": str(document.get("displayName") or asset_id),
        "category": str(document.get("category") or "unknown"),
        "physicalEnvelope": {
            "footprint": footprint,
            "height": height,
        },
        "mobility": mobility,
        "supportRelationships": supports,
        "directionalInterfaces": directions,
        "clearances": clearances,
        "operatingEnvelope": envelope,
        "utilities": utilities,
        "zoneAndProcessSemantics": {
            "semanticType": semantic["semanticType"],
            "semanticTypeEvidenceStatus": semantic[
                "semanticTypeEvidenceStatus"
            ],
            "operationalRoles": deepcopy(semantic["operationalRoles"]),
            "permittedZoneRoles": deepcopy(semantic["typicalZoneFamilies"]),
            "permittedZoneRoleEvidenceStatus": (
                "inferred" if semantic["typicalZoneFamilies"] else "unknown"
            ),
            "processCapabilities": _capability_ids(document),
            "processCapabilityEvidenceStatus": (
                "authored" if _capability_ids(document) else "unknown"
            ),
        },
        "readiness": {
            "level": readiness_level,
            "visualReady": visual_ready,
            "placementReady": placement_ready,
            "geometricPlanningReady": geometric_ready,
            "controlledPlanningReady": controlled_ready,
            "sourcePlanningReady": source_planning_ready,
            "blockerCodes": sorted(set(blockers)),
            "unresolvedEvidenceCodes": sorted(set(unresolved)),
            "sourceVisualBlockers": visual_blockers,
            "sourcePlacementBlockers": placement_blockers,
        },
        "qualification": (
            "Geometry can support bounded preview planning when revision-bound. "
            "Controlled placement additionally requires authoritative planning "
            "and clearance evidence. Inferred semantics remain advisory."
        ),
    }
    report["readinessRevision"] = _fingerprint(report)
    return report


def compile_asset_catalog_planning_readiness(
    assets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile an asset inventory without omitting unavailable definitions."""

    reports = [compile_asset_planning_readiness(asset) for asset in assets]
    identities = [
        (item["assetId"], item.get("assetDefinitionRevision")) for item in reports
    ]
    if len(identities) != len(set(identities)):
        raise FacilityPlanningReadinessError(
            "duplicate_asset_revision",
            "Asset catalog contains a duplicate asset revision.",
        )
    return {
        "planningReadinessVersion": FACILITY_PLANNING_READINESS_VERSION,
        "assetCount": len(reports),
        "revisionBoundFootprintCount": sum(
            item["revisionBound"]
            and item["physicalEnvelope"]["footprint"]["available"]
            for item in reports
        ),
        "unavailableCount": sum(
            item["readiness"]["level"] == "unavailable" for item in reports
        ),
        "controlledPlanningReadyCount": sum(
            item["readiness"]["controlledPlanningReady"] for item in reports
        ),
        "assets": sorted(
            reports,
            key=lambda item: (
                item["assetId"],
                item.get("assetDefinitionRevision") or "",
            ),
        ),
    }


def compile_zone_semantic_readiness(
    zone: Mapping[str, Any],
    *,
    layout_revision: str | None = None,
) -> dict[str, Any]:
    """Preserve an exact user label while typing its semantic role."""

    if not isinstance(zone, Mapping):
        raise FacilityPlanningReadinessError(
            "zone_definition_invalid",
            "Zone definition must be a mapping.",
        )
    zone_id = str(zone.get("zoneId") or "").strip()
    raw_label = zone.get("label")
    label = raw_label if isinstance(raw_label, str) and raw_label.strip() else None
    if not zone_id:
        raise FacilityPlanningReadinessError(
            "zone_identity_missing",
            "Zone must provide zoneId.",
        )
    semantics = classify_facility_zone_semantics(zone)
    evidence_status = _status(semantics.get("evidenceStatus"))
    functional_status = _status(
        semantics.get("functionalInterfaceEvidenceStatus")
    )
    result = {
        "planningReadinessVersion": FACILITY_PLANNING_READINESS_VERSION,
        "zoneId": zone_id,
        "zoneRevision": _fingerprint(zone),
        "layoutRevision": layout_revision,
        "label": {
            "value": label,
            "evidenceStatus": "authored" if label is not None else "unknown",
            "source": (
                "user_authored_zone_label" if label is not None else None
            ),
        },
        "semanticRole": {
            "semanticType": semantics["semanticType"],
            "purpose": semantics["purpose"],
            "operationalRoles": deepcopy(semantics["operationalRoles"]),
            "evidenceStatus": evidence_status,
            "method": semantics["method"],
            "hardRuleEligible": _hard_rule_eligible(evidence_status),
        },
        "functionalInterfaces": {
            "values": deepcopy(semantics["functionalInterfaces"]),
            "evidenceStatus": functional_status,
            "hardRuleEligible": _hard_rule_eligible(functional_status),
        },
        "qualification": (
            "The label is preserved exactly as authored. Inferred semantic roles "
            "support search and suggestions but cannot satisfy hard policy."
        ),
    }
    result["readinessRevision"] = _fingerprint(result)
    return result


def compile_zone_catalog_semantic_readiness(
    layout: Mapping[str, Any],
    *,
    layout_revision: str | None = None,
) -> dict[str, Any]:
    if not isinstance(layout, Mapping):
        raise FacilityPlanningReadinessError(
            "layout_definition_invalid",
            "Layout must be a mapping.",
        )
    revision = layout_revision or _fingerprint(layout)
    zones = [
        compile_zone_semantic_readiness(zone, layout_revision=revision)
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping)
    ]
    return {
        "planningReadinessVersion": FACILITY_PLANNING_READINESS_VERSION,
        "layoutRevision": revision,
        "zoneCount": len(zones),
        "zones": sorted(zones, key=lambda item: item["zoneId"]),
    }


def analyze_planning_ready_asset_fit(
    layout: Mapping[str, Any],
    asset_definitions: Sequence[Mapping[str, Any]],
    *,
    asset_id: str,
    asset_definition_revision: str,
    zone_id: str,
    shell: Mapping[str, Any] | None = None,
    policy_set: Mapping[str, Any] | None = None,
    evidence_authority: Mapping[str, Any] | None = None,
    orientations_degrees: Sequence[int] | None = None,
    maximum_results: int = 8,
) -> dict[str, Any]:
    """Add evidence readiness to the existing bounded fit result."""

    before = canonical_spatial_bytes(layout)
    exact_asset = None
    for candidate in asset_definitions:
        if not isinstance(candidate, Mapping):
            continue
        _, candidate_id, candidate_revision = _asset_document(candidate)
        if (
            candidate_id == asset_id
            and candidate_revision == asset_definition_revision
        ):
            exact_asset = candidate
            break
    asset_readiness = (
        compile_asset_planning_readiness(exact_asset)
        if exact_asset is not None
        else None
    )
    target_zone = next(
        (
            zone
            for zone in layout.get("zones", [])
            if isinstance(zone, Mapping)
            and str(zone.get("zoneId") or "") == zone_id
        ),
        None,
    )
    zone_readiness = (
        compile_zone_semantic_readiness(
            target_zone,
            layout_revision=_fingerprint(layout),
        )
        if target_zone is not None
        else None
    )
    fit = analyze_facility_asset_fit(
        layout,
        asset_definitions,
        asset_id=asset_id,
        asset_definition_revision=asset_definition_revision,
        zone_id=zone_id,
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
        orientations_degrees=orientations_degrees,
        maximum_results=maximum_results,
    )
    if canonical_spatial_bytes(layout) != before:
        raise RuntimeError("planning-ready fit analysis mutated the layout")
    controlled = bool(
        asset_readiness
        and asset_readiness["readiness"]["controlledPlanningReady"]
        and zone_readiness
        and fit.get("fullyValidatedFitFound") is True
    )
    return {
        "planningReadinessVersion": FACILITY_PLANNING_READINESS_VERSION,
        "analysisOwner": "ai_inspector.facility_layout.fit_analysis",
        "assetReadiness": asset_readiness,
        "zoneReadiness": zone_readiness,
        "fit": fit,
        "controlledPlacementSupported": controlled,
        "mutated": False,
    }


__all__ = [
    "FACILITY_DIRECTIONAL_INTERFACE_ROLES",
    "FACILITY_PLANNING_EVIDENCE_STATUSES",
    "FACILITY_PLANNING_READINESS_LEVELS",
    "FACILITY_PLANNING_READINESS_VERSION",
    "FacilityPlanningReadinessError",
    "analyze_planning_ready_asset_fit",
    "compile_asset_catalog_planning_readiness",
    "compile_asset_planning_readiness",
    "compile_zone_catalog_semantic_readiness",
    "compile_zone_semantic_readiness",
]
