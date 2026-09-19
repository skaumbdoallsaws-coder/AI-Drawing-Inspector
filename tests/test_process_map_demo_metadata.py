"""Trusted Front Wheel demo metadata compilation and operation tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import (
    apply_process_map_operations,
    compile_demo_metadata_operations,
    reset_process_map_builder_state_for_tests,
    validate_placement_map,
)
from ai_inspector.process_map.repository import process_map_revision


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = REPO_ROOT / "generated" / "training"
PRODUCT_ID = "racing-bike"


def _plan() -> dict:
    return json.loads(
        (
            TRAINING_ROOT
            / PRODUCT_ID
            / "process_knowledge"
            / "front-wheel-process-demo.json"
        ).read_text(encoding="ascii")
    )


def _structure() -> dict:
    return json.loads(
        (
            TRAINING_ROOT
            / PRODUCT_ID
            / "racing_bike_product_structure.json"
        ).read_text(encoding="ascii")
    )


def _complete_map() -> dict:
    plan = _plan()
    structure = _structure()
    occurrences_by_name = {
        item["name"]: item["occurrenceId"]
        for item in structure["occurrences"]
        if item.get("occurrenceId", "").startswith("L1-001-02")
    }
    nodes = []
    map_id_by_plan_id = {}
    for index, item in enumerate(plan["nodes"]):
        node_id = "map-" + item["id"]
        map_id_by_plan_id[item["id"]] = node_id
        if item.get("occurrenceId"):
            nodes.append(
                {
                    "nodeId": node_id,
                    "nodeKind": "product_occurrence",
                    "sourceOccurrenceId": occurrences_by_name[item["label"]],
                    "position": {"x": float((index % 5) * 260), "y": float((index // 5) * 180)},
                    "portOrientation": "horizontal",
                    "portOrder": "input_first",
                }
            )
        else:
            nodes.append(
                {
                    "nodeId": node_id,
                    "nodeKind": "process_step",
                    "processType": "operation",
                    "name": item["label"],
                    "position": {"x": float((index % 5) * 260), "y": float((index // 5) * 180)},
                    "portOrientation": "horizontal",
                    "portOrder": "input_first",
                }
            )
    edges = [
        {
            "edgeId": "map-" + route["id"],
            "logicalConnectionId": "map-" + route["id"],
            "from": {"nodeId": map_id_by_plan_id[route["source"]], "port": "out"},
            "to": {"nodeId": map_id_by_plan_id[route["target"]], "port": "in"},
            "kind": "precedence",
        }
        for route in plan["routes"]
    ]
    return {
        "schemaVersion": 3,
        "layoutVersion": 3,
        "mapId": "default",
        "productId": PRODUCT_ID,
        "displayName": "Front Wheel Demo",
        "sourceStructureRevision": "fixture",
        "canvasNodes": nodes,
        "canvasEdges": edges,
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _compile(process_map: dict) -> dict:
    return compile_demo_metadata_operations(
        TRAINING_ROOT,
        PRODUCT_ID,
        process_map,
        _structure(),
        scope_occurrence_id="L1-001-02",
        fill_mode="fill_missing",
        populated_at="2026-07-22T12:00:00Z",
    )


def test_front_wheel_demo_compiles_complete_atomic_metadata_batch():
    process_map = _complete_map()
    compiled = _compile(process_map)
    assert len(compiled["operations"]) == 51
    assert sum(item["op"] == "attach_reference" for item in compiled["operations"]) == 37
    assert sum(item["op"] == "set_edge_label" for item in compiled["operations"]) == 13
    assert compiled["operations"][-1]["op"] == "record_process_plan_import"
    assert compiled["summary"] == {
        **compiled["summary"],
        "nodeRequirementSetsPopulated": 8,
        "routeNamesPopulated": 13,
        "routeRequirementSetsPopulated": 13,
        "illustrativeRequirements": 21,
        "preservedAuthoredValues": 0,
        "ambiguousMatches": 0,
        "unresolvedCount": 0,
        "unresolved": [],
        "demoData": True,
    }

    applied = apply_process_map_operations(
        process_map,
        _structure(),
        compiled["operations"],
    )
    assert not [item for item in applied["findings"] if item["severity"] == "error"]
    result = applied["map"]
    assert len(result["referenceCatalog"]) == 27
    assert len(result["processPlanImports"]) == 1
    assert all(item.get("demoData") is True for item in result["referenceCatalog"])
    assert all(
        item.get("knowledgeStatus") == "illustrative"
        for item in result["referenceCatalog"]
    )
    assert {edge["label"] for edge in result["canvasEdges"]} == {
        route["name"] for route in _plan()["routes"]
    }

    repeated = _compile(result)
    assert repeated["operations"] == []
    assert repeated["summary"]["unresolvedCount"] == 0


def test_demo_import_preserves_authored_requirement_and_reports_missing_stage():
    process_map = _complete_map()
    rim = next(
        node for node in process_map["canvasNodes"]
        if node.get("sourceOccurrenceId") == "L1-001-02-C01"
    )
    process_map["referenceCatalog"] = [
        {
            "referenceId": "authored-rim-requirement",
            "kind": "requirement",
            "name": "Approved rim preparation",
            "identifier": "WI-FW-001",
            "revision": "A",
            "clause": "3.1 Rim preparation",
            "details": "Approved production instruction.",
            "knowledgeStatus": "authored",
            "demoData": False,
        }
    ]
    rim["referenceIds"] = ["authored-rim-requirement"]
    process_map["canvasNodes"] = [
        node for node in process_map["canvasNodes"]
        if node.get("name") != "Stage 4: Prepare brake pads"
    ]

    compiled = _compile(process_map)
    assert compiled["summary"]["preservedAuthoredValues"] == 1
    assert any(
        item["reason"] == "stage_not_found"
        and item["planTargetId"] == "stage-4"
        for item in compiled["summary"]["unresolved"]
    )
    assert not any(
        operation.get("reference", {}).get("sourceRequirementId")
        == "part-rim:requirement:1"
        for operation in compiled["operations"]
    )


def test_edge_label_operation_propagates_across_logical_junction_segments():
    process_map = _complete_map()
    original = process_map["canvasEdges"].pop(0)
    junction = {
        "nodeId": "junction-route",
        "nodeKind": "junction",
        "junctionType": "wire_branch",
        "position": {"x": 400, "y": 200},
    }
    process_map["canvasNodes"].append(junction)
    logical_id = original["logicalConnectionId"]
    process_map["canvasEdges"].extend(
        [
            {
                **deepcopy(original),
                "edgeId": logical_id + "-left",
                "to": {"nodeId": junction["nodeId"], "port": "in"},
            },
            {
                **deepcopy(original),
                "edgeId": logical_id + "-right",
                "from": {"nodeId": junction["nodeId"], "port": "out"},
            },
        ]
    )
    applied = apply_process_map_operations(
        process_map,
        _structure(),
        [
            {
                "op": "set_edge_label",
                "edgeId": logical_id + "-left",
                "label": "Mount outer wheel ring",
            }
        ],
    )
    segments = [
        edge for edge in applied["map"]["canvasEdges"]
        if edge.get("logicalConnectionId") == logical_id
    ]
    assert len(segments) == 2
    assert {edge.get("label") for edge in segments} == {"Mount outer wheel ring"}
    assert not [
        item for item in validate_placement_map(applied["map"], set(_structure_ids()))
        if item["severity"] == "error"
    ]


def _structure_ids() -> list[str]:
    return [item["occurrenceId"] for item in _structure()["occurrences"]]


def test_demo_metadata_endpoint_proposes_then_applies_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "training"
    product_dir = root / PRODUCT_ID
    knowledge_dir = product_dir / "process_knowledge"
    knowledge_dir.mkdir(parents=True)
    structure = _structure()
    process_map = _complete_map()
    process_map["sourceStructureRevision"] = process_map_revision(structure)
    (product_dir / "racing_bike_product_structure.json").write_text(
        json.dumps(structure, ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
    )
    (product_dir / "racing_bike_process_map_working_draft.json").write_text(
        json.dumps(process_map, ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
    )
    (knowledge_dir / "front-wheel-process-demo.json").write_text(
        json.dumps(_plan(), ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    monkeypatch.setenv("INSPECTORPRO_BUILDER_WRITE", "1")
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE", raising=False)
    reset_process_map_builder_state_for_tests()
    client = TestClient(server.app)
    loaded = client.get(f"/api/training/process-maps/{PRODUCT_ID}/default")
    assert loaded.status_code == 200, loaded.text
    revision = loaded.json()["revision"]

    proposed = client.post(
        f"/api/builder/process-maps/{PRODUCT_ID}/default/demo-metadata-proposals",
        json={
            "baseRevision": revision,
            "scopeOccurrenceId": "L1-001-02",
            "fillMode": "fill_missing",
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["managedProposalType"] == "process_metadata"
    assert proposal["proposalId"]
    assert "spatialBindingHash" not in proposal
    assert proposal["summary"]["unresolvedCount"] == 0
    assert len(proposal["preview"]["nodes"]) == 8
    assert len(proposal["preview"]["edges"]) == 13

    key = "demo-metadata-approval"
    binding = {
        "productId": PRODUCT_ID,
        "mapId": "default",
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
        "userId": "demo-user",
        "sessionId": "demo-session",
        "idempotencyKey": key,
    }
    approved = client.post(
        f"/api/builder/process-map-proposals/{proposal['proposalId']}/approve",
        json={**binding, "explicitApproval": True},
    )
    assert approved.status_code == 200, approved.text
    applied = client.post(
        "/api/builder/process-map-apply",
        json={**binding, "approvalToken": approved.json()["approvalToken"]},
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["receipt"]["outcome"]["illustrativeRequirements"] == 21
    assert len(payload["map"]["referenceCatalog"]) == 27
    assert payload["map"]["processPlanImports"][0]["demoData"] is True
    reset_process_map_builder_state_for_tests()
