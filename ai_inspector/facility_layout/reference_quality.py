"""Deterministic reference-quality benchmark analysis for Facility Layout."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
from typing import Any, Mapping, Sequence

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .knowledge_foundation import canonical_facility_knowledge_bytes
from .spatial import (
    placement_spatial_records,
    point_in_polygon,
    polygon_area,
    polygon_contains_polygon,
    polygons_intersect,
)


REFERENCE_MANIFEST_SCHEMA = "facility-reference-manifest-v1"
REFERENCE_REVIEW_SCHEMA = "facility-reference-review-receipt-v1"
REFERENCE_EXPECTED_COUNTS = {
    "zones": 45,
    "routes": 8,
    "placements": 827,
    "floorMarkings": 50,
}


class FacilityReferenceQualityError(RuntimeError):
    """The reference archive cannot produce a complete review manifest."""


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _boundary(zone: Mapping[str, Any]) -> tuple[tuple[float, float], ...]:
    points = tuple(
        (float(point["x"]), float(point["z"]))
        for point in zone.get("boundary", [])
        if isinstance(point, Mapping)
    )
    if len(points) < 3 or abs(polygon_area(points)) <= 1.0e-9:
        raise FacilityReferenceQualityError(
            f"Zone '{zone.get('zoneId')}' has no usable boundary."
        )
    return points


def _catalog_index(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in catalog:
        asset_id = str(raw.get("assetId") or "")
        revision = str(raw.get("assetDefinitionRevision") or "")
        definition = raw.get("definition")
        if asset_id and revision and isinstance(definition, Mapping):
            result[(asset_id, revision)] = raw
    return result


def derive_zone_relationships(
    zones: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive one immediate spatial parent candidate for every reference zone."""

    prepared = []
    for zone in zones:
        polygon = _boundary(zone)
        prepared.append(
            {
                "zone": zone,
                "polygon": polygon,
                "area": abs(polygon_area(polygon)),
            }
        )
    result = []
    for child in prepared:
        containers = [
            parent
            for parent in prepared
            if parent is not child
            and parent["area"] > child["area"] + 1.0e-9
            and polygon_contains_polygon(parent["polygon"], child["polygon"])
        ]
        containers.sort(
            key=lambda item: (
                item["area"],
                str(item["zone"].get("zoneId") or ""),
            )
        )
        minimum_area = containers[0]["area"] if containers else None
        equally_small = [
            item
            for item in containers
            if minimum_area is not None
            and abs(item["area"] - minimum_area) <= 1.0e-9
        ]
        parent = containers[0] if len(equally_small) == 1 else None
        result.append(
            {
                "zoneId": str(child["zone"].get("zoneId") or ""),
                "label": str(child["zone"].get("label") or ""),
                "areaSquareMeters": round(child["area"], 9),
                "derivedParentZoneId": (
                    str(parent["zone"].get("zoneId") or "") if parent else None
                ),
                "candidateParentZoneIds": [
                    str(item["zone"].get("zoneId") or "")
                    for item in equally_small
                ],
                "evidenceStatus": "derived",
                "reviewStatus": "pending",
            }
        )
    return sorted(result, key=lambda item: item["zoneId"])


def _placement_polygons(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
) -> list[tuple[tuple[float, float], ...]]:
    definition = asset.get("definition")
    if not isinstance(definition, Mapping):
        return []
    try:
        return [
            tuple(record.polygon)
            for record in placement_spatial_records(placement, definition)
        ]
    except (KeyError, TypeError, ValueError):
        return []


def derive_placement_bindings(
    layout: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind manual placements to the smallest containing area without guessing."""

    zones = [item for item in layout.get("zones", []) if isinstance(item, Mapping)]
    prepared_zones = [
        {
            "zone": zone,
            "polygon": _boundary(zone),
            "area": abs(polygon_area(_boundary(zone))),
        }
        for zone in zones
    ]
    assets = _catalog_index(catalog)
    result: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    placement_ids = {
        str(item.get("placementId") or "")
        for item in layout.get("placements", [])
        if isinstance(item, Mapping)
    }
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        asset = assets.get(key)
        polygons = _placement_polygons(placement, asset) if asset else []
        transform = placement.get("transform")
        position = transform.get("position") if isinstance(transform, Mapping) else None
        center = (
            (float(position["x"]), float(position["z"]))
            if isinstance(position, Mapping)
            else None
        )
        containing = [
            item
            for item in prepared_zones
            if (
                polygons
                and all(
                    polygon_contains_polygon(item["polygon"], polygon)
                    for polygon in polygons
                )
            )
            or (
                center is not None
                and point_in_polygon(center, item["polygon"])
            )
        ]
        containing.sort(
            key=lambda item: (
                item["area"],
                str(item["zone"].get("zoneId") or ""),
            )
        )
        minimum_area = containing[0]["area"] if containing else None
        smallest = [
            item
            for item in containing
            if minimum_area is not None
            and abs(item["area"] - minimum_area) <= 1.0e-9
        ]
        target = smallest[0] if len(smallest) == 1 else None
        relationship = placement.get("snapRelationship")
        support_id = (
            str(relationship.get("supportPlacementId") or "")
            if isinstance(relationship, Mapping)
            else ""
        )
        dependency_status = "none"
        if support_id:
            dependency_status = "resolved" if support_id in placement_ids else "missing"
        record = {
            "placementId": placement_id,
            "assetId": key[0],
            "assetDefinitionRevision": key[1],
            "displayName": str((asset or {}).get("displayName") or key[0]),
            "derivedTargetZoneId": (
                str(target["zone"].get("zoneId") or "") if target else None
            ),
            "candidateTargetZoneIds": [
                str(item["zone"].get("zoneId") or "") for item in smallest
            ],
            "bindingMethod": (
                "full_footprint_or_center_containment" if target else "unresolved"
            ),
            "supportPlacementId": support_id or None,
            "supportDependencyStatus": dependency_status,
            "assetRevisionResolved": asset is not None,
            "evidenceStatus": "derived",
            "reviewStatus": "pending",
        }
        result.append(record)
        if target is None or asset is None or dependency_status == "missing":
            unresolved.append(
                {
                    "code": (
                        "reference_asset_revision_unavailable"
                        if asset is None
                        else "reference_support_missing"
                        if dependency_status == "missing"
                        else "reference_target_area_ambiguous"
                    ),
                    "placementId": placement_id,
                    "candidateTargetZoneIds": record["candidateTargetZoneIds"],
                    "assetId": key[0],
                    "assetDefinitionRevision": key[1],
                    "supportPlacementId": support_id or None,
                }
            )
    return (
        sorted(result, key=lambda item: item["placementId"]),
        sorted(unresolved, key=lambda item: (item["code"], item["placementId"])),
    )


def _bounds_overlap(left: Any, right: Any) -> bool:
    return not (
        left.bounds[2] < right.bounds[0]
        or right.bounds[2] < left.bounds[0]
        or left.bounds[3] < right.bounds[1]
        or right.bounds[3] < left.bounds[1]
    )


def derive_contact_audit(
    layout: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify reference contacts; unknown classes remain review blockers."""

    assets = _catalog_index(catalog)
    records: list[tuple[str, str, Any]] = []
    relationships: dict[str, str] = {}
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        asset = assets.get(
            (asset_id, str(placement.get("assetDefinitionRevision") or ""))
        )
        if asset is not None:
            definition = asset.get("definition")
            if isinstance(definition, Mapping):
                try:
                    for record in placement_spatial_records(placement, definition):
                        records.append((placement_id, asset_id, record))
                except (KeyError, TypeError, ValueError):
                    pass
        relationship = placement.get("snapRelationship")
        if isinstance(relationship, Mapping):
            support_id = str(relationship.get("supportPlacementId") or "")
            if support_id:
                relationships[placement_id] = support_id

    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for index, (left_id, left_asset, left) in enumerate(records):
        for right_id, right_asset, right in records[index + 1 :]:
            if left_id == right_id or not _bounds_overlap(left, right):
                continue
            vertical_overlap = not (
                left.interval[1] < right.interval[0]
                or right.interval[1] < left.interval[0]
            )
            if not vertical_overlap or not polygons_intersect(
                left.polygon, right.polygon
            ):
                continue
            pair = tuple(sorted((left_id, right_id)))
            if pair in pairs:
                continue
            if relationships.get(left_id) == right_id or relationships.get(right_id) == left_id:
                contact_class = "supported_or_surface_attached"
                review_status = "pending"
            elif left_asset == right_asset == "asset-5987t55-wire-mesh-machine-guard-panel":
                contact_class = "guard_panel_contact"
                review_status = "pending"
            elif "asset-operator" in {left_asset, right_asset}:
                contact_class = "operator_work_envelope_contact"
                review_status = "pending"
            else:
                contact_class = "unclassified_contact"
                review_status = "blocking"
            pairs[pair] = {
                "leftPlacementId": pair[0],
                "rightPlacementId": pair[1],
                "contactClass": contact_class,
                "evidenceStatus": "derived",
                "reviewStatus": review_status,
            }
    contacts = sorted(
        pairs.values(),
        key=lambda item: (item["contactClass"], item["leftPlacementId"], item["rightPlacementId"]),
    )
    unresolved = [
        {
            "code": "reference_contact_unclassified",
            "leftPlacementId": item["leftPlacementId"],
            "rightPlacementId": item["rightPlacementId"],
        }
        for item in contacts
        if item["contactClass"] == "unclassified_contact"
    ]
    return contacts, unresolved


def build_reference_manifest(
    layout: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    *,
    source_path: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    """Build a deterministic pending-review manifest from one saved archive."""

    document = canonicalize_layout(deepcopy(dict(layout)))
    counts = {
        "zones": len(document.get("zones", [])),
        "routes": len(document.get("routes", [])),
        "placements": len(document.get("placements", [])),
        "floorMarkings": len(document.get("floorMarkings", [])),
    }
    if counts != REFERENCE_EXPECTED_COUNTS:
        raise FacilityReferenceQualityError(
            f"Reference counts changed: expected {REFERENCE_EXPECTED_COUNTS}, got {counts}."
        )
    zone_relationships = derive_zone_relationships(document.get("zones", []))
    placement_bindings, binding_unresolved = derive_placement_bindings(
        document, catalog
    )
    contacts, contact_unresolved = derive_contact_audit(document, catalog)
    support_dependencies = [
        {
            "placementId": item["placementId"],
            "supportPlacementId": item["supportPlacementId"],
            "status": item["supportDependencyStatus"],
        }
        for item in placement_bindings
        if item["supportPlacementId"]
    ]
    asset_counts = Counter(
        str(item.get("assetId") or "")
        for item in document.get("placements", [])
        if isinstance(item, Mapping)
    )
    marking_counts = Counter(
        str(item.get("markingType") or "")
        for item in document.get("floorMarkings", [])
        if isinstance(item, Mapping)
    )
    unresolved = [
        *binding_unresolved,
        *contact_unresolved,
        *[
            {
                "code": "reference_zone_parent_ambiguous",
                "zoneId": item["zoneId"],
                "candidateParentZoneIds": item["candidateParentZoneIds"],
            }
            for item in zone_relationships
            if len(item["candidateParentZoneIds"]) > 1
        ],
    ]
    manifest_core = {
        "schemaVersion": REFERENCE_MANIFEST_SCHEMA,
        "manifestId": "facility-reference-manual-20260812-v1",
        "source": {
            "layoutId": str(document.get("layoutId") or ""),
            "layoutRevision": layout_revision(document),
            "sourcePath": source_path,
            "sourceFileSha256": source_file_sha256,
            "canonicalLayoutSha256": hashlib.sha256(
                canonical_layout_bytes(document)
            ).hexdigest(),
        },
        "authority": {
            "mode": "reference_reproduction",
            "evidenceStatus": "derived",
            "reviewStatus": "pending",
            "productionEligible": False,
        },
        "counts": counts,
        "assetCounts": dict(sorted(asset_counts.items())),
        "markingCounts": dict(sorted(marking_counts.items())),
        "zoneRelationships": zone_relationships,
        "placementBindings": placement_bindings,
        "supportDependencies": sorted(
            support_dependencies, key=lambda item: item["placementId"]
        ),
        "contactAudit": {
            "countsByClass": dict(
                sorted(Counter(item["contactClass"] for item in contacts).items())
            ),
            "contacts": contacts,
        },
        "routeRecords": [
            {
                "routeId": str(item.get("routeId") or ""),
                "label": str(item.get("label") or ""),
                "routeKind": str(item.get("routeKind") or ""),
                "corridorWidthMeters": float(item.get("corridorWidth") or 0),
                "recordRevision": _fingerprint(item),
            }
            for item in document.get("routes", [])
            if isinstance(item, Mapping)
        ],
        "markingRecords": [
            {
                "markingId": str(item.get("markingId") or ""),
                "markingType": str(item.get("markingType") or ""),
                "recordRevision": _fingerprint(item),
            }
            for item in document.get("floorMarkings", [])
            if isinstance(item, Mapping)
        ],
        "unresolved": sorted(
            unresolved,
            key=lambda item: (
                str(item.get("code") or ""),
                str(item.get("placementId") or item.get("zoneId") or ""),
            ),
        ),
    }
    manifest_core["manifestRevision"] = _fingerprint(manifest_core)
    return manifest_core


def build_reference_review_receipt(
    manifest: Mapping[str, Any],
    *,
    approver: str = "Shadrack",
    approved: bool = False,
) -> dict[str, Any]:
    """Create an explicit review receipt; approval is never inferred."""

    unresolved = list(manifest.get("unresolved") or [])
    can_approve = not unresolved
    status = "approved" if approved and can_approve else "pending"
    return {
        "schemaVersion": REFERENCE_REVIEW_SCHEMA,
        "manifestId": str(manifest.get("manifestId") or ""),
        "manifestRevision": str(manifest.get("manifestRevision") or ""),
        "sourceLayoutRevision": str(
            (manifest.get("source") or {}).get("layoutRevision") or ""
        ),
        "approver": approver,
        "approverRole": "InspectorPro product owner",
        "authorityBoundary": (
            "Prototype benchmark reconstruction only; not manufacturing, safety, "
            "compliance, production, or release approval."
        ),
        "reviewStatus": status,
        "approvalRequested": bool(approved),
        "approvalEligible": can_approve,
        "unresolvedCount": len(unresolved),
        "acceptedDerivedRelationshipCount": 0,
        "acceptedContactClassCount": 0,
        "reviewedAt": None,
        "receiptRevision": _fingerprint(
            {
                "manifestRevision": manifest.get("manifestRevision"),
                "approver": approver,
                "approved": approved,
                "approvalEligible": can_approve,
            }
        ),
    }


def approve_reference_manifest(
    manifest: Mapping[str, Any],
    *,
    approver: str,
    reviewed_at: str,
) -> dict[str, Any]:
    """Record an explicit human acceptance of every unambiguous derived item."""

    unresolved = list(manifest.get("unresolved") or [])
    if unresolved:
        raise FacilityReferenceQualityError(
            "A reference manifest with unresolved findings cannot be approved."
        )
    if not isinstance(approver, str) or not approver.strip():
        raise FacilityReferenceQualityError("Reference approval requires an approver.")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise FacilityReferenceQualityError("Reference approval requires a review timestamp.")

    relationships = [
        *[
            {
                "kind": "zone_parent",
                "entityId": str(item.get("zoneId") or ""),
                "relatedEntityId": str(item.get("derivedParentZoneId") or ""),
            }
            for item in manifest.get("zoneRelationships", [])
            if isinstance(item, Mapping) and item.get("derivedParentZoneId")
        ],
        *[
            {
                "kind": "placement_target_area",
                "entityId": str(item.get("placementId") or ""),
                "relatedEntityId": str(item.get("derivedTargetZoneId") or ""),
            }
            for item in manifest.get("placementBindings", [])
            if isinstance(item, Mapping) and item.get("derivedTargetZoneId")
        ],
    ]
    contacts = [
        {
            "leftPlacementId": str(item.get("leftPlacementId") or ""),
            "rightPlacementId": str(item.get("rightPlacementId") or ""),
            "contactClass": str(item.get("contactClass") or ""),
        }
        for item in (manifest.get("contactAudit") or {}).get("contacts", [])
        if isinstance(item, Mapping)
    ]
    core = {
        "schemaVersion": REFERENCE_REVIEW_SCHEMA,
        "manifestId": str(manifest.get("manifestId") or ""),
        "manifestRevision": str(manifest.get("manifestRevision") or ""),
        "sourceLayoutRevision": str(
            (manifest.get("source") or {}).get("layoutRevision") or ""
        ),
        "approver": approver.strip(),
        "approverRole": "InspectorPro product owner",
        "authorityBoundary": (
            "Prototype benchmark reconstruction only; not manufacturing, safety, "
            "compliance, production, or release approval."
        ),
        "reviewStatus": "approved",
        "approvalRequested": True,
        "approvalEligible": True,
        "unresolvedCount": 0,
        "acceptedDerivedRelationshipCount": len(relationships),
        "acceptedContactClassCount": len(
            {item["contactClass"] for item in contacts}
        ),
        "acceptedDerivedRelationships": relationships,
        "acceptedContacts": contacts,
        "reviewedAt": reviewed_at.strip(),
    }
    core["receiptRevision"] = _fingerprint(core)
    return core
