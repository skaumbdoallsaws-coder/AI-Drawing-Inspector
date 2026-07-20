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
    response = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json={
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": proposal["baseRevision"],
            "diffHash": proposal["diffHash"],
            "userId": "fixture-user",
            "sessionId": "fixture-session",
            "idempotencyKey": key,
            "explicitApproval": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client: TestClient, proposal: dict, approval: dict, key: str):
    return client.post(
        "/api/builder/process-map-apply",
        json={
            "approvalToken": approval["approvalToken"],
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": proposal["baseRevision"],
            "diffHash": proposal["diffHash"],
            "userId": "fixture-user",
            "sessionId": "fixture-session",
            "idempotencyKey": key,
        },
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


def test_unknown_operation_fails_closed_without_mutating_input():
    process_map = _placement_map()
    before = deepcopy(process_map)
    with pytest.raises(ProcessMapOperationError) as caught:
        apply_process_map_operations(process_map, _structure(), [{"op": "write_json"}])
    assert caught.value.code == "unknown_process_map_operation"
    assert process_map == before


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
