"""Builder process-map operations, authorization, CAS, and revert tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import (
    ProcessMapOperationError,
    apply_process_map_operations,
    authorize_process_map_asset_write,
    load_asset_write_authorization_contract,
    reset_process_map_builder_state_for_tests,
    resolve_process_map_receipts,
)


def _legacy_map() -> dict:
    return {
        "schemaVersion": "fixture-process-map-1",
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "nodes": [
            {
                "nodeId": "root",
                "level": 0,
                "name": "Fixture Product",
                "parentNodeId": None,
                "partIds": [],
            },
            {
                "nodeId": "module",
                "level": 1,
                "name": "Fixture Module",
                "parentNodeId": "root",
                "partIds": ["P-001"],
            },
            {
                "nodeId": "part-a",
                "level": 3,
                "name": "Fixture Part A",
                "parentNodeId": "module",
                "partIds": ["P-001"],
            },
            {
                "nodeId": "part-b",
                "level": 3,
                "name": "Fixture Part B",
                "parentNodeId": "module",
                "partIds": ["P-002"],
            },
        ],
    }


def _structure() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "occurrences": [
            {
                "occurrenceId": "root",
                "parentOccurrenceId": None,
                "itemId": None,
                "name": "Fixture Product",
                "kind": "assembly",
                "level": 0,
                "partIds": [],
            },
            {
                "occurrenceId": "module",
                "parentOccurrenceId": "root",
                "itemId": "P-001",
                "name": "Fixture Module",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["P-001"],
            },
            {
                "occurrenceId": "part-a",
                "parentOccurrenceId": "module",
                "itemId": "P-001",
                "name": "Fixture Part A",
                "kind": "part",
                "level": 3,
                "partIds": ["P-001"],
            },
            {
                "occurrenceId": "part-b",
                "parentOccurrenceId": "module",
                "itemId": "P-002",
                "name": "Fixture Part B",
                "kind": "part",
                "level": 3,
                "partIds": ["P-002"],
            },
        ],
    }


def _placement_map() -> dict:
    return {
        "schemaVersion": 3,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "sourceStructureRevision": "fixture",
        "layoutVersion": 2,
        "canvasNodes": [],
        "canvasEdges": [],
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _semantic_plan() -> dict:
    return {
        "schemaVersion": 1,
        "planId": "fixture-module-plan",
        "scope": {
            "assemblyOccurrenceId": "module",
            "label": "Fixture Module",
        },
        "requiredOccurrences": [
            {"occurrenceId": "part-a", "quantity": 1},
            {"occurrenceId": "part-b", "quantity": 1},
        ],
        "operations": [
            {
                "id": "op-join-parts",
                "operationType": "operation",
                "label": "Join fixture parts",
                "inputs": [
                    {"ref": "part-a", "type": "occurrence"},
                    {"ref": "part-b", "type": "occurrence"},
                ],
                "output": {"ref": "module", "type": "occurrence"},
                "branchId": "main",
                "stageIndex": 1,
                "knowledgeStatus": "inferred",
                "evidence": [
                    {
                        "sourceType": "domain_heuristic",
                        "sourceRef": "fixture-assembly",
                        "supports": "candidate-operation",
                    }
                ],
                "properties": {},
            }
        ],
        "intermediateResults": [],
        "junctions": [],
        "branches": [{"id": "main", "label": "Main assembly"}],
        "evidence": [],
        "assumptions": [],
        "layoutHints": [
            {"ref": "op-join-parts", "branchId": "main", "stageIndex": 1}
        ],
        "unresolvedQuestions": [],
    }


@pytest.fixture
def builder_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "training"
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    legacy = product_dir / "fixture_process_map_working_draft.json"
    legacy.write_text(json.dumps(_legacy_map(), indent=2) + "\n", encoding="ascii")
    (product_dir / "fixture_product_product_structure.json").write_text(
        json.dumps(_structure(), indent=2) + "\n", encoding="ascii"
    )
    (product_dir / "fixture_unique_items.json").write_text(
        json.dumps({"items": [{"partId": "P-001"}, {"partId": "P-002"}]}, indent=2) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    monkeypatch.setenv("INSPECTORPRO_BUILDER_WRITE", "1")
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_SPATIAL_PLACEMENT", "1")
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_AUTO_ROUTING", "1")
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE", "1")
    reset_process_map_builder_state_for_tests()
    yield {"root": root, "productDir": product_dir}
    reset_process_map_builder_state_for_tests()


def _client() -> TestClient:
    return TestClient(server.app)


def _loaded(client: TestClient) -> dict:
    response = client.get("/api/training/process-maps/fixture-product/default")
    assert response.status_code == 200, response.text
    return response.json()


def _proposal(client: TestClient, revision: str, operations: list[dict]) -> dict:
    response = client.post(
        "/api/builder/process-maps/fixture-product/default/proposals",
        json={"baseRevision": revision, "operations": operations},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(client: TestClient, proposal: dict, key: str) -> dict:
    body = {
        "productId": "fixture-product",
        "mapId": "default",
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
        "userId": "fixture-user",
        "sessionId": "fixture-session",
        "idempotencyKey": key,
        "explicitApproval": True,
    }
    if proposal.get("spatialBindingHash"):
        body["spatialBindingHash"] = proposal["spatialBindingHash"]
    if proposal.get("semanticBindingHash"):
        body["semanticBindingHash"] = proposal["semanticBindingHash"]
    response = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client: TestClient, proposal: dict, approval: dict, key: str):
    body = {
        "approvalToken": approval["approvalToken"],
        "productId": "fixture-product",
        "mapId": "default",
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
        "userId": "fixture-user",
        "sessionId": "fixture-session",
        "idempotencyKey": key,
    }
    if proposal.get("spatialBindingHash"):
        body["spatialBindingHash"] = proposal["spatialBindingHash"]
    if proposal.get("semanticBindingHash"):
        body["semanticBindingHash"] = proposal["semanticBindingHash"]
    return client.post(
        "/api/builder/process-map-apply",
        json=body,
    )


def _approved_edit(client: TestClient, revision: str, operations: list[dict], key: str) -> dict:
    proposal = _proposal(client, revision, operations)
    approval = _approve(client, proposal, key)
    response = _apply(client, proposal, approval, key)
    assert response.status_code == 200, response.text
    return response.json()


def test_shared_asset_write_contract_cases_match_server_policy():
    contract = load_asset_write_authorization_contract()
    assert contract["contractVersion"] == 1
    assert len(contract["cases"]) >= 6
    for case in contract["cases"]:
        result = authorize_process_map_asset_write(case["request"])
        assert result["authorized"] is case["authorized"], case["id"]
        assert result["reason"] == case["reason"], case["id"]


def test_semantic_preview_is_revision_bound_and_commits_with_rich_receipt(
    builder_product,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_SEMANTIC_GENERATION", "1")
    client = _client()
    loaded = _loaded(client)
    response = client.post(
        "/api/builder/process-maps/fixture-product/default/semantic-proposals",
        json={
            "baseRevision": loaded["revision"],
            "scopeOccurrenceId": "module",
            "semanticPlan": _semantic_plan(),
        },
    )
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["managedProposalType"] == "semantic_process_map"
    assert proposal["semanticBindingHash"]
    assert proposal["summary"]["requiredOccurrenceCount"] == 2
    assert proposal["summary"]["operationCount"] == 1
    assert proposal["createdIds"]["nodeIds"]
    assert proposal["preview"]["nodes"]

    approval = _approve(client, proposal, "semantic-preview-apply")
    applied_response = _apply(
        client,
        proposal,
        approval,
        "semantic-preview-apply",
    )
    assert applied_response.status_code == 200, applied_response.text
    applied = applied_response.json()
    receipt = applied["receipt"]
    assert receipt["semanticBindingHash"] == proposal["semanticBindingHash"]
    assert receipt["createdIds"] == proposal["createdIds"]
    assert receipt["revision"] == applied["revision"]
    assert receipt["warnings"] == proposal["warnings"]
    assert receipt["unresolvedItems"] == proposal["unresolvedItems"]
    resolved = resolve_process_map_receipts(
        [
            {"receiptId": "pmr-forged", "warnings": ["browser supplied"]},
            {"receiptId": receipt["receiptId"], "warnings": ["tampered"]},
        ]
    )
    assert resolved == [receipt]
    assert all(
        node["positionMode"] == "auto"
        for node in applied["map"]["canvasNodes"]
    )


def test_domain_operations_are_immutable_and_cover_core_edit_vocabulary():
    original = _placement_map()
    operations = [
        {"op": "place_occurrence", "occurrenceId": "part-a", "nodeId": "node-a", "position": {"x": 20, "y": 30}},
        {"op": "add_process_step", "nodeId": "step-machine", "processType": "operation", "name": "Machine part", "position": {"x": 360, "y": 30}},
        {"op": "connect", "edgeId": "edge-a-step", "fromNodeId": "node-a", "toNodeId": "step-machine"},
        {"op": "move_node", "nodeId": "step-machine", "position": {"x": 390, "y": 80}},
        {"op": "retype_step", "nodeId": "step-machine", "processType": "inspection"},
        {"op": "set_port_layout", "nodeId": "step-machine", "orientation": "vertical", "order": "output_first"},
        {"op": "set_label", "nodeId": "node-a", "label": "Primary part"},
        {"op": "set_note", "nodeId": "step-machine", "note": "Verify before release."},
        {"op": "add_group", "groupId": "group-cell", "label": "Cell 1", "position": {"x": 0, "y": 0}, "size": {"width": 760, "height": 300}, "memberNodeIds": ["node-a", "step-machine"]},
        {"op": "edit_group", "groupId": "group-cell", "colorKey": "blue", "description": "Primary cell"},
        {"op": "attach_reference", "targetType": "node", "targetId": "step-machine", "reference": {"referenceId": "ref-machine", "kind": "machine", "name": "5-axis mill"}},
    ]
    result = apply_process_map_operations(original, _structure(), operations)
    assert original == _placement_map()
    assert result["changed"] is True
    assert not [item for item in result["findings"] if item["severity"] == "error"]
    step = next(node for node in result["map"]["canvasNodes"] if node["nodeId"] == "step-machine")
    assert step["processType"] == "inspection"
    assert step["portOrientation"] == "vertical"
    assert step["referenceIds"] == ["ref-machine"]
    assert result["map"]["canvasGroups"][0]["memberNodeIds"] == ["node-a", "step-machine"]


def test_domain_operations_create_semantic_junctions_and_stage_details():
    original = _placement_map()
    result = apply_process_map_operations(
        original,
        _structure(),
        [
            {
                "op": "add_process_step",
                "nodeId": "stage-install",
                "processType": "operation",
                "name": "Install panels",
                "position": {"x": 120, "y": 80},
                "properties": {"duration": "12 min"},
            },
            {
                "op": "set_process_properties",
                "nodeId": "stage-install",
                "properties": {
                    "description": "Install both lower panels.",
                    "torqueRequirements": "10 N m",
                    "inspectionRequirements": "Verify flushness.",
                },
            },
            {
                "op": "add_junction",
                "nodeId": "junction-parallel",
                "junctionType": "parallel_and",
                "position": {"x": 420, "y": 80},
            },
        ],
    )
    assert original == _placement_map()
    assert not [item for item in result["findings"] if item["severity"] == "error"]
    stage = next(node for node in result["map"]["canvasNodes"] if node["nodeId"] == "stage-install")
    junction = next(
        node for node in result["map"]["canvasNodes"]
        if node["nodeId"] == "junction-parallel"
    )
    assert stage["properties"] == {
        "description": "Install both lower panels.",
        "torqueRequirements": "10 N m",
        "inspectionRequirements": "Verify flushness.",
    }
    assert junction["junctionType"] == "parallel_and"


def test_split_delete_and_reference_detach_operations_preserve_valid_topology():
    base = _placement_map()
    seeded = apply_process_map_operations(
        base,
        _structure(),
        [
            {"op": "add_process_step", "nodeId": "a", "processType": "operation", "name": "A", "position": {"x": 0, "y": 0}},
            {"op": "add_process_step", "nodeId": "b", "processType": "operation", "name": "B", "position": {"x": 400, "y": 0}},
            {"op": "add_process_step", "nodeId": "c", "processType": "inspection", "name": "C", "position": {"x": 180, "y": 220}},
            {"op": "connect", "edgeId": "edge-ab", "fromNodeId": "a", "toNodeId": "b"},
        ],
    )["map"]
    split = apply_process_map_operations(
        seeded,
        _structure(),
        [{
            "op": "split_edge_with_junction",
            "targetEdgeId": "edge-ab",
            "sourceNodeId": "c",
            "junctionNodeId": "junction-1",
            "firstEdgeId": "edge-a-j",
            "secondEdgeId": "edge-j-b",
            "branchEdgeId": "edge-c-j",
            "position": {"x": 220, "y": 40},
        }],
    )
    assert len(split["map"]["canvasEdges"]) == 3
    deleted = apply_process_map_operations(
        split["map"], _structure(), [{"op": "delete_edge", "edgeId": "edge-c-j"}]
    )
    assert not any(node.get("nodeKind") == "junction" for node in deleted["map"]["canvasNodes"])
    assert len(deleted["map"]["canvasEdges"]) == 1


def test_deleting_a_branch_never_collapses_a_semantic_merge_junction():
    seeded = apply_process_map_operations(
        _placement_map(),
        _structure(),
        [
            {"op": "add_process_step", "nodeId": "a", "processType": "operation", "name": "A", "position": {"x": 0, "y": 0}},
            {"op": "add_process_step", "nodeId": "b", "processType": "operation", "name": "B", "position": {"x": 500, "y": 0}},
            {"op": "add_process_step", "nodeId": "c", "processType": "operation", "name": "C", "position": {"x": 0, "y": 220}},
            {"op": "add_junction", "nodeId": "merge", "junctionType": "merge", "position": {"x": 360, "y": 73}},
            {"op": "connect", "edgeId": "a-merge", "logicalConnectionId": "trunk", "fromNodeId": "a", "toNodeId": "merge"},
            {"op": "connect", "edgeId": "merge-b", "logicalConnectionId": "trunk", "fromNodeId": "merge", "toNodeId": "b"},
            {"op": "connect", "edgeId": "c-merge", "fromNodeId": "c", "toNodeId": "merge"},
        ],
    )["map"]
    result = apply_process_map_operations(
        seeded,
        _structure(),
        [{"op": "delete_edge", "edgeId": "c-merge"}],
    )
    assert any(
        node.get("nodeId") == "merge" and node.get("junctionType") == "merge"
        for node in result["map"]["canvasNodes"]
    )
    assert {
        (edge["from"]["nodeId"], edge["to"]["nodeId"])
        for edge in result["map"]["canvasEdges"]
    } == {("a", "merge"), ("merge", "b")}


def test_unknown_operation_fails_closed_without_mutating_input():
    process_map = _placement_map()
    before = deepcopy(process_map)
    with pytest.raises(ProcessMapOperationError) as caught:
        apply_process_map_operations(process_map, _structure(), [{"op": "write_json"}])
    assert caught.value.code == "unknown_process_map_operation"
    assert process_map == before


def test_spatial_operations_cover_lock_policy_and_routing_without_mutation():
    source = _placement_map()
    result = apply_process_map_operations(
        source,
        _structure(),
        [
            {"op": "add_process_step", "nodeId": "a", "processType": "operation", "name": "A", "position": {"x": 0, "y": 0}},
            {"op": "add_process_step", "nodeId": "b", "processType": "inspection", "name": "B", "position": {"x": 420, "y": 0}},
            {"op": "connect", "edgeId": "ab", "fromNodeId": "a", "toNodeId": "b"},
            {"op": "set_node_locked", "nodeId": "a", "locked": True},
            {"op": "set_layout_policy", "policy": {"flowDirection": "left_to_right", "routeMode": "orthogonal_auto", "gridSize": 20}},
            {"op": "set_edge_routing", "edgeId": "ab", "routing": {"mode": "orthogonal_auto", "routerVersion": 1, "waypoints": [{"x": 300, "y": 73}], "obstacleFingerprint": "a" * 64}},
        ],
    )
    assert source == _placement_map()
    node = next(item for item in result["map"]["canvasNodes"] if item["nodeId"] == "a")
    edge = next(item for item in result["map"]["canvasEdges"] if item["edgeId"] == "ab")
    assert node["locked"] is True
    assert result["map"]["layoutPolicy"]["gridSize"] == 20
    assert edge["routing"]["mode"] == "orthogonal_auto"
    cleared = apply_process_map_operations(
        result["map"], _structure(), [{"op": "clear_edge_routing", "edgeId": "ab"}]
    )
    assert "routing" not in cleared["map"]["canvasEdges"][0]


def test_builder_accepts_user_authored_polyline_without_obstacle_fingerprint():
    source = _placement_map()
    result = apply_process_map_operations(
        source,
        _structure(),
        [
            {
                "op": "add_process_step",
                "nodeId": "manual-a",
                "processType": "operation",
                "name": "Manual A",
                "position": {"x": 0, "y": 0},
            },
            {
                "op": "add_process_step",
                "nodeId": "manual-b",
                "processType": "output",
                "name": "Manual B",
                "position": {"x": 640, "y": 220},
            },
            {
                "op": "connect",
                "edgeId": "manual-ab",
                "fromNodeId": "manual-a",
                "toNodeId": "manual-b",
            },
            {
                "op": "set_edge_routing",
                "edgeId": "manual-ab",
                "routing": {
                    "mode": "polyline_manual",
                    "routerVersion": 1,
                    "waypoints": [{"x": 310, "y": 260}, {"x": 470, "y": 120}],
                },
            },
        ],
    )
    routing = result["map"]["canvasEdges"][0]["routing"]
    assert source == _placement_map()
    assert result["map"]["layoutVersion"] == 3
    assert routing == {
        "mode": "polyline_manual",
        "routerVersion": 1,
        "waypoints": [{"x": 310.0, "y": 260.0}, {"x": 470.0, "y": 120.0}],
    }


def test_spatial_inspection_and_proposal_are_read_only_and_hide_coordinates(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    canonical = builder_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    inspected = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-inspection",
        json={"revision": loaded["revision"], "scopeIds": []},
    )
    assert inspected.status_code == 200, inspected.text
    payload = inspected.json()
    assert "worldBounds" not in payload and "nodes" not in payload
    assert canonical.read_bytes() == before

    proposed = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-proposals",
        json={
            "baseRevision": loaded["revision"],
            "tool": "propose_process_map_node_placement",
            "request": {"targetKind": "process_step", "processType": "operation", "name": "Machine part"},
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["wouldSave"] is True
    assert len(proposal["spatialBindingHash"]) == 64
    assert proposal["summary"]["message"] == "Placed Machine part."
    assert len(proposal["preview"]["nodes"]) == 1
    assert canonical.read_bytes() == before


def test_spatial_tool_rejects_model_authored_geometry(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    response = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-proposals",
        json={
            "baseRevision": loaded["revision"],
            "tool": "propose_process_map_node_placement",
            "request": {
                "targetKind": "process_step",
                "processType": "operation",
                "name": "Injected",
                "position": {"x": 999, "y": 999},
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "model_geometry_not_allowed"


def test_spatial_approval_binds_preview_and_returns_grounded_receipt(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    proposal_response = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-proposals",
        json={
            "baseRevision": loaded["revision"],
            "tool": "propose_process_map_node_placement",
            "request": {"targetKind": "product_occurrence", "occurrenceId": "part-a"},
        },
    )
    assert proposal_response.status_code == 200, proposal_response.text
    proposal = proposal_response.json()
    missing_binding = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json={
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": proposal["baseRevision"],
            "diffHash": proposal["diffHash"],
            "userId": "fixture-user",
            "sessionId": "fixture-session",
            "idempotencyKey": "spatial-missing-binding",
            "explicitApproval": True,
        },
    )
    assert missing_binding.status_code == 403
    assert missing_binding.json()["error"] == "approval_binding_mismatch"

    key = "spatial-exact-binding"
    approval = _approve(client, proposal, key)
    applied = _apply(client, proposal, approval, key)
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["receipt"]["spatialBindingHash"] == proposal["spatialBindingHash"]
    assert payload["receipt"]["outcome"]["message"] == "Placed Fixture Part A."
    assert any(node.get("sourceOccurrenceId") == "part-a" for node in payload["map"]["canvasNodes"])


def test_agent_layout_write_flag_blocks_only_spatial_writes(
    builder_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = _client()
    loaded = _loaded(client)
    proposal_response = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-proposals",
        json={
            "baseRevision": loaded["revision"],
            "tool": "propose_process_map_node_placement",
            "request": {"targetKind": "product_occurrence", "occurrenceId": "part-a"},
        },
    )
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE", raising=False)

    inspection = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-inspection",
        json={"revision": loaded["revision"], "scopeIds": []},
    )
    assert inspection.status_code == 200
    denied = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json={
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": proposal["baseRevision"],
            "diffHash": proposal["diffHash"],
            "spatialBindingHash": proposal["spatialBindingHash"],
            "userId": "fixture-user",
            "sessionId": "fixture-session",
            "idempotencyKey": "spatial-write-flag-off",
            "explicitApproval": True,
        },
    )
    assert denied.status_code == 404
    assert _loaded(client)["revision"] == loaded["revision"]

    generic = _proposal(
        client,
        loaded["revision"],
        [{
            "op": "add_process_step",
            "nodeId": "generic-step",
            "processType": "operation",
            "name": "Generic Builder step",
            "position": {"x": 100, "y": 100},
        }],
    )
    approval = _approve(client, generic, "generic-write-with-agent-layout-off")
    applied = _apply(client, generic, approval, "generic-write-with-agent-layout-off")
    assert applied.status_code == 200


def test_spatial_apply_rejects_altered_binding_and_wrong_identity(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    proposal = client.post(
        "/api/builder/process-maps/fixture-product/default/spatial-proposals",
        json={
            "baseRevision": loaded["revision"],
            "tool": "propose_process_map_node_placement",
            "request": {"targetKind": "product_occurrence", "occurrenceId": "part-a"},
        },
    ).json()
    key = "spatial-altered-binding"
    approval = _approve(client, proposal, key)
    wrong_binding = _apply(client, {**proposal, "spatialBindingHash": "f" * 64}, approval, key)
    assert wrong_binding.status_code == 403
    assert wrong_binding.json()["error"] == "approval_binding_mismatch"

    wrong_user_body = {
        "approvalToken": approval["approvalToken"],
        "productId": "fixture-product",
        "mapId": "default",
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
        "spatialBindingHash": proposal["spatialBindingHash"],
        "userId": "different-user",
        "sessionId": "fixture-session",
        "idempotencyKey": key,
    }
    wrong_user = client.post("/api/builder/process-map-apply", json=wrong_user_body)
    assert wrong_user.status_code == 403
    assert wrong_user.json()["error"] == "approval_binding_mismatch"

    applied = _apply(client, proposal, approval, key)
    assert applied.status_code == 200
    replay = _apply(client, proposal, approval, key)
    assert replay.status_code == 409
    assert replay.json()["error"] == "idempotency_replay"


def test_propose_is_read_only_and_show_diff_is_stable(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    canonical = builder_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    proposal = _proposal(
        client,
        loaded["revision"],
        [{"op": "add_process_step", "nodeId": "inspect", "processType": "inspection", "name": "Inspect", "position": {"x": 500, "y": 200}}],
    )
    assert proposal["wouldSave"] is True
    assert len(proposal["diffHash"]) == 64
    assert canonical.read_bytes() == before
    shown = client.get(f"/api/builder/process-map-proposals/{proposal['proposalId']}")
    assert shown.status_code == 200
    assert shown.json()["diffHash"] == proposal["diffHash"]
    assert canonical.read_bytes() == before


def test_structurally_invalid_batch_never_creates_proposal_or_writes(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    canonical = builder_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    proposal = _proposal(
        client,
        loaded["revision"],
        [
            {"op": "add_process_step", "nodeId": "a", "processType": "operation", "name": "A", "position": {"x": 0, "y": 0}},
            {"op": "add_process_step", "nodeId": "b", "processType": "operation", "name": "B", "position": {"x": 300, "y": 0}},
            {"op": "connect", "edgeId": "ab", "fromNodeId": "a", "toNodeId": "b"},
            {"op": "connect", "edgeId": "ba", "fromNodeId": "b", "toNodeId": "a"},
        ],
    )
    assert proposal["wouldSave"] is False
    assert proposal["proposalId"] is None
    assert "precedence_cycle" in {item["code"] for item in proposal["findings"]}
    assert canonical.read_bytes() == before


def test_approval_requires_flag_explicit_consent_and_exact_binding(builder_product: dict, monkeypatch):
    client = _client()
    loaded = _loaded(client)
    proposal = _proposal(
        client,
        loaded["revision"],
        [{"op": "add_process_step", "processType": "operation", "name": "Build", "position": {"x": 100, "y": 100}}],
    )
    body = {
        "productId": "fixture-product",
        "mapId": "default",
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
        "userId": "fixture-user",
        "sessionId": "fixture-session",
        "idempotencyKey": "fixture-approval-100",
        "explicitApproval": False,
    }
    denied = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve", json=body
    )
    assert denied.status_code == 403
    body["explicitApproval"] = True
    body["diffHash"] = "f" * 64
    mismatch = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve", json=body
    )
    assert mismatch.status_code == 403
    monkeypatch.delenv("INSPECTORPRO_BUILDER_WRITE", raising=False)
    body["diffHash"] = proposal["diffHash"]
    disabled = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve", json=body
    )
    assert disabled.status_code == 404


def test_approved_apply_writes_once_and_replay_is_rejected(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    proposal = _proposal(
        client,
        loaded["revision"],
        [{"op": "add_process_step", "nodeId": "inspect", "processType": "inspection", "name": "Final inspection", "position": {"x": 500, "y": 200}}],
    )
    key = "fixture-apply-once-001"
    approval = _approve(client, proposal, key)
    applied = _apply(client, proposal, approval, key)
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["revision"] != loaded["revision"]
    assert payload["receipt"]["diffHash"] == proposal["diffHash"]
    assert any(node["nodeId"] == "inspect" for node in payload["map"]["canvasNodes"])
    replay = _apply(client, proposal, approval, key)
    assert replay.status_code == 409
    assert replay.json()["error"] == "idempotency_replay"


def test_stale_revision_rejects_approval_before_write(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    proposal = _proposal(
        client,
        loaded["revision"],
        [{"op": "add_process_step", "processType": "operation", "name": "Stale", "position": {"x": 100, "y": 100}}],
    )
    edited = deepcopy(loaded["map"])
    edited["displayName"] = "Changed elsewhere"
    changed = client.put(
        "/api/training/process-maps/fixture-product/default",
        json={"map": edited, "baseRevision": loaded["revision"]},
    )
    assert changed.status_code == 200
    approval = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json={
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": proposal["baseRevision"],
            "diffHash": proposal["diffHash"],
            "userId": "fixture-user",
            "sessionId": "fixture-session",
            "idempotencyKey": "fixture-stale-approval",
            "explicitApproval": True,
        },
    )
    assert approval.status_code == 409
    assert approval.json()["error"] == "revision_conflict"


def test_read_find_validate_and_revision_tools_are_non_mutating(builder_product: dict):
    client = _client()
    loaded = _loaded(client)
    canonical = builder_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    assert client.get("/api/builder/process-maps/fixture-product").status_code == 200
    read = client.get("/api/builder/process-maps/fixture-product/default")
    assert read.status_code == 200
    found = client.get(
        "/api/builder/process-maps/fixture-product/default/find", params={"query": "fixture part"}
    )
    assert found.status_code == 200
    assert {item["kind"] for item in found.json()["matches"]} >= {"occurrence"}
    validated = client.get("/api/builder/process-maps/fixture-product/default/validate")
    assert validated.status_code == 200
    assert validated.json()["revision"] == loaded["revision"]
    revisions = client.get("/api/builder/process-maps/fixture-product/default/revisions")
    assert revisions.status_code == 200
    assert revisions.json()["revisions"][0]["current"] is True
    assert canonical.read_bytes() == before


def test_revert_targets_named_revision_and_creates_new_forward_revision(builder_product: dict):
    client = _client()
    initial = _loaded(client)
    first = _approved_edit(
        client,
        initial["revision"],
        [{"op": "add_process_step", "nodeId": "step-one", "processType": "operation", "name": "Step one", "position": {"x": 100, "y": 100}}],
        "fixture-first-change",
    )
    second = _approved_edit(
        client,
        first["revision"],
        [{"op": "set_label", "nodeId": "step-one", "label": "Renamed step"}],
        "fixture-second-change",
    )
    revisions = client.get(
        "/api/builder/process-maps/fixture-product/default/revisions"
    ).json()["revisions"]
    assert first["revision"] in {item["revision"] for item in revisions}
    proposal_response = client.post(
        "/api/builder/process-maps/fixture-product/default/revert-proposals",
        json={"baseRevision": second["revision"], "targetRevision": first["revision"]},
    )
    assert proposal_response.status_code == 200, proposal_response.text
    proposal = proposal_response.json()
    assert proposal["action"] == "revert_to_revision"
    key = "fixture-revert-forward"
    approval = _approve(client, proposal, key)
    reverted_response = _apply(client, proposal, approval, key)
    assert reverted_response.status_code == 200, reverted_response.text
    reverted = reverted_response.json()
    assert reverted["revision"] not in {first["revision"], second["revision"]}
    step = next(node for node in reverted["map"]["canvasNodes"] if node["nodeId"] == "step-one")
    assert step["name"] == "Step one"
    assert reverted["receipt"]["action"] == "revert_to_revision"
