"""Reviewed reference-manifest adapter and deterministic reproduction plans."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .diff import build_exact_layout_diff
from .facility_program import (
    FACILITY_PROGRAM_SCHEMA,
    FacilityProgramError,
    canonicalize_facility_program,
)
from .knowledge_foundation import canonical_facility_knowledge_bytes
from .industrial_patterns import select_industrial_pattern
from .operations import apply_facility_layout_operations
from .reference_quality import (
    REFERENCE_EXPECTED_COUNTS,
    REFERENCE_MANIFEST_SCHEMA,
    REFERENCE_REVIEW_SCHEMA,
)


REFERENCE_OPERATION_PLAN_SCHEMA = "facility-reference-operation-plan-v1"
REFERENCE_MINIMUM_NONFINAL_PLACEMENT_BATCH = 100
REFERENCE_MAXIMUM_OPERATION_BATCH = 500


class FacilityReferenceGenerationError(RuntimeError):
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


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _source_counts(layout: Mapping[str, Any]) -> dict[str, int]:
    return {
        "zones": len(layout.get("zones", [])),
        "routes": len(layout.get("routes", [])),
        "placements": len(layout.get("placements", [])),
        "floorMarkings": len(layout.get("floorMarkings", [])),
    }


def _assert_reference_bindings(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    source_layout: Mapping[str, Any],
    *,
    require_approved: bool,
) -> dict[str, Any]:
    if manifest.get("schemaVersion") != REFERENCE_MANIFEST_SCHEMA:
        raise FacilityReferenceGenerationError(
            "reference_manifest_schema_invalid",
            "The reference manifest schema is unsupported.",
        )
    if receipt.get("schemaVersion") != REFERENCE_REVIEW_SCHEMA:
        raise FacilityReferenceGenerationError(
            "reference_review_receipt_invalid",
            "The reference review receipt schema is unsupported.",
        )
    if receipt.get("manifestRevision") != manifest.get("manifestRevision"):
        raise FacilityReferenceGenerationError(
            "reference_review_receipt_stale",
            "The review receipt is not bound to this reference manifest.",
        )
    document = canonicalize_layout(deepcopy(dict(source_layout)))
    source = manifest.get("source")
    source = source if isinstance(source, Mapping) else {}
    current_revision = layout_revision(document)
    if current_revision != source.get("layoutRevision"):
        raise FacilityReferenceGenerationError(
            "reference_source_revision_mismatch",
            "The reference source layout does not match the manifest revision.",
            details={
                "expected": source.get("layoutRevision"),
                "actual": current_revision,
            },
        )
    canonical_sha = hashlib.sha256(canonical_layout_bytes(document)).hexdigest()
    if canonical_sha != source.get("canonicalLayoutSha256"):
        raise FacilityReferenceGenerationError(
            "reference_source_hash_mismatch",
            "The reference source layout bytes do not match the manifest.",
        )
    counts = _source_counts(document)
    if counts != REFERENCE_EXPECTED_COUNTS or counts != manifest.get("counts"):
        raise FacilityReferenceGenerationError(
            "reference_source_count_mismatch",
            "The reference source inventory does not match the frozen manifest.",
            details={"expected": REFERENCE_EXPECTED_COUNTS, "actual": counts},
        )
    if require_approved:
        if (
            receipt.get("reviewStatus") != "approved"
            or receipt.get("approvalRequested") is not True
            or receipt.get("approvalEligible") is not True
            or receipt.get("unresolvedCount") != 0
            or not receipt.get("reviewedAt")
        ):
            raise FacilityReferenceGenerationError(
                "reference_review_required",
                "Reference reproduction requires an explicit revision-bound product-owner review.",
            )
        expected_relationships = sum(
            1
            for item in manifest.get("zoneRelationships", [])
            if isinstance(item, Mapping) and item.get("derivedParentZoneId")
        ) + sum(
            1
            for item in manifest.get("placementBindings", [])
            if isinstance(item, Mapping) and item.get("derivedTargetZoneId")
        )
        if receipt.get("acceptedDerivedRelationshipCount") != expected_relationships:
            raise FacilityReferenceGenerationError(
                "reference_review_incomplete",
                "The review receipt does not accept every derived hierarchy and target binding.",
                details={
                    "expected": expected_relationships,
                    "actual": receipt.get("acceptedDerivedRelationshipCount"),
                },
            )
    return document


def _family_stem(label: str) -> str | None:
    match = re.fullmatch(r"(.+?)\s+[A-Z]\d{2}", label.strip())
    return match.group(1).strip() if match else None


def facility_program_from_reference_manifest(
    manifest: Mapping[str, Any],
    review_receipt: Mapping[str, Any],
    source_layout: Mapping[str, Any],
    *,
    require_approved: bool = True,
) -> dict[str, Any]:
    """Represent the reviewed archive without exposing its geometry to Sage."""

    document = _assert_reference_bindings(
        manifest,
        review_receipt,
        source_layout,
        require_approved=require_approved,
    )
    zones = {
        str(item.get("zoneId") or ""): item
        for item in document.get("zones", [])
        if isinstance(item, Mapping)
    }
    relationships = {
        str(item.get("zoneId") or ""): str(item.get("derivedParentZoneId") or "")
        for item in manifest.get("zoneRelationships", [])
        if isinstance(item, Mapping)
    }
    bindings = {
        str(item.get("placementId") or ""): item
        for item in manifest.get("placementBindings", [])
        if isinstance(item, Mapping)
    }
    placements = {
        str(item.get("placementId") or ""): item
        for item in document.get("placements", [])
        if isinstance(item, Mapping)
    }

    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for placement_id, binding in bindings.items():
        target_zone_id = str(binding.get("derivedTargetZoneId") or "")
        groups[
            (
                target_zone_id,
                str(binding.get("assetId") or ""),
                str(binding.get("assetDefinitionRevision") or ""),
            )
        ].append(placement_id)

    batch_by_group: dict[tuple[str, str, str], str] = {}
    batch_by_placement: dict[str, str] = {}
    resource_batches = []
    for target_zone_id, asset_id, asset_revision in sorted(groups):
        member_ids = sorted(groups[(target_zone_id, asset_id, asset_revision)])
        batch_id = _stable_id(
            "resource-batch",
            {
                "targetZoneId": target_zone_id,
                "assetId": asset_id,
                "assetDefinitionRevision": asset_revision,
            },
        )
        batch_by_group[(target_zone_id, asset_id, asset_revision)] = batch_id
        for placement_id in member_ids:
            batch_by_placement[placement_id] = batch_id
        display_name = str(bindings[member_ids[0]].get("displayName") or asset_id)
        pattern = select_industrial_pattern(
            {
                "displayName": display_name,
                "category": str(
                    bindings[member_ids[0]].get("category") or ""
                ),
                "tags": list(bindings[member_ids[0]].get("tags") or []),
            }
        )
        resource_batches.append(
            {
                "batch_id": batch_id,
                "exact_catalog_identity": {
                    "asset_id": asset_id,
                    "asset_definition_revision": asset_revision,
                    "display_name": display_name,
                },
                "quantity": len(member_ids),
                "target_area": str(zones[target_zone_id].get("label") or target_zone_id),
                "placement_pattern": pattern,
                "semantic_orientation": "reviewed_reference_transform",
                "resource_role": "reference_reproduction",
                "authored_spacing": None,
                "ordering_or_grouping": target_zone_id,
                "required_relationships": [],
                "placement_dependencies": [],
                "evidence_refs": [str(manifest.get("manifestRevision") or "")],
                "reference_entity_ids": member_ids,
            }
        )

    resources_by_id = {item["batch_id"]: item for item in resource_batches}
    for dependency in manifest.get("supportDependencies", []):
        if not isinstance(dependency, Mapping):
            continue
        placement_id = str(dependency.get("placementId") or "")
        support_id = str(dependency.get("supportPlacementId") or "")
        batch_id = batch_by_placement.get(placement_id)
        support_batch_id = batch_by_placement.get(support_id)
        if not batch_id or not support_batch_id or batch_id == support_batch_id:
            continue
        batch = resources_by_id[batch_id]
        if support_batch_id not in batch["placement_dependencies"]:
            batch["placement_dependencies"].append(support_batch_id)
            batch["required_relationships"].append(
                {
                    "kind": "supported_by",
                    "target_batch_id": support_batch_id,
                    "evidence_ref": str(manifest.get("manifestRevision") or ""),
                }
            )
    for batch in resource_batches:
        batch["placement_dependencies"].sort()
        batch["required_relationships"].sort(
            key=lambda item: (item["kind"], item["target_batch_id"])
        )

    family_zones: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for zone_id, zone in zones.items():
        stem = _family_stem(str(zone.get("label") or ""))
        if stem:
            family_zones[stem].append((str(zone.get("label") or ""), zone_id))
    cell_recipes = []
    module_families = []
    for stem, members in sorted(family_zones.items()):
        if len(members) < 2:
            continue
        members.sort()
        source_label, source_zone_id = members[0]
        recipe_id = _stable_id("cell-recipe", {"familyStem": stem})
        source_batches = sorted(
            batch_id
            for (target_zone_id, _asset_id, _revision), batch_id in batch_by_group.items()
            if target_zone_id == source_zone_id
        )
        cell_recipes.append(
            {
                "recipe_id": recipe_id,
                "target_area": source_label,
                "member_batches": source_batches,
                "candidate_strategies": ["reviewed_reference_geometry"],
                "selected_strategy_or_objective": "reviewed_reference_geometry",
                "authored_spacing": None,
                "process_order": [],
                "interfaces": [],
                "evidence_refs": [str(manifest.get("manifestRevision") or "")],
            }
        )
        module_families.append(
            {
                "family_id": _stable_id("module-family", {"familyStem": stem}),
                "source_recipe_or_cell": recipe_id,
                "target_areas": [label for label, _zone_id in members[1:]],
                "allowed_transform_mode": "translate_exact",
                "preserve_source": True,
                "conformance_requirements": ["reviewed_reference_identity"],
                "composable_with": [],
                "evidence_refs": [str(manifest.get("manifestRevision") or "")],
            }
        )

    source_ref = manifest.get("source") or {}
    plan_settings = (document.get("extensions") or {}).get("facilityPlan") or {}
    root_zones = [
        {
            "department_id": zone_id,
            "label": str(zone.get("label") or ""),
            "zone_type": str(zone.get("zoneType") or ""),
            "reference_entity_id": zone_id,
            "evidence_refs": [str(manifest.get("manifestRevision") or "")],
        }
        for zone_id, zone in sorted(zones.items())
        if not relationships.get(zone_id)
    ]
    hierarchy = [
        {
            "parent_area": str(zones[parent_id].get("label") or parent_id),
            "child_area": str(zones[zone_id].get("label") or zone_id),
            "reference_entity_id": zone_id,
            "evidence_refs": [str(manifest.get("manifestRevision") or "")],
        }
        for zone_id, parent_id in sorted(relationships.items())
        if parent_id
    ]
    routes = [
        {
            "route_id": str(item.get("routeId") or ""),
            "label": str(item.get("label") or ""),
            "route_kind": str(item.get("routeKind") or ""),
            "width": float(item.get("corridorWidth") or 0.0),
            "dimension_authority": "reviewed_reference",
            "reference_entity_id": str(item.get("routeId") or ""),
            "evidence_refs": [str(manifest.get("manifestRevision") or "")],
        }
        for item in document.get("routes", [])
        if isinstance(item, Mapping)
    ]
    floor_communication = [
        {
            "communication_id": str(item.get("markingId") or ""),
            "marking_type": str(item.get("markingType") or ""),
            "pattern": "reviewed_reference_marking",
            "reference_entity_ids": [str(item.get("markingId") or "")],
            "dimension_authority": "reviewed_reference",
            "evidence_refs": [str(manifest.get("manifestRevision") or "")],
        }
        for item in document.get("floorMarkings", [])
        if isinstance(item, Mapping)
    ]
    review_status = (
        "confirmed" if review_receipt.get("reviewStatus") == "approved" else "pending"
    )
    program = {
        "schema_version": FACILITY_PROGRAM_SCHEMA,
        "identity": {
            "program_id": _stable_id(
                "facility-program-reference",
                {"manifestRevision": manifest.get("manifestRevision")},
            ),
            "display_name": str(document.get("displayName") or "Reference Factory"),
            "source_revision_refs": [
                str(manifest.get("manifestRevision") or ""),
                str(source_ref.get("layoutRevision") or ""),
            ],
        },
        "authority_and_mode": {
            "mode": "reference_reproduction",
            "evidence_status": "derived",
            "review_status": review_status,
            "production_eligible": False,
            "prototype_assumptions_allowed": False,
        },
        "facility_envelope": {
            "width": float(plan_settings.get("widthMeters") or 0.0),
            "depth": float(plan_settings.get("depthMeters") or 0.0),
            "source_unit": "m",
            "display_name": str(document.get("displayName") or "Reference Factory"),
            "grid_size": float(plan_settings.get("gridSpacingMeters") or 1.0),
            "dimension_evidence_refs": [str(source_ref.get("layoutRevision") or "")],
        },
        "macro_departments": root_zones,
        "area_hierarchy": hierarchy,
        "flow_requirements": [],
        "route_network": {"primary_routes": routes, "local_routes": []},
        "resource_batches": resource_batches,
        "cell_recipes": cell_recipes,
        "module_families": module_families,
        "floor_communication": floor_communication,
        "presentation_intent": {
            "fit_to_occupied_content": True,
            "semantic_zoom": True,
            "overview_label_priority": "macro_then_cells",
        },
        "unresolved_requirements": deepcopy(list(manifest.get("unresolved") or [])),
        "reference_manifest_ref": {
            "manifest_id": str(manifest.get("manifestId") or ""),
            "manifest_revision": str(manifest.get("manifestRevision") or ""),
            "source_layout_revision": str(source_ref.get("layoutRevision") or ""),
        },
    }
    try:
        return canonicalize_facility_program(program)
    except FacilityProgramError as exc:
        raise FacilityReferenceGenerationError(exc.code, str(exc), details=exc.details) from exc


def topologically_order_reference_placements(
    placements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Order exact placements so every authored support precedes its dependent."""

    records = [deepcopy(dict(item)) for item in placements]
    by_id = {
        str(item.get("placementId") or ""): item
        for item in records
        if item.get("placementId")
    }
    if len(by_id) != len(records):
        raise FacilityReferenceGenerationError(
            "reference_placement_identity_invalid",
            "Reference placements require unique stable identities.",
        )
    original_order = {
        str(item.get("placementId") or ""): index
        for index, item in enumerate(records)
    }
    dependencies: dict[str, set[str]] = {placement_id: set() for placement_id in by_id}
    dependents: dict[str, set[str]] = {placement_id: set() for placement_id in by_id}
    for placement_id, placement in by_id.items():
        relation = placement.get("snapRelationship")
        if not isinstance(relation, Mapping):
            continue
        support_id = str(relation.get("supportPlacementId") or "")
        if not support_id:
            continue
        if support_id not in by_id:
            raise FacilityReferenceGenerationError(
                "reference_support_missing",
                "A surface-attached placement references a missing support.",
                details={"placementId": placement_id, "supportPlacementId": support_id},
            )
        dependencies[placement_id].add(support_id)
        dependents[support_id].add(placement_id)

    ready = sorted(
        (placement_id for placement_id, values in dependencies.items() if not values),
        key=original_order.__getitem__,
    )
    result: list[dict[str, Any]] = []
    while ready:
        placement_id = ready.pop(0)
        result.append(by_id[placement_id])
        for dependent_id in sorted(
            dependents[placement_id], key=original_order.__getitem__
        ):
            dependencies[dependent_id].discard(placement_id)
            if not dependencies[dependent_id]:
                ready.append(dependent_id)
        ready.sort(key=original_order.__getitem__)
    if len(result) != len(records):
        cycle = sorted(
            placement_id for placement_id, values in dependencies.items() if values
        )
        raise FacilityReferenceGenerationError(
            "reference_support_cycle",
            "Reference placement support relationships contain a cycle.",
            details={"placementIds": cycle},
        )
    return result


def _reviewed_zone(
    zone: Mapping[str, Any],
    parent_zone_id: str | None,
    manifest_revision: str,
) -> dict[str, Any]:
    result = deepcopy(dict(zone))
    extensions = deepcopy(dict(result.get("extensions") or {}))
    knowledge = deepcopy(dict(extensions.get("knowledgeFoundation") or {}))
    knowledge.update(
        {
            "entityKind": "subzone" if parent_zone_id else "macro_department",
            "parentZoneId": parent_zone_id,
            "parentBindingEvidenceStatus": "reviewed_derived",
            "referenceManifestRevision": manifest_revision,
            "generatedBy": "facility_reference_reproduction_rq",
        }
    )
    extensions["knowledgeFoundation"] = knowledge
    result["extensions"] = extensions
    return result


def _reviewed_placement(
    placement: Mapping[str, Any],
    binding: Mapping[str, Any],
    zones: Mapping[str, Mapping[str, Any]],
    manifest_revision: str,
) -> dict[str, Any]:
    result = deepcopy(dict(placement))
    target_zone_id = str(binding.get("derivedTargetZoneId") or "")
    result["zoneIds"] = [target_zone_id]
    metadata = deepcopy(dict(result.get("metadata") or {}))
    metadata.update(
        {
            "generatedBy": "facility_reference_reproduction_rq",
            "targetZoneId": target_zone_id,
            "targetArea": str((zones.get(target_zone_id) or {}).get("label") or ""),
            "targetBindingEvidenceStatus": "reviewed_derived",
            "referenceManifestRevision": manifest_revision,
        }
    )
    result["metadata"] = metadata
    return result


def _operation_batch(
    stage_id: str,
    index: int,
    operations: Sequence[Mapping[str, Any]],
    *,
    planned_instance_count: int,
    prerequisite_batch_ids: Sequence[str],
    dependency_atomic_reason: str | None = None,
) -> dict[str, Any]:
    values = [deepcopy(dict(item)) for item in operations]
    if len(values) > REFERENCE_MAXIMUM_OPERATION_BATCH:
        raise FacilityReferenceGenerationError(
            "reference_operation_batch_exceeded",
            "A reference operation batch exceeds the kernel limit.",
        )
    identity = {
        "stageId": stage_id,
        "index": index,
        "operationsRevision": _revision(values),
    }
    return {
        "batchId": _stable_id("reference-batch", identity),
        "stageId": stage_id,
        "sequence": index,
        "operationCount": len(values),
        "plannedInstanceCount": planned_instance_count,
        "operations": values,
        "operationsRevision": _revision(values),
        "prerequisiteBatchIds": sorted(set(prerequisite_batch_ids)),
        "dependencyAtomicReason": dependency_atomic_reason,
    }


def compile_reference_reproduction_plan(
    program: Mapping[str, Any],
    manifest: Mapping[str, Any],
    review_receipt: Mapping[str, Any],
    source_layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile the approved reference into immutable, dependency-safe operations."""

    canonical_program = canonicalize_facility_program(program)
    if canonical_program["authority_and_mode"]["mode"] != "reference_reproduction":
        raise FacilityReferenceGenerationError(
            "reference_program_mode_invalid",
            "Only reference_reproduction programs can use the archive adapter.",
        )
    document = _assert_reference_bindings(
        manifest, review_receipt, source_layout, require_approved=True
    )
    program_ref = canonical_program.get("reference_manifest_ref") or {}
    if program_ref.get("manifest_revision") != manifest.get("manifestRevision"):
        raise FacilityReferenceGenerationError(
            "reference_program_stale",
            "The FacilityProgram is not bound to the supplied reference manifest.",
        )

    manifest_revision = str(manifest.get("manifestRevision") or "")
    parent_by_zone = {
        str(item.get("zoneId") or ""): str(item.get("derivedParentZoneId") or "")
        for item in manifest.get("zoneRelationships", [])
        if isinstance(item, Mapping)
    }
    zones = {
        str(item.get("zoneId") or ""): item
        for item in document.get("zones", [])
        if isinstance(item, Mapping)
    }
    bindings = {
        str(item.get("placementId") or ""): item
        for item in manifest.get("placementBindings", [])
        if isinstance(item, Mapping)
    }

    stage_operations: dict[str, list[dict[str, Any]]] = {
        "facility_envelope": [
            {"op": "rename_layout", "displayName": document["displayName"]},
            {
                "op": "set_plan_settings",
                "planSettings": deepcopy(
                    (document.get("extensions") or {}).get("facilityPlan") or {}
                ),
            },
        ],
        "macro_departments": [],
        "primary_circulation": [
            {"op": "add_route", "route": deepcopy(dict(item))}
            for item in document.get("routes", [])
            if isinstance(item, Mapping)
        ],
        "department_subdivisions": [],
        "department_resources": [],
        "seed_cells": [],
        "repeated_modules": [],
        "floor_communication": [
            {"op": "add_floor_marking", "floorMarking": deepcopy(dict(item))}
            for item in document.get("floorMarkings", [])
            if isinstance(item, Mapping)
        ],
        "deterministic_validation": [],
        "review_and_save": [],
    }
    for zone_id, zone in zones.items():
        parent_id = parent_by_zone.get(zone_id) or None
        operation = {
            "op": "add_zone",
            "zone": _reviewed_zone(zone, parent_id, manifest_revision),
        }
        stage_operations[
            "department_subdivisions" if parent_id else "macro_departments"
        ].append(operation)

    ordered_placements = topologically_order_reference_placements(
        document.get("placements", [])
    )
    placement_operations = [
        {
            "op": "place_asset",
            "placement": _reviewed_placement(
                item,
                bindings[str(item.get("placementId") or "")],
                zones,
                manifest_revision,
            ),
        }
        for item in ordered_placements
    ]
    stage_operations["department_resources"] = placement_operations

    stage_order = list(stage_operations)
    stages = []
    previous_batch_id: str | None = None
    placement_batch_by_id: dict[str, str] = {}
    for stage_sequence, stage_id in enumerate(stage_order, start=1):
        operations = stage_operations[stage_id]
        chunks = [
            operations[index : index + REFERENCE_MAXIMUM_OPERATION_BATCH]
            for index in range(0, len(operations), REFERENCE_MAXIMUM_OPERATION_BATCH)
        ]
        if not chunks:
            chunks = [[]]
        batches = []
        for batch_sequence, chunk in enumerate(chunks, start=1):
            prerequisites = [previous_batch_id] if previous_batch_id else []
            if stage_id == "department_resources":
                for operation in chunk:
                    placement = operation["placement"]
                    relation = placement.get("snapRelationship")
                    if isinstance(relation, Mapping):
                        support_id = str(relation.get("supportPlacementId") or "")
                        support_batch = placement_batch_by_id.get(support_id)
                        if support_id and support_batch:
                            prerequisites.append(support_batch)
            batch = _operation_batch(
                stage_id,
                batch_sequence,
                chunk,
                planned_instance_count=(
                    len(chunk) if stage_id == "department_resources" else 0
                ),
                prerequisite_batch_ids=prerequisites,
            )
            batches.append(batch)
            previous_batch_id = batch["batchId"]
            if stage_id == "department_resources":
                for operation in chunk:
                    placement_batch_by_id[
                        str(operation["placement"].get("placementId") or "")
                    ] = batch["batchId"]
        stages.append(
            {
                "stageId": stage_id,
                "sequence": stage_sequence,
                "batchCount": len(batches),
                "operationCount": sum(item["operationCount"] for item in batches),
                "plannedInstanceCount": sum(
                    item["plannedInstanceCount"] for item in batches
                ),
                "batches": batches,
            }
        )

    resource_batches = next(
        item for item in stages if item["stageId"] == "department_resources"
    )["batches"]
    for batch in resource_batches[:-1]:
        if not (
            REFERENCE_MINIMUM_NONFINAL_PLACEMENT_BATCH
            <= batch["plannedInstanceCount"]
            <= REFERENCE_MAXIMUM_OPERATION_BATCH
        ):
            raise FacilityReferenceGenerationError(
                "reference_placement_batch_size_invalid",
                "A non-final placement batch violates the frozen construction floor.",
                details={"batchId": batch["batchId"]},
            )

    core = {
        "schemaVersion": REFERENCE_OPERATION_PLAN_SCHEMA,
        "programId": canonical_program["identity"]["program_id"],
        "programRevision": _revision(canonical_program),
        "manifestRevision": manifest_revision,
        "sourceLayoutRevision": layout_revision(document),
        "reviewReceiptRevision": str(review_receipt.get("receiptRevision") or ""),
        "stages": stages,
        "counts": {
            **_source_counts(document),
            "operationBatches": sum(item["batchCount"] for item in stages),
            "operations": sum(item["operationCount"] for item in stages),
        },
    }
    core["planRevision"] = _revision(core)
    return core


def _entity_index(layout: Mapping[str, Any], collection: str, field: str) -> dict[str, Any]:
    return {
        str(item.get(field) or ""): item
        for item in layout.get(collection, [])
        if isinstance(item, Mapping)
    }


def validate_reference_reproduction_result(
    result_layout: Mapping[str, Any],
    source_layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Check exact entity identity and authoritative geometry against the archive."""

    result = canonicalize_layout(deepcopy(dict(result_layout)))
    source = canonicalize_layout(deepcopy(dict(source_layout)))
    errors: list[str] = []
    identity_fields = {
        "zones": "zoneId",
        "routes": "routeId",
        "placements": "placementId",
        "floorMarkings": "markingId",
    }
    geometry_fields = {
        "zones": ("boundary", "floorElevation", "anchors"),
        "routes": ("centerline", "corridorWidth", "sourceEndpoint", "targetEndpoint"),
        "placements": ("transform", "snapRelationship"),
        "floorMarkings": ("transform", "width", "depth"),
    }
    collection_results = {}
    for collection, id_field in identity_fields.items():
        expected = _entity_index(source, collection, id_field)
        actual = _entity_index(result, collection, id_field)
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = []
        for entity_id in sorted(set(expected) & set(actual)):
            if any(
                expected[entity_id].get(field) != actual[entity_id].get(field)
                for field in geometry_fields[collection]
            ):
                changed.append(entity_id)
        if missing:
            errors.append(f"{collection}_missing")
        if extra:
            errors.append(f"{collection}_extra")
        if changed:
            errors.append(f"{collection}_geometry_changed")
        collection_results[collection] = {
            "expectedCount": len(expected),
            "actualCount": len(actual),
            "missingIds": missing,
            "extraIds": extra,
            "geometryChangedIds": changed,
        }
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "collections": collection_results,
        "resultLayoutRevision": layout_revision(result),
        "sourceLayoutRevision": layout_revision(source),
    }


def execute_reference_reproduction_plan(
    base_layout: Mapping[str, Any],
    operation_plan: Mapping[str, Any],
    source_layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one immutable plan in memory; persistence remains an explicit later Save."""

    if operation_plan.get("schemaVersion") != REFERENCE_OPERATION_PLAN_SCHEMA:
        raise FacilityReferenceGenerationError(
            "reference_operation_plan_invalid", "Reference operation plan schema is invalid."
        )
    base = canonicalize_layout(deepcopy(dict(base_layout)))
    draft = deepcopy(base)
    completed_batch_ids: set[str] = set()
    receipts = []
    for stage in operation_plan.get("stages", []):
        if not isinstance(stage, Mapping):
            raise FacilityReferenceGenerationError(
                "reference_operation_plan_invalid", "Reference stage is invalid."
            )
        for batch in stage.get("batches", []):
            prerequisites = set(batch.get("prerequisiteBatchIds") or [])
            missing = sorted(prerequisites - completed_batch_ids)
            if missing:
                raise FacilityReferenceGenerationError(
                    "reference_batch_prerequisite_incomplete",
                    "A reference batch cannot execute before its prerequisites.",
                    details={"batchId": batch.get("batchId"), "missing": missing},
                )
            before_revision = layout_revision(draft)
            applied = apply_facility_layout_operations(
                draft,
                list(batch.get("operations") or []),
                base_revision=before_revision,
            )
            draft = applied["document"]
            receipt = {
                "receiptId": _stable_id(
                    "reference-receipt",
                    {
                        "planRevision": operation_plan.get("planRevision"),
                        "batchId": batch.get("batchId"),
                        "beforeRevision": before_revision,
                        "afterRevision": layout_revision(draft),
                    },
                ),
                "batchId": batch.get("batchId"),
                "stageId": stage.get("stageId"),
                "baseDraftRevision": before_revision,
                "resultDraftRevision": layout_revision(draft),
                "prerequisiteBatchIds": sorted(prerequisites),
                "operationCount": int(batch.get("operationCount") or 0),
                "plannedInstanceCount": int(batch.get("plannedInstanceCount") or 0),
                "operationsRevision": batch.get("operationsRevision"),
                "status": "valid",
            }
            receipts.append(receipt)
            completed_batch_ids.add(str(batch.get("batchId") or ""))

    validation = validate_reference_reproduction_result(draft, source_layout)
    if validation["status"] != "valid":
        raise FacilityReferenceGenerationError(
            "reference_reproduction_validation_failed",
            "The deterministic draft does not match the reviewed reference geometry.",
            details=validation,
        )
    return {
        "schemaVersion": "facility-reference-execution-result-v1",
        "status": "complete",
        "saved": False,
        "saveEligibility": "review_required",
        "baseLayoutRevision": layout_revision(base),
        "draftLayoutRevision": layout_revision(draft),
        "operationPlanRevision": operation_plan.get("planRevision"),
        "draftLayout": draft,
        "undoLayout": base,
        "receiptChain": receipts,
        "cumulativeDiff": build_exact_layout_diff(base, draft),
        "validation": validation,
    }


__all__ = [
    "REFERENCE_MAXIMUM_OPERATION_BATCH",
    "REFERENCE_MINIMUM_NONFINAL_PLACEMENT_BATCH",
    "REFERENCE_OPERATION_PLAN_SCHEMA",
    "FacilityReferenceGenerationError",
    "compile_reference_reproduction_plan",
    "execute_reference_reproduction_plan",
    "facility_program_from_reference_manifest",
    "topologically_order_reference_placements",
    "validate_reference_reproduction_result",
]
