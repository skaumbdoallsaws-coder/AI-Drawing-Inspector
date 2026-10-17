"""Exact operation previews and receipt-bound undo using the existing transaction kernel."""
from copy import deepcopy
import hashlib
import json

from .authorization import require_facility_action
from .diff import build_exact_layout_diff, facility_layout_diff_hash
from .errors import FacilityConflictError, FacilityValidationError
from .operations import apply_facility_layout_operations
from .transaction_adapter import deterministic_facility_proposal_id, facility_layout_binding


PROPOSAL_TYPE = "exact-operations-v1"
UNDO_TYPE = "exact-undo-v1"
# Whole-layout clearing/archiving and raw navigation writer authority stay denied.
# Navigation requires its separate coordinate-free Sage semantic contract.
ALLOWED_OPERATIONS = frozenset({
    "rename_layout", "add_zone", "edit_zone", "delete_zone", "place_asset", "move_placement",
    "rotate_placement", "set_appearance", "set_component_materials", "replace_asset",
    "duplicate_placement", "delete_placement", "set_position_mode", "set_snap_relationship",
    "add_floor_marking", "add_floor_path", "edit_floor_marking", "delete_floor_marking", "set_interior_walls", "set_floor_surfaces",
    "set_decals", "set_perimeter_walls", "set_ground", "set_plan_settings", "add_aisle", "edit_aisle",
    "add_route", "edit_route", "delete_route", "add_utility_network", "edit_utility_network", "delete_utility_network",
    "add_utility_network_node", "edit_utility_network_node", "delete_utility_network_node",
    "add_utility_network_segment", "edit_utility_network_segment", "delete_utility_network_segment",
    "attach_process_binding", "edit_process_binding", "detach_process_binding",
    "upsert_floor_surface", "delete_floor_surface", "upsert_interior_wall", "delete_interior_wall",
    "upsert_decal", "delete_decal", "edit_perimeter_walls", "upsert_wall_artwork", "delete_wall_artwork",
})


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def guard_operations(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 50:
        raise FacilityValidationError("operation_proposal_invalid", "Propose between 1 and 50 operations.")
    if len(json.dumps(operations, allow_nan=False).encode()) > 24000:
        raise FacilityValidationError("operation_proposal_too_large", "Split the proposal into smaller batches.")
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in ALLOWED_OPERATIONS:
            raise FacilityValidationError("operation_proposal_denied", "This operation is not authorized for assisted editing.")


def prepare_undo(service, principal, site_id, layout_id, base_revision, receipt_id):
    current = service.get_layout(principal, site_id, layout_id)
    receipt = service.get_layout_receipt(principal, site_id, layout_id, receipt_id)
    if current["revision"] != base_revision or receipt["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "Undo is available only while the approved result is still current.")
    target = service.get_layout_revision(principal, site_id, layout_id, receipt["binding"]["baseRevision"])["layout"]
    target = deepcopy(target)
    for key in ("createdAt", "updatedAt"):
        target[key] = current["layout"][key]
    prepared = apply_facility_layout_operations(target, [], base_revision=base_revision)
    # Untouched historical placements keep their pinned revisions; restored or
    # changed placements must still match current catalog authority.
    current_placements = {item["placementId"]: item for item in current["layout"]["placements"]}
    restored_placements = [item for item in prepared["document"]["placements"]
        if current_placements.get(item["placementId"]) != item]
    service._validate_current_proposal_asset_revisions(principal, site_id, {"assetSet": [
        {"assetId": item["assetId"], "assetDefinitionRevision": item["assetDefinitionRevision"]}
        for item in restored_placements]})
    dependencies = service.validate_dependencies(principal, site_id, target)
    spatial = service._diagnose_spatial(principal, site_id, target)
    # Restore historical geometry exactly, but revalidate derived route bindings
    # against that geometry instead of restoring an obsolete layout fingerprint.
    target, routing, rebound_ids = service._revalidate_route_layout_sources(
        principal, site_id, target, inherited_routes=target["routes"])
    service._require_no_new_spatial_errors(
        service._diagnose_spatial(principal, site_id, current["layout"]), spatial,
        operations=[], baseline_layout=current["layout"])
    service._require_no_new_routing_errors(service._diagnose_routing(principal, site_id, current["layout"]), routing)
    operations = [{"op": "restore_approved_revision", "receiptId": receipt_id}]
    diff = build_exact_layout_diff(current["layout"], target)
    prepared.update(document=target, affectedIds=rebound_ids,
        changed=bool(diff["changed"]), canonicalDiff=diff,
        diffHash=facility_layout_diff_hash(layout_id=layout_id, base_revision=base_revision,
            operations=operations, after=target, canonical_diff=diff),
        spatialDiagnostics=spatial, routingDiagnostics=routing)
    return prepared, dependencies, operations


def prepare(service, principal, site_id, layout_id, base_revision, request, *, undo=False, edit_mode="preview"):
    component_proofs = []
    design_review = None
    workstation_review = None
    if undo:
        prepared, dependencies, operations = prepare_undo(
            service, principal, site_id, layout_id, base_revision, request["receiptId"])
    else:
        operations = deepcopy(request["operations"])
        guard_operations(operations)
        from .proposal_artifacts import validate_proposal_artwork
        current = service.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision:
            raise FacilityConflictError("revision_conflict", "The layout changed before validating the proposal.")
        validate_proposal_artwork(service, principal, site_id, current["layout"], operations)
        from .proposal_components import validate_proposal_components
        component_proofs = validate_proposal_components(
            service, principal, site_id, layout_id, base_revision, operations)
        prepared, dependencies = service._prepare_operations(
            principal, site_id, layout_id, base_revision, operations, required_action=None)
        affected = set(prepared["affectedIds"]) | set(prepared["createdIds"])
        service._validate_current_proposal_asset_revisions(principal, site_id, {"assetSet": [
            {"assetId": placement["assetId"], "assetDefinitionRevision": placement["assetDefinitionRevision"]}
            for placement in prepared["document"]["placements"] if placement["placementId"] in affected]})
        from .parking_review import review_changed_parking
        design_review = review_changed_parking(current["layout"], prepared["document"])
        from .workstation_review import review_changed_workstations
        workstation_review = review_changed_workstations(service, principal, site_id, current["layout"], prepared["document"])
    dependency_hash = fingerprint({"schemaVersion": 1, "dependencies": dependencies.to_dict(),
        "spatialEngineVersion": prepared["spatialDiagnostics"].get("spatialEngineVersion"),
        "routingEngineVersion": prepared["routingDiagnostics"].get("routingEngineVersion"),
        **({"componentVisuals": component_proofs} if component_proofs else {})})
    binding = facility_layout_binding(tenant_id=principal.tenant_id, site_id=site_id, layout_id=layout_id,
        base_revision=base_revision, diff_hash=prepared["diffHash"], dependency_fingerprint=dependency_hash)
    alternative = {"alternativeId": "exact-" + fingerprint(request)[:24],
        "strategy": UNDO_TYPE if undo else PROPOSAL_TYPE, "operations": operations,
        "metrics": {"operationCount": len(operations), "affectedCount": len(prepared["affectedIds"])},
        "operationReceipt": deepcopy(prepared), "ghostPreview": {"layout": deepcopy(prepared["document"])},
        "transactionBinding": binding.to_dict(), "validation": {
            "noNewErrors": True, "spatial": service._diagnostic_receipt_summary(prepared["spatialDiagnostics"]),
            "routing": service._diagnostic_receipt_summary(prepared["routingDiagnostics"]),
            **({"workstationReview": workstation_review} if workstation_review is not None else {}),
            **({"functionalDesign": design_review} if design_review is not None else {})}}
    from .direct_edit_policy import evaluate
    alternative["editMode"] = edit_mode
    alternative["directApplyPolicy"] = evaluate(operations, prepared, undo=undo)
    if design_review is not None:
        alternative["directApplyPolicy"].update(eligible=False,
            reason="Review the parking access and circulation findings before applying.")
    return alternative, binding, prepared, dependencies


def create(service, principal, site_id, layout_id, base_revision, *, operations=None, undo_receipt_id=None, edit_mode="preview"):
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="proposal.create")
    service._require_capability("agent_preview")
    if edit_mode not in {"direct", "preview"}:
        raise FacilityValidationError("invalid_edit_mode", "Choose direct or preview editing.")
    undo = undo_receipt_id is not None
    request = {"receiptId": undo_receipt_id} if undo else {"operations": deepcopy(operations)}
    alternative, binding, prepared, _ = prepare(service, principal, site_id, layout_id, base_revision, request,
        undo=undo, edit_mode=edit_mode)
    if not prepared["changed"]:
        raise FacilityValidationError("operation_proposal_no_change", "The proposal makes no change to the saved layout.")
    # A preview is never permission to commit, even when another writer races it.
    if service.get_layout(principal, site_id, layout_id)["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The layout changed while validating the proposal.")
    proposal_type = UNDO_TYPE if undo else PROPOSAL_TYPE
    proposal_id = deterministic_facility_proposal_id(layout_id=layout_id, base_revision=base_revision,
        proposal_type=proposal_type, semantic_plan_hash=fingerprint({"request": request, "editMode": edit_mode}),
        dependency_fingerprint=binding.dependency_fingerprint)
    proposal = service.transaction_runtime.propose(tenant_id=principal.tenant_id, principal_id=principal.principal_id,
        proposal_id=proposal_id, binding=binding, payload={"tenantId": principal.tenant_id,
            "siteId": site_id, "layoutId": layout_id, "baseRevision": base_revision,
            "proposalType": proposal_type, "request": request, "editMode": edit_mode},
        public_summary={**alternative["metrics"], "directApplyPolicy": alternative["directApplyPolicy"]})
    alternative.update(proposalId=proposal.proposal_id, createdAt=proposal.created_at, expiresAt=proposal.expires_at)
    return {"proposalId": proposal.proposal_id, "baseRevision": base_revision, "layoutRevision": base_revision,
        "selectedProposalId": proposal.proposal_id, "alternatives": [deepcopy(alternative)],
        "createdAt": proposal.created_at, "expiresAt": proposal.expires_at,
        "previewPure": True, "approvalRequired": True, "alternative": alternative}


def regenerate(service, principal, site_id, layout_id, payload):
    service._require_capability("agent_preview")
    return prepare(service, principal, site_id, layout_id, payload["baseRevision"], payload["request"],
        undo=payload["proposalType"] == UNDO_TYPE, edit_mode=payload.get("editMode", "preview"))
