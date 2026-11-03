"""Exact operation previews and receipt-bound undo using the existing transaction kernel."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import pickle
import threading
import time
import weakref

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
    "rotate_placement", "set_appearance", "set_component_materials", "set_scene", "replace_asset",
    "duplicate_placement", "delete_placement", "set_position_mode", "set_snap_relationship",
    "add_floor_marking", "add_floor_path", "edit_floor_marking", "delete_floor_marking", "set_interior_walls", "set_floor_surfaces",
    "set_decals", "set_perimeter_walls", "set_ground", "set_plan_settings", "add_aisle", "edit_aisle",
    "add_route", "edit_route", "delete_route", "add_utility_network", "edit_utility_network", "delete_utility_network",
    "add_utility_network_node", "edit_utility_network_node", "delete_utility_network_node",
    "add_utility_network_segment", "edit_utility_network_segment", "delete_utility_network_segment",
    "attach_process_binding", "edit_process_binding", "detach_process_binding",
    "upsert_floor_surface", "delete_floor_surface", "place_asset_array", "delete_asset_array", "upsert_interior_wall", "delete_interior_wall",
    "upsert_decal", "delete_decal", "edit_perimeter_walls", "upsert_wall_artwork", "delete_wall_artwork",
    "set_site_context", "set_building_pose", "upsert_site_area", "delete_site_area",
    "upsert_site_reference", "delete_site_reference", "set_emergency_plan", "set_zone_ceiling",
    "set_zone_roof",
})
# A package from the server's planner (a cell plan or its clear) may also remove the saved walks its own deletions
# strand; the kernel allows nothing else (operations.py, delete_stranded_movements). Model-written batches may not.
PLANNED_ONLY_OPERATIONS = frozenset({"delete_stranded_movements"})


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def guard_operations(operations, max_operations=50, max_bytes=24000, planned=False):
    """Model-written batches stay small; a design package built by the server's planner may be larger."""
    allowed = ALLOWED_OPERATIONS | PLANNED_ONLY_OPERATIONS if planned else ALLOWED_OPERATIONS
    if not isinstance(operations, list) or not 1 <= len(operations) <= max_operations:
        raise FacilityValidationError("operation_proposal_invalid", f"Propose between 1 and {max_operations} operations.")
    if len(json.dumps(operations, allow_nan=False).encode()) > max_bytes:
        raise FacilityValidationError("operation_proposal_too_large", "Split the proposal into smaller batches.")
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in allowed:
            raise FacilityValidationError("operation_proposal_denied", "This operation is not authorized for assisted editing.")


def prepare_undo(service, principal, site_id, layout_id, base_revision, receipt_id, baseline_out=None):
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
    baseline_spatial = service._diagnose_spatial(principal, site_id, current["layout"])
    service._require_no_new_spatial_errors(baseline_spatial, spatial, operations=[], baseline_layout=current["layout"])
    baseline_routing = service._diagnose_routing(principal, site_id, current["layout"])
    service._require_no_new_routing_errors(baseline_routing, routing)
    if baseline_out is not None:
        baseline_out.update(spatial=baseline_spatial, routing=baseline_routing)
    operations = [{"op": "restore_approved_revision", "receiptId": receipt_id}]
    diff = build_exact_layout_diff(current["layout"], target)
    prepared.update(document=target, affectedIds=rebound_ids,
        changed=bool(diff["changed"]), canonicalDiff=diff,
        diffHash=facility_layout_diff_hash(layout_id=layout_id, base_revision=base_revision,
            operations=operations, after=target, canonical_diff=diff),
        spatialDiagnostics=spatial, routingDiagnostics=routing)
    return prepared, dependencies, operations


def _introduced_problems(service, baseline, prepared):
    """What the change adds to the checks: the proposed layout's findings that the saved layout (BASELINE) did not
    have, by the no-new-errors rule's keys (code and subjects) plus the severity, counted as validation.spatial and
    validation.routing count the whole layout. The review card's "Checks:" line reads these, so a problem the layout
    already had is not shown as the change's own result. None when the saved layout's diagnostics are missing."""
    if not isinstance(baseline.get("spatial"), dict) or not isinstance(baseline.get("routing"), dict):
        return None

    def new(diagnostics, before, key):
        known = {(item.get("severity"),) + key(item) for item in before.get("findings", []) if isinstance(item, dict)}
        return [item for item in diagnostics.get("findings", [])
                if isinstance(item, dict) and (item.get("severity"),) + key(item) not in known]
    spatial = new(prepared["spatialDiagnostics"], baseline["spatial"], service._spatial_error_key)
    routing = new(prepared["routingDiagnostics"], baseline["routing"], service._routing_error_key)
    routes = {route.get("routeId") for route in prepared["document"].get("routes", [])}
    return {
        "spatial": {
            "errorCount": sum(item.get("severity") == "error" for item in spatial),
            "warningCount": sum(item.get("severity") == "warning" for item in spatial),
            "placementCollisions": sum(item.get("code") == "placement_collision" for item in spatial),
            "shellObstacleCollisions": sum(item.get("code") == "shell_obstacle_collision" for item in spatial),
            "clearanceConflicts": sum(str(item.get("code") or "").endswith("_clearance_violation")
                                      or item.get("code") in {"door_swing_obstructed", "egress_obstructed"}
                                      for item in spatial),
            # Aisles with an obstruction the saved layout did not have (one already blocked counts again).
            "obstructedAisleCount": len({subject for item in spatial
                                         if item.get("code") in {"aisle_obstructed", "aisle_shell_obstructed"}
                                         for subject in item.get("subjectRefs") or [] if subject in routes}),
        },
        "routing": {
            "errorCount": sum(item.get("severity") == "error" for item in routing),
            "blockedCount": sum(item.get("severity") == "blocked" for item in routing),
        },
    }


def _review_changed_aisle_reach(prepared, affected):
    """Name changed aisles that stop at the edge of a department they are bound to.

    Routing findings reach the proposal only as a count, so without this the
    agent staging the edit never learns which aisle falls short.
    """
    labels = {route.get("routeId"): route.get("label") for route in prepared["document"].get("routes", [])}
    aisles = []
    for finding in prepared["routingDiagnostics"].get("findings", []):
        subjects = set(finding.get("subjects") or [])
        if finding.get("code") != "aisle_zone_not_entered" or not subjects & affected:
            continue
        details = finding.get("details") or {}
        route_id = next((item for item in sorted(subjects) if item in labels), None)
        aisles.append({"routeId": route_id, "label": labels.get(route_id),
            "bindingRole": details.get("bindingRole"), "zoneId": details.get("zoneId"),
            "zoneLabel": details.get("zoneLabel")})
    if not aisles:
        return None
    return {"status": "aisles_stop_short", "aisles": aisles, "message": (
        "These aisles stop at or run along the edge of a department they are bound to "
        "without extending into it, so they do not reach its equipment, storage or doors. "
        "Extend each aisle into the department or bind it to the departments it enters.")}


AISLE_OBSTRUCTION_REVIEW_LIMIT = 25


def _review_changed_aisle_obstructions(prepared, affected):
    """Name equipment that a changed aisle runs through, or that is placed in an aisle.

    Spatial findings reach the proposal only as a count, and an obstructed aisle
    is a warning rather than an error, so a staged edit could otherwise put a
    machine in a forklift lane while reporting no new errors.
    """
    document = prepared["document"]
    routes = {route.get("routeId"): route for route in document.get("routes", [])}
    placements = {item.get("placementId"): item for item in document.get("placements", [])}
    obstructions = []
    for finding in prepared["spatialDiagnostics"].get("findings", []):
        subjects = set(finding.get("subjectRefs") or [])
        if finding.get("code") != "aisle_obstructed" or not subjects & affected:
            continue
        route_id = next((item for item in sorted(subjects) if item in routes), None)
        placement_id = next((item for item in sorted(subjects) if item in placements), None)
        aisle = ((routes.get(route_id) or {}).get("extensions") or {}).get("facilityAisle") or {}
        obstructions.append({"routeId": route_id, "aisleLabel": (routes.get(route_id) or {}).get("label"),
            "aisleKind": aisle.get("aisleKind"), "placementId": placement_id,
            "assetId": (placements.get(placement_id) or {}).get("assetId")})
    if not obstructions:
        return None
    return {"status": "aisles_obstructed", "count": len(obstructions),
        "obstructions": obstructions[:AISLE_OBSTRUCTION_REVIEW_LIMIT], "message": (
        "This equipment sits inside an aisle corridor, so forklifts or people cannot pass. "
        "Move the equipment out of the aisle, or reroute the aisle around it.")}


# Notes a planner cannot settle stay in the review text but do not hold back a build-step package.
VERIFICATION_NOTES = frozenset({"parking_maneuvering_unverified"})


def _finding_key(finding):
    return (finding.get("code"), finding.get("areaId"), finding.get("edgeIndex"), finding.get("otherAreaId"))


def _design_findings(review):
    return [finding for item in (review or {}).get("reviews") or [] for finding in item.get("findings") or []]


def _cleared_pole_lights(service, principal, site_id, before, prepared, zones):
    """New pole lights in ZONES (the parking zones a change touches) standing on spots the light helper clears (3c):
    the server's own check of each spot, by the helper's rules, on the layout as proposed
    (light_positions.cleared_pole_spots). {placementId: where}."""
    from shapely.geometry import Point, Polygon
    areas = [Polygon([(p["x"], p["z"]) for p in zone["boundary"]]) for zone in zones
             if len(zone.get("boundary") or []) >= 3]
    old = {placement["placementId"] for placement in before.get("placements", [])}
    new = [placement["placementId"] for placement in prepared["document"].get("placements", [])
           if placement["placementId"] not in old and any(area.covers(Point(
               placement["transform"]["position"]["x"], placement["transform"]["position"]["z"])) for area in areas)]
    if not new:
        return {}
    from .light_positions import cleared_pole_spots
    definitions = service._spatial_context(principal, site_id, prepared["document"]).asset_definitions
    catalog = {key: {"assetId": key[0], "assetDefinitionRevision": key[1], "definition": document}
               for key, document in definitions.items()}
    return cleared_pole_spots(prepared["document"], catalog, new)


# A prepared proposal is kept for its next look (2026-11-02). After a Sage turn stages a batch, the app opens its
# review, or in Apply directly fetches it, approves it and applies it; the preview and the apply each rebuilt the whole
# proposal again, about 30 s each on Factory 02. The rebuild depends only on the saved layout (its revision is the hash
# of its bytes), the request, and the revisions the result references, so a prepared result is reused while the layout
# is still at its base revision and recheck() still passes for it: the artwork, the component visuals, the catalog's
# current revision for each changed or restored item, and the shell, policy, asset, vehicle and process-map revisions,
# giving the same dependency fingerprint. Anything else rebuilds it, and the rebuild reports what changed.
MEMO_LIMIT = 3  # proposals kept per service, pickled (a few MB each on Factory 02)
MEMO_SECONDS = 1800


class _PreparedMemo:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None or time.monotonic() - entry[0] > MEMO_SECONDS:
                self.entries.pop(key, None)
                return None
            self.entries.move_to_end(key)
            return entry[1]

    def put(self, key, blob):
        with self.lock:
            self.entries[key] = (time.monotonic(), blob)
            self.entries.move_to_end(key)
            while len(self.entries) > MEMO_LIMIT:
                self.entries.popitem(last=False)

    def drop(self, key):
        with self.lock:
            self.entries.pop(key, None)


_MEMOS = weakref.WeakKeyDictionary()
_MEMOS_LOCK = threading.Lock()


def _memo(service):
    with _MEMOS_LOCK:
        try:
            memo = _MEMOS.get(service)
            if memo is None:
                memo = _MEMOS[service] = _PreparedMemo()
        except TypeError:  # a service that cannot be weakly referenced keeps nothing
            return None
        return memo


def _memo_key(principal, site_id, layout_id, base_revision, request, undo, edit_mode, limits, planned):
    try:
        return fingerprint({"tenant": principal.tenant_id, "principal": principal.principal_id,
            "roles": sorted(principal.roles), "sites": sorted(principal.allowed_site_ids), "site": site_id,
            "layout": layout_id, "base": base_revision, "request": request, "undo": bool(undo), "editMode": edit_mode,
            "limits": list(limits) if limits else None, "planned": bool(planned)})
    except (AttributeError, TypeError, ValueError):
        return None  # prepare itself says what is wrong with the request


def _dependency_hash(dependencies, prepared, component_proofs):
    return fingerprint({"schemaVersion": 1, "dependencies": dependencies.to_dict(),
        "spatialEngineVersion": prepared["spatialDiagnostics"].get("spatialEngineVersion"),
        "routingEngineVersion": prepared["routingDiagnostics"].get("routingEngineVersion"),
        **({"componentVisuals": component_proofs} if component_proofs else {})})


def recheck(service, principal, site_id, layout_id, base_revision, operations, prepared, *, undo=False):
    """A prepared result checked again: the layout is still at its base revision, and what can change outside its
    bytes still passes. Raises as prepare would; returns the dependency fingerprint to compare with the binding."""
    current = service.get_layout(principal, site_id, layout_id)
    if current["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "Facility Layout revision conflict.",
                                    details={"currentRevision": current["revision"]})
    document = prepared["document"]
    component_proofs = []
    if undo:
        saved = {item["placementId"]: item for item in current["layout"]["placements"]}
        checked = [item for item in document["placements"] if saved.get(item["placementId"]) != item]
    else:
        from .proposal_artifacts import validate_proposal_artwork
        from .proposal_components import validate_proposal_components
        validate_proposal_artwork(service, principal, site_id, current["layout"], operations)
        component_proofs = validate_proposal_components(
            service, principal, site_id, layout_id, base_revision, operations)
        affected = set(prepared["affectedIds"]) | set(prepared["createdIds"])
        checked = [item for item in document["placements"] if item["placementId"] in affected]
    service._validate_current_proposal_asset_revisions(principal, site_id, {"assetSet": [
        {"assetId": item["assetId"], "assetDefinitionRevision": item["assetDefinitionRevision"]} for item in checked]})
    dependencies = service.validate_dependencies(principal, site_id, document)
    return _dependency_hash(dependencies, prepared, component_proofs)


def prepare(service, principal, site_id, layout_id, base_revision, request, *, undo=False, edit_mode="preview",
            limits=None, planned=False):
    key = _memo_key(principal, site_id, layout_id, base_revision, request, undo, edit_mode, limits, planned)
    memo = _memo(service) if key else None
    blob = memo.get(key) if memo else None
    if blob is not None:
        kept = pickle.loads(blob)  # a fresh copy for this caller
        alternative, binding, prepared, _ = kept
        try:
            if recheck(service, principal, site_id, layout_id, base_revision, alternative["operations"], prepared,
                       undo=undo) == binding.dependency_fingerprint:
                return kept
        except Exception:  # noqa: BLE001 - the rebuild below raises the real reason
            pass
        memo.drop(key)
    result = _prepare(service, principal, site_id, layout_id, base_revision, request, undo=undo,
                      edit_mode=edit_mode, limits=limits, planned=planned)
    if memo:
        try:
            memo.put(key, pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL))
        except (pickle.PicklingError, TypeError, AttributeError):
            pass  # not kept: the next look rebuilds it
    return result


def _prepare(service, principal, site_id, layout_id, base_revision, request, *, undo=False, edit_mode="preview",
             limits=None, planned=False):
    component_proofs = []
    design_review = None
    cleared_lights = {}
    workstation_review = None
    aisle_review = None
    obstruction_review = None
    site_review = None
    baseline = {}
    if undo:
        prepared, dependencies, operations = prepare_undo(
            service, principal, site_id, layout_id, base_revision, request["receiptId"], baseline_out=baseline)
    else:
        operations = deepcopy(request["operations"])
        guard_operations(operations, *(limits or ()), planned=planned)
        from .proposal_artifacts import validate_proposal_artwork
        current = service.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision:
            raise FacilityConflictError("revision_conflict", "The layout changed before validating the proposal.")
        from .site_context import KEY, normalize_site_context
        for operation in operations:
            if operation.get('op') != 'set_site_context':
                continue
            raw = current['layout'].get('extensions',{}).get(KEY)
            if not raw or operation.get('siteContext') is None:
                raise FacilityValidationError('site_location_manual_only','Place or remove the site through the manual Site tab.')
            # Sage cannot carry reference overlays, check results or roads through its schema; keep the stored ones.
            proposed = dict(operation['siteContext']) if isinstance(operation['siteContext'], dict) else operation['siteContext']
            if isinstance(proposed, dict):
                for key in ('overlays','layerChecks','roads','references'):
                    if key in raw and key not in proposed:
                        proposed[key] = raw[key]
                operation['siteContext'] = proposed
            try:
                before = normalize_site_context(raw,current['layout'])
                after = normalize_site_context(operation['siteContext'],current['layout'])
            except ValueError as exc:
                raise FacilityValidationError('invalid_site_context',str(exc)) from exc
            if any(before.get(key) != after.get(key) for key in ('georeference','imagery','overlays','layerChecks','roads')):
                raise FacilityValidationError('site_location_manual_only','Keep the existing georeference, imagery, roads and reference layers. Location and layer changes use the manual Site tab.')
        validate_proposal_artwork(service, principal, site_id, current["layout"], operations)
        from .proposal_components import validate_proposal_components
        component_proofs = validate_proposal_components(
            service, principal, site_id, layout_id, base_revision, operations)
        prepared, dependencies = service._prepare_operations(
            principal, site_id, layout_id, base_revision, operations, required_action=None, baseline_out=baseline)
        affected = set(prepared["affectedIds"]) | set(prepared["createdIds"])
        service._validate_current_proposal_asset_revisions(principal, site_id, {"assetSet": [
            {"assetId": placement["assetId"], "assetDefinitionRevision": placement["assetDefinitionRevision"]}
            for placement in prepared["document"]["placements"] if placement["placementId"] in affected]})
        from .parking_review import review_changed_parking

        def excuse(zones):
            # A new pole light on a spot the light helper clears is not a parking change to review (3c).
            cleared_lights.update(_cleared_pole_lights(service, principal, site_id, current["layout"], prepared, zones))
            return set(cleared_lights)
        design_review = review_changed_parking(current["layout"], prepared["document"], excuse)
        from .workstation_review import review_changed_workstations
        workstation_review = review_changed_workstations(service, principal, site_id, current["layout"], prepared["document"])
        aisle_review = _review_changed_aisle_reach(prepared, affected)
        obstruction_review = _review_changed_aisle_obstructions(prepared, affected)
        if any(op['op'] in {'set_site_context','set_building_pose','upsert_site_area','delete_site_area',
                            'upsert_site_reference','delete_site_reference','set_plan_settings'} for op in operations):
            from .site_context import analyze_site_context
            site_review = analyze_site_context(prepared['document'])
            # What this batch adds: a finding the saved layout already has (a placeholder building off the lot,
            # say) is not this batch's doing.
            try:
                saved_findings = analyze_site_context(current['layout'])['findings'] if (
                    current['layout'].get('extensions') or {}).get(KEY) else []
            except (ValueError, KeyError):
                saved_findings = []
            known = {_finding_key(f) for f in saved_findings}
            site_review['newFindingCount'] = sum(1 for f in site_review['findings'] if _finding_key(f) not in known)
            site_review['newWarnings'] = [f['code'] for f in site_review['findings']
                                          if f.get('severity') != 'info' and _finding_key(f) not in known][:40]
            site_review['findingCount'] = len(site_review['findings'])
            site_review['findingsTruncated'] = len(site_review['findings']) > 40
            site_review['findings'] = site_review['findings'][:40]
    dependency_hash = _dependency_hash(dependencies, prepared, component_proofs)
    binding = facility_layout_binding(tenant_id=principal.tenant_id, site_id=site_id, layout_id=layout_id,
        base_revision=base_revision, diff_hash=prepared["diffHash"], dependency_fingerprint=dependency_hash)
    introduced = _introduced_problems(service, baseline, prepared)
    alternative = {"alternativeId": "exact-" + fingerprint(request)[:24],
        "strategy": UNDO_TYPE if undo else PROPOSAL_TYPE, "operations": operations,
        "metrics": {"operationCount": len(operations), "affectedCount": len(prepared["affectedIds"])},
        "operationReceipt": deepcopy(prepared), "ghostPreview": {"layout": deepcopy(prepared["document"])},
        "transactionBinding": binding.to_dict(), "validation": {
            "noNewErrors": True,
            # What the change adds; spatial and routing below are the whole layout.
            **({"introduced": introduced} if introduced is not None else {}),
            **({"siteContext": site_review} if site_review is not None else {}),
            # Early in the payload: agents may see only the start of a large result.
            **({"aisleObstructions": obstruction_review} if obstruction_review is not None else {}),
            **({"aisleReach": aisle_review} if aisle_review is not None else {}),
            "spatial": service._diagnostic_receipt_summary(prepared["spatialDiagnostics"]),
            "routing": service._diagnostic_receipt_summary(prepared["routingDiagnostics"]),
            **({"workstationReview": workstation_review} if workstation_review is not None else {}),
            **({"functionalDesign": design_review} if design_review is not None else {}),
            **({"clearedLightSpots": [{"placementId": placement_id, "where": where} for placement_id, where
                                      in sorted(cleared_lights.items())]} if cleared_lights else {})}}
    from .direct_edit_policy import evaluate
    alternative["editMode"] = edit_mode
    alternative["directApplyPolicy"] = evaluate(operations, prepared, undo=undo, planned=planned)
    site_warnings = (site_review or {}).get("newWarnings") or []
    if planned and design_review is not None and all(
            f.get("code") in VERIFICATION_NOTES for f in _design_findings(design_review)):
        design_review_blocks = False  # the planner's car park: aisles, entrance and walk all present
    else:
        design_review_blocks = design_review is not None
    if site_warnings:
        alternative["directApplyPolicy"].update(eligible=False,
            reason="Review the site findings before applying.")
    elif design_review_blocks:
        alternative["directApplyPolicy"].update(eligible=False,
            reason="Review the parking access and circulation findings before applying.")
    elif obstruction_review is not None:
        alternative["directApplyPolicy"].update(eligible=False,
            reason="Review the equipment placed inside aisles before applying.")
    return alternative, binding, prepared, dependencies


def create(service, principal, site_id, layout_id, base_revision, *, operations=None, undo_receipt_id=None, edit_mode="preview",
           limits=None, planned=False):
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="proposal.create")
    service._require_capability("agent_preview")
    if edit_mode not in {"direct", "preview"}:
        raise FacilityValidationError("invalid_edit_mode", "Choose direct or preview editing.")
    undo = undo_receipt_id is not None
    request = {"receiptId": undo_receipt_id} if undo else {"operations": deepcopy(operations)}
    alternative, binding, prepared, _ = prepare(service, principal, site_id, layout_id, base_revision, request,
        undo=undo, edit_mode=edit_mode, limits=limits, planned=planned)
    if not prepared["changed"]:
        raise FacilityValidationError("operation_proposal_no_change", "The proposal makes no change to the saved layout.")
    # A preview is never permission to commit, even when another writer races it.
    if service.get_layout(principal, site_id, layout_id)["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The layout changed while validating the proposal.")
    proposal_type = UNDO_TYPE if undo else PROPOSAL_TYPE
    proposal_id = deterministic_facility_proposal_id(layout_id=layout_id, base_revision=base_revision,
        proposal_type=proposal_type, semantic_plan_hash=fingerprint({"request": request, "editMode": edit_mode,
                                                                     **({"planned": True} if planned else {})}),
        dependency_fingerprint=binding.dependency_fingerprint)
    proposal = service.transaction_runtime.propose(tenant_id=principal.tenant_id, principal_id=principal.principal_id,
        proposal_id=proposal_id, binding=binding, payload={"tenantId": principal.tenant_id,
            "siteId": site_id, "layoutId": layout_id, "baseRevision": base_revision,
            "proposalType": proposal_type, "request": request, "editMode": edit_mode,
            **({"limits": list(limits)} if limits else {}), **({"planned": True} if planned else {})},
        public_summary={**alternative["metrics"], "directApplyPolicy": alternative["directApplyPolicy"]})
    alternative.update(proposalId=proposal.proposal_id, createdAt=proposal.created_at, expiresAt=proposal.expires_at)
    return {"proposalId": proposal.proposal_id, "baseRevision": base_revision, "layoutRevision": base_revision,
        "selectedProposalId": proposal.proposal_id, "alternatives": [deepcopy(alternative)],
        "createdAt": proposal.created_at, "expiresAt": proposal.expires_at,
        "previewPure": True, "approvalRequired": True, "alternative": alternative}


def regenerate(service, principal, site_id, layout_id, payload):
    service._require_capability("agent_preview")
    # Opening the review and approving it rebuild the proposal; a planner package keeps the limits it was staged under.
    return prepare(service, principal, site_id, layout_id, payload["baseRevision"], payload["request"],
        undo=payload["proposalType"] == UNDO_TYPE, edit_mode=payload.get("editMode", "preview"),
        limits=payload.get("limits"), planned=bool(payload.get("planned")))
