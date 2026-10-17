from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.navigation_compiler import (
    FACILITY_NAVIGATION_COMPILER_VERSION,
    FacilityNavigationCompilerError,
    FacilityNavigationSnapshotStore,
    compile_navigation_snapshot,
    navigation_snapshot_summary,
)
from ai_inspector.facility_layout import navigation_compiler
from ai_inspector.facility_layout.navigation_contract import (
    validate_navigation_snapshot,
)
from ai_inspector.facility_layout.navigation_geometry import (
    geometry_from_canonical_polygons,
)
from ai_inspector.facility_layout.journey_planning import (
    plan_pedestrian_journey,
    plan_vehicle_journey,
)
from ai_inspector.facility_layout.navigation_handoffs import (
    compile_handoff_topology,
)
from ai_inspector.facility_layout.motion_package import (
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3,
    FACILITY_NAVIGATION_MOTION_QUALIFICATION,
    build_navigation_journey_motion_package,
    validate_facility_motion_package,
    validate_facility_motion_package_for_playback,
)
from ai_inspector.facility_layout.activity_scenario import (
    FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION,
    build_navigation_activity_scenario,
    validate_facility_activity_scenario,
)
from ai_inspector.facility_layout.navigation_activity import (
    build_navigation_activity_presentation,
)
from ai_inspector.facility_layout import navigation_activity


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"
SHELL_REVISION = "a" * 64
POLICY_REVISION = "d" * 64
PROFILE_REVISION = "1" * 64


def _rectangle(x0: float, z0: float, x1: float, z1: float):
    return [
        {"x": x0, "z": z0},
        {"x": x1, "z": z0},
        {"x": x1, "z": z1},
        {"x": x0, "z": z1},
    ]


def _shell():
    return {
        "features": [{
            "featureId": "floor-test",
            "featureKind": "floor_surface",
            "geometry": {"boundary": _rectangle(0, 0, 12, 8)},
        }]
    }


def _asset(asset_id: str, revision: str, half: float = 0.5):
    return {
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "category": "machine",
        "geometry": {
            "heightInterval": {"minimumY": 0, "maximumY": 2},
            "aabb": {
                "minimum": {"x": -half, "y": 0, "z": -half},
                "maximum": {"x": half, "y": 2, "z": half},
            },
            "footprintPolygons": [[
                {"x": -half, "z": -half},
                {"x": half, "z": -half},
                {"x": half, "z": half},
                {"x": -half, "z": half},
            ]],
        },
    }


def _navigation():
    return {
        "schemaVersion": 1,
        "anchors": [
            {
                "navigationAnchorId": "na-home",
                "anchorKind": "actor_home",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-machine-01",
                },
                "interactionKind": "none",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 4, "z": 1},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-plan-pointer"],
                "reviewStatus": "pending",
            },
            {
                "navigationAnchorId": "na-work",
                "anchorKind": "station_operate",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-workstation-01",
                },
                "interactionKind": "operate",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 10, "z": 1},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-plan-pointer"],
                "reviewStatus": "pending",
            },
        ],
        "movementPrograms": [{
            "movementProgramId": "nmp-cycle",
            "actorPlacementId": "pl-machine-01",
            "actorClass": "pedestrian",
            "actorProfileRef": {
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": PROFILE_REVISION,
            },
            "orderedStops": [
                {
                    "stopId": "nst-home",
                    "navigationAnchorId": "na-home",
                    "interactionKind": "none",
                    "required": True,
                },
                {
                    "stopId": "nst-work",
                    "navigationAnchorId": "na-work",
                    "interactionKind": "operate",
                    "required": True,
                },
            ],
            "loopMode": "out_and_return",
            "requiredRouteIds": [],
            "requiredAnchorIds": ["na-home", "na-work"],
            "forbiddenZoneIds": [],
            "forbiddenRouteIds": [],
            "manualPathConstraintIds": [],
            "handoffProgramIds": [],
            "sourceRevisions": {"layout": "2" * 64},
            "evidenceStatus": "authored",
            "evidence": ["ev-plan-pointer"],
            "reviewStatus": "pending",
        }],
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }


def _route(route_id, points, *, direction="two_way"):
    return {
        "routeId": route_id,
        "routeKind": "operator",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {**points[0]},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {**points[-1]},
        },
        "routingMode": "polyline",
        "centerline": points,
        "corridorWidth": 2,
        "routeFingerprint": "3" * 64,
        "sourceRevisions": {"layout": "2" * 64},
        "requirements": [],
        "evidence": [],
        "extensions": {
            "facilityAisle": {
                "schemaVersion": 1,
                "aisleKind": "pedestrian",
                "direction": direction,
                "color": "#38bdf8",
                "clearanceEvidenceStatus": "unverified",
            }
        },
    }


def _layout():
    layout = json.loads(
        (FIXTURES / "two_asset_cell.json").read_text(encoding="ascii")
    )
    layout.setdefault("extensions", {})["facilityNavigation"] = _navigation()
    layout["routes"] = [
        _route(
            "rt-pedestrian-horizontal",
            [
                {"x": 1, "y": 0, "z": 1},
                {"x": 11, "y": 0, "z": 1},
            ],
        ),
        _route(
            "rt-pedestrian-vertical",
            [
                {"x": 6, "y": 0, "z": 0.5},
                {"x": 6, "y": 0, "z": 3},
            ],
            direction="one_way",
        ),
    ]
    layout["floorMarkings"] = []
    return layout


def _assets():
    return {
        ("asset-machine-01", "e" * 64): _asset(
            "asset-machine-01", "e" * 64, 0.35
        ),
        ("asset-workstation-01", "f" * 64): _asset(
            "asset-workstation-01", "f" * 64, 0.6
        ),
    }


def _compile(layout=None, **kwargs):
    return compile_navigation_snapshot(
        layout or _layout(),
        shell=_shell(),
        asset_definitions=_assets(),
        actor_class="pedestrian",
        actor_profile_revision=PROFILE_REVISION,
        navigation_radius_meters=0.35,
        shell_revision=SHELL_REVISION,
        policy_revision=POLICY_REVISION,
        **kwargs,
    )


def test_nav3_snapshot_is_sealed_reproducible_and_source_traceable():
    layout = _layout()
    before = deepcopy(layout)
    first = _compile(layout)
    second = _compile(layout)

    assert first == second
    assert layout == before
    assert first["snapshot"] == validate_navigation_snapshot(first["snapshot"])
    assert first["snapshot"]["compilerVersion"] == FACILITY_NAVIGATION_COMPILER_VERSION
    assert first["snapshot"]["snapshotFingerprint"] == second["snapshot"]["snapshotFingerprint"]
    assert all(edge.get("sourceRefIds") for edge in first["snapshot"]["edges"])
    assert first["canonicalBytes"] < 16 * 1024 * 1024


def test_nav3_geometry_context_ignores_semantic_only_layout_revision_changes():
    layout = _layout()
    before = _compile(layout)
    before_bytes = json.dumps(before, sort_keys=True, separators=(",", ":"))

    revised = deepcopy(layout)
    revised["extensions"]["facilityNavigation"]["movementPrograms"][0][
        "evidence"
    ].append("ev-semantic-review-note")
    after = _compile(revised)

    assert before["snapshot"]["layoutRevision"] != after["snapshot"]["layoutRevision"]
    assert (
        before["snapshot"]["geometryContextFingerprint"]
        == after["snapshot"]["geometryContextFingerprint"]
    )
    assert json.dumps(before, sort_keys=True, separators=(",", ":")) == before_bytes


def test_nav3_splits_exact_route_intersection_and_preserves_direction():
    package = _compile()
    intersection = [
        node
        for node in package["snapshot"]["nodes"]
        if node["position"] == {"x": 6.0, "z": 1.0}
        and node["nodeKind"] == "connector"
    ]
    assert len(intersection) == 1
    vertical_edges = [
        edge
        for edge in package["snapshot"]["edges"]
        if edge.get("sourceRefIds") == ["rt-pedestrian-vertical"]
        and edge.get("derivationKind") == "network_segment"
    ]
    assert vertical_edges
    assert {edge["direction"] for edge in vertical_edges} == {"forward"}
    assert package["directionFacts"]["oneWayEdgeCount"] >= 2


def test_nav3_free_space_excludes_expanded_static_obstacle():
    package = _compile()
    free_space = geometry_from_canonical_polygons(package["freeSpacePolygons"])
    assert free_space.covers(__import__("shapely").geometry.Point(1, 1))
    assert not free_space.covers(__import__("shapely").geometry.Point(8, 4))
    assert package["metrics"]["sourceObstacleCount"] == 1
    assert package["metrics"]["postUnionExpandedVertexCount"] > 4


def test_nav3_derives_a_feasible_access_point_for_a_target_placement():
    layout = _layout()
    target_anchor = layout["extensions"]["facilityNavigation"]["anchors"][1]
    target_anchor.update({
        "positionAuthority": "derived",
        "localPosition": None,
        "derivedPositionRef": {
            "sourceKind": "placement_access",
            "sourceId": "pl-workstation-01",
            "sourceRevision": "f" * 64,
        },
        "evidenceStatus": "derived",
        "evidence": ["evidence:deterministic-placement-access-v1"],
    })

    package = _compile(layout)
    records = {
        item["navigationAnchorId"]: item
        for item in package["anchorRecords"]
    }
    access = records["na-work"]
    free_space = geometry_from_canonical_polygons(package["freeSpacePolygons"])

    assert access["positionDerivation"] == "nearest_feasible_placement_access"
    assert access["position"] != {"x": 8.0, "z": 4.0}
    assert free_space.covers(__import__("shapely").geometry.Point(
        access["position"]["x"],
        access["position"]["z"],
    ))
    assert plan_pedestrian_journey(layout, package, "nmp-cycle")[
        "outcome"
    ] == "accepted"


def test_nav3_derives_exact_northeast_placement_access():
    layout = _layout()
    target_anchor = layout["extensions"]["facilityNavigation"]["anchors"][1]
    target_anchor.update({
        "positionAuthority": "derived",
        "localPosition": None,
        "derivedPositionRef": {
            "sourceKind": "placement_access",
            "sourceId": "pl-workstation-01",
            "sourceRevision": "f" * 64,
        },
        "approachDirections": ["northeast"],
        "evidenceStatus": "derived",
        "evidence": ["evidence:deterministic-placement-access-v1"],
    })

    package = _compile(layout)
    records = {
        item["navigationAnchorId"]: item
        for item in package["anchorRecords"]
    }

    assert records["na-work"]["position"] == {
        "x": 8.950422,
        "z": 4.950422,
    }
    assert records["na-work"]["positionDerivation"] == (
        "nearest_feasible_placement_access"
    )
    assert plan_pedestrian_journey(layout, package, "nmp-cycle")[
        "outcome"
    ] == "accepted"


def test_nav3_named_placement_side_never_falls_back_to_another_side():
    layout = _layout()
    placement = next(
        item for item in layout["placements"]
        if item["placementId"] == "pl-workstation-01"
    )
    free_space = Polygon([(0, 0), (8.8, 0), (8.8, 8), (0, 8)])

    candidates = navigation_compiler._placement_access_candidates(
        placement,
        _assets()[("asset-workstation-01", "f" * 64)],
        free_space,
        0.35,
        ["northeast"],
    )

    assert candidates == []


def test_nav3_cache_and_sage_summary_are_bounded():
    package = _compile()
    store = FacilityNavigationSnapshotStore(maximum_items=2)
    stored = store.put(package)
    fetched = store.get(package["navigationPackageId"])
    assert fetched == stored == package
    fetched["metrics"]["nodeCount"] = -1
    assert store.get(package["navigationPackageId"])["metrics"]["nodeCount"] >= 1

    summary = navigation_snapshot_summary(package)
    assert summary["canonicalBytes"] <= 8192
    assert "freeSpacePolygons" not in summary
    assert summary["navigationSnapshotId"] == package["snapshot"]["navigationSnapshotId"]


def test_nav3_disconnected_authored_anchor_returns_finding_not_bridge():
    layout = _layout()
    layout["extensions"]["facilityNavigation"]["anchors"][1]["localPosition"] = {
        "x": 8,
        "z": 4,
    }
    package = _compile(layout)
    codes = [item["code"] for item in package["findings"]]
    assert "facility_navigation_node_outside_free_space" in codes
    assert "facility_navigation_anchor_unreachable" in codes


def test_nav3_intersection_budget_fails_before_pairwise_work(monkeypatch):
    layout = _layout()
    monkeypatch.setattr(
        navigation_compiler,
        "FACILITY_NAVIGATION_MAXIMUM_INTERSECTION_COMPARISONS",
        0,
    )
    with pytest.raises(FacilityNavigationCompilerError) as error:
        _compile(layout)
    assert error.value.code == "facility_navigation_intersection_budget_exceeded"


def test_nav4_plans_ordered_out_and_return_on_authored_network():
    layout = _layout()
    package = _compile(layout)
    journey = plan_pedestrian_journey(layout, package, "nmp-cycle")

    assert journey["outcome"] == "accepted"
    assert journey["orderedAnchorIds"] == ["na-home", "na-work", "na-home"]
    assert journey["centerline"][0] == {"x": 4.0, "z": 1.0}
    assert journey["centerline"][-1] == {"x": 4.0, "z": 1.0}
    assert journey["networkEdgeIds"]
    assert journey["validation"] == {
        "authority": "pass",
        "direction": "pass",
        "identity": "pass",
        "physical": "pass",
        "stale": "pass",
        "topology": "pass",
    }
    assert journey == plan_pedestrian_journey(layout, package, "nmp-cycle")


def test_nav4_uses_navmesh_to_detour_around_exact_obstacle():
    layout = _layout()
    navigation = layout["extensions"]["facilityNavigation"]
    navigation["anchors"][0]["localPosition"] = {"x": 4, "z": 4}
    navigation["anchors"][1]["localPosition"] = {"x": 10, "z": 4}
    layout["routes"] = []
    package = _compile(layout)
    journey = plan_pedestrian_journey(layout, package, "nmp-cycle")

    assert journey["outcome"] == "accepted"
    assert journey["networkEdgeIds"] == []
    assert len(journey["centerline"]) > 3
    free_space = geometry_from_canonical_polygons(package["freeSpacePolygons"])
    route_line = __import__("shapely").geometry.LineString([
        (item["x"], item["z"]) for item in journey["centerline"]
    ])
    assert route_line.within(free_space) or free_space.covers(route_line)


def test_nav4_preserves_one_complete_ui_override_exactly():
    layout = _layout()
    navigation = layout["extensions"]["facilityNavigation"]
    authored = [
        {"x": 4, "z": 1},
        {"x": 4, "z": 2},
        {"x": 10, "z": 2},
        {"x": 10, "z": 1},
        {"x": 4, "z": 1},
    ]
    navigation["manualPathConstraints"] = [{
        "manualPathConstraintId": "nmc-exact-cycle",
        "movementProgramId": "nmp-cycle",
        "constraintMode": "complete_override",
        "authoredPolyline": authored,
        "snapRefs": [],
        "lockedSegmentIndexes": [0, 1, 2, 3],
        "direction": "forward",
        "positionAuthority": "ui_authored",
        "evidenceStatus": "authored",
        "evidence": ["ev-plan-pointer"],
        "reviewStatus": "pending",
    }]
    navigation["movementPrograms"][0]["manualPathConstraintIds"] = [
        "nmc-exact-cycle"
    ]
    package = _compile(layout)
    journey = plan_pedestrian_journey(layout, package, "nmp-cycle")

    assert journey["outcome"] == "accepted"
    assert journey["centerline"] == [
        {"x": float(item["x"]), "z": float(item["z"])} for item in authored
    ]


def test_nav4_complete_override_points_expand_scope_beyond_home_zone():
    layout = _layout()
    navigation = layout["extensions"]["facilityNavigation"]
    authored = [
        {"x": 4, "z": 1},
        {"x": 4, "z": 2},
        {"x": 10, "z": 2},
        {"x": 10, "z": 1},
        {"x": 4, "z": 1},
    ]
    layout["zones"].append({
        **deepcopy(layout["zones"][0]),
        "zoneId": "zn-home-scope",
        "label": "Operator home scope",
        "boundary": _rectangle(3, 0, 5, 2),
    })
    navigation["manualPathConstraints"] = [{
        "manualPathConstraintId": "nmc-scope-cycle",
        "movementProgramId": "nmp-cycle",
        "constraintMode": "complete_override",
        "authoredPolyline": authored,
        "snapRefs": [],
        "lockedSegmentIndexes": [0, 1, 2, 3],
        "direction": "forward",
        "positionAuthority": "ui_authored",
        "evidenceStatus": "authored",
        "evidence": ["ev-plan-pointer"],
        "reviewStatus": "pending",
    }]
    navigation["movementPrograms"][0]["manualPathConstraintIds"] = [
        "nmc-scope-cycle"
    ]
    navigation["movementPrograms"][0]["orderedStops"] = [
        navigation["movementPrograms"][0]["orderedStops"][0]
    ]
    navigation["movementPrograms"][0]["requiredAnchorIds"] = ["na-home"]

    anchor_only = _compile(layout, required_anchor_ids=["na-home"])
    assert plan_pedestrian_journey(
        layout, anchor_only, "nmp-cycle"
    )["outcome"] == "constraint_conflict"

    complete_scope = _compile(
        layout,
        required_anchor_ids=["na-home"],
        required_scope_points=authored,
    )
    journey = plan_pedestrian_journey(layout, complete_scope, "nmp-cycle")
    assert journey["outcome"] == "accepted"
    assert journey["centerline"] == [
        {"x": float(item["x"]), "z": float(item["z"])} for item in authored
    ]


def test_nav4_fails_closed_when_required_one_way_route_cannot_return():
    layout = _layout()
    layout["routes"][0]["extensions"]["facilityAisle"]["direction"] = "one_way"
    program = layout["extensions"]["facilityNavigation"]["movementPrograms"][0]
    program["requiredRouteIds"] = ["rt-pedestrian-horizontal"]
    package = _compile(layout)
    journey = plan_pedestrian_journey(layout, package, "nmp-cycle")

    assert journey["outcome"] == "constraint_conflict"
    assert journey["centerline"] == []
    assert journey["validation"]["topology"] == "refused"


def test_nav4_returns_unreachable_without_bridging_blocked_anchor():
    layout = _layout()
    layout["extensions"]["facilityNavigation"]["anchors"][1]["localPosition"] = {
        "x": 8,
        "z": 4,
    }
    package = _compile(layout)
    journey = plan_pedestrian_journey(layout, package, "nmp-cycle")
    assert journey["outcome"] == "unreachable"
    assert journey["centerline"] == []


def _vehicle_profile():
    return {
        "vehicleProfileId": "vehicle-test",
        "vehicleProfileRevision": PROFILE_REVISION,
        "footprint": [
            {"x": -1.0, "z": -0.5}, {"x": 1.0, "z": -0.5},
            {"x": 1.0, "z": 0.5}, {"x": -1.0, "z": 0.5},
        ],
        "steeringLimits": {"minimumTurningRadiusMeters": 0.5},
        "gradeLimits": {"maximumPercent": 8},
        "loadLimits": {"maximumKilograms": 1000},
        "reversePolicy": "prohibited",
    }


def _vehicle_marking(marking_id, x, z, rotation):
    return {
        "markingId": marking_id,
        "markingType": "direction_arrow",
        "label": marking_id,
        "semanticRole": "material_flow",
        "transform": {
            "position": {"x": x, "y": 0.0, "z": z},
            "rotationDegrees": rotation,
        },
        "width": 0.8,
        "depth": 1.6,
        "fillColor": "#ffffff",
        "strokeColor": "#1f2937",
        "opacity": 0.9,
        "text": "",
        "positionMode": "manual",
        "metadata": {"createdBy": "user"},
        "evidence": [],
    }


def _vehicle_layout(*, loop_mode="one_way"):
    layout = _layout()
    layout["placements"][1]["transform"]["position"] = {
        "x": 8.0, "y": 0.0, "z": 7.0,
    }
    route = _route(
        "rt-vehicle-main",
        [
            {"x": 1, "y": 0, "z": 4},
            {"x": 11, "y": 0, "z": 4},
        ],
    )
    route["routeKind"] = "material"
    route["corridorWidth"] = 6
    route["extensions"]["facilityAisle"]["aisleKind"] = "material"
    layout["routes"] = [route]
    layout["floorMarkings"] = [
        _vehicle_marking("fm-forward-a", 3, 3, 90),
        _vehicle_marking("fm-forward-b", 9, 3, 90),
        _vehicle_marking("fm-return-a", 3, 5, 270),
        _vehicle_marking("fm-return-b", 9, 5, 270),
    ]
    navigation = _navigation()
    for anchor in navigation["anchors"]:
        anchor["actorClasses"] = ["vehicle"]
    navigation["anchors"][0].update({
        "anchorKind": "vehicle_parking",
        "localPosition": {"x": 2, "z": 3},
    })
    navigation["anchors"][1].update({
        "anchorKind": "vehicle_turnaround",
        "ownerRef": {"ownerKind": "route", "ownerId": "rt-vehicle-main"},
        "localPosition": {"x": 10, "z": 3},
    })
    program = navigation["movementPrograms"][0]
    program.update({
        "actorClass": "vehicle",
        "actorProfileRef": {
            "profileKind": "vehicle",
            "profileId": "vehicle-test",
            "profileRevision": PROFILE_REVISION,
        },
        "loopMode": loop_mode,
        "requiredRouteIds": ["rt-vehicle-main"],
    })
    layout["extensions"]["facilityNavigation"] = navigation
    return layout


def _compile_vehicle(layout):
    return compile_navigation_snapshot(
        layout,
        shell=_shell(),
        asset_definitions=_assets(),
        actor_class="vehicle",
        actor_profile_revision=PROFILE_REVISION,
        navigation_radius_meters=math.sqrt(1.25),
        shell_revision=SHELL_REVISION,
        policy_revision=POLICY_REVISION,
    )


def test_nav5_uses_marked_directed_lane_and_passes_exact_vehicle_sweep():
    layout = _vehicle_layout()
    package = _compile_vehicle(layout)
    journey = plan_vehicle_journey(
        layout,
        package,
        "nmp-cycle",
        vehicle_profile=_vehicle_profile(),
    )

    assert journey["outcome"] == "accepted"
    assert journey["validation"]["direction"] == "pass"
    assert journey["validation"]["physical"] == "pass"
    assert all(abs(item["z"] - 3.0) <= 1.0 for item in journey["centerline"])
    assert journey["networkEdgeIds"]


def test_nav5_paired_lane_return_changes_lane_at_validated_turnaround():
    layout = _vehicle_layout(loop_mode="paired_lane_return")
    package = _compile_vehicle(layout)
    journey = plan_vehicle_journey(
        layout,
        package,
        "nmp-cycle",
        vehicle_profile=_vehicle_profile(),
    )

    assert journey["orderedAnchorIds"] == ["na-home", "na-work", "na-home"]
    assert any(item["z"] == 3.0 for item in journey["centerline"])
    assert any(item["z"] == 5.0 for item in journey["centerline"])
    assert journey["outcome"] == "accepted"
    assert journey["validation"]["direction"] == "pass"
    assert journey["validation"]["physical"] == "pass"


def test_nav5_refuses_paired_return_without_authored_turnaround():
    layout = _vehicle_layout(loop_mode="paired_lane_return")
    layout["extensions"]["facilityNavigation"]["anchors"][1]["anchorKind"] = (
        "station_unload"
    )
    package = _compile_vehicle(layout)
    journey = plan_vehicle_journey(
        layout,
        package,
        "nmp-cycle",
        vehicle_profile=_vehicle_profile(),
    )
    assert journey["outcome"] == "authority_missing"
    assert journey["centerline"] == []


def _handoff_layout():
    layout = _layout()
    layout["placements"].append({
        "placementId": "pl-operator-02",
        "assetId": "asset-machine-01",
        "assetDefinitionRevision": "e" * 64,
        "transform": {
            "position": {"x": 2.0, "y": 0.0, "z": 6.0},
            "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "scale": 1,
        },
        "positionMode": "manual",
        "snapRelationship": None,
        "metadata": {},
    })
    navigation = layout["extensions"]["facilityNavigation"]
    navigation["anchors"] = [
        navigation["anchors"][0],
        {
            **deepcopy(navigation["anchors"][0]),
            "navigationAnchorId": "na-fifo-out",
            "anchorKind": "fifo_output",
            "ownerRef": {"ownerKind": "zone", "ownerId": "zn-machine-cell"},
            "interactionKind": "handoff",
            "localPosition": {"x": 6, "z": 2},
        },
        {
            **deepcopy(navigation["anchors"][0]),
            "navigationAnchorId": "na-home-02",
            "ownerRef": {"ownerKind": "placement", "ownerId": "pl-operator-02"},
            "localPosition": {"x": 2, "z": 6},
        },
        {
            **deepcopy(navigation["anchors"][0]),
            "navigationAnchorId": "na-fifo-in",
            "anchorKind": "fifo_input",
            "ownerRef": {"ownerKind": "zone", "ownerId": "zn-machine-cell"},
            "interactionKind": "handoff",
            "localPosition": {"x": 6, "z": 6},
        },
    ]
    source = deepcopy(navigation["movementPrograms"][0])
    source.update({
        "movementProgramId": "nmp-source-cycle",
        "orderedStops": [
            {"stopId": "nst-source-home", "navigationAnchorId": "na-home", "interactionKind": "none", "required": True},
            {"stopId": "nst-source-fifo", "navigationAnchorId": "na-fifo-out", "interactionKind": "handoff", "required": True},
        ],
        "loopMode": "task_cycle",
        "requiredAnchorIds": ["na-home", "na-fifo-out"],
        "handoffProgramIds": ["nhp-transfer"],
    })
    target = deepcopy(source)
    target.update({
        "movementProgramId": "nmp-target-cycle",
        "actorPlacementId": "pl-operator-02",
        "orderedStops": [
            {"stopId": "nst-target-home", "navigationAnchorId": "na-home-02", "interactionKind": "none", "required": True},
            {"stopId": "nst-target-fifo", "navigationAnchorId": "na-fifo-in", "interactionKind": "handoff", "required": True},
        ],
        "requiredAnchorIds": ["na-home-02", "na-fifo-in"],
    })
    navigation["movementPrograms"] = [source, target]
    navigation["handoffPrograms"] = [{
        "handoffProgramId": "nhp-transfer",
        "sourceMovementProgramId": "nmp-source-cycle",
        "sourceFifoAnchorId": "na-fifo-out",
        "targetMovementProgramId": "nmp-target-cycle",
        "targetFifoAnchorId": "na-fifo-in",
        "materialIdentityRef": "material-mmle-subassembly",
        "sequencePolicy": "source_before_target",
        "timingAuthority": "topology_only",
        "evidenceStatus": "authored",
        "evidence": ["ev-process-map"],
        "reviewStatus": "pending",
    }]
    return layout


def test_nav6_compiles_two_actor_fifo_topology_without_timing_claim():
    layout = _handoff_layout()
    package = _compile(layout)
    source = plan_pedestrian_journey(layout, package, "nmp-source-cycle")
    target = plan_pedestrian_journey(layout, package, "nmp-target-cycle")
    result = compile_handoff_topology(
        layout,
        "nhp-transfer",
        [source, target],
    )

    assert source["outcome"] == target["outcome"] == "accepted"
    assert result["outcome"] == "complete"
    assert result["topologyComplete"] is True
    assert result["timingKnown"] is False
    assert result["materialEdge"]["renderAsActorWalking"] is False
    assert result["sourceParticipant"]["actorPlacementId"] != (
        result["targetParticipant"]["actorPlacementId"]
    )
    assert "Sequence does not imply timing" in result["qualification"]
    assert result["canonicalBytes"] == len(json.dumps(
        result,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii"))


def test_nav6_never_calls_handoff_complete_with_missing_participant():
    layout = _handoff_layout()
    package = _compile(layout)
    source = plan_pedestrian_journey(layout, package, "nmp-source-cycle")
    result = compile_handoff_topology(layout, "nhp-transfer", [source])

    assert result["outcome"] == "incomplete"
    assert result["topologyComplete"] is False
    assert "facility_navigation_handoff_journey_missing" in {
        item["code"] for item in result["findings"]
    }


def test_nav7_serializes_accepted_pedestrian_journey_through_motion_package():
    layout = _layout()
    journey = plan_pedestrian_journey(layout, _compile(layout), "nmp-cycle")
    built = build_navigation_journey_motion_package(
        journey,
        actor_class="pedestrian",
        actor_profile_ref={
            "profileKind": "pedestrian",
            "profileId": "operator-profile-standard",
            "profileRevision": PROFILE_REVISION,
        },
        generated_at="2026-09-01T00:00:00Z",
    )
    package = validate_facility_motion_package(built["package"])

    assert package["schemaVersion"] == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3
    assert package["movement"]["journeySolutionId"] == journey["journeySolutionId"]
    assert package["movement"]["actorPlacementId"] == "pl-machine-01"
    assert package["movement"]["presentationTimingAuthority"] == (
        "derived_display_only"
    )
    assert package["qualification"] == FACILITY_NAVIGATION_MOTION_QUALIFICATION
    validate_facility_motion_package_for_playback(
        package,
        active_layout_revision=journey["generationLayoutRevision"],
        active_validation_context_fingerprint=journey[
            "validationContextFingerprint"
        ],
    )


def test_nav7_refuses_nonaccepted_journey_and_stale_context():
    layout = _layout()
    journey = plan_pedestrian_journey(layout, _compile(layout), "nmp-cycle")
    built = build_navigation_journey_motion_package(
        journey,
        actor_class="pedestrian",
        actor_profile_ref={
            "profileKind": "pedestrian",
            "profileId": "operator-profile-standard",
            "profileRevision": PROFILE_REVISION,
        },
    )
    with pytest.raises(FacilityValidationError) as stale:
        validate_facility_motion_package_for_playback(
            built["package"],
            active_layout_revision=journey["generationLayoutRevision"],
            active_validation_context_fingerprint="f" * 64,
        )
    assert stale.value.code == "facility_motion_package_stale"

    refused = deepcopy(journey)
    refused["outcome"] = "unreachable"
    refused["centerline"] = []
    refused["poses"] = []
    refused["networkEdgeIds"] = []
    refused["distanceMeters"] = 0
    refused.pop("journeySolutionId")
    refused.pop("solutionFingerprint")
    from ai_inspector.facility_layout.navigation_contract import (
        seal_journey_solution,
    )
    refused = seal_journey_solution(refused)
    with pytest.raises(FacilityValidationError) as unavailable:
        build_navigation_journey_motion_package(
            refused,
            actor_class="pedestrian",
            actor_profile_ref={
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": PROFILE_REVISION,
            },
        )
    assert unavailable.value.code == "facility_navigation_journey_not_replayable"


def _nav7_actor(journey, built, index):
    placement_id = journey["actorPlacementId"]
    return {
        "actorId": f"actor-nav-{index}",
        "actorType": "operator",
        "label": f"Operator {index}",
        "motionPackageId": built["package"]["packageId"],
        "returnMotionPackageId": None,
        "endTransferMotionPackageId": None,
        "startTransferMotionPackageId": None,
        "cycleMotionPackageIds": [],
        "placementId": placement_id,
        "assetDefinitionRef": {
            "assetId": "asset-machine-01",
            "assetDefinitionRevision": "e" * 64,
        },
        "routeId": journey["movementProgramId"],
        "departmentZoneIds": ["zn-machine-cell"],
        "startOffsetSeconds": 0,
        "repeat": True,
        "loopMode": "journey_cycle",
        "endpointTurnSeconds": 0,
        "visualAlignment": {
            "forwardAxis": "+X",
            "authority": "curated_revision_bound_visual_review",
            "evidenceArtifact": "tests/fixtures/operator-forward-axis-v1.json",
        },
    }


def test_nav7_builds_shared_clock_diagnostics_without_rescheduling():
    layout = _handoff_layout()
    package = _compile(layout)
    journeys = [
        plan_pedestrian_journey(layout, package, "nmp-source-cycle"),
        plan_pedestrian_journey(layout, package, "nmp-target-cycle"),
    ]
    builds = [
        build_navigation_journey_motion_package(
            journey,
            actor_class="pedestrian",
            actor_profile_ref={
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": PROFILE_REVISION,
            },
        )
        for journey in journeys
    ]
    actors = [_nav7_actor(journey, built, index + 1) for index, (journey, built) in enumerate(zip(journeys, builds))]
    actors[1]["placementId"] = "pl-operator-02"
    payloads = {
        built["package"]["packageId"]: {"package": built["package"]}
        for built in builds
    }
    presentation = build_navigation_activity_presentation(
        actors,
        payloads,
        cycle_duration_seconds=30,
        handoff_result_ids=["nhr-topology"],
        sample_count=21,
    )
    scenario = build_navigation_activity_scenario(
        layout_revision=journeys[0]["generationLayoutRevision"],
        label="NAV7 shared-clock proof",
        actors=actors,
        cycle_duration_seconds=30,
        navigation_presentation=presentation,
        stationary_evidence={
            "placementCount": 1,
            "assetTypeCount": 1,
            "reason": "Fixed machinery has no revision-bound kinematic track.",
            "evidenceStatus": "unknown",
        },
    )
    canonical = validate_facility_activity_scenario(scenario)

    assert canonical["schemaVersion"] == FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION
    assert canonical["navigationPresentation"]["sharedClock"] is True
    assert canonical["navigationPresentation"]["processTimingClaimed"] is False
    assert canonical["navigationPresentation"]["generatedCollisionAvoidanceOffsets"] is False
    assert all(item["offsetSeconds"] == 0 for item in canonical["navigationPresentation"]["phaseOffsets"])
    assert len(canonical["navigationPresentation"]["sampledProximity"]["pairMinimums"]) == 1


def test_nav7_bounds_dense_intersections_per_actor_pair(monkeypatch):
    layout = _handoff_layout()
    package = _compile(layout)
    journeys = [
        plan_pedestrian_journey(layout, package, "nmp-source-cycle"),
        plan_pedestrian_journey(layout, package, "nmp-target-cycle"),
    ]
    builds = [
        build_navigation_journey_motion_package(
            journey,
            actor_class="pedestrian",
            actor_profile_ref={
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": PROFILE_REVISION,
            },
        )
        for journey in journeys
    ]
    actors = [
        _nav7_actor(journey, built, index + 1)
        for index, (journey, built) in enumerate(zip(journeys, builds))
    ]
    actors[1]["placementId"] = "pl-operator-02"
    payloads = {
        built["package"]["packageId"]: {"package": built["package"]}
        for built in builds
    }
    monkeypatch.setattr(
        navigation_activity,
        "_intersection_points",
        lambda _geometry: [(float(index), float(index)) for index in range(8)],
    )
    presentation = build_navigation_activity_presentation(
        actors,
        payloads,
        cycle_duration_seconds=30,
        sample_count=5,
        maximum_static_intersections_per_actor_pair=2,
    )
    assert len(presentation["pathIntersections"]) == 2


def test_shared_clock_samples_each_actor_once_per_instant(monkeypatch):
    import math
    records = [{"actorId": f"actor-{i:02d}", "index": i} for i in range(40)]
    calls = []

    def pose(record, time):
        calls.append((record["actorId"], time))
        return {"x": math.sin(record["index"] + time), "z": math.cos(record["index"] * .3 - time)}

    monkeypatch.setattr(navigation_activity, "_sample_pose", pose)
    actual = navigation_activity._sampled_pair_minimums(records, cycle_duration_seconds=7, sample_count=11)
    assert len(calls) == 40 * 11
    expected = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            values = []
            for tick in range(11):
                normalized = tick / 10
                a, b = pose(left, 7 * normalized), pose(right, 7 * normalized)
                values.append((math.hypot(a["x"] - b["x"], a["z"] - b["z"]), normalized))
            distance, normalized = min(values)
            expected.append({"actorIds": [left["actorId"], right["actorId"]],
                             "centerDistanceMeters": round(distance, 6), "normalizedTime": round(normalized, 6)})
    assert actual == expected


def test_nav7_rejects_unauthorised_phase_offset():
    layout = _layout()
    journey = plan_pedestrian_journey(layout, _compile(layout), "nmp-cycle")
    built = build_navigation_journey_motion_package(
        journey,
        actor_class="pedestrian",
        actor_profile_ref={
            "profileKind": "pedestrian",
            "profileId": "operator-profile-standard",
            "profileRevision": PROFILE_REVISION,
        },
    )
    actor = _nav7_actor(journey, built, 1)
    actor["startOffsetSeconds"] = 2
    with pytest.raises(FacilityValidationError) as error:
        build_navigation_activity_presentation(
            [actor],
            {built["package"]["packageId"]: {"package": built["package"]}},
            cycle_duration_seconds=10,
        )
    assert error.value.code == "facility_activity_navigation_rescheduling_prohibited"
