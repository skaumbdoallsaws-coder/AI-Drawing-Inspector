"""Focused contracts for the Facility Layout semantic layer."""

from __future__ import annotations

import json

from ai_inspector.facility_layout.semantic_model import (
    analyze_facility_asset_access,
    analyze_facility_cell_access,
    analyze_facility_cell_alternatives,
    analyze_facility_clearances,
    analyze_facility_drone_clearance,
    analyze_facility_free_space,
    analyze_facility_layout_provenance,
    analyze_facility_module_fit,
    analyze_facility_operator_travel,
    analyze_facility_protected_intrusions,
    analyze_facility_render_consistency,
    analyze_facility_route_access,
    analyze_facility_route_widths,
    build_facility_semantic_map,
    facility_semantic_registry,
    resolve_facility_entities,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
)


def _zone(zone_id, label, boundary, zone_type="operating"):
    return {
        "zoneId": zone_id,
        "label": label,
        "zoneType": zone_type,
        "boundary": [
            {"x": x_value, "z": z_value}
            for x_value, z_value in boundary
        ],
    }


def _state():
    revision = "1" * 64
    return {
        "identity": {
            "layoutId": "fl-semantic-test",
            "displayName": "Semantic plant",
            "revision": revision,
        },
        "zones": [
            _zone(
                "dept-machining",
                "Machining Hall",
                [(0, 0), (20, 0), (20, 10), (0, 10)],
                "department",
            ),
            _zone(
                "cell-a",
                "Manufacturing Cell A01",
                [(2, 2), (8, 2), (8, 8), (2, 8)],
                "workcell",
            ),
            _zone(
                "dept-automation",
                "Automation + Robot cells",
                [(20, 0), (40, 0), (40, 10), (20, 10)],
                "department",
            ),
        ],
        "assets": [
            {
                "assetId": "asset-cnc",
                "assetDefinitionRevision": "2" * 64,
                "displayName": "CNC Milling Machine",
                "category": "Machines",
                "tags": ["cnc", "milling"],
                "capabilityIds": ["milling"],
                "dimensions": {"x": 2, "y": 2.5, "z": 3},
                "footprint": {
                    "areaSquareMeters": 6,
                    "method": "geometry_footprint",
                },
                "planningReady": True,
            },
            {
                "assetId": "asset-robot",
                "assetDefinitionRevision": "3" * 64,
                "displayName": "FANUC Industrial Robot",
                "category": "Automation",
                "capabilityIds": ["robotic-handling"],
                "dimensions": {"x": 1, "y": 2, "z": 1},
                "footprint": {"areaSquareMeters": 1},
                "planningReady": True,
            },
        ],
        "placements": [
            {
                "placementId": "pl-cnc",
                "assetId": "asset-cnc",
                "assetDefinitionRevision": "2" * 64,
                "displayName": "CNC Milling Machine",
                "category": "Machines",
                "dimensions": {"x": 2, "y": 2.5, "z": 3},
                "footprint": {"areaSquareMeters": 6},
                "physicalGeometry": [{
                    "recordId": "physical:pl-cnc",
                    "polygon": [
                        {"x": 3, "z": 2.5},
                        {"x": 5, "z": 2.5},
                        {"x": 5, "z": 5.5},
                        {"x": 3, "z": 5.5},
                    ],
                    "minimumY": 0,
                    "maximumY": 2.5,
                    "authoritative": True,
                }],
                "transform": {
                    "position": {"x": 4, "y": 0, "z": 4},
                    "scale": 1,
                },
                "zoneIds": ["dept-machining", "cell-a"],
            },
            {
                "placementId": "pl-robot",
                "assetId": "asset-robot",
                "assetDefinitionRevision": "3" * 64,
                "displayName": "FANUC Industrial Robot",
                "category": "Automation",
                "dimensions": {"x": 1, "y": 2, "z": 1},
                "footprint": {"areaSquareMeters": 1},
                "physicalGeometry": [{
                    "recordId": "physical:pl-robot",
                    "polygon": [
                        {"x": 29.5, "z": 3.5},
                        {"x": 30.5, "z": 3.5},
                        {"x": 30.5, "z": 4.5},
                        {"x": 29.5, "z": 4.5},
                    ],
                    "minimumY": 0,
                    "maximumY": 2,
                    "authoritative": True,
                }],
                "transform": {
                    "position": {"x": 30, "y": 0, "z": 4},
                },
                "zoneIds": ["dept-automation"],
            },
        ],
        "routes": [
            {
                "routeId": "rt-material",
                "label": "Material spine",
                "routeKind": "material",
                "corridorWidth": 3,
                "centerline": [
                    {"x": 0, "y": 0, "z": 5},
                    {"x": 40, "y": 0, "z": 5},
                ],
            }
        ],
        "floorMarkings": [
            {
                "markingId": "fm-crossing",
                "markingType": "crosswalk",
                "semanticRole": "pedestrian_lane",
                "label": "Main crossing",
                "width": 3,
                "depth": 2,
            }
        ],
    }


def test_route_semantics_separate_entered_zones_from_edge_contact():
    state = _state()
    state["routes"] = [{
        "routeId": "rt-stub",
        "label": "Stub aisle",
        "routeKind": "forklift",
        "corridorWidth": 3,
        "centerline": [
            {"x": 10, "y": 0, "z": 5},
            {"x": 20, "y": 0, "z": 5},
        ],
    }]

    route = build_facility_semantic_map(state)["routes"][0]

    # The aisle ends exactly on the Automation edge: touching, not reaching.
    assert route["connectedZoneIds"] == ["dept-automation", "dept-machining"]
    assert route["enteredZoneIds"] == ["dept-machining"]
    assert route["edgeContactZoneIds"] == ["dept-automation"]
    assert "edgeContactZoneIds" in route["qualification"]


def test_semantic_map_derives_area_hierarchy_roles_routes_and_metrics():
    semantic = build_facility_semantic_map(_state())

    assert semantic["source"]["layoutRevision"] == "1" * 64
    assert semantic["facilitySummary"]["departmentCount"] == 2
    machining = next(
        item for item in semantic["departments"]
        if item["zoneId"] == "dept-machining"
    )
    assert machining["semanticType"] == "machining"
    assert machining["purposeEvidenceStatus"] == "inferred"
    assert machining["areaSquareMeters"] == 200
    assert machining["areaSquareFeet"] == 2152.782083
    assert machining["grossAssetFootprintAreaSquareMeters"] == 6
    assert machining["grossFootprintCoveragePercent"] == 3
    assert machining["assetOperationalRoles"] == {
        "machining": 1,
        "production_equipment": 1,
    }
    assert machining["connectedRouteIds"] == ["rt-material"]
    assert machining["nearestDepartments"][0] == {
        "zoneId": "dept-automation",
        "label": "Automation + Robot cells",
        "boundaryDistanceMeters": 0.0,
        "relationship": "touching",
        "evidenceStatus": "derived",
    }
    cell = next(
        item for item in semantic["zones"]
        if item["zoneId"] == "cell-a"
    )
    assert cell["scopeKind"] == "subzone"
    assert cell["parentZoneId"] == "dept-machining"
    assert semantic["routes"][0]["lengthMeters"] == 40
    assert semantic["floorMarkings"][0]["operationalMeaning"] == (
        "communicates a pedestrian crossing"
    )
    assert "clearance compliance" in semantic[
        "analysisCapabilities"
    ]["requiresAuthoritativeEvidenceOrValidation"]


def test_route_crossings_are_derived_independently_of_network_components():
    state = _state()
    state["routes"].append({
        "routeId": "rt-pedestrian",
        "label": "Pedestrian connector",
        "routeKind": "pedestrian",
        "corridorWidth": 2,
        "centerline": [
            {"x": 10, "y": 0, "z": 0},
            {"x": 10, "y": 0, "z": 10},
        ],
    })
    state["floorMarkings"][0]["transform"] = {
        "position": {"x": 10, "y": 0, "z": 5},
        "rotationDegrees": 0,
    }
    state["floorMarkings"][0]["width"] = 4
    state["floorMarkings"][0]["depth"] = 4

    semantic = build_facility_semantic_map(state)
    crossing = semantic["routeCrossings"][0]
    summary = semantic["routeNetworkSummary"]

    assert summary["geometricMovementComponentCount"] == 2
    assert summary["geometricCrossingCount"] == 1
    assert summary["mixedTrafficCrossingCount"] == 1
    assert summary["protectedMixedTrafficCrossingCount"] == 1
    assert crossing["routeIds"] == ["rt-material", "rt-pedestrian"]
    assert crossing["position"] == {"x": 10.0, "z": 5.0}
    assert crossing["mixedPedestrianMaterialTraffic"] is True
    assert crossing["crosswalkCoverageStatus"] == "protected"
    assert crossing["crosswalkMarkingIds"] == ["fm-crossing"]
    assert all(
        route["networkComponentId"] != semantic["routes"][0]["networkComponentId"]
        for route in semantic["routes"]
        if route["routeId"] == "rt-pedestrian"
    )


def test_entity_resolution_uses_labels_selection_and_never_guesses_ties():
    state = _state()
    state["selection"] = {
        "placementIds": ["pl-cnc"],
        "zoneIds": [],
    }
    named = resolve_facility_entities(
        state,
        query="CNC Milling Machine",
        entity_kinds=["placement"],
    )
    selected = resolve_facility_entities(
        state,
        entity_kinds=["placement"],
        use_selection=True,
    )

    assert named["resolutionStatus"] == "unique"
    assert named["resolved"]["entityId"] == "pl-cnc"
    assert selected["resolutionStatus"] == "unique"
    assert selected["resolved"]["entityId"] == "pl-cnc"
    assert selected["resolved"]["matchReason"] == "current_selection"

    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-2",
    })
    ambiguous = resolve_facility_entities(
        state,
        query="CNC Milling Machine",
        entity_kinds=["placement"],
    )
    assert ambiguous["resolutionStatus"] == "ambiguous"
    assert ambiguous["resolved"] is None


def test_clearance_analysis_reports_actual_distance_separately_from_requirement():
    state = _state()
    state["placements"][1]["physicalGeometry"][0]["polygon"] = [
        {"x": 7, "z": 2.5},
        {"x": 8, "z": 2.5},
        {"x": 8, "z": 3.5},
        {"x": 7, "z": 3.5},
    ]
    state["placements"][1]["zoneIds"] = ["dept-machining"]

    result = analyze_facility_clearances(
        state,
        scope_ids=["dept-machining"],
        unit_mode="placements",
        maximum_results=5,
    )

    assert result["returnedCount"] == 1
    assert result["records"][0]["actualEdgeToEdgeDistanceMeters"] == 2.0
    assert result["records"][0]["geometricRelationship"] == "separated"
    assert result["records"][0]["requirementStatus"] == "unknown"


def test_protected_intrusion_analysis_uses_positive_area_intersections():
    state = _state()
    result = analyze_facility_protected_intrusions(
        state,
        scope_ids=["dept-machining"],
    )

    route_hit = next(
        item for item in result["records"]
        if item["protectedAreaId"] == "rt-material"
    )
    assert route_hit["placementId"] == "pl-cnc"
    assert route_hit["intersectionAreaSquareMeters"] > 0
    assert route_hit["semanticRole"] == "material_flow_route"


def test_route_width_profile_reports_known_physical_constriction_without_policy_claim():
    result = analyze_facility_route_widths(
        _state(),
        scope_ids=["dept-machining"],
        movement_class="material",
    )

    assert result["returnedCount"] == 1
    record = result["records"][0]
    assert record["routeId"] == "rt-material"
    assert record["authoredCorridorWidthMeters"] == 3
    assert record["minimumKnownUsableWidthMeters"] == 0
    assert record["geometricWidthStatus"] == "blocked"
    assert record["constrainingPlacementIds"] == ["pl-cnc"]
    assert record["policyAdequacyStatus"] == "unknown"
    assert record["physicalGeometryComplete"] is True


def test_free_space_reports_connected_geometry_without_promoting_missing_clearance():
    state = _state()

    geometric = analyze_facility_free_space(
        state,
        scope_ids=["cell-a"],
        metric="geometric",
    )
    operational = analyze_facility_free_space(
        state,
        scope_ids=["cell-a"],
        metric="operational",
    )

    assert geometric["records"][0]["grossAreaSquareMeters"] == 36
    assert geometric["records"][0]["freeAreaSquareMeters"] == 30
    assert geometric["records"][0]["contiguousRegions"]["largestRegion"][
        "areaSquareMeters"
    ] == 30
    assert operational["records"][0]["freeAreaSquareMeters"] is None
    assert operational["records"][0]["evidenceStatus"] == "unknown"
    assert "clearance_model_absent" in operational["records"][0][
        "blockerCodes"
    ]


def test_layout_provenance_resolves_cell_label_and_returns_authored_parameters():
    state = _state()
    provenance = {
        "schemaVersion": 1,
        "provenanceId": "layout-pattern:test-u-a",
        "command": "cell_layout",
        "authoredStrategy": "u",
        "seedEntityIds": ["pl-cnc"],
        "parameters": {"invertU": False, "gap": 1.5},
        "authoredGeometry": {
            "kind": "placement",
            "transform": state["placements"][0]["transform"],
        },
    }
    state["placements"][0]["metadata"] = {
        "layoutProvenance": provenance,
    }

    result = analyze_facility_layout_provenance(
        state,
        query="Manufacturing Cell A01",
    )

    assert result["resolution"]["resolutionStatus"] == "unique"
    assert result["returnedCount"] == 1
    assert result["records"][0]["authoredStrategy"] == "u"
    assert result["records"][0]["parameters"] == {
        "gap": 1.5,
        "invertU": False,
    }
    assert result["records"][0]["relatedZoneIds"] == [
        "cell-a",
        "dept-machining",
    ]


def test_route_access_uses_centerline_intersections_and_reports_obstruction():
    state = _state()

    result = analyze_facility_route_access(
        state,
        source_query="Machining Hall",
        target_query="Automation + Robot cells",
        movement_class="material",
    )

    assert result["accessStatus"] == "blocked"
    assert result["topologyPath"]["distanceMeters"] == 0
    assert result["topologyPath"]["routeIds"] == []
    assert result["obstructedPathRoutes"] == []


def test_route_access_keeps_crossing_traffic_out_of_movement_path():
    state = _state()
    state["routes"].append({
        "routeId": "rt-pedestrian",
        "label": "Pedestrian connector",
        "routeKind": "pedestrian",
        "corridorWidth": 2,
        "centerline": [
            {"x": 10, "y": 0, "z": 0},
            {"x": 10, "y": 0, "z": 10},
        ],
    })

    material = analyze_facility_route_access(
        state,
        source_query="Machining Hall",
        target_query="Automation + Robot cells",
        movement_class="material",
    )
    pedestrian = analyze_facility_route_access(
        state,
        source_query="Machining Hall",
        target_query="Automation + Robot cells",
        movement_class="pedestrian",
    )

    assert material["topologyPath"] is not None
    assert pedestrian["accessStatus"] == "disconnected"


def test_operator_travel_labels_unsequenced_geometry_as_proxy():
    state = _state()
    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-2",
        "displayName": "CNC Milling Machine 2",
        "transform": {
            "position": {"x": 7, "y": 0, "z": 4},
            "scale": 1,
        },
        "physicalGeometry": [{
            **state["placements"][0]["physicalGeometry"][0],
            "recordId": "physical:pl-cnc-2",
            "polygon": [
                {"x": 6.5, "z": 3.5},
                {"x": 7.5, "z": 3.5},
                {"x": 7.5, "z": 4.5},
                {"x": 6.5, "z": 4.5},
            ],
        }],
    })

    result = analyze_facility_operator_travel(
        state,
        scope_ids=["cell-a"],
    )

    record = result["records"][0]
    assert record["metricId"] == "geometric_station_center_proxy"
    assert record["travelDistanceMeters"] == 3
    assert record["evidenceStatus"] == "inferred"
    assert record["walkabilityValidated"] is False


def test_cell_alternatives_are_read_only_measured_and_reject_invalid_options():
    state = _state()
    state["placements"][0]["zoneIds"] = ["dept-machining", "cell-a"]
    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-2",
        "displayName": "CNC Milling Machine 2",
        "transform": {
            "position": {"x": 7, "y": 0, "z": 4},
            "scale": 1,
        },
        "physicalGeometry": [{
            **state["placements"][0]["physicalGeometry"][0],
            "recordId": "physical:pl-cnc-2",
            "polygon": [
                {"x": 6, "z": 2.5},
                {"x": 8, "z": 2.5},
                {"x": 8, "z": 5.5},
                {"x": 6, "z": 5.5},
            ],
        }],
    })
    before = json.dumps(state, sort_keys=True)

    result = analyze_facility_cell_alternatives(
        state,
        query="Manufacturing Cell A01",
        strategies=["line", "l", "u"],
        preferred_gap_meters=0.5,
    )

    assert result["resolutionStatus"] == "unique"
    assert result["mutationPerformed"] is False
    assert result["returnedCount"] == 3
    assert {item["strategy"] for item in result["records"]} == {
        "line", "l", "u",
    }
    assert all(
        item["metrics"]["physicalFootprintUnionSquareMeters"] == 12
        for item in result["records"]
    )
    assert all(
        transform["rotationPreserved"] is True
        for item in result["records"]
        for transform in item["proposedTransforms"]
    )
    assert json.dumps(state, sort_keys=True) == before


def test_cell_alternatives_fail_closed_when_a_member_is_locked():
    state = _state()
    state["placements"][0]["positionMode"] = "locked"
    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-2",
        "positionMode": "manual",
        "transform": {"position": {"x": 7, "y": 0, "z": 4}},
    })

    result = analyze_facility_cell_alternatives(
        state,
        scope_ids=["cell-a"],
    )

    assert result["records"] == []
    assert result["lockedPlacementIds"] == ["pl-cnc"]
    assert "locked_cell_placements" in result["blockerCodes"]


def test_module_fit_counts_complete_cell_envelopes_without_claiming_maximum_capacity():
    state = _state()
    source = next(item for item in state["zones"] if item["zoneId"] == "cell-a")
    source["extensions"] = {
        "cellGroup": {
            "groupKind": "manufacturing_cell",
            "functionalInterfaces": {
                "gate": {"side": "south", "evidenceStatus": "authored"},
                "loading": {"side": "south", "evidenceStatus": "authored"},
                "service": {"side": "north", "evidenceStatus": "authored"},
            },
        }
    }
    state["placements"][0]["clearanceGeometry"] = [{
        "recordId": "clearance:pl-cnc",
        "polygon": [
            {"x": 2.5, "z": 2.25},
            {"x": 5.5, "z": 2.25},
            {"x": 5.5, "z": 5.75},
            {"x": 2.5, "z": 5.75},
        ],
        "minimumY": 0,
        "maximumY": 2.5,
        "authoritative": True,
    }]
    state["placements"][0]["clearanceRecordCount"] = 1
    state["routes"] = []
    before = json.dumps(state, sort_keys=True)

    result = analyze_facility_module_fit(
        state,
        source_query="Manufacturing Cell A01",
        target_query="Automation + Robot cells",
        orientations_degrees=[0, 90],
        gap_meters=1,
        maximum_results=20,
    )

    assert result["resolutionStatus"] == "unique"
    assert result["moduleMemberPlacementIds"] == ["pl-cnc"]
    assert result["boundedGeometricAdditionalCount"] > 0
    assert result["boundedClearanceValidatedAdditionalCount"] == (
        result["boundedGeometricAdditionalCount"]
    )
    assert result["fullyValidatedAdditionalCapacity"] is None
    assert result["productionCapacity"] is None
    assert result["searchCompleteness"] == (
        "bounded_grid_lower_bound_not_exhaustive"
    )
    assert result["mutationPerformed"] is False
    assert all(
        len(item["memberTransforms"]) == 1 for item in result["candidates"]
    )
    assert json.dumps(state, sort_keys=True) == before


def test_module_fit_keeps_operational_capacity_unknown_without_interfaces():
    state = _state()
    state["routes"] = []

    result = analyze_facility_module_fit(
        state,
        source_zone_ids=["cell-a"],
        target_zone_ids=["dept-automation"],
        maximum_results=4,
    )

    assert result["boundedGeometricAdditionalCount"] > 0
    assert result["functionalInterfaceEvidence"]["complete"] is False
    assert result["fullyValidatedAdditionalCapacity"] is None


def test_cell_access_measures_authored_interface_and_keeps_missing_roles_unknown():
    state = _state()
    cell = next(item for item in state["zones"] if item["zoneId"] == "cell-a")
    cell["extensions"] = {
        "cellGroup": {
            "groupKind": "manufacturing_cell",
            "functionalInterfaces": {
                "gate": {
                    "side": "south",
                    "openingWidthMeters": 2,
                    "approachDepthMeters": 1,
                    "evidenceStatus": "authored",
                },
            },
        },
    }
    state["routes"].append({
        "routeId": "rt-pedestrian-cell-a",
        "label": "Cell A01 pedestrian approach",
        "routeKind": "pedestrian",
        "corridorWidth": 1,
        "centerline": [
            {"x": 0, "y": 0, "z": 1.75},
            {"x": 10, "y": 0, "z": 1.75},
        ],
    })
    before = json.dumps(state, sort_keys=True)

    result = analyze_facility_cell_access(
        state,
        query="Manufacturing Cell A01",
    )

    assert result["mutationPerformed"] is False
    assert result["returnedCount"] == 1
    record = result["records"][0]
    assert record["zoneId"] == "cell-a"
    assert record["interfaceEvidenceComplete"] is False
    assert record["missingRoleAlternatives"] == [
        ["load_unload", "loading", "material_input"],
        ["maintenance", "service"],
    ]
    gate = record["interfaces"][0]
    assert gate["role"] == "gate"
    assert gate["side"] == "south"
    assert gate["accessEnvelopeAreaSquareMeters"] == 2
    assert gate["connectedMatchingRouteIds"] == ["rt-pedestrian-cell-a"]
    assert gate["geometryStatus"] == (
        "route_connected_no_static_footprint_intrusion"
    )
    assert gate["adequacyStatus"] == "unknown_without_applicable_policy"
    assert json.dumps(state, sort_keys=True) == before


def test_drone_clearance_uses_live_collider_and_detects_overhead_blocker():
    state = _state()
    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-right",
        "displayName": "CNC Right",
        "transform": {"position": {"x": 7, "y": 0, "z": 4}},
        "physicalGeometry": [{
            "recordId": "physical:pl-cnc-right",
            "polygon": [
                {"x": 6, "z": 2.5},
                {"x": 8, "z": 2.5},
                {"x": 8, "z": 5.5},
                {"x": 6, "z": 5.5},
            ],
            "minimumY": 0,
            "maximumY": 2.5,
            "authoritative": True,
        }],
    })
    state["editor"] = {
        "navigationCapabilities": {
            "activeMode": "drone",
            "drone": {
                "supported": True,
                "active": True,
                "assistedFlight": True,
                "colliderRadiusMeters": 0.35,
                "altitudeMeters": 1,
            },
        },
    }
    clear = analyze_facility_drone_clearance(
        state,
        scope_ids=["pl-cnc", "pl-cnc-right"],
    )
    passage = clear["records"][0]
    assert passage["horizontalGapMeters"] == 1
    assert passage["droneColliderDiameterMeters"] == 0.7
    assert passage["horizontalColliderMarginMeters"] == 0.3
    assert passage["constrainsAtAnalysisAltitude"] is True
    assert passage["passageStatus"] == "static_cross_section_passable"

    state["placements"].append({
        **state["placements"][1],
        "placementId": "pl-overhead",
        "displayName": "Overhead utility",
        "physicalGeometry": [{
            "recordId": "physical:pl-overhead",
            "polygon": [
                {"x": 5.25, "z": 3.5},
                {"x": 5.75, "z": 3.5},
                {"x": 5.75, "z": 4.5},
                {"x": 5.25, "z": 4.5},
            ],
            "minimumY": 1.2,
            "maximumY": 1.8,
            "authoritative": True,
        }],
    })
    blocked = analyze_facility_drone_clearance(
        state,
        scope_ids=["pl-cnc", "pl-cnc-right"],
    )
    blocked_passage = blocked["records"][0]
    assert blocked_passage["passageStatus"] == (
        "blocked_by_overhead_geometry"
    )
    assert blocked_passage["overheadConstraints"][0] == {
        "placementId": "pl-overhead",
        "recordId": "physical:pl-overhead",
        "undersideElevationMeters": 1.2,
        "verticalSurfaceClearanceMeters": -0.15,
    }


def test_render_consistency_requires_adapter_evidence_and_reconciles_count():
    state = _state()
    state["editor"] = {
        "renderConsistency": {
            "topPlan": {
                "status": "match",
                "expectedPlacementCount": 2,
                "auditedPlacementCount": 2,
            },
            "three": {
                "status": "mismatch",
                "expectedPlacementCount": 2,
                "auditedPlacementCount": 2,
                "transformMismatchIds": ["pl-robot"],
            },
        }
    }

    result = analyze_facility_render_consistency(state)

    assert result["overallStatus"] == "mismatch"
    assert result["records"][0]["status"] == "match"
    assert result["records"][1]["transformMismatchIds"] == ["pl-robot"]
    assert all(
        item["authoritativeExpectedPlacementCount"] == 2
        for item in result["records"]
    )


def test_semantic_registry_closes_existing_command_and_strategy_vocabulary():
    registry = facility_semantic_registry()
    commands = {item["commandId"] for item in registry["commands"]}
    strategies = {
        item["strategyId"] for item in registry["cellLayoutStrategies"]
    }

    assert {
        "bulk-zones",
        "aisle",
        "floor-marking",
        "linear-pattern",
        "circular-pattern",
        "perimeter-pattern",
        "cell-layout",
        "create-cell-group",
        "vertical-stack",
        "surface-stack",
        "mirror",
        "swap",
        "walkthrough",
        "drone",
        "record",
    } <= commands
    assert strategies == {
        "line",
        "l",
        "u",
        "grid",
        "parallel",
        "serpentine",
        "loop",
        "spine",
        "herringbone",
        "cluster",
    }
    u_shape = next(
        item for item in registry["cellLayoutStrategies"]
        if item["strategyId"] == "u"
    )
    assert u_shape["variants"][0]["parameter"] == "invertU"
    assert u_shape["knowledgeEvidenceStatus"] == "inferred"
    assert json.dumps(registry, allow_nan=False, sort_keys=True).isascii()


def test_authored_semantics_take_precedence_over_inferred_asset_knowledge():
    state = _state()
    state["assets"][0]["facilitySemantics"] = {
        "semanticType": "special_fixture_station",
        "operationalRoles": ["fixture_preparation"],
        "evidenceStatus": "authored",
    }
    semantic = build_facility_semantic_map(state)
    asset = next(
        item for item in semantic["assets"]
        if item["assetId"] == "asset-cnc"
    )
    assert asset["semanticType"] == "special_fixture_station"
    assert asset["operationalRoles"] == ["fixture_preparation"]
    assert asset["semanticTypeEvidenceStatus"] == "authored"


def test_asset_access_measures_authored_service_side_and_reports_missing_sides():
    state = _state()
    state["assets"][0]["facilitySemantics"] = {
        "semanticType": "cnc_machining_center",
        "operationalRoles": ["production_equipment", "machining"],
        "functionalSides": {
            "service": {
                "side": "east",
                "evidenceStatus": "authored",
            }
        },
        "evidenceStatus": "authored",
    }
    state["placements"][1]["physicalGeometry"][0]["polygon"] = [
        {"x": 7, "z": 2.5},
        {"x": 8, "z": 2.5},
        {"x": 8, "z": 5.5},
        {"x": 7, "z": 5.5},
    ]

    result = analyze_facility_asset_access(
        state,
        interface_role="service",
    )

    assert result["analysis"] == "asset_access"
    assert result["mutationPerformed"] is False
    assert result["measurablePlacementCount"] == 1
    assert result["missingFunctionalSideCount"] == 1
    record = result["records"][0]
    assert record["placementId"] == "pl-cnc"
    assert record["localSide"] == "east"
    assert record["worldSide"] == "east"
    assert record["anchor"] == {"x": 5.0, "z": 4.0}
    assert record["actualOutwardClearanceMeters"] == 2.0
    assert record["nearestPhysicalObstacle"]["placementId"] == "pl-robot"
    assert record["adequacyStatus"] == (
        "unknown_without_applicable_policy"
    )
    assert result["missingFunctionalSidePlacements"][0]["placementId"] == (
        "pl-robot"
    )


def test_department_metric_summaries_are_compact_exact_and_metric_faithful():
    semantic = build_facility_semantic_map(_state())
    summaries = semantic["departmentMetricSummaries"]

    assert [item["zoneId"] for item in summaries] == [
        "dept-machining",
        "dept-automation",
    ]
    machining = summaries[0]
    assert machining["areaSquareMeters"] == 200
    assert machining["netPhysicalFootprintSquareMeters"] == 6
    assert machining["physicalCoveragePercent"] == 3
    assert machining["placementCount"] == 1
    assert machining["componentPlacementCount"] == 1
    assert machining["cellModuleCount"] == 1
    assert machining["ungroupedOperationalPlacementCount"] == 0
    assert machining["operationalUnitCount"] == 1
    assert machining["operationallyUsableFreeAreaSquareMeters"] is None
    assert "facility_shell_not_reviewed" in machining[
        "operationalBlockerCodes"
    ]


def test_cell_components_and_envelopes_are_not_reported_as_independent_units():
    state = _state()
    state["placements"].append({
        **state["placements"][0],
        "placementId": "pl-cnc-guard-component",
        "displayName": "Machine guarding component",
        "zoneIds": ["dept-machining", "cell-a"],
        "transform": {"position": {"x": 7, "y": 0, "z": 4}},
        "physicalGeometry": [{
            "recordId": "physical:pl-cnc-guard-component",
            "polygon": [
                {"x": 6.5, "z": 3.5},
                {"x": 7.5, "z": 3.5},
                {"x": 7.5, "z": 4.5},
                {"x": 6.5, "z": 4.5},
            ],
            "minimumY": 0,
            "maximumY": 2,
            "authoritative": True,
        }],
    })

    semantic = build_facility_semantic_map(state)
    machining = next(
        item for item in semantic["departments"]
        if item["zoneId"] == "dept-machining"
    )
    metrics = machining["spatialMetrics"]

    assert machining["componentPlacementCount"] == 2
    assert machining["cellModuleCount"] == 1
    assert machining["cellComponentPlacementCount"] == 2
    assert machining["ungroupedOperationalPlacementCount"] == 0
    assert machining["operationalUnitCount"] == 1
    assert metrics["physicalFloorContact"][
        "netUnionAreaSquareMeters"
    ] == 7
    assert metrics["cellEnvelopeReservedArea"] == {
        "authoredUnionAreaSquareMeters": 36,
        "cellZoneCount": 1,
        "cellZoneIds": ["cell-a"],
        "evidenceStatus": "authored",
        "qualification": (
            "Descendant manufacturing-cell envelopes are authored "
            "operational allocations. They are planning reservations, not "
            "physical equipment footprint or safety clearance."
        ),
    }
    assert metrics["reconciledPlanningAreaBreakdown"][
        "cellEnvelopeOnlySquareMeters"
    ] == 29


def test_pattern_group_preserves_authored_strategy_and_detects_current_drift():
    state = _state()
    state["placements"] = state["placements"][:1]
    provenance = {
        "schemaVersion": 1,
        "provenanceId": "layout-pattern:test-u-a",
        "command": "cell_layout",
        "authoredStrategy": "u",
        "seedEntityIds": ["pl-cnc"],
        "parameters": {"invertU": False},
        "manuallyEditedSinceCreation": False,
        "authoredGeometry": {
            "kind": "placement",
            "transform": state["placements"][0]["transform"],
        },
    }
    state["placements"][0]["metadata"] = {
        "layoutProvenance": provenance,
    }
    consistent = build_facility_semantic_map(state)[
        "layoutPatternGroups"
    ][0]
    assert consistent["authoredStrategy"] == "u"
    assert consistent["currentClassification"] == {
        "strategy": "u",
        "status": "consistent",
        "confidence": 1.0,
        "evidenceStatus": "derived",
        "method": "current_geometry_compared_with_authored_snapshot",
    }

    state["placements"][0]["transform"]["position"]["x"] = 5.0
    state["placements"][0]["metadata"]["layoutProvenance"][
        "geometryEditedSinceCreation"
    ] = True
    state["placements"][0]["metadata"]["layoutProvenance"][
        "manuallyEditedSinceCreation"
    ] = True
    modified = build_facility_semantic_map(state)["layoutPatternGroups"][0]
    assert modified["currentClassification"]["status"] == "modified"
    assert modified["modifiedMemberCount"] == 1
    assert modified["members"][0]["manuallyEditedSinceCreation"] is True


def test_revision_bound_process_graph_derives_upstream_downstream_relationships():
    state = _state()
    process_revision = "4" * 64
    state["processMaps"] = [{
        "productId": "product-a",
        "processMapId": "pm-a",
        "processMapRevision": process_revision,
        "displayName": "Product A flow",
        "nodeIds": ["op-machine", "op-automate"],
        "edgeIds": ["edge-machine-automate"],
        "graphTopologyLoaded": True,
        "precedenceEdges": [{
            "edgeId": "edge-machine-automate",
            "fromNodeId": "op-machine",
            "toNodeId": "op-automate",
            "edgeKind": "precedence",
            "evidenceStatus": "authored",
        }],
    }]
    state["processBindings"] = [
        {
            "processBindingId": "pb-machine",
            "productId": "product-a",
            "processMapId": "pm-a",
            "processMapRevision": process_revision,
            "processNodeIds": ["op-machine"],
            "placementIds": ["pl-cnc"],
            "bindingRole": "resource",
        },
        {
            "processBindingId": "pb-automate",
            "productId": "product-a",
            "processMapId": "pm-a",
            "processMapRevision": process_revision,
            "processNodeIds": ["op-automate"],
            "placementIds": ["pl-robot"],
            "bindingRole": "resource",
        },
    ]

    relationships = build_facility_semantic_map(state)[
        "processRelationships"
    ]
    assert relationships["flowSequenceStatus"] == "available"
    assert relationships["flowSequenceEvidenceStatus"] == "derived"
    assert relationships["graphTopologyLoadedMapCount"] == 1
    assert relationships["relationshipEdges"] == [{
        "productId": "product-a",
        "processMapId": "pm-a",
        "processMapRevision": process_revision,
        "processEdgeId": "edge-machine-automate",
        "edgeKind": "precedence",
        "fromNodeId": "op-machine",
        "toNodeId": "op-automate",
        "upstreamProcessBindingId": "pb-machine",
        "downstreamProcessBindingId": "pb-automate",
        "upstreamZoneIds": ["cell-a", "dept-machining"],
        "downstreamZoneIds": ["dept-automation"],
        "evidenceStatus": "derived",
        "derivation": (
            "revision-bound authored process edge joined to authored "
            "facility process bindings"
        ),
    }]
    by_id = {
        item["processBindingId"]: item
        for item in relationships["bindings"]
    }
    assert by_id["pb-machine"]["downstreamProcessBindingIds"] == [
        "pb-automate"
    ]
    assert by_id["pb-automate"]["upstreamProcessBindingIds"] == [
        "pb-machine"
    ]


def test_process_bindings_do_not_invent_order_without_loaded_graph_topology():
    state = _state()
    process_revision = "5" * 64
    state["processMaps"] = [{
        "productId": "product-a",
        "processMapId": "pm-a",
        "processMapRevision": process_revision,
        "displayName": "ID-only catalog record",
        "nodeIds": ["op-machine"],
        "edgeIds": [],
    }]
    state["processBindings"] = [{
        "processBindingId": "pb-machine",
        "productId": "product-a",
        "processMapId": "pm-a",
        "processMapRevision": process_revision,
        "processNodeIds": ["op-machine"],
        "placementIds": ["pl-cnc"],
        "bindingRole": "resource",
    }]

    relationships = build_facility_semantic_map(state)[
        "processRelationships"
    ]
    assert relationships["flowSequenceStatus"] == "unknown"
    assert relationships["flowSequenceEvidenceStatus"] == "unknown"
    assert relationships["relationshipEdges"] == []
    assert relationships["graphTopologyMissingMapCount"] == 1
