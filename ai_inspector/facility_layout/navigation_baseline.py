"""NAV0 reference inventory, review candidates, and algorithm benchmark evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import platform
import sys
import time
from typing import Any, Callable, Mapping, Sequence

import shapely

from .lean_motion import derive_facility_lean_motion_blueprint
from .navigation_geometry import (
    FacilityNavigationGeometryError,
    build_triangulated_mesh,
    build_visibility_graph,
    canonicalize_polygon_geometry,
    deterministic_geometry_contract,
    deterministic_query_points,
    free_space_geometry,
    geometry_from_canonical_polygons,
    solve_triangulated_mesh,
    solve_visibility_graph,
    union_and_expand_obstacles,
    validate_centerline,
    visibility_graph_projection,
)
from .reference_performance import summarize_timing_samples
from .spatial import placement_spatial_records


NAV0_BASELINE_SCHEMA = "facility-navigation-nav0-baseline-v1"
NAV0_REVIEW_SCHEMA = "facility-navigation-nav0-review-v1"
NAV0_PERFORMANCE_SCHEMA = "facility-navigation-nav0-performance-v1"
NAV0_GEOMETRY_FIXTURE_SCHEMA = "facility-navigation-nav0-geometry-fixtures-v1"
NAV0_ROUTING_FIXTURE_SCHEMA = "facility-navigation-nav0-routing-cases-v1"

NAV0_REFERENCE_LAYOUT_ID = "fl-reference-manual-20260812"
NAV0_REFERENCE_LAYOUT_REVISION = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)
NAV0_REFERENCE_MANIFEST_REVISION = (
    "95f233aecbfd26e2fa4e36784d2bc7c6009ed83e0e622346c82b1da5448b7fab"
)
NAV0_AUTOMATION_ZONE_ID = "zn-7fd3010b58867b2d15e4ac08"
NAV0_AUTOMATION_ZONE_LABEL = "Automation + Robot cells"
NAV0_GUARD_ASSET_ID = "asset-5987t55-wire-mesh-machine-guard-panel"
NAV0_OPERATOR_ASSET_ID = "asset-operator"
NAV0_OPERATOR_ASSET_REVISION = (
    "773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757"
)
NAV0_EXPECTED_COUNTS = {
    "zones": 45,
    "routes": 8,
    "placements": 827,
    "floorMarkings": 50,
    "availableOperators": 20,
    "candidateOperatorCycles": 12,
    "candidateVehicles": 4,
    "candidateHandoffs": 7,
    "automationPlacements": 492,
    "automationGuardPanels": 456,
}
NAV0_PERFORMANCE_LIMITS_MILLISECONDS = {
    "automationGeometryCompile": 5000.0,
    "coldNavigationSnapshotCompile": 5000.0,
    "visibilityBuildAndQuery": 5000.0,
    "visibilityWarmQuery": 1500.0,
    "navmeshBuildAndQuery": 5000.0,
    "navmeshWarmQuery": 1500.0,
}


NAV0_VEHICLE_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "placementId": "pl-043ba93c06287a1189f76121",
        "assetId": "asset-forklift-telescopic-red",
        "assetDefinitionRevision": (
            "ab73c19258c171d1c3cab496cd317b1d896293249ddd62c57cba81a61829f214"
        ),
        "routeId": "rt-332016e60dd81aea2df8b79a",
        "travelDirection": "forward",
        "laneEvidenceStatus": "derived",
        "laneStatus": "direction_markings",
    },
    {
        "placementId": "pl-46b0312cba7ef0ec17177dbb",
        "assetId": "asset-forklift",
        "assetDefinitionRevision": (
            "da1345e51b1a32c38ad8388799154ba77dc59e99890a855caac3648548f5be5f"
        ),
        "routeId": "rt-332016e60dd81aea2df8b79a",
        "travelDirection": "reverse",
        "laneEvidenceStatus": "derived",
        "laneStatus": "direction_markings",
    },
    {
        "placementId": "pl-6c217be9a92f28415348f8e2",
        "assetId": "asset-forklift-2610x2264x986-minimum-height-green",
        "assetDefinitionRevision": (
            "62e93539bc7bedeba184c0d0d59882d2464d9f01ee24e4dac1f73fc60d2147d9"
        ),
        "routeId": "rt-5ac6ba69087bcd081bea966b",
        "travelDirection": "reverse",
        "laneEvidenceStatus": "unknown",
        "laneStatus": "centerline_unmarked",
    },
    {
        "placementId": "pl-a40148427d47c3b5fa25a9b0",
        "assetId": "asset-forklift-2610x2264x986-minimum-height-green",
        "assetDefinitionRevision": (
            "62e93539bc7bedeba184c0d0d59882d2464d9f01ee24e4dac1f73fc60d2147d9"
        ),
        "routeId": "rt-a50abc809d8e129c0fe5fa68",
        "travelDirection": "forward",
        "laneEvidenceStatus": "unknown",
        "laneStatus": "centerline_unmarked",
    },
)


class FacilityNavigationBaselineError(RuntimeError):
    """The reference archive cannot satisfy the NAV0 evidence contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _catalog_index(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for item in catalog:
        asset_id = str(item.get("assetId") or "")
        revision = str(item.get("assetDefinitionRevision") or "")
        definition = item.get("definition")
        if asset_id and revision and isinstance(definition, Mapping):
            result[(asset_id, revision)] = item
    return result


def _assert_reference_source(
    layout: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    source = manifest.get("source")
    counts = manifest.get("counts")
    if (
        layout.get("layoutId") != NAV0_REFERENCE_LAYOUT_ID
        or not isinstance(source, Mapping)
        or source.get("layoutRevision") != NAV0_REFERENCE_LAYOUT_REVISION
        or source.get("sourceFileSha256") != NAV0_REFERENCE_LAYOUT_REVISION
        or manifest.get("manifestRevision") != NAV0_REFERENCE_MANIFEST_REVISION
        or not isinstance(counts, Mapping)
        or any(
            int(counts.get(name, -1)) != expected
            for name, expected in {
                "zones": 45,
                "routes": 8,
                "placements": 827,
                "floorMarkings": 50,
            }.items()
        )
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_reference_mismatch",
            "NAV0 requires the exact archived manual reference and manifest revision.",
        )


def _operator_navigation_envelope(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    asset = _catalog_index(catalog).get(
        (NAV0_OPERATOR_ASSET_ID, NAV0_OPERATOR_ASSET_REVISION)
    )
    definition = asset.get("definition") if isinstance(asset, Mapping) else None
    geometry = definition.get("geometry") if isinstance(definition, Mapping) else None
    polygons = geometry.get("footprintPolygons") if isinstance(geometry, Mapping) else None
    if not isinstance(polygons, list) or not polygons:
        raise FacilityNavigationBaselineError(
            "facility_navigation_operator_envelope_unavailable",
            "The exact reference operator footprint is unavailable.",
        )
    vertices = []
    for polygon in polygons:
        if not isinstance(polygon, list):
            continue
        for point in polygon:
            if isinstance(point, Mapping):
                vertices.append((float(point["x"]), float(point["z"])))
    if len(vertices) < 3:
        raise FacilityNavigationBaselineError(
            "facility_navigation_operator_envelope_unavailable",
            "The exact reference operator footprint is incomplete.",
        )
    radius = max(math.hypot(x, z) for x, z in vertices)
    return {
        "assetId": NAV0_OPERATOR_ASSET_ID,
        "assetDefinitionRevision": NAV0_OPERATOR_ASSET_REVISION,
        "shape": "rotation_invariant_bounding_circle",
        "radiusMeters": round(radius, 9),
        "evidenceStatus": "derived",
        "authority": "catalog_derived_prototype_benchmark",
        "productionEligible": False,
        "qualification": (
            "The radius is derived from the exact catalog footprint for NAV0 "
            "algorithm measurement. It is not an approved pedestrian clearance."
        ),
    }


def _zone_descendants(
    manifest: Mapping[str, Any],
    parent_zone_id: str,
) -> set[str]:
    relationships = [
        item
        for item in manifest.get("zoneRelationships", [])
        if isinstance(item, Mapping)
    ]
    descendants = set()
    pending = [parent_zone_id]
    while pending:
        parent = pending.pop()
        children = sorted(
            str(item.get("zoneId") or "")
            for item in relationships
            if item.get("derivedParentZoneId") == parent
        )
        for child in children:
            if child and child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def build_reference_automation_geometry(
    layout: Mapping[str, Any],
    manifest: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile exact NAV0 Automation-scope obstacle and free-space geometry."""

    _assert_reference_source(layout, manifest)
    zone = next(
        (
            item
            for item in layout.get("zones", [])
            if isinstance(item, Mapping)
            and item.get("zoneId") == NAV0_AUTOMATION_ZONE_ID
        ),
        None,
    )
    if not isinstance(zone, Mapping) or zone.get("label") != NAV0_AUTOMATION_ZONE_LABEL:
        raise FacilityNavigationBaselineError(
            "facility_navigation_automation_scope_unavailable",
            "The frozen Automation benchmark zone is unavailable.",
        )
    descendants = _zone_descendants(manifest, NAV0_AUTOMATION_ZONE_ID)
    binding_by_placement = {
        str(item.get("placementId") or ""): item
        for item in manifest.get("placementBindings", [])
        if isinstance(item, Mapping)
    }
    catalog_index = _catalog_index(catalog)
    obstacles = []
    role_counts = {"barrier": 0, "ordinary_obstacle": 0}
    asset_counts: dict[str, int] = {}
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        binding = binding_by_placement.get(placement_id)
        if (
            not isinstance(binding, Mapping)
            or binding.get("derivedTargetZoneId") not in descendants
        ):
            continue
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        asset = catalog_index.get((asset_id, revision))
        definition = asset.get("definition") if isinstance(asset, Mapping) else None
        if not isinstance(definition, Mapping):
            raise FacilityNavigationBaselineError(
                "facility_navigation_asset_geometry_unavailable",
                f"Placement {placement_id} has no exact catalog definition.",
            )
        try:
            records = placement_spatial_records(placement, definition)
        except (KeyError, TypeError, ValueError) as error:
            raise FacilityNavigationBaselineError(
                "facility_navigation_asset_geometry_unavailable",
                f"Placement {placement_id} has no usable physical footprint.",
            ) from error
        role = "barrier" if asset_id == NAV0_GUARD_ASSET_ID else "ordinary_obstacle"
        role_counts[role] += 1
        asset_counts[asset_id] = asset_counts.get(asset_id, 0) + 1
        for record in records:
            obstacles.append(
                {
                    "obstacleId": record.record_id,
                    "placementId": placement_id,
                    "assetId": asset_id,
                    "role": role,
                    "exterior": [
                        {"x": round(point[0], 9), "z": round(point[1], 9)}
                        for point in record.polygon
                    ],
                    "holes": [],
                }
            )
    if (
        role_counts["barrier"] != NAV0_EXPECTED_COUNTS["automationGuardPanels"]
        or sum(role_counts.values()) != NAV0_EXPECTED_COUNTS["automationPlacements"]
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_automation_inventory_mismatch",
            "The Automation obstacle inventory differs from the frozen reference.",
        )
    envelope = _operator_navigation_envelope(catalog)
    expanded = union_and_expand_obstacles(
        obstacles,
        navigation_radius_meters=envelope["radiusMeters"],
    )
    allowed_geometry = geometry_from_canonical_polygons(
        [{"exterior": zone["boundary"], "holes": []}]
    )
    allowed = canonicalize_polygon_geometry(allowed_geometry)
    free_space = free_space_geometry(allowed, expanded["expandedPolygons"])
    free_space_records = canonicalize_polygon_geometry(free_space)
    result = {
        "zoneId": NAV0_AUTOMATION_ZONE_ID,
        "zoneLabel": NAV0_AUTOMATION_ZONE_LABEL,
        "descendantZoneIds": sorted(descendants),
        "placementCount": sum(role_counts.values()),
        "roleCounts": role_counts,
        "assetCounts": dict(sorted(asset_counts.items())),
        "operatorBenchmarkEnvelope": envelope,
        "allowedPolygons": allowed,
        "obstacleCompilation": expanded,
        "freeSpacePolygons": free_space_records,
    }
    result["geometryContextFingerprint"] = _fingerprint(result)
    return result


def _layout_index(
    layout: Mapping[str, Any],
    field: str,
    identity_field: str,
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get(identity_field) or ""): item
        for item in layout.get(field, [])
        if isinstance(item, Mapping) and str(item.get(identity_field) or "")
    }


def build_nav0_reference_baseline(
    layout: Mapping[str, Any],
    manifest: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    *,
    historical_vehicle_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable pending-review candidate inventory for NAV0."""

    _assert_reference_source(layout, manifest)
    placements = _layout_index(layout, "placements", "placementId")
    routes = _layout_index(layout, "routes", "routeId")
    blueprint = derive_facility_lean_motion_blueprint(layout)
    operator_plans = blueprint.get("operatorPlans", [])
    handoffs = blueprint.get("materialHandoffs", [])
    available_operators = sorted(
        placement_id
        for placement_id, placement in placements.items()
        if placement.get("assetId") == NAV0_OPERATOR_ASSET_ID
    )
    if (
        len(available_operators) != NAV0_EXPECTED_COUNTS["availableOperators"]
        or len(operator_plans) != NAV0_EXPECTED_COUNTS["candidateOperatorCycles"]
        or len(handoffs) != NAV0_EXPECTED_COUNTS["candidateHandoffs"]
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_candidate_inventory_mismatch",
            "The current deterministic candidate inventory differs from NAV0.",
        )
    operator_candidates = []
    for plan in operator_plans:
        placement_id = str(plan.get("placementId") or "")
        if placement_id not in placements:
            raise FacilityNavigationBaselineError(
                "facility_navigation_candidate_identity_missing",
                f"Operator candidate {placement_id} is not an existing placement.",
            )
        candidate = {
            "candidateId": str(plan["planId"]),
            "placementId": placement_id,
            "zoneId": str(plan["zoneId"]),
            "zoneLabel": str(plan["zoneLabel"]),
            "pathKind": str(plan["pathKind"]),
            "segmentIndex": int(plan["segmentIndex"]),
            "segmentCount": int(plan["segmentCount"]),
            "assignedPlacementIds": sorted(plan["assignedPlacementIds"]),
            "candidateCenterline": deepcopy(plan["waypoints"]),
            "candidateTraversableBoundary": deepcopy(plan["traversableBoundary"]),
            "evidenceStatus": "derived",
            "authority": "legacy_heuristic_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "reviewFindings": [
                "service_side_not_authored",
                "station_visit_order_not_authored",
                "legacy_rectangle_path_not_gold",
            ],
        }
        candidate["candidateFingerprint"] = _fingerprint(candidate)
        operator_candidates.append(candidate)
    operator_candidates.sort(key=lambda item: item["candidateId"])

    vehicle_candidates = []
    for source in NAV0_VEHICLE_CANDIDATES:
        placement = placements.get(source["placementId"])
        route = routes.get(source["routeId"])
        if (
            not isinstance(placement, Mapping)
            or not isinstance(route, Mapping)
            or placement.get("assetId") != source["assetId"]
            or placement.get("assetDefinitionRevision")
            != source["assetDefinitionRevision"]
        ):
            raise FacilityNavigationBaselineError(
                "facility_navigation_vehicle_candidate_mismatch",
                f"Vehicle candidate {source['placementId']} no longer matches the archive.",
            )
        findings = ["exact_published_vehicle_profile_required"]
        if source["laneStatus"] == "centerline_unmarked":
            findings.append("directional_lane_markings_unavailable")
        candidate = {
            **deepcopy(source),
            "routeLabel": str(route.get("label") or ""),
            "evidenceStatus": "derived",
            "authority": "prototype_playback_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "reviewFindings": findings,
        }
        candidate["candidateFingerprint"] = _fingerprint(candidate)
        vehicle_candidates.append(candidate)

    handoff_candidates = []
    for handoff in handoffs:
        candidate = {
            "candidateId": str(handoff["handoffId"]),
            "fromZoneId": str(handoff["fromZoneId"]),
            "toZoneId": str(handoff["toZoneId"]),
            "fromPlanId": str(handoff["fromPlanId"]),
            "toPlanId": str(handoff["toPlanId"]),
            "fromPointId": str(handoff["fromPointId"]),
            "toPointId": str(handoff["toPointId"]),
            "candidateCenterline": deepcopy(handoff["centerline"]),
            "evidenceStatus": "derived",
            "authority": "legacy_proximity_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "reviewFindings": [
                "participant_assignment_not_authored",
                "fifo_identity_not_authored",
                "sequence_and_timing_not_authored",
            ],
        }
        candidate["candidateFingerprint"] = _fingerprint(candidate)
        handoff_candidates.append(candidate)
    handoff_candidates.sort(key=lambda item: item["candidateId"])

    automation = build_reference_automation_geometry(layout, manifest, catalog)
    historical_evidence = None
    if isinstance(historical_vehicle_evidence, Mapping):
        historical_evidence = {
            "path": historical_vehicle_evidence.get("path"),
            "sha256": historical_vehicle_evidence.get("sha256"),
            "actorCount": historical_vehicle_evidence.get("actorCount"),
            "vehicleCount": historical_vehicle_evidence.get("vehicleCount"),
            "status": "prototype_browser_evidence",
        }
    result = {
        "schemaVersion": NAV0_BASELINE_SCHEMA,
        "baselineId": "facility-navigation-nav0-reference-v1",
        "status": "candidate_review_pending",
        "source": {
            "layoutId": NAV0_REFERENCE_LAYOUT_ID,
            "layoutRevision": NAV0_REFERENCE_LAYOUT_REVISION,
            "manifestRevision": NAV0_REFERENCE_MANIFEST_REVISION,
            "historicalVehicleEvidence": historical_evidence,
        },
        "counts": {
            **NAV0_EXPECTED_COUNTS,
            "automationSourceUnionVertices": automation["obstacleCompilation"][
                "sourceUnionVertexCount"
            ],
            "automationExpandedVertices": automation["obstacleCompilation"][
                "expandedVertexCount"
            ],
        },
        "availableOperatorPlacementIds": available_operators,
        "operatorCycleCandidates": operator_candidates,
        "vehicleCandidates": vehicle_candidates,
        "handoffCandidates": handoff_candidates,
        "automationBenchmark": automation,
        "authorityBoundary": (
            "NAV0 freezes prototype candidates for product-owner review. No item "
            "is authored, approved, production eligible, or evidence of safety, "
            "staffing, throughput, timing, or regulatory compliance."
        ),
    }
    result["baselineRevision"] = _fingerprint(result)
    return result


def build_nav0_review_receipt(baseline: Mapping[str, Any]) -> dict[str, Any]:
    if baseline.get("schemaVersion") != NAV0_BASELINE_SCHEMA:
        raise FacilityNavigationBaselineError(
            "facility_navigation_baseline_invalid",
            "The NAV0 review receipt requires the exact baseline schema.",
        )
    operators = baseline.get("operatorCycleCandidates", [])
    vehicles = baseline.get("vehicleCandidates", [])
    handoffs = baseline.get("handoffCandidates", [])
    return {
        "schemaVersion": NAV0_REVIEW_SCHEMA,
        "baselineRevision": baseline.get("baselineRevision"),
        "reviewStatus": "pending",
        "approvalRequested": False,
        "approvalEligible": True,
        "approver": "Shadrack",
        "approverRole": "InspectorPro product owner and reference-layout author",
        "reviewedAt": None,
        "approvedOperatorCycleIds": [],
        "approvedVehiclePlacementIds": [],
        "approvedHandoffIds": [],
        "pendingOperatorCycleIds": [item["candidateId"] for item in operators],
        "pendingVehiclePlacementIds": [item["placementId"] for item in vehicles],
        "pendingHandoffIds": [item["candidateId"] for item in handoffs],
        "authorityBoundary": (
            "This generated receipt requests no approval and grants no human "
            "authority. Approval requires an explicit product-owner review event."
        ),
    }


def build_nav0_routing_fixture() -> dict[str, Any]:
    """Freeze the seven bounded synthetic cases required before NAV1."""

    common_boundary = [
        {"x": 0.0, "z": 0.0},
        {"x": 20.0, "z": 0.0},
        {"x": 20.0, "z": 12.0},
        {"x": 0.0, "z": 12.0},
    ]
    divider = [
        {"x": 9.0, "z": 0.0},
        {"x": 11.0, "z": 0.0},
        {"x": 11.0, "z": 12.0},
        {"x": 9.0, "z": 12.0},
    ]
    cases = [
        {
            "caseId": "free_space_routing",
            "scope": "pedestrian_local",
            "input": {
                "allowedBoundary": common_boundary,
                "obstacles": [
                    {
                        "obstacleId": "machine-a",
                        "role": "ordinary_obstacle",
                        "exterior": [
                            {"x": 8.0, "z": 3.0},
                            {"x": 12.0, "z": 3.0},
                            {"x": 12.0, "z": 9.0},
                            {"x": 8.0, "z": 9.0},
                        ],
                    }
                ],
                "start": {"x": 2.0, "z": 6.0},
                "goal": {"x": 18.0, "z": 6.0},
                "navigationRadiusMeters": 0.4,
            },
            "expected": {
                "outcome": "accepted",
                "pathMustRemainInsideFreeSpace": True,
            },
        },
        {
            "caseId": "disconnected_space",
            "scope": "pedestrian_local",
            "input": {
                "allowedBoundary": common_boundary,
                "obstacles": [
                    {
                        "obstacleId": "full-depth-divider",
                        "role": "barrier",
                        "exterior": divider,
                    }
                ],
                "start": {"x": 2.0, "z": 6.0},
                "goal": {"x": 18.0, "z": 6.0},
                "navigationRadiusMeters": 0.4,
            },
            "expected": {
                "outcome": "refused",
                "code": "facility_navigation_route_unreachable",
            },
        },
        {
            "caseId": "blocked_service_side",
            "scope": "pedestrian_service_anchor",
            "input": {
                "allowedBoundary": common_boundary,
                "serviceTargetId": "machine-a",
                "authoredServiceAnchor": {"x": 10.0, "z": 6.0},
                "obstacles": [
                    {
                        "obstacleId": "machine-a",
                        "role": "service_target",
                        "exterior": [
                            {"x": 8.0, "z": 3.0},
                            {"x": 12.0, "z": 3.0},
                            {"x": 12.0, "z": 9.0},
                            {"x": 8.0, "z": 9.0},
                        ],
                    }
                ],
                "navigationRadiusMeters": 0.4,
            },
            "expected": {
                "outcome": "refused",
                "code": "facility_navigation_service_anchor_blocked",
                "mustNotMoveAuthoredAnchor": True,
            },
        },
        {
            "caseId": "multi_stop_loop",
            "scope": "pedestrian_movement_program",
            "input": {
                "orderedAnchorIds": ["station-a", "station-b", "fifo-a"],
                "returnToStart": True,
                "orderAuthority": "authored_fixture",
            },
            "expected": {
                "outcome": "accepted",
                "resolvedAnchorIds": [
                    "station-a",
                    "station-b",
                    "fifo-a",
                    "station-a",
                ],
                "mayReorder": False,
            },
        },
        {
            "caseId": "paired_lanes",
            "scope": "vehicle_lane_graph",
            "input": {
                "routeId": "route-two-way",
                "direction": "two_way",
                "laneCount": 2,
                "directionMarkings": ["forward", "reverse"],
                "laneDerivationOwner": "motion_lanes.py",
            },
            "expected": {
                "outcome": "accepted",
                "forwardAndReverseUseDifferentLanes": True,
                "mustUseExistingLaneDerivation": True,
            },
        },
        {
            "caseId": "turnaround_profile_required",
            "scope": "vehicle_turnaround",
            "input": {
                "routeId": "route-dead-end",
                "vehicleProfileId": None,
                "vehicleProfileRevision": None,
            },
            "expected": {
                "outcome": "refused",
                "code": "facility_navigation_vehicle_profile_unavailable",
                "mustNotInferTurningRadius": True,
            },
        },
        {
            "caseId": "unreachable_handoff",
            "scope": "handoff_topology",
            "input": {
                "allowedBoundary": common_boundary,
                "obstacles": [
                    {
                        "obstacleId": "full-depth-divider",
                        "role": "barrier",
                        "exterior": divider,
                    }
                ],
                "fromAnchor": {"anchorId": "fifo-left", "x": 2.0, "z": 6.0},
                "toAnchor": {"anchorId": "fifo-right", "x": 18.0, "z": 6.0},
                "navigationRadiusMeters": 0.4,
            },
            "expected": {
                "outcome": "refused",
                "code": "facility_navigation_handoff_unreachable",
                "mustPreserveBothAuthoredAnchors": True,
            },
        },
    ]
    result = {
        "schemaVersion": NAV0_ROUTING_FIXTURE_SCHEMA,
        "status": "frozen_for_future_phase_evaluation",
        "authorityBoundary": (
            "Synthetic fixtures test deterministic behavior only. Their dimensions "
            "and outcomes are not manufacturing, safety, or regulatory evidence."
        ),
        "cases": cases,
    }
    result["fixtureRevision"] = _fingerprint(result)
    return result


def nav0_cross_platform_geometry_cases() -> list[dict[str, Any]]:
    return [
        {
            "caseId": "touching_guard_panels",
            "navigationRadiusMeters": 0.4,
            "allowedPolygons": [{
                "exterior": [
                    {"x": -2, "z": -2},
                    {"x": 6, "z": -2},
                    {"x": 6, "z": 4},
                    {"x": -2, "z": 4},
                ],
                "holes": [],
            }],
            "start": {"x": -1, "z": 2},
            "goal": {"x": 5, "z": 2},
            "obstacles": [
                {
                    "obstacleId": "guard-a",
                    "exterior": [
                        {"x": 0, "z": 0},
                        {"x": 2, "z": 0},
                        {"x": 2, "z": 0.05},
                        {"x": 0, "z": 0.05},
                    ],
                },
                {
                    "obstacleId": "guard-b",
                    "exterior": [
                        {"x": 2, "z": 0},
                        {"x": 4, "z": 0},
                        {"x": 4, "z": 0.05},
                        {"x": 2, "z": 0.05},
                    ],
                },
            ],
        },
        {
            "caseId": "hole_and_narrow_passage",
            "navigationRadiusMeters": 0.4,
            "allowedPolygons": [{
                "exterior": [
                    {"x": -2, "z": -2},
                    {"x": 10, "z": -2},
                    {"x": 10, "z": 10},
                    {"x": -2, "z": 10},
                ],
                "holes": [],
            }],
            "start": {"x": -1, "z": 4},
            "goal": {"x": 9, "z": 4},
            "obstacles": [
                {
                    "obstacleId": "ring",
                    "exterior": [
                        {"x": 0, "z": 0},
                        {"x": 8, "z": 0},
                        {"x": 8, "z": 8},
                        {"x": 0, "z": 8},
                    ],
                    "holes": [[
                        {"x": 1, "z": 1},
                        {"x": 1, "z": 7},
                        {"x": 7, "z": 7},
                        {"x": 7, "z": 1},
                    ]],
                },
                {
                    "obstacleId": "interior-machine",
                    "exterior": [
                        {"x": 3.55, "z": 2},
                        {"x": 4.45, "z": 2},
                        {"x": 4.45, "z": 6},
                        {"x": 3.55, "z": 6},
                    ],
                },
            ],
        },
        {
            "caseId": "acute_corner_multipolygon",
            "navigationRadiusMeters": 0.403119915,
            "allowedPolygons": [{
                "exterior": [
                    {"x": -2, "z": -2},
                    {"x": 13, "z": -2},
                    {"x": 13, "z": 13},
                    {"x": -2, "z": 13},
                ],
                "holes": [],
            }],
            "start": {"x": -1, "z": -1},
            "goal": {"x": 12, "z": 12},
            "obstacles": [
                {
                    "obstacleId": "acute",
                    "exterior": [
                        {"x": 0, "z": 0},
                        {"x": 4, "z": 0},
                        {"x": 0.000001, "z": 0.2},
                    ],
                },
                {
                    "obstacleId": "separate",
                    "exterior": [
                        {"x": 10, "z": 10},
                        {"x": 11, "z": 10},
                        {"x": 11, "z": 11},
                        {"x": 10, "z": 11},
                    ],
                },
            ],
        },
    ]


def build_nav0_geometry_fixture() -> dict[str, Any]:
    cases = []
    for source in nav0_cross_platform_geometry_cases():
        compiled = union_and_expand_obstacles(
            source["obstacles"],
            navigation_radius_meters=source["navigationRadiusMeters"],
        )
        free_space = free_space_geometry(
            source["allowedPolygons"],
            compiled["expandedPolygons"],
        )
        start = (float(source["start"]["x"]), float(source["start"]["z"]))
        goal = (float(source["goal"]["x"]), float(source["goal"]["z"]))
        graph = build_visibility_graph(free_space, start, goal)
        route = solve_visibility_graph(graph, start, goal)
        free_space_records = canonicalize_polygon_geometry(free_space)
        cases.append(
            {
                **deepcopy(source),
                "expectedGeometryFingerprint": compiled["geometryFingerprint"],
                "expectedSourceUnionPolygonCount": compiled[
                    "sourceUnionPolygonCount"
                ],
                "expectedSourceUnionVertexCount": compiled[
                    "sourceUnionVertexCount"
                ],
                "expectedExpandedPolygonCount": compiled["expandedPolygonCount"],
                "expectedExpandedVertexCount": compiled["expandedVertexCount"],
                "expectedFreeSpaceFingerprint": _fingerprint(free_space_records),
                "expectedGraphFingerprint": _fingerprint(
                    {"nodes": graph.nodes, "edges": graph.edges}
                ),
                "expectedRouteFingerprint": route["routeFingerprint"],
                "expectedCenterline": route["centerline"],
            }
        )
    result = {
        "schemaVersion": NAV0_GEOMETRY_FIXTURE_SCHEMA,
        "contract": deterministic_geometry_contract(),
        "cases": cases,
        "requiredPlatforms": ["windows", "linux"],
        "promotionStatus": "pending_cross_platform_receipt",
    }
    result["fixtureRevision"] = _fingerprint(result)
    return result


def _measure(
    callback: Callable[[], Any],
    *,
    measured_runs: int,
    warmup_runs: int = 1,
) -> tuple[list[float], Any]:
    result = None
    for _ in range(warmup_runs):
        result = callback()
    samples = []
    for _ in range(measured_runs):
        started = time.perf_counter()
        result = callback()
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples, result


def benchmark_nav0_algorithms(
    baseline: Mapping[str, Any],
    *,
    hardware_profile: Mapping[str, Any],
    cold_geometry_builder: Callable[[], Mapping[str, Any]],
    measured_runs: int = 20,
) -> dict[str, Any]:
    """Measure both NAV0 candidate algorithms on the frozen Automation scope."""

    if measured_runs != 20:
        raise FacilityNavigationBaselineError(
            "facility_navigation_performance_protocol_invalid",
            "The NAV0 performance protocol requires exactly 20 measured runs.",
        )
    automation = baseline.get("automationBenchmark")
    if not isinstance(automation, Mapping):
        raise FacilityNavigationBaselineError(
            "facility_navigation_baseline_invalid",
            "The NAV0 baseline has no Automation benchmark context.",
        )
    placement_ids = automation["obstacleCompilation"]["sourceObstacleIds"]
    expanded = automation["obstacleCompilation"]
    free_space_records = automation["freeSpacePolygons"]
    free_space = geometry_from_canonical_polygons(free_space_records)
    start, goal = deterministic_query_points(free_space)

    obstacle_samples, rebuilt_geometry = _measure(
        cold_geometry_builder,
        measured_runs=measured_runs,
    )
    if (
        not isinstance(rebuilt_geometry, Mapping)
        or rebuilt_geometry.get("geometryContextFingerprint")
        != automation.get("geometryContextFingerprint")
        or len(placement_ids) != 492
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_benchmark_context_invalid",
            "The Automation benchmark geometry is incomplete.",
        )

    def cold_snapshot_compile() -> dict[str, Any]:
        rebuilt = cold_geometry_builder()
        rebuilt_free_space = geometry_from_canonical_polygons(
            rebuilt["freeSpacePolygons"]
        )
        rebuilt_mesh = build_triangulated_mesh(rebuilt_free_space)
        return {
            "geometryContextFingerprint": rebuilt["geometryContextFingerprint"],
            "triangleCount": len(rebuilt_mesh.triangles),
            "adjacencyEdgeCount": len(rebuilt_mesh.adjacency),
        }

    cold_snapshot_samples, cold_snapshot = _measure(
        cold_snapshot_compile,
        measured_runs=measured_runs,
    )
    if cold_snapshot["geometryContextFingerprint"] != automation.get(
        "geometryContextFingerprint"
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_benchmark_context_invalid",
            "The cold navigation snapshot used a different geometry context.",
        )

    visibility_projection = visibility_graph_projection(free_space, start, goal)
    visibility_refused = (
        visibility_projection["candidatePairCount"]
        > visibility_projection["maximumCandidatePairCount"]
    )
    if visibility_refused:
        def visibility_preflight() -> dict[str, Any]:
            try:
                build_visibility_graph(free_space, start, goal)
            except FacilityNavigationGeometryError as error:
                if error.code != "facility_navigation_visibility_budget_exceeded":
                    raise
                return {
                    "outcome": "resource_refused",
                    "code": error.code,
                    "details": error.details,
                }
            raise FacilityNavigationBaselineError(
                "facility_navigation_visibility_preflight_failed",
                "The visibility graph unexpectedly bypassed its resource ceiling.",
            )

        visibility_samples, visibility_result = _measure(
            visibility_preflight,
            measured_runs=measured_runs,
        )
        visibility_measurement = summarize_timing_samples(
            visibility_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "visibilityBuildAndQuery"
            ],
        )
        visibility_measurement.update(
            {
                "outcome": "resource_refused",
                "passed": False,
                "code": visibility_result["code"],
            }
        )
        visibility_warm_measurement = {
            "outcome": "not_applicable_resource_refused",
            "rawMilliseconds": [],
            "sampleCount": 0,
            "limitMilliseconds": NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "visibilityWarmQuery"
            ],
            "passed": False,
        }
        visibility_graph = None
        visibility_warm_result = None
    else:
        visibility_samples, visibility_pair = _measure(
            lambda: (
                (graph := build_visibility_graph(free_space, start, goal)),
                solve_visibility_graph(graph, start, goal),
            ),
            measured_runs=measured_runs,
        )
        visibility_graph, visibility_result = visibility_pair
        visibility_warm_samples, visibility_warm_result = _measure(
            lambda: solve_visibility_graph(visibility_graph, start, goal),
            measured_runs=measured_runs,
        )
        visibility_measurement = summarize_timing_samples(
            visibility_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "visibilityBuildAndQuery"
            ],
        )
        visibility_measurement["outcome"] = "accepted"
        visibility_warm_measurement = summarize_timing_samples(
            visibility_warm_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "visibilityWarmQuery"
            ],
        )
        visibility_warm_measurement["outcome"] = "accepted"

    navmesh_samples, navmesh_pair = _measure(
        lambda: (
            (mesh := build_triangulated_mesh(free_space)),
            solve_triangulated_mesh(mesh, free_space, start, goal),
        ),
        measured_runs=measured_runs,
    )
    navmesh, navmesh_result = navmesh_pair
    navmesh_warm_samples, navmesh_warm_result = _measure(
        lambda: solve_triangulated_mesh(navmesh, free_space, start, goal),
        measured_runs=measured_runs,
    )

    visibility_valid = visibility_refused or (
        validate_centerline(free_space, visibility_result["centerline"])
        and validate_centerline(free_space, visibility_warm_result["centerline"])
    )
    if not (
        visibility_valid
        and validate_centerline(free_space, navmesh_result["centerline"])
        and validate_centerline(free_space, navmesh_warm_result["centerline"])
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_benchmark_route_invalid",
            "A NAV0 candidate algorithm left traversable free space.",
        )

    measurements = {
        "automationGeometryCompile": summarize_timing_samples(
            obstacle_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "automationGeometryCompile"
            ],
        ),
        "coldNavigationSnapshotCompile": summarize_timing_samples(
            cold_snapshot_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "coldNavigationSnapshotCompile"
            ],
        ),
        "visibilityBuildAndQuery": visibility_measurement,
        "visibilityWarmQuery": visibility_warm_measurement,
        "navmeshBuildAndQuery": summarize_timing_samples(
            navmesh_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "navmeshBuildAndQuery"
            ],
        ),
        "navmeshWarmQuery": summarize_timing_samples(
            navmesh_warm_samples,
            limit_milliseconds=NAV0_PERFORMANCE_LIMITS_MILLISECONDS[
                "navmeshWarmQuery"
            ],
        ),
    }
    visibility_passed = (
        not visibility_refused
        and measurements["visibilityBuildAndQuery"]["passed"]
        and measurements["visibilityWarmQuery"]["passed"]
    )
    navmesh_passed = (
        measurements["navmeshBuildAndQuery"]["passed"]
        and measurements["navmeshWarmQuery"]["passed"]
    )
    geometry_compile_passed = (
        measurements["automationGeometryCompile"]["passed"]
        and measurements["coldNavigationSnapshotCompile"]["passed"]
    )
    selected = (
        "visibility_graph_astar"
        if geometry_compile_passed and visibility_passed
        else "triangulated_navmesh_astar_funnel"
        if geometry_compile_passed and navmesh_passed
        else None
    )
    machine = hardware_profile.get("measurement")
    if (
        hardware_profile.get("schemaVersion")
        != "facility-layout-reference-hardware-v1"
        or hardware_profile.get("machineLabel") != "dell-15-dc15250-standard"
        or not isinstance(machine, Mapping)
    ):
        raise FacilityNavigationBaselineError(
            "facility_navigation_hardware_profile_invalid",
            "NAV0 performance evidence requires the frozen Dell hardware fixture.",
        )
    result = {
        "schemaVersion": NAV0_PERFORMANCE_SCHEMA,
        "status": "pass" if selected else "fail",
        "baselineRevision": baseline.get("baselineRevision"),
        "protocol": {
            "discardedWarmupRuns": 1,
            "measuredRuns": measured_runs,
            "percentileMethod": "nearest_rank",
        },
        "machine": {
            "machineLabel": hardware_profile["machineLabel"],
            "operatingSystem": deepcopy(machine.get("operatingSystem")),
            "cpu": deepcopy(machine.get("cpu")),
            "memory": deepcopy(machine.get("memory")),
            "browser": deepcopy(machine.get("browser")),
            "display": deepcopy(machine.get("display")),
            "gpu": deepcopy(machine.get("gpu")),
            "python": platform.python_version(),
            "pythonImplementation": platform.python_implementation(),
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
            "platform": sys.platform,
        },
        "query": {
            "start": {"x": start[0], "z": start[1]},
            "goal": {"x": goal[0], "z": goal[1]},
            "freeSpaceFingerprint": _fingerprint(free_space_records),
        },
        "complexity": {
            "sourcePlacementCount": automation["placementCount"],
            "sourceGuardPanelCount": automation["roleCounts"]["barrier"],
            "sourceUnionVertexCount": expanded["sourceUnionVertexCount"],
            "expandedVertexCount": expanded["expandedVertexCount"],
            "visibilityNodeCount": visibility_projection["nodeCount"],
            "visibilityCandidatePairCount": visibility_projection[
                "candidatePairCount"
            ],
            "visibilityMaximumCandidatePairCount": visibility_projection[
                "maximumCandidatePairCount"
            ],
            "visibilityAcceptedEdgeCount": (
                visibility_result.get("acceptedEdgeCount")
                if not visibility_refused
                else None
            ),
            "visibilityGraphCanonicalBytes": (
                visibility_result.get("graphCanonicalBytes")
                if not visibility_refused
                else None
            ),
            "navmeshTriangleCount": navmesh_result["triangleCount"],
            "navmeshAdjacencyEdgeCount": navmesh_result["adjacencyEdgeCount"],
            "navmeshGraphCanonicalBytes": navmesh_result["graphCanonicalBytes"],
        },
        "measurements": measurements,
        "results": {
            "coldSnapshot": cold_snapshot,
            "visibility": visibility_result,
            "navmesh": navmesh_result,
            "selectedAlgorithm": selected,
            "selectionRule": (
                "Prefer visibility_graph_astar when its frozen accuracy and p95 "
                "gates pass; otherwise select the qualified navmesh candidate."
            ),
        },
    }
    result["performanceRevision"] = _fingerprint(result)
    return result


__all__ = [
    "NAV0_AUTOMATION_ZONE_ID",
    "NAV0_BASELINE_SCHEMA",
    "NAV0_EXPECTED_COUNTS",
    "NAV0_GEOMETRY_FIXTURE_SCHEMA",
    "NAV0_PERFORMANCE_SCHEMA",
    "NAV0_ROUTING_FIXTURE_SCHEMA",
    "NAV0_REFERENCE_LAYOUT_ID",
    "NAV0_REFERENCE_LAYOUT_REVISION",
    "NAV0_REVIEW_SCHEMA",
    "FacilityNavigationBaselineError",
    "benchmark_nav0_algorithms",
    "build_nav0_geometry_fixture",
    "build_nav0_reference_baseline",
    "build_nav0_review_receipt",
    "build_nav0_routing_fixture",
    "build_reference_automation_geometry",
    "nav0_cross_platform_geometry_cases",
]
