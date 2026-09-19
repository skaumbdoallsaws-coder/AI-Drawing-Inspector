"""Deterministic process-map suggestion engine and revision-bound API tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import (
    suggest_process_map_connections,
    validate_placement_map,
)
from ai_inspector.process_map.repository import process_map_revision


def _structure() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "occurrences": [
            {
                "occurrenceId": "root",
                "parentOccurrenceId": None,
                "itemId": "ASSY-001",
                "name": "Fixture Assembly",
                "kind": "assembly",
                "level": 0,
                "partIds": [],
                "suggestedBuildOrder": 0,
            },
            *[
                {
                    "occurrenceId": node_id,
                    "parentOccurrenceId": "root",
                    "itemId": part_id,
                    "name": name,
                    "kind": "part",
                    "level": 1,
                    "partIds": [part_id],
                    "suggestedBuildOrder": order,
                }
                for node_id, part_id, name, order in (
                    ("a", "PART-A", "Part A", 1),
                    ("b", "PART-B", "Part B", 2),
                    ("c", "PART-C", "Part C", 3),
                )
            ],
        ],
    }


def _edge(edge_id: str, source: str, target: str) -> dict:
    return {
        "edgeId": edge_id,
        "logicalConnectionId": edge_id,
        "from": {"nodeId": source, "port": "out"},
        "to": {"nodeId": target, "port": "in"},
        "kind": "precedence",
    }


def _map(edges: list[dict] | None = None) -> dict:
    structure = _structure()
    return {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "default",
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "sourceStructureRevision": process_map_revision(structure),
        "canvasNodes": [
            {
                "nodeId": f"node-{node_id}",
                "nodeKind": "product_occurrence",
                "sourceOccurrenceId": node_id,
                "nameSnapshot": f"Part {node_id.upper()}",
                "itemIdSnapshot": f"PART-{node_id.upper()}",
                "position": {"x": index * 280, "y": 120},
            }
            for index, node_id in enumerate(("a", "b", "c"))
        ],
        "canvasEdges": list(edges or []),
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def test_build_order_and_containment_alone_never_create_a_wire():
    result = suggest_process_map_connections(_map(), _structure())
    assert result["suggestions"] == []
    assert result["summary"]["edgeSuggestions"] == 0


def test_authored_pattern_produces_stable_evidence_versioned_suggestion():
    process_map = _map([_edge("edge-a-b", "node-a", "node-b")])
    process_map_before = deepcopy(process_map)
    structure = _structure()
    structure_before = deepcopy(structure)
    first = suggest_process_map_connections(process_map, structure)
    second = suggest_process_map_connections(deepcopy(process_map), deepcopy(_structure()))
    assert first == second
    assert process_map == process_map_before
    assert structure == structure_before
    assert len(first["suggestions"]) == 1
    suggestion = first["suggestions"][0]
    assert suggestion["edge"]["from"]["nodeId"] == "node-b"
    assert suggestion["edge"]["to"]["nodeId"] == "node-c"
    assert suggestion["confidence"] == "medium"
    assert {item["source"] for item in suggestion["provenance"]} == {
        "product_containment",
        "suggested_build_order",
        "authored_precedence_pattern",
    }
    assert suggestion["suggestionId"].startswith("pms-")


def test_authored_pattern_can_propose_one_unplaced_next_card_without_changing_identity_rules():
    process_map = _map([_edge("edge-a-b", "node-a", "node-b")])
    process_map["canvasNodes"] = process_map["canvasNodes"][:2]
    first = suggest_process_map_connections(process_map, _structure())
    second = suggest_process_map_connections(deepcopy(process_map), deepcopy(_structure()))
    assert first == second
    placements = [item for item in first["suggestions"] if "placement" in item]
    assert len(placements) == 1
    suggestion = placements[0]
    assert suggestion["ruleId"] == "sibling_sequence_next_card"
    assert suggestion["placement"] == {
        "sourceOccurrenceId": "c",
        "nameSnapshot": "Part C",
        "itemIdSnapshot": "PART-C",
        "anchorNodeId": "node-b",
        "connectionDirection": "outgoing",
        "edgeKind": "precedence",
        "edgeId": "pm-e-suggest-" + suggestion["suggestionId"][4:20],
    }
    assert suggestion["suggestionId"].startswith("pms-")
    assert first["summary"]["placementSuggestions"] == 1


def test_unplaced_next_card_still_requires_corroborating_evidence():
    process_map = _map()
    process_map["canvasNodes"] = process_map["canvasNodes"][:1]
    result = suggest_process_map_connections(process_map, _structure())
    assert result["suggestions"] == []
    assert result["summary"]["placementSuggestions"] == 0


def test_equal_build_order_never_invents_direction_from_functional_evidence():
    structure = _structure()
    structure["occurrences"][2]["suggestedBuildOrder"] = 1
    process_map = _map()
    process_map["sourceStructureRevision"] = process_map_revision(structure)
    functional_graph = {
        "interfaces": [{
            "interface_id": "interface-a-b-v1",
            "participants": [
                {"part_number": "PART-A"},
                {"part_number": "PART-B"},
            ],
        }]
    }
    result = suggest_process_map_connections(
        process_map,
        structure,
        functional_graph=functional_graph,
    )
    assert result["suggestions"] == []


def test_functional_evidence_is_optional_and_changes_suggestion_identity():
    functional_graph = {
        "interfaces": [{
            "interface_id": "interface-a-b-v1",
            "participants": [
                {"part_number": "PART-A"},
                {"part_number": "PART-B"},
            ],
        }]
    }
    first = suggest_process_map_connections(
        _map(),
        _structure(),
        functional_graph=functional_graph,
    )["suggestions"][0]
    changed = deepcopy(functional_graph)
    changed["interfaces"][0]["interface_id"] = "interface-a-b-v2"
    second = suggest_process_map_connections(
        _map(),
        _structure(),
        functional_graph=changed,
    )["suggestions"][0]
    assert first["edge"]["from"]["nodeId"] == "node-a"
    assert first["edge"]["to"]["nodeId"] == "node-b"
    assert first["suggestionId"] != second["suggestionId"]


def test_shared_resource_is_annotation_only_and_never_an_ordering_wire():
    process_map = _map()
    process_map["referenceCatalog"] = [{
        "referenceId": "machine-1",
        "kind": "machine",
        "name": "Five-axis mill",
    }]
    process_map["canvasNodes"][0]["referenceIds"] = ["machine-1"]
    process_map["canvasNodes"][1]["referenceIds"] = ["machine-1"]
    result = suggest_process_map_connections(process_map, _structure())
    assert result["summary"]["edgeSuggestions"] == 0
    assert result["summary"]["annotations"] == 1
    assert result["suggestions"][0]["annotation"]["kind"] == "resource_contention"


def test_dismissal_suppresses_only_the_exact_evidence_identity():
    process_map = _map([_edge("edge-a-b", "node-a", "node-b")])
    suggestion = suggest_process_map_connections(process_map, _structure())["suggestions"][0]
    process_map["dismissedSuggestions"] = [suggestion["suggestionId"]]
    dismissed = suggest_process_map_connections(process_map, _structure())
    assert dismissed["suggestions"] == []
    assert dismissed["summary"]["suppressedDismissed"] == 1
    process_map["canvasEdges"][0]["edgeId"] = "edge-a-b-new-evidence"
    process_map["canvasEdges"][0]["logicalConnectionId"] = "edge-a-b-new-evidence"
    refreshed = suggest_process_map_connections(process_map, _structure())
    assert len(refreshed["suggestions"]) == 1
    assert refreshed["suggestions"][0]["suggestionId"] != suggestion["suggestionId"]


def test_cycle_risk_is_reported_before_any_mutation():
    process_map = _map([
        _edge("edge-a-b", "node-a", "node-b"),
        _edge("edge-c-b", "node-c", "node-b"),
    ])
    suggestion = suggest_process_map_connections(process_map, _structure())["suggestions"][0]
    assert suggestion["edge"]["from"]["nodeId"] == "node-b"
    assert suggestion["edge"]["to"]["nodeId"] == "node-c"
    assert suggestion["validation"]["wouldCreateCycle"] is True


def test_explicit_operation_subject_can_suggest_its_inspection():
    process_map = _map()
    process_map["canvasNodes"] = [
        {
            "nodeId": "operation",
            "nodeKind": "process_step",
            "processType": "operation",
            "name": "Machine bore",
            "subjectOccurrenceId": "a",
            "position": {"x": 0, "y": 0},
        },
        {
            "nodeId": "inspection",
            "nodeKind": "process_step",
            "processType": "inspection",
            "name": "Inspect bore",
            "subjectOccurrenceId": "a",
            "position": {"x": 300, "y": 0},
        },
    ]
    result = suggest_process_map_connections(process_map, _structure())
    assert result["suggestions"][0]["ruleId"] == "inspection_after_operation"
    assert result["suggestions"][0]["confidence"] == "high"


def test_dismissed_suggestion_schema_is_bounded_unique_and_string_only():
    process_map = _map()
    process_map["dismissedSuggestions"] = ["pms-one", "pms-one", "", 42]
    codes = {item["code"] for item in validate_placement_map(process_map, {"a", "b", "c"})}
    assert "duplicate_dismissed_suggestion" in codes
    assert "invalid_dismissed_suggestion" in codes
    process_map["dismissedSuggestions"] = "pms-one"
    codes = {item["code"] for item in validate_placement_map(process_map, {"a", "b", "c"})}
    assert "dismissed_suggestions_not_array" in codes

    process_map["dismissedSuggestions"] = [f"pms-{index}" for index in range(501)]
    codes = {item["code"] for item in validate_placement_map(process_map, {"a", "b", "c"})}
    assert "dismissed_suggestions_too_large" in codes


@pytest.fixture
def suggestion_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "training"
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    structure = _structure()
    process_map = _map([_edge("edge-a-b", "node-a", "node-b")])
    (product_dir / "fixture_product_product_structure.json").write_text(
        json.dumps(structure, indent=2) + "\n",
        encoding="ascii",
    )
    (product_dir / "fixture_process_map_working_draft.json").write_text(
        json.dumps(process_map, indent=2) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setattr(server, "_optional_process_map_functional_graph", lambda *_args: None)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    return {"root": root, "productDir": product_dir}


def test_suggestion_endpoint_is_revision_bound_and_read_only(suggestion_product: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-maps/fixture-product/default").json()
    canonical = suggestion_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    response = client.get(
        "/api/training/process-maps/fixture-product/default/suggestions",
        params={"revision": loaded["revision"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["revision"] == loaded["revision"]
    assert payload["suggestions"][0]["edge"]["from"]["nodeId"] == "node-b"
    assert canonical.read_bytes() == before

    stale = client.get(
        "/api/training/process-maps/fixture-product/default/suggestions",
        params={"revision": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "error": "revision_conflict",
        "currentRevision": loaded["revision"],
    }
    assert canonical.read_bytes() == before


def test_suggestion_endpoint_adds_discardable_spatial_geometry_when_both_flags_are_on(
    suggestion_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_SPATIAL_PLACEMENT", "1")
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_AUTO_ROUTING", "1")
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-maps/fixture-product/default").json()
    canonical = suggestion_product["productDir"] / "process_maps" / "default.json"
    before = canonical.read_bytes()
    response = client.get(
        "/api/training/process-maps/fixture-product/default/suggestions",
        params={"revision": loaded["revision"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    suggestion = payload["suggestions"][0]
    assert suggestion["suggestionId"].startswith("pms-")
    assert suggestion["spatialProposal"]["semanticSuggestionId"] == suggestion["suggestionId"]
    assert suggestion["spatialProposal"]["accepted"] is True
    assert suggestion["spatialProposal"]["route"]["points"]
    assert payload["spatialSummary"]["spatialized"] == 1
    assert canonical.read_bytes() == before


def test_suggestion_endpoint_obeys_process_map_feature_flag(
    suggestion_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    response = TestClient(server.app).get(
        "/api/training/process-maps/fixture-product/default/suggestions",
        params={"revision": "unused"},
    )
    assert response.status_code == 404


def test_dismissal_round_trips_through_revision_aware_save(suggestion_product: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-maps/fixture-product/default").json()
    edited = deepcopy(loaded["map"])
    edited["dismissedSuggestions"] = ["pms-reviewed-evidence-v1"]
    saved = client.put(
        "/api/training/process-maps/fixture-product/default",
        json={"map": edited, "baseRevision": loaded["revision"]},
    )
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["revision"] != loaded["revision"]
    assert payload["map"]["dismissedSuggestions"] == ["pms-reviewed-evidence-v1"]

    reloaded = client.get("/api/training/process-maps/fixture-product/default")
    assert reloaded.status_code == 200
    assert reloaded.json()["map"]["dismissedSuggestions"] == [
        "pms-reviewed-evidence-v1"
    ]
