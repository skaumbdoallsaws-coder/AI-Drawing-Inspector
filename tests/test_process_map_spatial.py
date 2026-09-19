"""Phase 0-2 tests for deterministic process-map spatial geometry."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import ai_inspector.process_map.spatial as spatial_module

from ai_inspector.process_map import (
    PLACEMENT_HARD_REJECTIONS,
    PROCESS_MAP_CANDIDATE_POLICY_VERSION,
    PROCESS_MAP_SPATIAL_CONTRACT_ID,
    PROCESS_MAP_SPATIAL_VERSION,
    SpatialGeometryError,
    apply_orthogonal_route,
    compile_spatial_scene,
    diagnose_spatial_scene,
    generate_arrangement_plan,
    generate_placement_candidates,
    load_spatial_contract,
    refresh_orthogonal_auto_routes,
    route_orthogonal_edge,
    spatialize_semantic_suggestions,
    viewport_rect_to_world,
    viewport_to_world,
    world_rect_to_viewport,
    world_to_normalized,
    world_to_viewport,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "static" / "contracts" / "process-map-spatial-contract-v1.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase1_scene.json"
DIAGNOSTIC_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase2_diagnostics.json"
)
PLACEMENT_MAP_PATH = (
    ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase3_placement_map.json"
)
PLACEMENT_CANDIDATES_PATH = (
    ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase3_candidates.json"
)
ROUTE_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase4_route.json"
)
ARRANGEMENT_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase7_arrangement.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="ascii"))


def _diagnostic_fixture() -> dict:
    return json.loads(DIAGNOSTIC_FIXTURE_PATH.read_text(encoding="ascii"))


def _placement_map() -> dict:
    return json.loads(PLACEMENT_MAP_PATH.read_text(encoding="ascii"))


def _placement_candidates_fixture() -> dict:
    return json.loads(PLACEMENT_CANDIDATES_PATH.read_text(encoding="ascii"))


def _arrangement_fixture() -> dict:
    return json.loads(ARRANGEMENT_FIXTURE_PATH.read_text(encoding="ascii"))


def test_contract_is_ascii_versioned_and_matches_editor_envelopes():
    raw = CONTRACT_PATH.read_bytes()
    assert all(byte < 128 for byte in raw)
    contract = load_spatial_contract()
    assert contract["contractId"] == PROCESS_MAP_SPATIAL_CONTRACT_ID
    assert contract["spatialVersion"] == PROCESS_MAP_SPATIAL_VERSION
    assert contract["coordinateSpaces"]["persisted"] == "world"
    assert contract["geometry"]["nodeEnvelopes"]["default"] == {
        "width": 270,
        "height": 146,
    }
    assert contract["geometry"]["junction"]["hitDiameter"] == 24
    assert contract["geometry"]["groupHeaderHeight"] == 28
    assert contract["geometry"]["legacyBezierSamplingSegments"] == 32
    assert contract["diagnostics"]["regionColumns"] == 4
    assert contract["diagnostics"]["regionRows"] == 2


def test_contract_callers_receive_isolated_copies():
    first = load_spatial_contract()
    first["geometry"]["nodeEnvelopes"]["default"]["width"] = 1
    second = load_spatial_contract()
    assert second["geometry"]["nodeEnvelopes"]["default"]["width"] == 270


@pytest.mark.parametrize(
    ("point", "transform"),
    [
        ({"x": 0, "y": 0}, {"x": 0, "y": 0, "scale": 1}),
        ({"x": 410.5, "y": -23.25}, {"x": 88, "y": -40, "scale": 0.28}),
        ({"x": -900, "y": 612}, {"x": -120, "y": 350, "scale": 1.6}),
    ],
)
def test_point_coordinate_round_trip(point: dict, transform: dict):
    viewport = world_to_viewport(point, transform)
    restored = viewport_to_world(viewport, transform)
    assert restored["x"] == pytest.approx(point["x"])
    assert restored["y"] == pytest.approx(point["y"])


def test_rectangle_coordinate_round_trip():
    rect = {"x": 120, "y": 80, "width": 270, "height": 146}
    transform = {"x": -42, "y": 91, "scale": 1.35}
    viewport = world_rect_to_viewport(rect, transform)
    assert viewport == pytest.approx({"x": 120, "y": 199, "width": 364.5, "height": 197.1})
    assert viewport_rect_to_world(viewport, transform) == pytest.approx(rect)


def test_normalized_regions_are_derived_from_world_bounds():
    normalized = world_to_normalized(
        {"x": 445, "y": 246},
        {"x": 70, "y": 32, "width": 750, "height": 428},
    )
    assert normalized == pytest.approx({"x": 0.5, "y": 0.5})


def test_invalid_transform_fails_closed():
    with pytest.raises(SpatialGeometryError, match="positive scale"):
        world_to_viewport({"x": 1, "y": 2}, {"x": 0, "y": 0, "scale": 0})


def test_scene_compiler_matches_shared_golden_fixture():
    fixture = _fixture()
    actual = compile_spatial_scene(fixture["processMap"], revision=fixture["revision"])
    assert actual == fixture["expectedScene"]


def test_scene_compiler_is_deterministic_across_input_order():
    fixture = _fixture()
    source = fixture["processMap"]
    reordered = deepcopy(source)
    reordered["canvasNodes"] = list(reversed(reordered["canvasNodes"]))
    reordered["canvasEdges"] = list(reversed(reordered["canvasEdges"]))
    reordered["canvasGroups"][0]["memberNodeIds"] = list(
        reversed(reordered["canvasGroups"][0]["memberNodeIds"])
    )
    assert compile_spatial_scene(source) == compile_spatial_scene(reordered)


def test_scene_world_geometry_is_viewport_invariant():
    fixture = _fixture()
    scene = compile_spatial_scene(fixture["processMap"])
    first = world_rect_to_viewport(scene["nodes"][0]["rect"], {"x": 0, "y": 0, "scale": 1})
    second = world_rect_to_viewport(scene["nodes"][0]["rect"], {"x": 400, "y": -50, "scale": 0.5})
    assert first != second
    assert scene == compile_spatial_scene(fixture["processMap"])


def test_duplicate_group_membership_fails_closed():
    process_map = deepcopy(_fixture()["processMap"])
    process_map["canvasGroups"].append(
        {
            "groupId": "group-second",
            "position": {"x": 0, "y": 0},
            "size": {"width": 300, "height": 200},
            "memberNodeIds": ["node-a"],
        }
    )
    with pytest.raises(SpatialGeometryError, match="multiple groups"):
        compile_spatial_scene(process_map)


def test_dangling_edge_and_group_member_fail_closed():
    process_map = deepcopy(_fixture()["processMap"])
    process_map["canvasEdges"][0]["to"]["nodeId"] = "missing"
    with pytest.raises(SpatialGeometryError, match="dangling endpoint"):
        compile_spatial_scene(process_map)

    process_map = deepcopy(_fixture()["processMap"])
    process_map["canvasGroups"][0]["memberNodeIds"].append("missing")
    with pytest.raises(SpatialGeometryError, match="unknown node"):
        compile_spatial_scene(process_map)


def test_clean_scene_diagnostics_ignore_explicit_junction_connections():
    fixture = _fixture()
    diagnostics = diagnose_spatial_scene(compile_spatial_scene(fixture["processMap"]))
    assert diagnostics["metrics"]["nodeOverlaps"] == 0
    assert diagnostics["metrics"]["edgeNodeIntersections"] == 0
    assert diagnostics["metrics"]["edgeCrossings"] == 0
    assert diagnostics["problems"] == []
    assert diagnostics["metrics"]["worldRegionCount"] == 8


def test_diagnostic_metrics_and_problem_order_match_shared_golden_fixture():
    fixture = _diagnostic_fixture()
    diagnostics = diagnose_spatial_scene(compile_spatial_scene(fixture["processMap"]))
    assert diagnostics["metrics"] == fixture["expectedMetrics"]
    assert [item["problemId"] for item in diagnostics["problems"]] == fixture[
        "expectedProblemIds"
    ]
    assert [
        [item["regionId"], item["relativeLocation"], item["classification"]]
        for item in diagnostics["regions"]
    ] == fixture["expectedRegions"]


def test_diagnostics_are_deterministic_across_scene_input_order():
    fixture = _diagnostic_fixture()
    scene = compile_spatial_scene(fixture["processMap"])
    reordered = deepcopy(scene)
    reordered["nodes"].reverse()
    reordered["edges"].reverse()
    reordered["groups"].reverse()
    assert diagnose_spatial_scene(scene) == diagnose_spatial_scene(reordered)


def test_legacy_bezier_is_sampled_instead_of_treated_as_endpoint_chord():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "curve-map",
        "productId": "fixture-product",
        "canvasNodes": [
            {
                "nodeId": "source",
                "nodeKind": "process_step",
                "position": {"x": 0, "y": 200},
                "portOrientation": "vertical",
                "portOrder": "output_first",
            },
            {
                "nodeId": "obstacle",
                "nodeKind": "process_step",
                "position": {"x": 220, "y": 20},
            },
            {
                "nodeId": "target",
                "nodeKind": "process_step",
                "position": {"x": 500, "y": 200},
            },
        ],
        "canvasEdges": [
            {
                "edgeId": "curved-edge",
                "from": {"nodeId": "source", "port": "out"},
                "to": {"nodeId": "target", "port": "in"},
                "kind": "precedence",
            }
        ],
        "canvasGroups": [],
    }
    diagnostics = diagnose_spatial_scene(compile_spatial_scene(process_map))
    assert "edge_node_intersection:curved-edge:obstacle" in {
        item["problemId"] for item in diagnostics["problems"]
    }


def test_minimum_clearance_is_global_even_when_nodes_share_no_index_cells():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "clearance-map",
        "productId": "fixture-product",
        "canvasNodes": [
            {
                "nodeId": "left",
                "nodeKind": "process_step",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "right",
                "nodeKind": "process_step",
                "position": {"x": 5000, "y": 0},
            },
        ],
        "canvasEdges": [],
        "canvasGroups": [],
    }
    diagnostics = diagnose_spatial_scene(compile_spatial_scene(process_map))
    assert diagnostics["metrics"]["minimumNodeClearance"] == 4730


# -- Phase 3: deterministic incremental placement -----------------------


def test_placement_candidates_match_shared_golden_fixture():
    process_map = _placement_map()
    scene = compile_spatial_scene(process_map)
    fixture = _placement_candidates_fixture()["cases"]
    cases = {
        "anchoredOutgoing": dict(
            target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
        ),
        "requiredGroup": dict(
            target_kind="process_step",
            anchor_node_id="anchor-a",
            connection_direction="outgoing",
            required_group_id="group-main",
        ),
        "anchorless": dict(target_kind="product_occurrence"),
        "lockedTargetMove": dict(target_kind="process_step", target_node_id="locked-b"),
        "junctionAnchor": dict(
            target_kind="process_step", anchor_node_id="junction-d", connection_direction="outgoing"
        ),
        "existingNodeMove": dict(target_kind="process_step", target_node_id="clutter-c"),
        "verticalFlow": dict(
            target_kind="process_step",
            anchor_node_id="anchor-a",
            connection_direction="outgoing",
            preferred_flow_direction="top_to_bottom",
        ),
    }
    for name, kwargs in cases.items():
        assert generate_placement_candidates(scene, **kwargs) == fixture[name], name


def test_candidates_are_deterministic_across_repeated_calls():
    scene = compile_spatial_scene(_placement_map())
    first = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    second = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    assert first == second
    ids = [candidate["candidateId"] for candidate in first["candidates"]]
    assert ids == sorted(set(ids), key=ids.index)


def test_candidate_ranking_is_stable_and_unique():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    ids = [candidate["candidateId"] for candidate in result["candidates"]]
    assert len(ids) == len(set(ids))
    assert len(result["candidates"]) <= 3


def test_locked_target_move_rejects_before_generating_candidates():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(scene, target_kind="process_step", target_node_id="locked-b")
    assert result["candidates"] == []
    assert result["rejectionCounts"] == {"locked_node_movement": 1}
    assert result["evaluatedCount"] == 0


def test_fully_blocked_placement_fails_closed_with_deterministic_rejections():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "blocked-map",
        "productId": "fixture-product",
        "canvasNodes": [
            {"nodeId": "a", "nodeKind": "process_step", "position": {"x": 0, "y": 0}},
        ],
        "canvasEdges": [],
        "canvasGroups": [],
    }
    scene = compile_spatial_scene(process_map)
    result = generate_placement_candidates(
        scene,
        target_kind="process_step",
        anchor_node_id="a",
        required_group_id="no-such-group",
    )
    assert result["candidates"] == []
    assert result["rejectionCounts"] == {"group_containment_violation": 1}
    for code in result["rejectionCounts"]:
        assert code in PLACEMENT_HARD_REJECTIONS


def test_anchorless_placement_uses_least_dense_available_region():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(scene, target_kind="product_occurrence")
    assert result["candidates"]
    assert result["anchorNodeId"] is None
    for candidate in result["candidates"]:
        assert candidate["candidateId"].startswith("cand-region-")


def test_anchorless_origin_does_not_run_full_scene_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("anchorless origin must not invoke full diagnostics")

    monkeypatch.setattr(spatial_module, "diagnose_spatial_scene", fail_if_called)
    result = generate_placement_candidates(
        compile_spatial_scene(_placement_map()),
        target_kind="product_occurrence",
    )
    assert result["candidates"]


def test_group_containment_and_header_rejections_are_counted():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(
        scene,
        target_kind="process_step",
        anchor_node_id="anchor-a",
        connection_direction="outgoing",
        required_group_id="group-main",
    )
    assert result["rejectionCounts"].get("group_containment_violation", 0) > 0
    for candidate in result["candidates"]:
        assert candidate["position"]["x"] >= -40
        assert candidate["position"]["y"] >= -40


def test_port_orientation_and_order_are_each_evaluated():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(
        scene,
        target_kind="process_step",
        anchor_node_id="anchor-a",
        connection_direction="outgoing",
        limit=3,
    )
    combos = {(c["portOrientation"], c["portOrder"]) for c in result["candidates"]}
    assert combos.issubset({
        ("horizontal", "input_first"),
        ("horizontal", "output_first"),
        ("vertical", "input_first"),
        ("vertical", "output_first"),
    })


def test_legacy_wire_card_intersection_is_a_hard_rejection():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "wire-block-map",
        "productId": "fixture-product",
        "canvasNodes": [
            {
                "nodeId": "anchor",
                "nodeKind": "process_step",
                "position": {"x": 0, "y": 0},
                "portOrientation": "vertical",
                "portOrder": "output_first",
            },
            {
                "nodeId": "obstacle",
                "nodeKind": "process_step",
                "position": {"x": 220, "y": -60},
            },
        ],
        "canvasEdges": [],
        "canvasGroups": [],
    }
    scene = compile_spatial_scene(process_map)
    result = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor", connection_direction="outgoing", limit=3
    )
    assert result["rejectionCounts"].get("edge_node_intersection", 0) > 0


def test_candidate_cap_never_exceeds_contract_limit():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    contract = load_spatial_contract()
    assert result["evaluatedCount"] <= contract["limits"]["maximumCandidates"]
    assert result["evaluatedCount"] <= 96


def test_non_finite_target_kind_is_rejected_without_raising():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(scene, target_kind="not_a_real_kind")
    assert result["candidates"] == []
    assert result["rejectionCounts"] == {"invalid_geometry": 1}


def test_pan_and_zoom_transform_never_alters_candidate_positions():
    scene = compile_spatial_scene(_placement_map())
    baseline = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    for point in scene["nodes"][0]["rect"], scene["nodes"][0]["center"]:
        world_to_viewport(point, {"x": 400, "y": -50, "scale": 0.5})
    unaffected = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    assert baseline == unaffected


def test_stale_obstacle_fingerprint_is_detectable_after_map_edit():
    process_map = _placement_map()
    scene_before = compile_spatial_scene(process_map)
    result_before = generate_placement_candidates(scene_before, target_kind="product_occurrence")

    edited = json.loads(json.dumps(process_map))
    edited["canvasNodes"].append(
        {"nodeId": "new-obstacle", "nodeKind": "process_step", "position": {"x": -400, "y": 60}}
    )
    scene_after = compile_spatial_scene(edited)
    result_after = generate_placement_candidates(scene_after, target_kind="product_occurrence")

    assert result_before["obstacleFingerprint"] != result_after["obstacleFingerprint"]


def test_candidate_identity_fields_are_present_for_staleness_binding():
    scene = compile_spatial_scene(_placement_map())
    result = generate_placement_candidates(
        scene, target_kind="process_step", anchor_node_id="anchor-a", connection_direction="outgoing"
    )
    assert result["spatialEngineVersion"] == PROCESS_MAP_SPATIAL_VERSION
    assert result["candidatePolicyVersion"] == PROCESS_MAP_CANDIDATE_POLICY_VERSION
    assert result["identity"]["mapId"] == "default"
    assert len(result["obstacleFingerprint"]) == 16
    for candidate in result["candidates"]:
        assert "candidateId" in candidate
        assert "position" in candidate
        assert "score" in candidate


def test_existing_node_move_rejects_positions_whose_incident_wire_hits_a_card():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "incident-route-probe",
        "productId": "fixture-product",
        "canvasNodes": [
            {
                "nodeId": "a",
                "nodeKind": "process_step",
                "processType": "operation",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "b",
                "nodeKind": "process_step",
                "processType": "operation",
                "position": {"x": -480, "y": -240},
            },
            {
                "nodeId": "obstacle",
                "nodeKind": "process_step",
                "processType": "operation",
                "position": {"x": -240, "y": -480},
            },
        ],
        "canvasEdges": [
            {
                "edgeId": "edge-a-b",
                "logicalConnectionId": "edge-a-b",
                "from": {"nodeId": "a", "port": "out"},
                "to": {"nodeId": "b", "port": "in"},
                "kind": "precedence",
            }
        ],
        "canvasGroups": [],
    }
    result = generate_placement_candidates(
        compile_spatial_scene(process_map),
        target_kind="process_step",
        target_node_id="b",
    )
    assert result["candidates"]
    assert result["rejectionCounts"].get("edge_node_intersection", 0) > 0
    for candidate in result["candidates"]:
        moved = deepcopy(process_map)
        target = next(node for node in moved["canvasNodes"] if node["nodeId"] == "b")
        target["position"] = candidate["position"]
        target["portOrientation"] = candidate["portOrientation"]
        target["portOrder"] = candidate["portOrder"]
        diagnostics = diagnose_spatial_scene(compile_spatial_scene(moved))
        assert diagnostics["metrics"]["edgeNodeIntersections"] == 0


def test_anchorless_candidates_prefer_the_visible_world_rectangle():
    scene = compile_spatial_scene(_placement_map())
    visible = {"x": 900, "y": 500, "width": 900, "height": 600}
    result = generate_placement_candidates(
        scene,
        target_kind="product_occurrence",
        visible_world_rect=visible,
    )
    assert result["candidates"]
    first = result["candidates"][0]
    assert first["score"]["regionPreference"] == 0
    assert first["position"]["x"] >= visible["x"]
    assert first["position"]["y"] >= visible["y"]
    assert first["position"]["x"] + 270 <= visible["x"] + visible["width"]
    assert first["position"]["y"] + 146 <= visible["y"] + visible["height"]


def _phase4_route_map() -> dict:
    return json.loads(ROUTE_FIXTURE_PATH.read_text(encoding="ascii"))["processMap"]


def test_phase4_route_matches_shared_golden_fixture():
    fixture = json.loads(ROUTE_FIXTURE_PATH.read_text(encoding="ascii"))
    actual = route_orthogonal_edge(
        compile_spatial_scene(fixture["processMap"]),
        "route-me",
    )
    assert actual == fixture["expectedRoute"]


def test_phase4_router_is_deterministic_and_avoids_non_endpoint_cards():
    process_map = _phase4_route_map()
    scene = compile_spatial_scene(process_map)
    first = route_orthogonal_edge(scene, "route-me")
    second = route_orthogonal_edge(scene, "route-me")
    assert first == second
    assert first["accepted"] is True
    assert first["mode"] == "orthogonal_auto"
    assert first["metrics"]["bends"] >= 2
    assert len(first["obstacleFingerprint"]) == 16

    applied = apply_orthogonal_route(process_map, "route-me")
    assert applied["accepted"] is True
    routed_edge = next(edge for edge in applied["map"]["canvasEdges"] if edge["edgeId"] == "route-me")
    assert routed_edge["routing"]["waypoints"] == first["waypoints"]
    assert applied["map"]["layoutVersion"] == 3
    legacy = next(edge for edge in applied["map"]["canvasEdges"] if edge["edgeId"] == "legacy-control")
    assert "routing" not in legacy
    diagnostics = diagnose_spatial_scene(compile_spatial_scene(applied["map"]))
    route_problem_ids = {
        problem.get("edgeIds", [None])[0]
        for problem in diagnostics["problems"]
        if problem["code"] == "edge_node_intersection" and problem.get("edgeIds")
    }
    assert "route-me" not in route_problem_ids


def test_phase4_auto_route_refreshes_after_geometry_changes_and_manual_route_is_preserved():
    routed = apply_orthogonal_route(_phase4_route_map(), "route-me")["map"]
    routed["canvasEdges"][1]["routing"] = {
        "mode": "orthogonal_manual",
        "routerVersion": 1,
        "waypoints": [{"x": 290, "y": 173}],
        "obstacleFingerprint": "manual-owner",
    }
    before = deepcopy(next(edge for edge in routed["canvasEdges"] if edge["edgeId"] == "route-me")["routing"])
    manual_before = deepcopy(next(edge for edge in routed["canvasEdges"] if edge["edgeId"] == "legacy-control")["routing"])
    obstacle = next(node for node in routed["canvasNodes"] if node["nodeId"] == "obstacle")
    obstacle["position"] = {"x": 330, "y": 220}
    refreshed = refresh_orthogonal_auto_routes(routed)
    assert refreshed["failures"] == []
    auto_after = next(edge for edge in refreshed["map"]["canvasEdges"] if edge["edgeId"] == "route-me")["routing"]
    manual_after = next(edge for edge in refreshed["map"]["canvasEdges"] if edge["edgeId"] == "legacy-control")["routing"]
    assert auto_after["obstacleFingerprint"] != before["obstacleFingerprint"]
    assert manual_after == manual_before


def test_phase4_router_fails_closed_when_the_source_lead_is_blocked():
    process_map = _phase4_route_map()
    blocking = next(node for node in process_map["canvasNodes"] if node["nodeId"] == "obstacle")
    blocking["position"] = {"x": 275, "y": 100}
    result = route_orthogonal_edge(compile_spatial_scene(process_map), "route-me")
    assert result["accepted"] is False
    assert result["failureReason"] == "no_obstacle_free_orthogonal_route"
    assert result["points"] == []


def test_phase5_connection_geometry_is_separate_from_semantic_identity():
    fixture = json.loads(ROUTE_FIXTURE_PATH.read_text(encoding="ascii"))
    process_map = deepcopy(fixture["processMap"])
    route_edge = next(edge for edge in process_map["canvasEdges"] if edge["edgeId"] == "route-me")
    process_map["canvasEdges"] = [
        edge for edge in process_map["canvasEdges"] if edge["edgeId"] != "route-me"
    ]
    suggestion = {
        "suggestionId": "pms-phase5-connection",
        "evidenceFingerprint": "evidence-v1",
        "edge": route_edge,
        "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
    }
    before_map = deepcopy(process_map)
    before_suggestion = deepcopy(suggestion)
    result = spatialize_semantic_suggestions(process_map, [suggestion])
    spatialized = result["suggestions"][0]
    proposal = spatialized["spatialProposal"]
    assert process_map == before_map
    assert suggestion == before_suggestion
    assert spatialized["suggestionId"] == suggestion["suggestionId"]
    assert spatialized["evidenceFingerprint"] == suggestion["evidenceFingerprint"]
    assert proposal["semanticSuggestionId"] == suggestion["suggestionId"]
    assert proposal["semanticEvidenceFingerprint"] == suggestion["evidenceFingerprint"]
    assert proposal["proposalId"] == "pm-sp-51f763ad0640268b"
    assert proposal["accepted"] is True
    assert proposal["route"]["points"] == fixture["expectedRoute"]["points"]
    assert proposal["route"]["waypoints"] == fixture["expectedRoute"]["waypoints"]
    assert result["summary"] == {
        "spatialized": 1,
        "placementProposals": 0,
        "unavailable": 0,
    }


def test_phase5_unplaced_semantic_target_gets_one_card_and_one_routed_wire_proposal():
    process_map = {
        "schemaVersion": 3,
        "layoutVersion": 3,
        "mapId": "phase5-placement",
        "productId": "fixture-product",
        "canvasNodes": [{
            "nodeId": "anchor",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "part-a",
            "position": {"x": 0, "y": 100},
        }],
        "canvasEdges": [],
        "canvasGroups": [],
    }
    suggestion = {
        "suggestionId": "pms-phase5-placement",
        "evidenceFingerprint": "reviewed-sequence-v1",
        "placement": {
            "sourceOccurrenceId": "part-b",
            "nameSnapshot": "Part B",
            "itemIdSnapshot": "PART-B",
            "anchorNodeId": "anchor",
            "connectionDirection": "outgoing",
            "edgeKind": "precedence",
            "edgeId": "phase5-next-edge",
        },
        "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
    }
    first = spatialize_semantic_suggestions(process_map, [suggestion])
    second = spatialize_semantic_suggestions(deepcopy(process_map), [deepcopy(suggestion)])
    assert first == second
    proposal = first["suggestions"][0]["spatialProposal"]
    assert proposal["accepted"] is True
    assert proposal["placement"]["node"]["sourceOccurrenceId"] == "part-b"
    assert proposal["placement"]["metricsAfter"]["nodeOverlaps"] == 0
    assert proposal["edge"]["from"]["nodeId"] == "anchor"
    assert proposal["edge"]["to"]["nodeId"] == proposal["placement"]["node"]["nodeId"]
    assert len(proposal["route"]["points"]) >= 2
    assert first["summary"]["placementProposals"] == 1


def test_phase5_spatial_proposal_changes_after_relevant_geometry_edit():
    process_map = _phase4_route_map()
    route_edge = process_map["canvasEdges"].pop(0)
    suggestion = {
        "suggestionId": "pms-phase5-staleness",
        "evidenceFingerprint": "evidence-v1",
        "edge": route_edge,
        "validation": {"wouldCreateCycle": False},
    }
    first = spatialize_semantic_suggestions(process_map, [suggestion])["suggestions"][0]
    changed = deepcopy(process_map)
    next(node for node in changed["canvasNodes"] if node["nodeId"] == "obstacle")["position"]["y"] += 180
    second = spatialize_semantic_suggestions(changed, [suggestion])["suggestions"][0]
    assert first["suggestionId"] == second["suggestionId"]
    assert first["evidenceFingerprint"] == second["evidenceFingerprint"]
    assert first["spatialProposal"]["proposalId"] != second["spatialProposal"]["proposalId"]


def test_phase7_full_map_arrangement_matches_shared_fixture_and_improves_metric():
    fixture = _arrangement_fixture()
    original = deepcopy(fixture["ungroupedMap"])
    plan = generate_arrangement_plan(original, revision="revision-7")
    assert plan["accepted"] is True
    assert plan["planId"] == fixture["expected"]["ungroupedFullPlanId"]
    assert original == fixture["ungroupedMap"]
    assert plan["metricsAfter"]["hardViolationCount"] < plan["metricsBefore"]["hardViolationCount"]
    assert plan["hardViolationsAdded"] == []
    assert plan["pinnedNodeIds"] == ["c"]
    locked_before = next(node for node in original["canvasNodes"] if node["nodeId"] == "c")
    locked_after = next(node for node in plan["proposedMap"]["canvasNodes"] if node["nodeId"] == "c")
    assert locked_after == locked_before


def test_phase7_group_arrangement_preserves_frame_and_locked_member():
    fixture = _arrangement_fixture()
    process_map = deepcopy(fixture["groupMap"])
    plan = generate_arrangement_plan(process_map, scope="group", group_id="g")
    assert plan["accepted"] is True
    assert plan["planId"] == fixture["expected"]["groupPlanId"]
    assert plan["scope"] == {
        "kind": "group",
        "nodeIds": ["a", "b", "c"],
        "groupId": "g",
    }
    assert plan["proposedMap"]["canvasGroups"] == process_map["canvasGroups"]
    assert next(
        node for node in plan["proposedMap"]["canvasNodes"] if node["nodeId"] == "c"
    ) == next(node for node in process_map["canvasNodes"] if node["nodeId"] == "c")
    group = process_map["canvasGroups"][0]
    for move in plan["moves"]:
        position = move["to"]["position"]
        assert group["position"]["x"] <= position["x"]
        assert group["position"]["y"] <= position["y"]


def test_phase7_selection_arrangement_moves_only_selected_unlocked_cards():
    fixture = _arrangement_fixture()
    process_map = deepcopy(fixture["ungroupedMap"])
    plan = generate_arrangement_plan(
        process_map,
        scope="selection",
        node_ids=["a", "b", "c"],
        pinned_node_ids=["b"],
    )
    assert all(move["nodeId"] == "a" for move in plan.get("moves", []))
    assert set(plan["pinnedNodeIds"]) == {"b", "c"}
    if plan["accepted"]:
        before_by_id = {node["nodeId"]: node for node in process_map["canvasNodes"]}
        after_by_id = {node["nodeId"]: node for node in plan["proposedMap"]["canvasNodes"]}
        assert after_by_id["b"] == before_by_id["b"]
        assert after_by_id["c"] == before_by_id["c"]


def test_arrangement_preserves_manual_and_locked_positions_by_default():
    fixture = _arrangement_fixture()
    process_map = deepcopy(fixture["ungroupedMap"])
    by_id = {node["nodeId"]: node for node in process_map["canvasNodes"]}
    by_id["a"]["positionMode"] = "manual"
    by_id["b"]["positionMode"] = "auto"
    by_id["c"]["positionMode"] = "locked"
    by_id["c"]["locked"] = True
    plan = generate_arrangement_plan(process_map)
    assert set(plan["pinnedNodeIds"]) == {"a", "c"}
    if plan["accepted"]:
        proposed = {
            node["nodeId"]: node for node in plan["proposedMap"]["canvasNodes"]
        }
        assert proposed["a"]["position"] == by_id["a"]["position"]
        assert proposed["c"]["position"] == by_id["c"]["position"]
        assert all(move["nodeId"] == "b" for move in plan["moves"])


def test_phase7_rejects_cleanups_that_cannot_improve_or_move_any_card():
    fixture = _arrangement_fixture()
    process_map = deepcopy(fixture["ungroupedMap"])
    for node in process_map["canvasNodes"]:
        node["locked"] = True
    plan = generate_arrangement_plan(process_map)
    assert plan["accepted"] is False
    assert plan["failureReason"] == "no_movable_nodes"
    assert plan["moves"] == []
