"""Second-pass workstation evidence over the existing geometry and access analyses."""
from collections import Counter
from copy import deepcopy

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .errors import FacilityValidationError
from .semantic_model import (
    analyze_facility_asset_access, analyze_facility_route_access,
    build_facility_semantic_map,
)


VERSION = "workstation-review-v1"
LIMITATIONS = [
    "Measured footprint gaps are not operating, maintenance or safety clearances.",
    "Functional sides must come from authored asset information, not machine names or an avatar's position.",
    "Route topology does not establish loaded turning space, dynamic machine travel or process capacity.",
    "This review does not certify installation, floor capacity, utilities, egress or regulatory compliance.",
]


def tool_spec():
    ids = {"type": "array", "maxItems": 50, "uniqueItems": True,
           "items": {"type": "string", "minLength": 1, "maxLength": 128}}
    return {"name": "review_facility_workstations", "description":
        "Second-pass functional review of the saved layout: actual footprint gaps, authored working/service "
        "sides, operator assignments and route evidence. Run before arranging workstations and after changes. "
        "Supply processZoneIds in the user's intended process order to check each material-flow leg. "
        "Missing evidence is not a clearance failure or permission to invent machine sides. Paginate all results.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "zoneIds": deepcopy(ids), "placementIds": deepcopy(ids),
            "processZoneIds": {**deepcopy(ids), "minItems": 2, "maxItems": 12},
            "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
            "pageSize": {"type": "integer", "minimum": 1, "maximum": 12}}}}


def _shape(placement):
    shapes = [Polygon([(p["x"], p["z"]) for p in record["polygon"]])
              for record in placement.get("physicalGeometry", []) if record.get("polygon")]
    return unary_union(shapes) if shapes else None


def _interval(placement):
    records = placement.get("physicalGeometry", [])
    if not records:
        return None
    return min(r["minimumY"] for r in records), max(r["maximumY"] for r in records)


def _same_height(a, b):
    ia, ib = _interval(a), _interval(b)
    return bool(ia and ib and min(ia[1], ib[1]) - max(ia[0], ib[0]) > 1e-6)


def _required_roles(semantic):
    needs = set(semantic.get("genericAccessNeeds", []))
    roles = set(semantic.get("operationalRoles", []))
    result = []
    if "operator_access" in needs or "workstation" in roles:
        result.append("operator")
    if "maintenance_access" in needs or "production_equipment" in roles:
        result.append("service")
    if needs.intersection({"material_transfer", "load_unload_access", "transfer_interfaces"}):
        result.extend(("material_input", "material_output"))
    return result


def review_workstations(state, arguments=None, *, shell_obstacles=()):
    arguments = arguments or {}
    placements = {p["placementId"]: p for p in state.get("placements", [])}
    zones = {z["zoneId"]: z for z in state.get("zones", [])}
    zone_ids, placement_ids = set(arguments.get("zoneIds", [])), set(arguments.get("placementIds", []))
    process = arguments.get("processZoneIds", [])
    unknown = sorted((zone_ids | set(process)) - zones.keys()) + sorted(placement_ids - placements.keys())
    if unknown:
        raise FacilityValidationError("workstation_scope_missing", "Inspect current zone and placement IDs before reviewing.",
                                      details={"references": unknown[:10]})
    result = {"reviewVersion": VERSION, "certified": False, "mutationPerformed": False,
              "status": "not_checked", "limitations": LIMITATIONS, "workstations": [], "findings": []}
    if len(placements) > 2500 or len(state.get("routes", [])) > 500:
        return dict(result, reason="Layout exceeds the bounded workstation review geometry budget.")
    semantic = build_facility_semantic_map(state)
    semantics = {p["placementId"]: p for p in semantic["placements"]}
    candidates = sorted(p for p, s in semantics.items() if _required_roles(s)
                        and (not zone_ids or zone_ids.intersection(s.get("zoneIds", [])))
                        and (not placement_ids or p in placement_ids))
    offset, page_size = arguments.get("offset", 0), arguments.get("pageSize", 12)
    selected = candidates[offset:offset + page_size]
    result.update(totalWorkstations=len(candidates), returnedCount=len(selected), offset=offset,
                  nextOffset=offset + page_size if offset + page_size < len(candidates) else None)
    findings = result["findings"]

    def finding(code, message, ids, action, *, evidence="unknown"):
        findings.append({"code": code, "severity": "warning" if evidence == "derived" else "unverified",
                         "message": message, "entityIds": list(ids), "evidenceStatus": evidence,
                         "nextAction": action})

    access = {}
    for role in ("operator", "service", "material_input", "material_output"):
        scoped = [p for p in selected if role in _required_roles(semantics[p])]
        if scoped:
            analyzed = analyze_facility_asset_access(state, interface_role=role,
                scope_ids=scoped, maximum_results=50, shell_obstacles=shell_obstacles)
            access[role] = {p["placementId"]: p for p in analyzed["records"]}
    shapes = {key: _shape(p) for key, p in placements.items()}
    operators = {key: p for key, p in placements.items()
                 if "personnel_reference" in semantics[key].get("operationalRoles", [])}
    associated = [key for key, operator in operators.items()
                  if operator.get("metadata", {}).get("machinePlacementId") in selected]
    operator_faces = {}
    if associated:
        faces = analyze_facility_asset_access(state, interface_role="front", scope_ids=associated, maximum_results=50)
        operator_faces = {p["placementId"]: p for p in faces["records"]}
    for operator_id, operator in operators.items():
        assigned = operator.get("metadata", {}).get("machinePlacementId")
        if assigned and assigned not in placements:
            finding("operator_assignment_missing", "Operator references a missing workstation.", [operator_id, assigned],
                    "Assign the operator to an existing workstation before positioning it.", evidence="derived")
    for key in selected:
        raw, sem, shape = placements[key], semantics[key], shapes[key]
        station = {"placementId": key, "assetId": raw["assetId"], "label": sem["displayName"],
                   "zoneIds": sem.get("zoneIds", []), "locked": sem.get("locked", False),
                   "roleEvidenceStatus": sem.get("semanticEvidenceStatus"), "access": {},
                   "nearbyFootprintGaps": [], "operatorIds": []}
        if shape is None:
            finding("workstation_geometry_missing", "No physical footprint is available.", [key],
                    "Resolve the pinned library geometry before arranging this workstation.")
        else:
            distances = [(float(shape.distance(other)), other_key) for other_key, other in shapes.items()
                         if other_key != key and other_key not in operators and other is not None
                         and _same_height(raw, placements[other_key])]
            station["nearbyFootprintGaps"] = [{"placementId": other, "distanceMeters": round(distance, 4)}
                                              for distance, other in sorted(distances)[:3]]
        missing = []
        for role in _required_roles(sem):
            record = access.get(role, {}).get(key)
            if record is None:
                missing.append(role)
                continue
            station["access"][role] = record
            if record["geometricAccessStatus"] == "blocked_by_static_footprint":
                finding("workstation_side_blocked", f"The authored {role} side is blocked by static geometry.", [key],
                        "Inspect the limiting geometry and move unlocked equipment or reroute access; recheck the proposal.",
                        evidence="derived")
            if role in {"material_input", "material_output"} and not record["connectedMatchingRouteIds"]:
                finding("workstation_handoff_unconnected", f"No authored corridor reaches the measured {role} approach.", [key],
                        "Provide a connected loading/handoff route and verify the loaded handling envelope.", evidence="derived")
        if missing:
            finding("workstation_functional_sides_missing", "Functional sides are not measurable: " + ", ".join(missing) + ".",
                    [key], "Confirm the control/loading/service sides from CAD or manufacturer evidence; do not guess rotations.")
        if not raw.get("clearanceRecordCount"):
            finding("workstation_envelopes_missing", "Operating and service envelopes are not authored.", [key],
                    "Obtain door/cabinet swings, full machine travel and maintenance dimensions; reserve provisional space explicitly.")
        for operator_id, operator in operators.items():
            if operator.get("metadata", {}).get("machinePlacementId") != key:
                continue
            station["operatorIds"].append(operator_id)
            operator_access = station["access"].get("operator")
            if operator_access:
                anchor, outward = operator_access["anchor"], operator_access["worldFacing"]
                position = operator["transform"]["position"]
                projection = sum((position[axis] - anchor[axis]) * outward[axis] for axis in ("x", "z"))
                if projection <= 0:
                    finding("operator_wrong_working_side", "Assigned operator is not in front of the authored operating face.",
                            [operator_id, key], "Move the operator to the documented operating side, then check access and facing.",
                            evidence="derived")
            face = operator_faces.get(operator_id)
            if operator_access and face:
                position = operator["transform"]["position"]
                direction = sum((operator_access["anchor"][axis] - position[axis]) * face["worldFacing"][axis]
                                for axis in ("x", "z"))
                if direction <= 0:
                    finding("operator_facing_away", "Assigned operator faces away from the documented operating face.",
                            [operator_id, key], "Rotate the operator toward the controls and recheck working reach.", evidence="derived")
            else:
                finding("operator_facing_unverified", "An operator assignment does not verify the avatar's facing direction or working reach.",
                        [operator_id, key], "Verify avatar forward direction against the controls and reachable working position.")
        result["workstations"].append(station)
    result["processFlow"] = {"status": "not_checked", "legs": [], "zoneSequence": list(process)}
    if process:
        for source, target in zip(process, process[1:]):
            leg = analyze_facility_route_access(state, source_zone_ids=[source], target_zone_ids=[target], movement_class="material")
            result["processFlow"]["legs"].append({k: leg.get(k) for k in
                ("sourceZoneIds", "targetZoneIds", "accessStatus", "minimumAuthoredCorridorWidthMeters", "path")})
            if leg.get("accessStatus") in {"blocked", "disconnected"}:
                finding("process_leg_" + leg["accessStatus"], "The authored material route does not provide this process connection.",
                        [source, target], "Connect the two stages through clear corridors; verify the machine loading points and handling space.",
                        evidence="derived")
        result["processFlow"]["status"] = "topology_checked_only"
    elif candidates:
        finding("process_sequence_unverified", "The intended station-to-station material sequence has not been reviewed.", [],
                "Call this review with processZoneIds in the intended order, then inspect each machine's loading/handoff connection.")
    result["findingCounts"] = dict(Counter(f["code"] for f in findings))
    result["status"] = "needs_review" if findings else "no_issues_detected_in_checked_scope" if selected else "no_workstations_in_scope"
    if result["nextOffset"] is not None:
        result["status"] = "partial_review"
    return result


def review_document(service, principal, site_id, layout, arguments=None):
    """Resolve the same pinned authorities for saved and candidate documents."""
    from .canonical import layout_revision
    from .observation import build_facility_layout_observation, trusted_facility_source
    from .spatial import shell_obstacle_records
    context = service._spatial_context(principal, site_id, layout)
    source = trusted_facility_source
    assets = {"assets": [{"document": document, "revision": revision}
                         for (_, revision), document in context.asset_definitions.items()]}
    state = build_facility_layout_observation(
        source("facility_layout", layout, revision=layout_revision(layout), provider="workstation-review"),
        source("industrial_asset_catalog", assets, provider="pinned-asset-definitions"),
        shell_source=source("facility_shell", context.shell, revision=layout["sourceShellRef"]["shellRevision"], provider="active-plan-shell"),
        policy_source=source("facility_policy", context.policy_set, revision=layout["policySetRef"]["policySetRevision"], provider="pinned-policy"),
    )["state"]
    return review_workstations(state, arguments, shell_obstacles=shell_obstacle_records(context.shell))


def review_changed_workstations(service, principal, site_id, before, after):
    def geometry(document):
        extensions = document.get("extensions", {})
        perimeter = extensions.get("facilityPerimeterWalls", {})
        settings = perimeter.get("settings", {})
        return {"placements": [(p["placementId"], p["assetId"], p["assetDefinitionRevision"], p["transform"],
                                 p.get("metadata", {}).get("machinePlacementId")) for p in document.get("placements", [])],
                "zones": [(z["zoneId"], z["zoneType"], z["boundary"], z["floorElevation"]) for z in document.get("zones", [])],
                "routes": [{k: r.get(k) for k in ("routeId", "routeKind", "centerline", "corridorWidth",
                            "sourceEndpoint", "targetEndpoint")} for r in document.get("routes", [])],
                "plan": {k: extensions.get("facilityPlan", {}).get(k) for k in ("widthMeters", "depthMeters")},
                "ground": [{k: s.get(k) for k in ("surfaceId", "boundary", "elevation", "kind", "slope")}
                           for s in extensions.get("facilityGround", {}).get("surfaces", [])],
                "perimeter": (perimeter.get("panels"), {k: settings.get(k) for k in
                              ("heightMeters", "thicknessMeters", "boundary", "openings")}),
                "interior": [{k: v for k, v in wall.items() if k not in {"color", "label"}}
                             for wall in extensions.get("facilityInteriorWalls", {}).get("walls", [])]}
    if geometry(before) == geometry(after) or not after.get("placements"):
        return None
    report = review_document(service, principal, site_id, after)
    if report.get("status") == "no_workstations_in_scope":
        return None
    # Preview responses stay small; the read tool provides paginated details after commit.
    return {**{k: v for k, v in report.items() if k not in {"workstations", "findings"}},
            "findings": report["findings"][:12], "findingCount": len(report["findings"]),
            "workstations": [{k: v for k, v in station.items() if k != "access"} for station in report["workstations"]],
            "reviewScope": "candidate_layout", "findingsTruncated": len(report["findings"]) > 12}
