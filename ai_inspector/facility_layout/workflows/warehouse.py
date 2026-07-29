"""Warehouse-lane workflow package.

The compiler expands rack hierarchy and capacity arithmetic deterministically,
then emits coordinate-free P8 and P9 artifacts. A planner or Sage may select
the package inputs, but neither path can write a layout directly.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from .common import (
    MAXIMUM_WORKFLOW_ASSET_INSTANCES,
    WORKFLOW_PACKAGE_SCHEMA_VERSION,
    base_compilation,
    build_manual_planner_request,
    detached,
    fail,
    identifier,
    mapping,
    normalize_basis,
    normalize_provenance,
    normalize_scope,
    normalize_source_revisions,
    normalize_strategies,
    percentage,
    positive_integer,
    records,
    reject_raw_geometry,
    revision,
    semantic_alternatives,
    stable_workflow_id,
    text,
)


WAREHOUSE_PACKAGE_TYPE = "warehouse_lane"
WAREHOUSE_PACKAGE_VERSION = 1
_SUPPORTING_ROLES = {
    "pallet": "storage",
    "staging": "material_handling",
    "dock": "material_handling",
    "charger": "utility",
    "workstation": "workstation",
}
_WAREHOUSE_ZONE_TYPES = {
    "storage",
    "staging",
    "receiving",
    "shipping",
    "aisle",
    "dock",
    "charging",
}


def _basis(
    raw: Mapping[str, Any],
    *,
    field: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return normalize_basis(
        raw,
        field=field,
        known_evidence_ids=set(provenance["evidenceIds"]),
        known_assumption_ids=set(provenance["assumptionIds"]),
        unresolved_subjects=set(provenance["unresolvedSubjects"]),
    )


def _rack_hierarchy(
    rack: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_item_id = identifier(rack.get("itemId"), "rackSystem.itemId")
    asset_id = identifier(rack.get("assetId"), "rackSystem.assetId")
    asset_revision = revision(
        rack.get("assetDefinitionRevision"),
        "rackSystem.assetDefinitionRevision",
    )
    row_count = positive_integer(
        rack.get("rowCount"),
        "rackSystem.rowCount",
        maximum=100,
    )
    bays_per_row = positive_integer(
        rack.get("baysPerRow"),
        "rackSystem.baysPerRow",
        maximum=100,
    )
    levels_per_bay = positive_integer(
        rack.get("levelsPerBay"),
        "rackSystem.levelsPerBay",
        maximum=50,
    )
    slots_per_level = positive_integer(
        rack.get("slotsPerLevel"),
        "rackSystem.slotsPerLevel",
        maximum=50,
    )
    pallet_positions = positive_integer(
        rack.get("palletPositionsPerSlot", 1),
        "rackSystem.palletPositionsPerSlot",
        maximum=20,
    )
    target_zone_ref = identifier(
        rack.get("targetZoneRef"),
        "rackSystem.targetZoneRef",
    )
    basis = _basis(
        rack,
        field="rackSystem",
        provenance=provenance,
    )
    rows = []
    selected_assets = []
    for row_index in range(row_count):
        row_number = row_index + 1
        row_id = f"{base_item_id}-row-{row_number:03d}"
        bays = []
        for bay_index in range(bays_per_row):
            bay_number = bay_index + 1
            bay_id = f"{row_id}-bay-{bay_number:03d}"
            slots = []
            for level_index in range(levels_per_bay):
                for slot_index in range(slots_per_level):
                    slots.append(
                        {
                            "slotId": (
                                f"{bay_id}-level-{level_index + 1:02d}"
                                f"-slot-{slot_index + 1:02d}"
                            ),
                            "levelNumber": level_index + 1,
                            "slotNumber": slot_index + 1,
                            "palletPositionCount": pallet_positions,
                        }
                    )
            bays.append(
                {
                    "bayId": bay_id,
                    "bayNumber": bay_number,
                    "slots": slots,
                }
            )
        rows.append(
            {
                "rowId": row_id,
                "rowNumber": row_number,
                "bays": bays,
            }
        )
        selected_assets.append(
            {
                "itemId": row_id,
                "assetId": asset_id,
                "assetDefinitionRevision": asset_revision,
                "quantity": bays_per_row,
                "resourceRole": "storage",
                "stage": row_index,
                "targetZoneRef": target_zone_ref,
                **basis,
            }
        )
    hierarchy = {
        "rackSystemId": base_item_id,
        "rows": rows,
        "counts": {
            "rows": row_count,
            "bays": row_count * bays_per_row,
            "levels": row_count * bays_per_row * levels_per_bay,
            "slots": (
                row_count
                * bays_per_row
                * levels_per_bay
                * slots_per_level
            ),
            "nominalPalletPositions": (
                row_count
                * bays_per_row
                * levels_per_bay
                * slots_per_level
                * pallet_positions
            ),
        },
    }
    return selected_assets, hierarchy


def _supporting_assets(
    raw_assets: Any,
    *,
    provenance: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    selected = []
    by_kind: dict[str, list[str]] = {"rack_rows": []}
    for index, raw in enumerate(
        records(raw_assets, "supportingAssets")
    ):
        field = f"supportingAssets[{index}]"
        kind = raw.get("kind")
        if kind not in _SUPPORTING_ROLES:
            fail(
                "unsupported_warehouse_asset_kind",
                f"{field}.kind is unsupported.",
                path=f"{field}.kind",
            )
        item_id = identifier(raw.get("itemId"), f"{field}.itemId")
        quantity = positive_integer(
            raw.get("quantity", 1),
            f"{field}.quantity",
        )
        selected.append(
            {
                "itemId": item_id,
                "assetId": identifier(
                    raw.get("assetId"),
                    f"{field}.assetId",
                ),
                "assetDefinitionRevision": revision(
                    raw.get("assetDefinitionRevision"),
                    f"{field}.assetDefinitionRevision",
                ),
                "quantity": quantity,
                "resourceRole": _SUPPORTING_ROLES[str(kind)],
                "stage": positive_integer(
                    raw.get("stage", 1),
                    f"{field}.stage",
                    minimum=0,
                    maximum=1000,
                ),
                "targetZoneRef": identifier(
                    raw.get("targetZoneRef"),
                    f"{field}.targetZoneRef",
                ),
                **_basis(raw, field=field, provenance=provenance),
            }
        )
        by_kind.setdefault(str(kind), []).append(item_id)
    return selected, by_kind


def _zones(
    raw_zones: Any,
    *,
    selected_assets: list[dict[str, Any]],
    by_kind: Mapping[str, list[str]],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected_ids = {item["itemId"] for item in selected_assets}
    rack_rows = sorted(
        item_id for item_id in selected_ids if "-row-" in item_id
    )
    kind_index = {
        **{key: list(value) for key, value in by_kind.items()},
        "rack_rows": rack_rows,
    }
    result = []
    for index, raw in enumerate(records(raw_zones, "zones")):
        field = f"zones[{index}]"
        zone_type = raw.get("zoneType")
        if zone_type not in _WAREHOUSE_ZONE_TYPES:
            fail(
                "unsupported_warehouse_zone_type",
                f"{field}.zoneType is unsupported.",
                path=f"{field}.zoneType",
            )
        member_ids = {
            identifier(value, f"{field}.memberItemIds")
            for value in raw.get("memberItemIds", [])
        }
        for kind in raw.get("memberKinds", []):
            if kind not in kind_index:
                fail(
                    "unknown_warehouse_member_kind",
                    f"{field} references unknown member kind '{kind}'.",
                )
            member_ids.update(kind_index[str(kind)])
        unknown = sorted(member_ids - selected_ids)
        if not member_ids or unknown:
            fail(
                "warehouse_zone_members_invalid",
                f"{field} must resolve to selected asset items.",
                details={"unknownItemIds": unknown},
            )
        zone = {
            "zoneRequestId": identifier(
                raw.get("zoneRequestId"),
                f"{field}.zoneRequestId",
            ),
            "zoneType": zone_type,
            "label": text(
                raw.get("label"),
                f"{field}.label",
                maximum=120,
            ),
            "memberItemIds": sorted(member_ids),
            "paddingClass": raw.get("paddingClass", "standard"),
            "allowedAssetCategories": sorted(
                {
                    identifier(value, f"{field}.allowedAssetCategories")
                    for value in raw.get("allowedAssetCategories", [])
                }
            ),
            **_basis(raw, field=field, provenance=provenance),
        }
        if raw.get("existingZoneId") is not None:
            zone["existingZoneId"] = identifier(
                raw.get("existingZoneId"),
                f"{field}.existingZoneId",
            )
        result.append(zone)
    zone_ids = {item["zoneRequestId"] for item in result}
    for item in selected_assets:
        if item["targetZoneRef"] not in zone_ids:
            fail(
                "warehouse_target_zone_unknown",
                (
                    f"Selected item '{item['itemId']}' references unknown "
                    f"zone '{item['targetZoneRef']}'."
                ),
            )
    return sorted(result, key=lambda item: item["zoneRequestId"])


def _flows(
    raw_flows: Any,
    *,
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(records(raw_flows, "forkliftFlows")):
        field = f"forkliftFlows[{index}]"
        result.append(
            {
                "flowId": identifier(
                    raw.get("flowId"),
                    f"{field}.flowId",
                ),
                "flowKind": "forklift",
                "sourceEndpoint": mapping(
                    raw.get("sourceEndpoint"),
                    f"{field}.sourceEndpoint",
                ),
                "targetEndpoint": mapping(
                    raw.get("targetEndpoint"),
                    f"{field}.targetEndpoint",
                ),
                "vehicleProfileId": identifier(
                    raw.get("vehicleProfileId"),
                    f"{field}.vehicleProfileId",
                ),
                "vehicleProfileRevision": revision(
                    raw.get("vehicleProfileRevision"),
                    f"{field}.vehicleProfileRevision",
                ),
                **_basis(raw, field=field, provenance=provenance),
            }
        )
    return sorted(result, key=lambda item: item["flowId"])


def _capability_requirements(
    raw_values: Any,
    *,
    selected_ids: set[str],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(
        records(raw_values, "requiredCapabilities")
    ):
        field = f"requiredCapabilities[{index}]"
        assigned = sorted(
            {
                identifier(value, f"{field}.assignedItemIds")
                for value in raw.get("assignedItemIds", [])
            }
        )
        if not assigned or not set(assigned).issubset(selected_ids):
            fail(
                "warehouse_capability_assignment_invalid",
                f"{field} must reference selected items.",
            )
        result.append(
            {
                "requirementId": identifier(
                    raw.get("requirementId"),
                    f"{field}.requirementId",
                ),
                "capabilityId": identifier(
                    raw.get("capabilityId"),
                    f"{field}.capabilityId",
                ),
                "quantity": positive_integer(
                    raw.get("quantity"),
                    f"{field}.quantity",
                ),
                "assignedItemIds": assigned,
                **_basis(raw, field=field, provenance=provenance),
            }
        )
    return sorted(result, key=lambda item: item["requirementId"])


def _pallets(
    raw_values: Any,
    *,
    hierarchy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    valid_slots = {
        slot["slotId"]
        for row in hierarchy["rows"]
        for bay in row["bays"]
        for slot in bay["slots"]
    }
    result = []
    seen_ids: set[str] = set()
    occupied: dict[str, int] = {}
    slot_capacity = {
        slot["slotId"]: int(slot["palletPositionCount"])
        for row in hierarchy["rows"]
        for bay in row["bays"]
        for slot in bay["slots"]
    }
    for index, raw in enumerate(records(raw_values, "pallets")):
        field = f"pallets[{index}]"
        pallet_id = identifier(raw.get("palletId"), f"{field}.palletId")
        slot_id = identifier(raw.get("slotId"), f"{field}.slotId")
        if pallet_id in seen_ids:
            fail(
                "duplicate_pallet_id",
                f"Duplicate pallet '{pallet_id}'.",
            )
        if slot_id not in valid_slots:
            fail(
                "warehouse_slot_unknown",
                f"Pallet '{pallet_id}' references an unknown slot.",
            )
        occupied[slot_id] = occupied.get(slot_id, 0) + 1
        if occupied[slot_id] > slot_capacity[slot_id]:
            fail(
                "warehouse_slot_capacity_exceeded",
                f"Slot '{slot_id}' exceeds its declared pallet positions.",
            )
        seen_ids.add(pallet_id)
        result.append(
            {
                "palletId": pallet_id,
                "slotId": slot_id,
                "loadRef": (
                    identifier(raw.get("loadRef"), f"{field}.loadRef")
                    if raw.get("loadRef") is not None
                    else None
                ),
            }
        )
    return sorted(result, key=lambda item: item["palletId"])


def compile_warehouse_lane_package(
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one warehouse lane into P8 manual and P9 Sage artifacts."""

    if not isinstance(spec, Mapping):
        fail(
            "invalid_warehouse_package",
            "Warehouse package must be an object.",
        )
    reject_raw_geometry(spec)
    normalized = detached(spec)
    if normalized.get("schemaVersion") != WAREHOUSE_PACKAGE_VERSION:
        fail(
            "unsupported_warehouse_package_version",
            "Warehouse package schemaVersion must equal 1.",
        )
    if normalized.get("packageType") != WAREHOUSE_PACKAGE_TYPE:
        fail(
            "invalid_warehouse_package_type",
            "packageType must equal warehouse_lane.",
        )
    package_id = identifier(normalized.get("packageId"), "packageId")
    scope = normalize_scope(normalized.get("scope"))
    source_revisions = normalize_source_revisions(
        normalized.get("sourceRevisions")
    )
    provenance = normalize_provenance(normalized)
    rack_assets, hierarchy = _rack_hierarchy(
        mapping(normalized.get("rackSystem"), "rackSystem"),
        provenance=provenance,
    )
    supporting, by_kind = _supporting_assets(
        normalized.get("supportingAssets", []),
        provenance=provenance,
    )
    selected_assets = sorted(
        rack_assets + supporting,
        key=lambda item: item["itemId"],
    )
    requested_count = sum(item["quantity"] for item in selected_assets)
    if requested_count > MAXIMUM_WORKFLOW_ASSET_INSTANCES:
        fail(
            "warehouse_asset_limit_exceeded",
            "Warehouse package exceeds the 500-placement planner limit.",
        )
    zones = _zones(
        normalized.get("zones", []),
        selected_assets=selected_assets,
        by_kind=by_kind,
        provenance=provenance,
    )
    zone_index = {item["zoneRequestId"]: item for item in zones}
    for item in selected_assets:
        zone = zone_index[item["targetZoneRef"]]
        if zone.get("existingZoneId"):
            item["targetZoneId"] = zone["existingZoneId"]
    flows = _flows(
        normalized.get("forkliftFlows", []),
        provenance=provenance,
    )
    capabilities = _capability_requirements(
        normalized.get("requiredCapabilities", []),
        selected_ids={item["itemId"] for item in selected_assets},
        provenance=provenance,
    )
    pallets = _pallets(
        normalized.get("pallets", []),
        hierarchy=hierarchy,
    )
    capacity = mapping(
        normalized.get("capacityPolicy", {}),
        "capacityPolicy",
    )
    utilization = percentage(
        capacity.get("planningUtilizationPercent", 100),
        "capacityPolicy.planningUtilizationPercent",
    )
    capacity_basis = _basis(
        {
            "itemId": f"{package_id}-capacity",
            "knowledgeStatus": capacity.get(
                "knowledgeStatus",
                "inferred",
            ),
            "evidenceIds": capacity.get("evidenceIds", []),
            "assumptionIds": capacity.get("assumptionIds", []),
        },
        field="capacityPolicy",
        provenance=provenance,
    )
    nominal = int(hierarchy["counts"]["nominalPalletPositions"])
    usable = int(math.floor(nominal * utilization / 100.0))
    occupied = len(pallets)
    if occupied > usable:
        fail(
            "warehouse_planning_capacity_exceeded",
            "Assigned pallets exceed the planning capacity estimate.",
        )
    estimates = {
        "capacity": {
            "estimateType": "planning_estimate",
            "nominalPalletPositions": nominal,
            "planningUtilizationPercent": utilization,
            "usablePalletPositions": usable,
            "occupiedPalletPositions": occupied,
            "availablePalletPositions": usable - occupied,
            "basis": capacity_basis,
            "sourceRevisions": deepcopy(source_revisions),
        },
        "forkliftTravel": [
            {
                "flowId": item["flowId"],
                "estimateStatus": "computed_by_deterministic_router_on_preview",
                "evidenceIds": item["evidenceIds"],
                "assumptionIds": item["assumptionIds"],
                "sourceRevisions": {
                    "layout": source_revisions["layout"],
                    "shell": source_revisions["shell"],
                    "policy": source_revisions["policy"],
                    "vehicle": item["vehicleProfileRevision"],
                },
            }
            for item in flows
        ],
    }
    strategies = normalize_strategies(
        normalized.get(
            "alternatives",
            ["flow_lanes", "compact_rows"],
        )
    )
    density = (
        mapping(normalized.get("layoutHints", {}), "layoutHints")
        .get("density", "balanced")
    )
    semantic_assets = [
        {
            key: deepcopy(value)
            for key, value in item.items()
            if key != "targetZoneId"
        }
        for item in selected_assets
    ]
    semantic_zones = [
        {
            key: deepcopy(value)
            for key, value in item.items()
            if key != "allowedAssetCategories"
        }
        for item in zones
    ]
    semantic_plan = {
        "schemaVersion": WORKFLOW_PACKAGE_SCHEMA_VERSION,
        "planId": stable_workflow_id(
            "plan-p10-warehouse-",
            {"packageId": package_id, "spec": normalized},
            length=20,
        ),
        "scope": scope,
        "objective": normalized.get("objective", "place_and_cleanup"),
        "sourceRevisions": {
            key: source_revisions[key]
            for key in ("layout", "shell", "policy")
        },
        "requiredCapabilities": capabilities,
        "selectedAssets": semantic_assets,
        "requiredZones": semantic_zones,
        "placementRelationships": [],
        "processBindings": [],
        "flows": flows,
        "evidence": deepcopy(provenance["evidence"]),
        "assumptions": deepcopy(provenance["assumptions"]),
        "unresolvedItems": deepcopy(provenance["unresolvedItems"]),
        "alternatives": semantic_alternatives(strategies),
        "layoutHints": {
            "density": density,
            "preserveManual": True,
            "preserveLocked": True,
            "primaryFlow": "forklift_access",
        },
    }
    manual_request = build_manual_planner_request(
        package_id=package_id,
        objective=semantic_plan["objective"],
        selected_assets=selected_assets,
        zones=zones,
        flows=flows,
        strategies=strategies,
        density=density,
        source_revisions=source_revisions,
    )
    domain_model = {
        "warehouseLane": {
            **hierarchy,
            "pallets": pallets,
            "stagingItemIds": sorted(by_kind.get("staging", [])),
            "dockItemIds": sorted(by_kind.get("dock", [])),
            "chargingItemIds": sorted(by_kind.get("charger", [])),
            "aisleZoneIds": sorted(
                {
                    endpoint["zoneId"]
                    for flow in flows
                    for endpoint in (
                        flow["sourceEndpoint"],
                        flow["targetEndpoint"],
                    )
                    if endpoint.get("kind") == "zone_anchor"
                    and endpoint.get("zoneId")
                }
            ),
        }
    }
    deferred = [
        {
            "id": item["flowId"],
            "code": "forklift_distance_pending_preview",
            "message": (
                "Distance and travel time are computed from the revision-bound "
                "route ghost, not guessed by the workflow package."
            ),
        }
        for item in flows
    ]
    return base_compilation(
        package_type=WAREHOUSE_PACKAGE_TYPE,
        package_id=package_id,
        spec=normalized,
        source_revisions=source_revisions,
        semantic_plan=semantic_plan,
        manual_request=manual_request,
        domain_model=domain_model,
        estimates=estimates,
        deferred=deferred,
    )


__all__ = [
    "WAREHOUSE_PACKAGE_TYPE",
    "WAREHOUSE_PACKAGE_VERSION",
    "compile_warehouse_lane_package",
]
