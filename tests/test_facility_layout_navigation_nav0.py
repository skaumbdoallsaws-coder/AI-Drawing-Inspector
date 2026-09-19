from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.navigation_baseline import (
    NAV0_BASELINE_SCHEMA,
    NAV0_EXPECTED_COUNTS,
    NAV0_GEOMETRY_FIXTURE_SCHEMA,
    NAV0_PERFORMANCE_SCHEMA,
    NAV0_REFERENCE_LAYOUT_REVISION,
    NAV0_REVIEW_SCHEMA,
    NAV0_ROUTING_FIXTURE_SCHEMA,
    build_nav0_geometry_fixture,
    build_nav0_reference_baseline,
    build_nav0_review_receipt,
    build_nav0_routing_fixture,
    build_reference_automation_geometry,
)
from ai_inspector.facility_layout.navigation_geometry import (
    FacilityNavigationGeometryError,
    build_triangulated_mesh,
    build_visibility_graph,
    deterministic_query_points,
    free_space_geometry,
    geometry_from_canonical_polygons,
    solve_triangulated_mesh,
    solve_visibility_graph,
    union_and_expand_obstacles,
    validate_centerline,
    visibility_graph_projection,
)
from ai_inspector.facility_layout.reference_performance import (
    nearest_rank_percentile,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
MANIFEST_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "reference-manifest-v1.json"
)
NAVIGATION_FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "navigation"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reference_context() -> tuple[dict, dict, list[dict]]:
    layout = _load(ARCHIVE_PATH)
    manifest = _load(MANIFEST_PATH)
    host = LocalFacilityLayoutHost(
        ROOT / ".runtime" / "facility-layout",
        process_map_root=ROOT / "generated" / "training",
        private_assets=True,
        private_asset_root=ROOT,
    )
    try:
        catalog = host.authoritative_asset_catalog()
    finally:
        host.close()
    return layout, manifest, catalog


def test_nav0_baseline_is_repeatable_and_never_grants_review_authority(
    reference_context: tuple[dict, dict, list[dict]],
) -> None:
    layout, manifest, catalog = reference_context
    archive_before = hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()
    first = build_nav0_reference_baseline(layout, manifest, catalog)
    second = build_nav0_reference_baseline(layout, manifest, catalog)
    review = build_nav0_review_receipt(first)

    assert first == second
    assert first["schemaVersion"] == NAV0_BASELINE_SCHEMA
    assert first["status"] == "candidate_review_pending"
    assert first["counts"]["availableOperators"] == 20
    assert len(first["operatorCycleCandidates"]) == 12
    assert len(first["vehicleCandidates"]) == 4
    assert len(first["handoffCandidates"]) == 7
    assert all(
        item["evidenceStatus"] == "derived"
        and item["reviewStatus"] == "pending"
        and item["productionEligible"] is False
        for collection in (
            first["operatorCycleCandidates"],
            first["vehicleCandidates"],
            first["handoffCandidates"],
        )
        for item in collection
    )
    assert review["schemaVersion"] == NAV0_REVIEW_SCHEMA
    assert review["reviewStatus"] == "pending"
    assert review["approvalRequested"] is False
    assert review["approvedOperatorCycleIds"] == []
    assert review["approvedVehiclePlacementIds"] == []
    assert review["approvedHandoffIds"] == []
    assert hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest() == archive_before
    assert archive_before == NAV0_REFERENCE_LAYOUT_REVISION


def test_checked_in_nav0_baseline_matches_current_reference(
    reference_context: tuple[dict, dict, list[dict]],
) -> None:
    layout, manifest, catalog = reference_context
    checked_in = _load(
        NAVIGATION_FIXTURE_ROOT / "nav0-reference-baseline-v1.json"
    )
    historical = checked_in["source"]["historicalVehicleEvidence"]
    generated = build_nav0_reference_baseline(
        layout,
        manifest,
        catalog,
        historical_vehicle_evidence=historical,
    )

    assert generated == checked_in
    assert generated["counts"] == {
        **NAV0_EXPECTED_COUNTS,
        "automationSourceUnionVertices": 1920,
        "automationExpandedVertices": 5808,
    }
    assert generated["automationBenchmark"]["roleCounts"] == {
        "barrier": 456,
        "ordinary_obstacle": 36,
    }


def test_nav0_visual_evidence_is_hash_bound_and_pending_review() -> None:
    manifest = _load(
        NAVIGATION_FIXTURE_ROOT / "nav0-visual-evidence-v1.json"
    )

    assert manifest["schemaVersion"] == (
        "facility-navigation-nav0-visual-evidence-v1"
    )
    assert len(manifest["captures"]) == 4
    assert {(item["view"], item["subject"]) for item in manifest["captures"]} == {
        ("plan", "legacy_operator_cycle_candidates"),
        ("3d", "legacy_operator_cycle_and_fifo_candidates"),
        ("plan", "prototype_vehicle_path_candidates"),
        ("3d", "prototype_vehicle_path_candidates"),
    }
    for capture in manifest["captures"]:
        destination = ROOT / capture["path"]
        source = ROOT / capture["sourcePath"]
        assert destination.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == capture["sha256"]
        assert capture["sha256"] == capture["sourceSha256"]
        if source.is_file():
            assert hashlib.sha256(source.read_bytes()).hexdigest() == capture["sourceSha256"]
        assert capture["reviewStatus"] == "pending"
        assert capture["productionEligible"] is False


def test_cross_platform_geometry_fixture_is_repeatable_on_this_host() -> None:
    checked_in = _load(
        NAVIGATION_FIXTURE_ROOT / "nav0-geometry-cross-platform-v1.json"
    )
    generated = build_nav0_geometry_fixture()

    assert checked_in["schemaVersion"] == NAV0_GEOMETRY_FIXTURE_SCHEMA
    assert generated["fixtureRevision"] == checked_in["fixtureRevision"]
    assert checked_in["promotionStatus"] == "pending_linux_receipt"
    assert checked_in["observedPlatformReceipts"][0]["platform"] == "win32"
    assert checked_in["observedPlatformReceipts"][0]["passed"] is True
    for case in checked_in["cases"]:
        compiled = union_and_expand_obstacles(
            case["obstacles"],
            navigation_radius_meters=case["navigationRadiusMeters"],
        )
        assert all(
            item["sourceObstacleIds"] == sorted(item["sourceObstacleIds"])
            and item["sourceObstacleIds"]
            for item in compiled["expandedPolygons"]
        )
        assert (
            compiled["geometryFingerprint"]
            == case["expectedGeometryFingerprint"]
        )
        free_space = free_space_geometry(
            case["allowedPolygons"],
            compiled["expandedPolygons"],
        )
        start = (float(case["start"]["x"]), float(case["start"]["z"]))
        goal = (float(case["goal"]["x"]), float(case["goal"]["z"]))
        graph = build_visibility_graph(free_space, start, goal)
        route = solve_visibility_graph(graph, start, goal)
        assert route["routeFingerprint"] == case["expectedRouteFingerprint"]
        assert route["centerline"] == case["expectedCenterline"]


def test_nav0_synthetic_routing_cases_cover_the_frozen_task_space() -> None:
    checked_in = _load(
        NAVIGATION_FIXTURE_ROOT / "nav0-routing-cases-v1.json"
    )
    generated = build_nav0_routing_fixture()

    assert generated == checked_in
    assert checked_in["schemaVersion"] == NAV0_ROUTING_FIXTURE_SCHEMA
    assert checked_in["status"] == "frozen_for_future_phase_evaluation"
    assert [item["caseId"] for item in checked_in["cases"]] == [
        "free_space_routing",
        "disconnected_space",
        "blocked_service_side",
        "multi_stop_loop",
        "paired_lanes",
        "turnaround_profile_required",
        "unreachable_handoff",
    ]
    assert "not manufacturing" in checked_in["authorityBoundary"]

    for case_id in ("free_space_routing", "disconnected_space"):
        case = next(
            item for item in checked_in["cases"] if item["caseId"] == case_id
        )
        compiled = union_and_expand_obstacles(
            case["input"]["obstacles"],
            navigation_radius_meters=case["input"]["navigationRadiusMeters"],
        )
        free_space = free_space_geometry(
            [{"exterior": case["input"]["allowedBoundary"], "holes": []}],
            compiled["expandedPolygons"],
        )
        start = (
            float(case["input"]["start"]["x"]),
            float(case["input"]["start"]["z"]),
        )
        goal = (
            float(case["input"]["goal"]["x"]),
            float(case["input"]["goal"]["z"]),
        )
        graph = build_visibility_graph(free_space, start, goal)
        if case_id == "free_space_routing":
            route = solve_visibility_graph(graph, start, goal)
            assert validate_centerline(free_space, route["centerline"])
        else:
            with pytest.raises(FacilityNavigationGeometryError) as caught:
                solve_visibility_graph(graph, start, goal)
            assert caught.value.code == case["expected"]["code"]


def test_secant_corrected_buffer_never_under_approximates_radius() -> None:
    radius = 0.4
    compiled = union_and_expand_obstacles(
        [
            {
                "obstacleId": "square",
                "exterior": [
                    {"x": -1, "z": -1},
                    {"x": 1, "z": -1},
                    {"x": 1, "z": 1},
                    {"x": -1, "z": 1},
                ],
            }
        ],
        navigation_radius_meters=radius,
    )
    source = geometry_from_canonical_polygons(
        [
            {
                "exterior": [
                    {"x": -1, "z": -1},
                    {"x": 1, "z": -1},
                    {"x": 1, "z": 1},
                    {"x": -1, "z": 1},
                ],
                "holes": [],
            }
        ]
    )
    expanded = geometry_from_canonical_polygons(compiled["expandedPolygons"])

    assert compiled["effectiveBufferRadiusMeters"] > radius
    assert expanded.exterior.distance(source) >= radius - 2.0e-6
    assert "not engineering clearance" in compiled["contract"]["qualification"]


def test_reference_visibility_graph_refuses_before_pair_allocation_and_navmesh_routes(
    reference_context: tuple[dict, dict, list[dict]],
) -> None:
    layout, manifest, catalog = reference_context
    automation = build_reference_automation_geometry(layout, manifest, catalog)
    free_space = geometry_from_canonical_polygons(
        automation["freeSpacePolygons"]
    )
    start, goal = deterministic_query_points(free_space)
    projection = visibility_graph_projection(free_space, start, goal)

    assert projection == {
        "nodeCount": 5814,
        "candidatePairCount": 16_898_391,
        "maximumCandidatePairCount": 5_000_000,
    }
    with pytest.raises(FacilityNavigationGeometryError) as caught:
        build_visibility_graph(free_space, start, goal)
    assert caught.value.code == "facility_navigation_visibility_budget_exceeded"
    assert caught.value.details["projectedCandidatePairCount"] == 16_898_391

    mesh = build_triangulated_mesh(free_space)
    result = solve_triangulated_mesh(mesh, free_space, start, goal)
    assert len(mesh.triangles) == 5882
    assert len(mesh.adjacency) == 5917
    assert validate_centerline(free_space, result["centerline"])
    assert result["algorithm"] == "triangulated_navmesh_astar_funnel"


def test_small_visibility_graph_remains_available() -> None:
    compiled = union_and_expand_obstacles(
        [
            {
                "obstacleId": "machine",
                "exterior": [
                    {"x": 4, "z": 2},
                    {"x": 6, "z": 2},
                    {"x": 6, "z": 8},
                    {"x": 4, "z": 8},
                ],
            }
        ],
        navigation_radius_meters=0.4,
    )
    allowed = [
        {
            "exterior": [
                {"x": 0, "z": 0},
                {"x": 10, "z": 0},
                {"x": 10, "z": 10},
                {"x": 0, "z": 10},
            ],
            "holes": [],
        }
    ]
    free_space = free_space_geometry(allowed, compiled["expandedPolygons"])
    start = (1.0, 1.0)
    goal = (9.0, 9.0)
    graph = build_visibility_graph(free_space, start, goal)
    result = solve_visibility_graph(graph, start, goal)

    assert result["algorithm"] == "visibility_graph_astar"
    assert validate_centerline(free_space, result["centerline"])


def test_nav0_performance_evidence_freezes_the_measured_algorithm() -> None:
    evidence = _load(NAVIGATION_FIXTURE_ROOT / "nav0-performance-v1.json")
    baseline = _load(
        NAVIGATION_FIXTURE_ROOT / "nav0-reference-baseline-v1.json"
    )

    assert evidence["schemaVersion"] == NAV0_PERFORMANCE_SCHEMA
    assert evidence["baselineRevision"] == baseline["baselineRevision"]
    assert evidence["status"] == "pass"
    assert evidence["results"]["selectedAlgorithm"] == (
        "triangulated_navmesh_astar_funnel"
    )
    assert evidence["complexity"]["visibilityCandidatePairCount"] == 16_898_391
    assert evidence["measurements"]["visibilityBuildAndQuery"]["outcome"] == (
        "resource_refused"
    )
    assert evidence["measurements"]["visibilityWarmQuery"]["outcome"] == (
        "not_applicable_resource_refused"
    )
    for name in (
        "automationGeometryCompile",
        "coldNavigationSnapshotCompile",
        "navmeshBuildAndQuery",
        "navmeshWarmQuery",
    ):
        measurement = evidence["measurements"][name]
        assert measurement["sampleCount"] == 20
        assert len(measurement["rawMilliseconds"]) == 20
        assert measurement["passed"] is True
        assert nearest_rank_percentile(
            measurement["rawMilliseconds"], 0.95
        ) == measurement["p95Milliseconds"]
    assert evidence["machine"]["machineLabel"] == "dell-15-dc15250-standard"
    assert evidence["machine"]["shapely"] == "2.1.2"
    assert evidence["machine"]["geos"] == "3.13.1"
    assert evidence["machine"]["browser"]["productVersion"] == (
        "150.0.4078.105"
    )
