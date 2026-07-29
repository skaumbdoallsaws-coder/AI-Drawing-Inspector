"""Manufacturing-cell workflow package and reusable template compiler."""

from __future__ import annotations

from copy import deepcopy
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
    positive_integer,
    records,
    reject_raw_geometry,
    revision,
    semantic_alternatives,
    stable_workflow_id,
    text,
    workflow_fingerprint,
)


MANUFACTURING_CELL_PACKAGE_TYPE = "manufacturing_cell"
MANUFACTURING_CELL_PACKAGE_VERSION = 1
MANUFACTURING_CELL_TEMPLATE_VERSION = 1

_CELL_ROLE_TO_RESOURCE_ROLE = {
    "machine": "machine",
    "robot": "machine",
    "fixture": "fixture",
    "guard": "safety",
    "workstation": "workstation",
    "conveyor": "material_handling",
    "tooling": "tooling",
    "inspection": "inspection",
    "material_input": "material_handling",
    "material_output": "material_handling",
}
_CELL_ZONE_TYPES = {
    "workcell",
    "operator",
    "service",
    "safety",
    "staging",
    "inspection",
    "utility",
}
_CELL_FLOW_KINDS = {
    "material",
    "operator",
    "forklift",
    "conveyor",
    "utility",
}


def _basis(
    raw: Mapping[str, Any],
    *,
    field: str,
    provenance: Mapping[str, Any],
    subject_id: str,
) -> dict[str, Any]:
    basis_input = deepcopy(dict(raw))
    basis_input.setdefault("itemId", subject_id)
    return normalize_basis(
        basis_input,
        field=field,
        known_evidence_ids=set(provenance["evidenceIds"]),
        known_assumption_ids=set(provenance["assumptionIds"]),
        unresolved_subjects=set(provenance["unresolvedSubjects"]),
    )


def _normalized_template_body(raw: Any) -> dict[str, Any]:
    template = mapping(raw, "template")
    if template.get("schemaVersion") != MANUFACTURING_CELL_TEMPLATE_VERSION:
        fail(
            "unsupported_cell_template_version",
            "Manufacturing-cell template schemaVersion must equal 1.",
        )
    template_id = identifier(template.get("templateId"), "template.templateId")
    role_records = records(template.get("roles", []), "template.roles")
    roles = []
    role_ids: set[str] = set()
    for index, raw_role in enumerate(role_records):
        field = f"template.roles[{index}]"
        role_id = identifier(raw_role.get("roleId"), f"{field}.roleId")
        cell_role = raw_role.get("cellRole")
        if role_id in role_ids:
            fail(
                "duplicate_cell_role",
                f"Duplicate template role '{role_id}'.",
            )
        if cell_role not in _CELL_ROLE_TO_RESOURCE_ROLE:
            fail(
                "unsupported_cell_role",
                f"{field}.cellRole is unsupported.",
                path=f"{field}.cellRole",
            )
        role_ids.add(role_id)
        roles.append(
            {
                "roleId": role_id,
                "cellRole": cell_role,
                "label": text(
                    raw_role.get("label"),
                    f"{field}.label",
                    maximum=120,
                ),
                "quantity": positive_integer(
                    raw_role.get("quantity", 1),
                    f"{field}.quantity",
                ),
                "stage": positive_integer(
                    raw_role.get("stage", 0),
                    f"{field}.stage",
                    minimum=0,
                    maximum=1000,
                ),
                "targetZoneRef": identifier(
                    raw_role.get("targetZoneRef"),
                    f"{field}.targetZoneRef",
                ),
            }
        )
    if not roles:
        fail(
            "cell_template_roles_required",
            "Manufacturing-cell templates require at least one role.",
        )
    return {
        "schemaVersion": MANUFACTURING_CELL_TEMPLATE_VERSION,
        "templateId": template_id,
        "label": text(
            template.get("label"),
            "template.label",
            maximum=120,
        ),
        "roles": sorted(roles, key=lambda item: item["roleId"]),
        "zones": records(template.get("zones", []), "template.zones"),
        "relationships": records(
            template.get("relationships", []),
            "template.relationships",
        ),
        "flows": records(template.get("flows", []), "template.flows"),
        "capabilityRequirements": records(
            template.get("capabilityRequirements", []),
            "template.capabilityRequirements",
        ),
    }


def _template(
    raw: Any,
) -> dict[str, Any]:
    template = mapping(raw, "template")
    template_revision = revision(
        template.get("templateRevision"),
        "template.templateRevision",
    )
    body = _normalized_template_body(template)
    computed_revision = workflow_fingerprint(
        body
    )
    if computed_revision != template_revision:
        fail(
            "cell_template_revision_mismatch",
            "templateRevision does not match the canonical template.",
            details={
                "expectedRevision": computed_revision,
                "actualRevision": template_revision,
            },
        )
    return {**body, "templateRevision": template_revision}


def cell_template_revision(template_without_revision: Mapping[str, Any]) -> str:
    """Return the immutable revision for a reusable role-based template."""

    return workflow_fingerprint(
        _normalized_template_body(template_without_revision)
    )


def _asset_assignments(
    template: Mapping[str, Any],
    raw_values: Any,
    *,
    provenance: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    role_index = {item["roleId"]: item for item in template["roles"]}
    assignments = records(raw_values, "assetAssignments")
    assignment_index = {}
    for index, raw in enumerate(assignments):
        field = f"assetAssignments[{index}]"
        role_id = identifier(raw.get("roleId"), f"{field}.roleId")
        if role_id not in role_index:
            fail(
                "cell_assignment_role_unknown",
                f"{field} references unknown role '{role_id}'.",
            )
        if role_id in assignment_index:
            fail(
                "duplicate_cell_role_assignment",
                f"Role '{role_id}' is assigned more than once.",
            )
        assignment_index[role_id] = raw
    missing = sorted(set(role_index) - set(assignment_index))
    if missing:
        fail(
            "cell_role_assignments_incomplete",
            "Missing cell role assignments: " + ", ".join(missing) + ".",
        )
    selected = []
    role_to_item: dict[str, str] = {}
    assigned_item_ids: set[str] = set()
    for role_id in sorted(role_index):
        role = role_index[role_id]
        raw = assignment_index[role_id]
        field = f"assetAssignments.{role_id}"
        item_id = identifier(raw.get("itemId"), f"{field}.itemId")
        if item_id in assigned_item_ids:
            fail(
                "duplicate_cell_item_assignment",
                f"Item ID '{item_id}' is assigned to more than one role.",
            )
        assigned_item_ids.add(item_id)
        role_to_item[role_id] = item_id
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
                "quantity": role["quantity"],
                "resourceRole": _CELL_ROLE_TO_RESOURCE_ROLE[
                    role["cellRole"]
                ],
                "stage": role["stage"],
                "targetZoneRef": role["targetZoneRef"],
                **_basis(
                    raw,
                    field=field,
                    provenance=provenance,
                    subject_id=item_id,
                ),
            }
        )
    return selected, role_to_item


def _zones(
    template: Mapping[str, Any],
    raw_bindings: Any,
    *,
    role_to_item: Mapping[str, str],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    bindings = {
        identifier(raw.get("zoneRequestId"), "zoneBindings.zoneRequestId"): raw
        for raw in records(raw_bindings, "zoneBindings")
    }
    result = []
    seen: set[str] = set()
    for index, raw in enumerate(template["zones"]):
        field = f"template.zones[{index}]"
        zone_request_id = identifier(
            raw.get("zoneRequestId"),
            f"{field}.zoneRequestId",
        )
        if zone_request_id in seen:
            fail(
                "duplicate_cell_zone",
                f"Duplicate zone '{zone_request_id}'.",
            )
        seen.add(zone_request_id)
        zone_type = raw.get("zoneType")
        if zone_type not in _CELL_ZONE_TYPES:
            fail(
                "unsupported_cell_zone_type",
                f"{field}.zoneType is unsupported.",
            )
        role_ids = sorted(
            {
                identifier(value, f"{field}.memberRoleIds")
                for value in raw.get("memberRoleIds", [])
            }
        )
        unknown = sorted(set(role_ids) - set(role_to_item))
        if not role_ids or unknown:
            fail(
                "cell_zone_members_invalid",
                f"{field} must reference assigned template roles.",
                details={"unknownRoleIds": unknown},
            )
        binding = bindings.get(zone_request_id, {})
        basis_source = {**raw, **binding, "zoneRequestId": zone_request_id}
        zone = {
            "zoneRequestId": zone_request_id,
            "zoneType": zone_type,
            "label": text(raw.get("label"), f"{field}.label", maximum=120),
            "memberItemIds": sorted(
                role_to_item[role_id] for role_id in role_ids
            ),
            "paddingClass": raw.get("paddingClass", "standard"),
            "allowedAssetCategories": sorted(
                {
                    identifier(
                        value,
                        f"{field}.allowedAssetCategories",
                    )
                    for value in raw.get("allowedAssetCategories", [])
                }
            ),
            **_basis(
                basis_source,
                field=f"zoneBindings.{zone_request_id}",
                provenance=provenance,
                subject_id=zone_request_id,
            ),
        }
        if binding.get("existingZoneId") is not None:
            zone["existingZoneId"] = identifier(
                binding.get("existingZoneId"),
                f"zoneBindings.{zone_request_id}.existingZoneId",
            )
        result.append(zone)
    unknown_bindings = sorted(set(bindings) - seen)
    if unknown_bindings:
        fail(
            "cell_zone_binding_unknown",
            "Unknown zone bindings: " + ", ".join(unknown_bindings) + ".",
        )
    return sorted(result, key=lambda item: item["zoneRequestId"])


def _relationships(
    template: Mapping[str, Any],
    *,
    role_to_item: Mapping[str, str],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(template["relationships"]):
        field = f"template.relationships[{index}]"
        relationship_id = identifier(
            raw.get("relationshipId"),
            f"{field}.relationshipId",
        )
        source_role = identifier(
            raw.get("sourceRoleId"),
            f"{field}.sourceRoleId",
        )
        target_role = identifier(
            raw.get("targetRoleId"),
            f"{field}.targetRoleId",
        )
        if source_role not in role_to_item or target_role not in role_to_item:
            fail(
                "cell_relationship_role_unknown",
                f"{field} references an unassigned role.",
            )
        result.append(
            {
                "relationshipId": relationship_id,
                "relationshipType": identifier(
                    raw.get("relationshipType"),
                    f"{field}.relationshipType",
                ),
                "sourceRef": role_to_item[source_role],
                "targetRef": role_to_item[target_role],
                **_basis(
                    raw,
                    field=field,
                    provenance=provenance,
                    subject_id=relationship_id,
                ),
            }
        )
    return sorted(result, key=lambda item: item["relationshipId"])


def _endpoint(
    raw: Any,
    *,
    field: str,
    role_to_item: Mapping[str, str],
    zone_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    endpoint = mapping(raw, field)
    kind = endpoint.get("kind")
    if kind == "role_connector":
        role_id = identifier(endpoint.get("roleId"), f"{field}.roleId")
        if role_id not in role_to_item:
            fail(
                "cell_flow_role_unknown",
                f"{field} references an unassigned role.",
            )
        return {
            "kind": "planned_asset_connector",
            "itemId": role_to_item[role_id],
            "occurrenceIndex": positive_integer(
                endpoint.get("occurrenceIndex", 0),
                f"{field}.occurrenceIndex",
                minimum=0,
                maximum=499,
            ),
            "connectorId": identifier(
                endpoint.get("connectorId"),
                f"{field}.connectorId",
            ),
        }
    if kind == "zone_anchor":
        zone_request_id = identifier(
            endpoint.get("zoneRequestId"),
            f"{field}.zoneRequestId",
        )
        binding = zone_bindings.get(zone_request_id)
        if not binding or not binding.get("existingZoneId"):
            fail(
                "cell_flow_zone_anchor_unbound",
                f"{field} requires an existing revision-bound zone.",
            )
        return {
            "kind": "zone_anchor",
            "zoneId": identifier(
                binding["existingZoneId"],
                f"{field}.zoneId",
            ),
            "anchorId": identifier(
                endpoint.get("anchorId"),
                f"{field}.anchorId",
            ),
        }
    fail(
        "unsupported_cell_flow_endpoint",
        f"{field}.kind is unsupported.",
    )
    raise AssertionError("unreachable")


def _flows(
    template: Mapping[str, Any],
    *,
    role_to_item: Mapping[str, str],
    zone_bindings: Mapping[str, Mapping[str, Any]],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(template["flows"]):
        field = f"template.flows[{index}]"
        flow_id = identifier(raw.get("flowId"), f"{field}.flowId")
        flow_kind = raw.get("flowKind")
        if flow_kind not in _CELL_FLOW_KINDS:
            fail(
                "unsupported_cell_flow_kind",
                f"{field}.flowKind is unsupported.",
            )
        record = {
            "flowId": flow_id,
            "flowKind": flow_kind,
            "sourceEndpoint": _endpoint(
                raw.get("sourceEndpoint"),
                field=f"{field}.sourceEndpoint",
                role_to_item=role_to_item,
                zone_bindings=zone_bindings,
            ),
            "targetEndpoint": _endpoint(
                raw.get("targetEndpoint"),
                field=f"{field}.targetEndpoint",
                role_to_item=role_to_item,
                zone_bindings=zone_bindings,
            ),
            **_basis(
                raw,
                field=field,
                provenance=provenance,
                subject_id=flow_id,
            ),
        }
        if flow_kind == "utility":
            record["utilityKind"] = identifier(
                raw.get("utilityKind"),
                f"{field}.utilityKind",
            )
        if flow_kind == "forklift":
            record["vehicleProfileId"] = identifier(
                raw.get("vehicleProfileId"),
                f"{field}.vehicleProfileId",
            )
            record["vehicleProfileRevision"] = revision(
                raw.get("vehicleProfileRevision"),
                f"{field}.vehicleProfileRevision",
            )
        result.append(record)
    return sorted(result, key=lambda item: item["flowId"])


def _capabilities(
    template: Mapping[str, Any],
    *,
    role_to_item: Mapping[str, str],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(template["capabilityRequirements"]):
        field = f"template.capabilityRequirements[{index}]"
        requirement_id = identifier(
            raw.get("requirementId"),
            f"{field}.requirementId",
        )
        role_ids = sorted(
            {
                identifier(value, f"{field}.roleIds")
                for value in raw.get("roleIds", [])
            }
        )
        if not role_ids or not set(role_ids).issubset(role_to_item):
            fail(
                "cell_capability_roles_invalid",
                f"{field} must reference assigned roles.",
            )
        result.append(
            {
                "requirementId": requirement_id,
                "capabilityId": identifier(
                    raw.get("capabilityId"),
                    f"{field}.capabilityId",
                ),
                "quantity": positive_integer(
                    raw.get("quantity"),
                    f"{field}.quantity",
                ),
                "assignedItemIds": sorted(
                    role_to_item[role_id] for role_id in role_ids
                ),
                **_basis(
                    raw,
                    field=field,
                    provenance=provenance,
                    subject_id=requirement_id,
                ),
            }
        )
    return sorted(result, key=lambda item: item["requirementId"])


def _process_bindings(
    raw_values: Any,
    *,
    role_to_item: Mapping[str, str],
    flow_ids: set[str],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(
        records(raw_values, "processAssignments")
    ):
        field = f"processAssignments[{index}]"
        binding_id = identifier(
            raw.get("bindingIntentId"),
            f"{field}.bindingIntentId",
        )
        role_ids = sorted(
            {
                identifier(value, f"{field}.roleIds")
                for value in raw.get("roleIds", [])
            }
        )
        if not role_ids or not set(role_ids).issubset(role_to_item):
            fail(
                "cell_process_assignment_roles_invalid",
                f"{field} must reference assigned roles.",
            )
        referenced_flows = sorted(
            {
                identifier(value, f"{field}.flowIds")
                for value in raw.get("flowIds", [])
            }
        )
        if not set(referenced_flows).issubset(flow_ids):
            fail(
                "cell_process_assignment_flow_unknown",
                f"{field} references unknown flows.",
            )
        result.append(
            {
                "bindingIntentId": binding_id,
                "productId": identifier(
                    raw.get("productId"),
                    f"{field}.productId",
                ),
                "processMapId": identifier(
                    raw.get("processMapId"),
                    f"{field}.processMapId",
                ),
                "processMapRevision": revision(
                    raw.get("processMapRevision"),
                    f"{field}.processMapRevision",
                ),
                "processNodeIds": sorted(
                    {
                        identifier(value, f"{field}.processNodeIds")
                        for value in raw.get("processNodeIds", [])
                    }
                ),
                "processEdgeIds": sorted(
                    {
                        identifier(value, f"{field}.processEdgeIds")
                        for value in raw.get("processEdgeIds", [])
                    }
                ),
                "resourceItemIds": sorted(
                    role_to_item[role_id] for role_id in role_ids
                ),
                "flowIds": referenced_flows,
                "bindingRole": identifier(
                    raw.get("bindingRole", "resource"),
                    f"{field}.bindingRole",
                ),
                **_basis(
                    raw,
                    field=field,
                    provenance=provenance,
                    subject_id=binding_id,
                ),
            }
        )
    return sorted(result, key=lambda item: item["bindingIntentId"])


def compile_manufacturing_cell_package(
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one reusable manufacturing-cell template instantiation."""

    if not isinstance(spec, Mapping):
        fail(
            "invalid_manufacturing_cell_package",
            "Manufacturing-cell package must be an object.",
        )
    reject_raw_geometry(spec)
    normalized = detached(spec)
    if normalized.get("schemaVersion") != MANUFACTURING_CELL_PACKAGE_VERSION:
        fail(
            "unsupported_manufacturing_cell_package_version",
            "Manufacturing-cell package schemaVersion must equal 1.",
        )
    if normalized.get("packageType") != MANUFACTURING_CELL_PACKAGE_TYPE:
        fail(
            "invalid_manufacturing_cell_package_type",
            "packageType must equal manufacturing_cell.",
        )
    package_id = identifier(normalized.get("packageId"), "packageId")
    scope = normalize_scope(normalized.get("scope"))
    source_revisions = normalize_source_revisions(
        normalized.get("sourceRevisions")
    )
    provenance = normalize_provenance(normalized)
    template = _template(normalized.get("template"))
    selected_assets, role_to_item = _asset_assignments(
        template,
        normalized.get("assetAssignments", []),
        provenance=provenance,
    )
    requested_count = sum(item["quantity"] for item in selected_assets)
    if requested_count > MAXIMUM_WORKFLOW_ASSET_INSTANCES:
        fail(
            "cell_asset_limit_exceeded",
            "Cell package exceeds the 500-placement planner limit.",
        )
    zone_bindings = {
        identifier(raw.get("zoneRequestId"), "zoneBindings.zoneRequestId"): raw
        for raw in records(
            normalized.get("zoneBindings", []),
            "zoneBindings",
        )
    }
    zones = _zones(
        template,
        normalized.get("zoneBindings", []),
        role_to_item=role_to_item,
        provenance=provenance,
    )
    zone_index = {item["zoneRequestId"]: item for item in zones}
    planner_zones = [
        item
        for item in zones
        if item["zoneType"] in {"workcell", "staging", "inspection"}
    ]
    overlay_zones = [
        item
        for item in zones
        if item["zoneType"] in {"operator", "service", "safety", "utility"}
    ]
    for item in selected_assets:
        zone = zone_index.get(item["targetZoneRef"])
        if zone is None:
            fail(
                "cell_target_zone_unknown",
                (
                    f"Selected item '{item['itemId']}' references unknown "
                    f"zone '{item['targetZoneRef']}'."
                ),
            )
        if zone["zoneType"] not in {"workcell", "staging", "inspection"}:
            fail(
                "cell_asset_target_requires_containment_zone",
                (
                    f"Selected item '{item['itemId']}' targets operational "
                    f"overlay '{zone['zoneRequestId']}'. Assets must target "
                    "a workcell, staging, or inspection containment zone."
                ),
            )
        if zone.get("existingZoneId"):
            item["targetZoneId"] = zone["existingZoneId"]
    relationships = _relationships(
        template,
        role_to_item=role_to_item,
        provenance=provenance,
    )
    flows = _flows(
        template,
        role_to_item=role_to_item,
        zone_bindings=zone_bindings,
        provenance=provenance,
    )
    capabilities = _capabilities(
        template,
        role_to_item=role_to_item,
        provenance=provenance,
    )
    process_bindings = _process_bindings(
        normalized.get("processAssignments", []),
        role_to_item=role_to_item,
        flow_ids={item["flowId"] for item in flows},
        provenance=provenance,
    )
    strategies = normalize_strategies(
        normalized.get(
            "alternatives",
            ["flow_lanes", "balanced_grid"],
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
        for item in planner_zones
    ]
    overlay_unresolved = [
        {
            "unresolvedId": stable_workflow_id(
                "unresolved-p10-zone-",
                {
                    "packageId": package_id,
                    "zoneRequestId": item["zoneRequestId"],
                },
                length=18,
            ),
            "code": "operational_overlay_zone_pending",
            "message": (
                f"{item['label']} remains a revision-bound operational "
                "overlay until its domain-specific envelope is computed."
            ),
            "subjectRefs": [item["zoneRequestId"]],
        }
        for item in overlay_zones
    ]
    semantic_plan = {
        "schemaVersion": WORKFLOW_PACKAGE_SCHEMA_VERSION,
        "planId": stable_workflow_id(
            "plan-p10-cell-",
            {
                "packageId": package_id,
                "templateId": template["templateId"],
                "templateRevision": template["templateRevision"],
                "assignments": selected_assets,
            },
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
        "placementRelationships": relationships,
        "processBindings": process_bindings,
        "flows": flows,
        "evidence": deepcopy(provenance["evidence"]),
        "assumptions": deepcopy(provenance["assumptions"]),
        "unresolvedItems": [
            *deepcopy(provenance["unresolvedItems"]),
            *overlay_unresolved,
        ],
        "alternatives": semantic_alternatives(strategies),
        "layoutHints": {
            "density": density,
            "preserveManual": True,
            "preserveLocked": True,
            "primaryFlow": "process_sequence",
        },
        "workflowIntent": {
            "packageType": MANUFACTURING_CELL_PACKAGE_TYPE,
            "templateId": template["templateId"],
            "templateRevision": template["templateRevision"],
            "operationalZones": [
                {
                    "zoneRequestId": item["zoneRequestId"],
                    "zoneType": item["zoneType"],
                    "label": item["label"],
                    "memberItemIds": deepcopy(item["memberItemIds"]),
                    "paddingClass": item["paddingClass"],
                    "knowledgeStatus": item["knowledgeStatus"],
                    "evidenceIds": deepcopy(item["evidenceIds"]),
                    "assumptionIds": deepcopy(item["assumptionIds"]),
                }
                for item in overlay_zones
            ],
        },
    }
    manual_request = build_manual_planner_request(
        package_id=package_id,
        objective=semantic_plan["objective"],
        selected_assets=selected_assets,
        zones=planner_zones,
        flows=flows,
        strategies=strategies,
        density=density,
        source_revisions=source_revisions,
        process_bindings=process_bindings,
    )
    role_records = [
        {
            "roleId": role_id,
            "itemId": item_id,
            "cellRole": next(
                item["cellRole"]
                for item in template["roles"]
                if item["roleId"] == role_id
            ),
        }
        for role_id, item_id in sorted(role_to_item.items())
    ]
    utility_flows = [
        item for item in flows if item["flowKind"] == "utility"
    ]
    material_flows = [
        item
        for item in flows
        if item["flowKind"] in {"material", "conveyor", "forklift"}
    ]
    estimates = {
        "resourceSummary": {
            "requestedPlacementCount": requested_count,
            "countsByCellRole": {
                role: sum(
                    next(
                        item["quantity"]
                        for item in selected_assets
                        if item["itemId"] == role_record["itemId"]
                    )
                    for role_record in role_records
                    if role_record["cellRole"] == role
                )
                for role in sorted(
                    {item["cellRole"] for item in role_records}
                )
            },
            "sourceRevisions": deepcopy(source_revisions),
        },
        "processCoverage": {
            "assignmentCount": len(process_bindings),
            "operationNodeCount": len(
                {
                    node_id
                    for item in process_bindings
                    for node_id in item["processNodeIds"]
                }
            ),
            "basis": [
                {
                    "bindingIntentId": item["bindingIntentId"],
                    "knowledgeStatus": item["knowledgeStatus"],
                    "evidenceIds": item["evidenceIds"],
                    "assumptionIds": item["assumptionIds"],
                    "processMapRevision": item["processMapRevision"],
                }
                for item in process_bindings
            ],
        },
        "flowSummary": {
            "materialInputOutputRouteCount": len(material_flows),
            "utilityRequirementCount": len(utility_flows),
            "routes": [
                {
                    "flowId": item["flowId"],
                    "flowKind": item["flowKind"],
                    "knowledgeStatus": item["knowledgeStatus"],
                    "evidenceIds": item["evidenceIds"],
                    "assumptionIds": item["assumptionIds"],
                }
                for item in flows
            ],
            "sourceRevisions": {
                "layout": source_revisions["layout"],
                "shell": source_revisions["shell"],
                "policy": source_revisions["policy"],
            },
        },
    }
    deferred = [
        {
            "id": item["flowId"],
            "code": (
                "utility_topology_pending_engineering"
                if item["flowKind"] == "utility"
                else "non_forklift_route_pending_domain_router"
            ),
            "message": (
                "The semantic requirement is retained, but deterministic "
                "topology is deferred to the applicable domain router."
            ),
        }
        for item in flows
        if item["flowKind"] != "forklift"
    ]
    deferred.extend(
        {
            "id": item["bindingIntentId"],
            "code": "process_binding_pending_placement_ids",
            "message": (
                "The revision-bound assignment is applied only after preview "
                "creates stable placement IDs."
            ),
        }
        for item in process_bindings
    )
    deferred.extend(
        {
            "id": item["zoneRequestId"],
            "code": "operational_overlay_zone_pending",
            "message": (
                "Operator, maintenance, safety, and utility overlays require "
                "their domain envelope; P8 containment sizing is not used."
            ),
        }
        for item in overlay_zones
    )
    domain_model = {
        "manufacturingCell": {
            "templateId": template["templateId"],
            "templateRevision": template["templateRevision"],
            "templateFingerprint": workflow_fingerprint(template),
            "roles": role_records,
            "operatorZoneIds": sorted(
                item["zoneRequestId"]
                for item in zones
                if item["zoneType"] == "operator"
            ),
            "maintenanceZoneIds": sorted(
                item["zoneRequestId"]
                for item in zones
                if item["zoneType"] == "service"
            ),
            "safetyZoneIds": sorted(
                item["zoneRequestId"]
                for item in zones
                if item["zoneType"] == "safety"
            ),
            "materialFlowIds": sorted(
                item["flowId"] for item in material_flows
            ),
            "utilityFlowIds": sorted(
                item["flowId"] for item in utility_flows
            ),
            "processBindingIntentIds": sorted(
                item["bindingIntentId"] for item in process_bindings
            ),
        },
        "reusableTemplate": deepcopy(template),
    }
    return base_compilation(
        package_type=MANUFACTURING_CELL_PACKAGE_TYPE,
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
    "MANUFACTURING_CELL_PACKAGE_TYPE",
    "MANUFACTURING_CELL_PACKAGE_VERSION",
    "MANUFACTURING_CELL_TEMPLATE_VERSION",
    "cell_template_revision",
    "compile_manufacturing_cell_package",
]
