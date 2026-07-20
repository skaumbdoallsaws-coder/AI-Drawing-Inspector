"""Product-neutral process-map template catalog and instantiation tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import (
    instantiate_template_skeleton,
    process_map_template_skeleton,
)


def _legacy_map() -> dict:
    return {
        "schemaVersion": "fixture-process-map-1",
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "nodes": [
            {"nodeId": "root", "level": 0, "name": "Fixture Product", "parentNodeId": None, "partIds": []},
            {"nodeId": "module", "level": 1, "name": "Module", "parentNodeId": "root", "partIds": ["P-001"]},
            {"nodeId": "part", "level": 3, "name": "Part", "parentNodeId": "module", "partIds": ["P-001"]},
        ],
    }


def _structure() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "occurrences": [
            {"occurrenceId": "root", "parentOccurrenceId": None, "itemId": None, "name": "Fixture Product", "kind": "assembly", "level": 0, "partIds": []},
            {"occurrenceId": "module", "parentOccurrenceId": "root", "itemId": "P-001", "name": "Module", "kind": "subassembly", "level": 1, "partIds": ["P-001"]},
            {"occurrenceId": "part", "parentOccurrenceId": "module", "itemId": "P-001", "name": "Part", "kind": "part", "level": 3, "partIds": ["P-001"]},
        ],
    }


def _authored_map() -> dict:
    return {
        "schemaVersion": 3,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "sourceStructureRevision": "fixture",
        "layoutVersion": 2,
        "canvasNodes": [
            {"nodeId": "occurrence-card", "nodeKind": "product_occurrence", "sourceOccurrenceId": "part", "position": {"x": 0, "y": 0}},
            {"nodeId": "step-machine", "nodeKind": "process_step", "processType": "operation", "name": "Machine", "position": {"x": 300, "y": 0}, "referenceIds": ["machine-1"]},
            {"nodeId": "junction-1", "nodeKind": "junction", "junctionType": "wire_branch", "position": {"x": 520, "y": 40}},
            {"nodeId": "step-inspect", "nodeKind": "process_step", "processType": "inspection", "name": "Inspect", "position": {"x": 720, "y": 0}},
        ],
        "canvasEdges": [
            {"edgeId": "edge-occ-machine", "from": {"nodeId": "occurrence-card", "port": "out"}, "to": {"nodeId": "step-machine", "port": "in"}, "kind": "precedence", "logicalConnectionId": "edge-occ-machine"},
            {"edgeId": "edge-machine-j", "from": {"nodeId": "step-machine", "port": "out"}, "to": {"nodeId": "junction-1", "port": "in"}, "kind": "precedence", "logicalConnectionId": "logical-machine-inspect", "referenceIds": ["standard-1"]},
            {"edgeId": "edge-j-inspect", "from": {"nodeId": "junction-1", "port": "out"}, "to": {"nodeId": "step-inspect", "port": "in"}, "kind": "precedence", "logicalConnectionId": "logical-machine-inspect", "referenceIds": ["standard-1"]},
        ],
        "canvasGroups": [
            {"groupId": "group-cell", "label": "Cell", "position": {"x": 250, "y": -50}, "size": {"width": 760, "height": 320}, "colorKey": "orange", "memberNodeIds": ["occurrence-card", "step-machine", "junction-1", "step-inspect"], "collapsed": False}
        ],
        "referenceCatalog": [
            {"referenceId": "machine-1", "kind": "machine", "name": "Mill"},
            {"referenceId": "standard-1", "kind": "standard", "name": "Inspection standard", "identifier": "STD-1"},
            {"referenceId": "unused-tool", "kind": "tool", "name": "Unused"},
        ],
        "viewport": {"x": 20, "y": 30, "scale": 0.9},
    }


@pytest.fixture
def template_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "training"
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    (product_dir / "fixture_process_map_working_draft.json").write_text(
        json.dumps(_legacy_map(), indent=2) + "\n", encoding="ascii"
    )
    (product_dir / "fixture_product_product_structure.json").write_text(
        json.dumps(_structure(), indent=2) + "\n", encoding="ascii"
    )
    (product_dir / "fixture_unique_items.json").write_text(
        json.dumps({"items": [{"partId": "P-001"}]}, indent=2) + "\n", encoding="ascii"
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    return {"root": root, "productDir": product_dir}


def _client() -> TestClient:
    return TestClient(server.app)


def _seed_authored_map(client: TestClient) -> dict:
    loaded = client.get("/api/training/process-maps/fixture-product/default").json()
    authored = _authored_map()
    authored.update({
        key: loaded["map"][key]
        for key in ("mapId", "displayName", "association", "status", "createdAt", "updatedAt")
        if key in loaded["map"]
    })
    authored["sourceStructureRevision"] = loaded["structureRevision"]
    saved = client.put(
        "/api/training/process-maps/fixture-product/default",
        json={"map": authored, "baseRevision": loaded["revision"]},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def _all_graph_ids(value: dict) -> set[str]:
    result = {
        node["nodeId"] for node in value.get("canvasNodes", [])
    } | {
        edge["edgeId"] for edge in value.get("canvasEdges", [])
    } | {
        edge.get("logicalConnectionId") for edge in value.get("canvasEdges", [])
        if edge.get("logicalConnectionId")
    } | {
        group["groupId"] for group in value.get("canvasGroups", [])
    } | {
        reference["referenceId"] for reference in value.get("referenceCatalog", [])
    }
    return result


def test_template_skeleton_strips_occurrences_and_incident_edges_without_mutating_source():
    source = _authored_map()
    before = deepcopy(source)
    skeleton, dropped = process_map_template_skeleton(source)
    assert source == before
    assert all(node["nodeKind"] != "product_occurrence" for node in skeleton["canvasNodes"])
    assert {node["nodeId"] for node in skeleton["canvasNodes"]} == {
        "step-machine", "junction-1", "step-inspect"
    }
    assert {edge["edgeId"] for edge in skeleton["canvasEdges"]} == {
        "edge-machine-j", "edge-j-inspect"
    }
    assert skeleton["canvasGroups"][0]["memberNodeIds"] == [
        "step-machine", "junction-1", "step-inspect"
    ]
    assert {item["referenceId"] for item in skeleton["referenceCatalog"]} == {
        "machine-1", "standard-1"
    }
    assert dropped == {"productOccurrences": 1, "nodes": 1, "edges": 1}


def test_instantiation_regenerates_every_graph_identifier_and_preserves_topology():
    skeleton, _ = process_map_template_skeleton(_authored_map())
    instantiated, remap = instantiate_template_skeleton(skeleton)
    assert _all_graph_ids(skeleton).isdisjoint(_all_graph_ids(instantiated))
    assert len(remap["nodes"]) == 3
    assert len(remap["edges"]) == 2
    assert len(remap["logicalConnections"]) == 1
    assert len(remap["groups"]) == 1
    assert len(remap["references"]) == 2
    junction = next(node for node in instantiated["canvasNodes"] if node["nodeKind"] == "junction")
    incident = [
        edge for edge in instantiated["canvasEdges"]
        if junction["nodeId"] in {edge["from"]["nodeId"], edge["to"]["nodeId"]}
    ]
    assert len(incident) == 2
    assert len({edge["logicalConnectionId"] for edge in incident}) == 1


def test_save_as_template_is_isolated_from_product_map_directory(template_product: dict):
    client = _client()
    saved = _seed_authored_map(client)
    before = {
        path.relative_to(template_product["productDir"]).as_posix(): path.read_bytes()
        for path in template_product["productDir"].rglob("*") if path.is_file()
    }
    response = client.post(
        "/api/training/process-maps/fixture-product/default/save-as-template",
        json={
            "baseRevision": saved["revision"],
            "displayName": "Machine and inspect",
            "description": "Product-neutral cell skeleton.",
            "templateId": "pmt-machine-inspect",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["template"]["templateId"] == "pmt-machine-inspect"
    assert payload["dropped"]["productOccurrences"] == 1
    after = {
        path.relative_to(template_product["productDir"]).as_posix(): path.read_bytes()
        for path in template_product["productDir"].rglob("*") if path.is_file()
    }
    assert after == before
    template_asset = (
        template_product["root"] / "_templates" / "process_maps" / "pmt-machine-inspect.json"
    )
    assert template_asset.is_file()
    assert not list(template_product["productDir"].rglob("*template*"))
    collision = client.post(
        "/api/training/process-maps/fixture-product/default/save-as-template",
        json={
            "baseRevision": saved["revision"],
            "displayName": "Duplicate identity",
            "templateId": "pmt-machine-inspect",
        },
    )
    assert collision.status_code == 422
    assert collision.json()["findings"][0]["code"] == "template_id_exists"


def test_template_list_and_clone_endpoint_create_only_remapped_skeleton(template_product: dict):
    client = _client()
    saved = _seed_authored_map(client)
    made = client.post(
        "/api/training/process-maps/fixture-product/default/save-as-template",
        json={
            "baseRevision": saved["revision"],
            "displayName": "Reusable cell",
            "templateId": "pmt-reusable-cell",
        },
    )
    assert made.status_code == 200, made.text
    skeleton = made.json()["template"]["skeleton"]
    listed = client.get("/api/training/process-map-templates")
    assert listed.status_code == 200
    assert listed.json()["templates"][0]["templateId"] == "pmt-reusable-cell"

    cloned = client.post(
        "/api/training/process-maps/fixture-product/from-template",
        json={"templateId": "pmt-reusable-cell", "displayName": "Cell from template"},
    )
    assert cloned.status_code == 200, cloned.text
    payload = cloned.json()
    process_map = payload["map"]
    assert process_map["displayName"] == "Cell from template"
    assert process_map["status"] == "draft"
    assert all(node["nodeKind"] != "product_occurrence" for node in process_map["canvasNodes"])
    assert _all_graph_ids(skeleton).isdisjoint(_all_graph_ids(process_map))
    assert payload["templateId"] == "pmt-reusable-cell"
    assert not [item for item in payload["findings"] if item["severity"] == "error"]
    reloaded = client.get(
        f"/api/training/process-maps/fixture-product/{process_map['mapId']}"
    )
    assert reloaded.status_code == 200
    assert reloaded.json()["map"] == process_map


def test_template_routes_obey_feature_flag(template_product: dict, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    client = _client()
    assert client.get("/api/training/process-map-templates").status_code == 404
    assert client.post(
        "/api/training/process-maps/fixture-product/from-template",
        json={"templateId": "pmt-missing"},
    ).status_code == 404
