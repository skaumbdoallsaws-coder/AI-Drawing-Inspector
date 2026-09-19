"""Semantic Process Plan, trusted state, and position-ownership tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.process_map import (
    ProcessMapOperationError,
    SemanticProcessPlanError,
    apply_process_map_operations,
    build_process_map_state,
    compile_semantic_process_plan,
    validate_placement_map,
)


REVISION = "a" * 64
STRUCTURE_REVISION = "b" * 64


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
                "itemId": "MODULE",
                "name": "Fixture Module",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["P-001", "P-002"],
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


def _empty_map() -> dict:
    return {
        "schemaVersion": 3,
        "layoutVersion": 3,
        "mapId": "default",
        "productId": "fixture-product",
        "sourceStructureRevision": STRUCTURE_REVISION,
        "canvasNodes": [],
        "canvasEdges": [],
        "canvasGroups": [],
    }


def _plan() -> dict:
    return {
        "schemaVersion": 1,
        "planId": "plan-fixture-module",
        "scope": {
            "assemblyOccurrenceId": "module",
            "label": "Fixture Module",
        },
        "requiredOccurrences": [
            {
                "occurrenceId": "part-a",
                "quantity": 1,
                "role": "input",
                "knowledgeStatus": "derived",
                "evidence": [
                    {
                        "sourceType": "assembly_structure",
                        "sourceRef": STRUCTURE_REVISION,
                        "supports": "component-membership",
                    }
                ],
            },
            {
                "occurrenceId": "part-b",
                "quantity": 1,
                "role": "input",
                "knowledgeStatus": "derived",
                "evidence": [
                    {
                        "sourceType": "assembly_structure",
                        "sourceRef": STRUCTURE_REVISION,
                        "supports": "component-membership",
                    }
                ],
            },
        ],
        "operations": [
            {
                "id": "op-prepare-a",
                "operationType": "operation",
                "label": "Prepare part A",
                "inputs": [{"ref": "part-a", "type": "occurrence"}],
                "output": {
                    "ref": "state-prepared-a",
                    "type": "intermediateResult",
                    "label": "Prepared part A",
                },
                "branchId": "branch-a",
                "stageIndex": 1,
                "knowledgeStatus": "inferred",
                "evidence": [
                    {
                        "sourceType": "domain_heuristic",
                        "sourceRef": "fixture-preparation",
                        "supports": "candidate-operation",
                    }
                ],
                "assumptionIds": ["assumption-sequence"],
                "properties": {},
            },
            {
                "id": "op-join",
                "operationType": "operation",
                "label": "Join fixture parts",
                "inputs": [
                    {"ref": "state-prepared-a", "type": "intermediateResult"},
                    {"ref": "part-b", "type": "occurrence"},
                ],
                "output": {"ref": "module", "type": "occurrence"},
                "branchId": "main",
                "stageIndex": 2,
                "knowledgeStatus": "inferred",
                "evidence": [
                    {
                        "sourceType": "domain_heuristic",
                        "sourceRef": "fixture-assembly",
                        "supports": "candidate-operation",
                    }
                ],
                "assumptionIds": ["assumption-sequence"],
                "properties": {},
            },
        ],
        "intermediateResults": [
            {
                "id": "state-prepared-a",
                "label": "Prepared part A",
                "producedBy": "op-prepare-a",
            }
        ],
        "junctions": [],
        "branches": [
            {"id": "branch-a", "label": "Preparation"},
            {"id": "main", "label": "Main assembly"},
        ],
        "evidence": [],
        "assumptions": [
            {
                "id": "assumption-sequence",
                "text": "Review the proposed preparation and joining sequence.",
            }
        ],
        "layoutHints": [
            {"ref": "op-prepare-a", "branchId": "branch-a", "stageIndex": 1},
            {"ref": "op-join", "branchId": "main", "stageIndex": 2},
        ],
        "unresolvedQuestions": [],
    }


def _compile(plan: dict, process_map: dict | None = None) -> dict:
    return compile_semantic_process_plan(
        plan,
        scope_occurrence_id="module",
        base_revision=REVISION,
        process_map=process_map or _empty_map(),
        product_structure=_structure(),
        structure_revision=STRUCTURE_REVISION,
    )


def test_semantic_plan_compiles_deterministically_through_domain_operations():
    first = _compile(_plan())
    second = _compile(deepcopy(_plan()))
    assert first == second
    assert first["summary"] == {
        "message": "Review the complete Fixture Module process-map proposal.",
        "requiredOccurrenceCount": 2,
        "operationCount": 2,
        "junctionCount": 0,
        "connectionCount": 4,
        "assumptionCount": 1,
        "unresolvedCount": 0,
        "inferredOperationCount": 2,
    }
    assert first["binding"]["baseRevision"] == REVISION
    assert first["binding"]["structureRevision"] == STRUCTURE_REVISION
    assert len(first["bindingHash"]) == 64
    applied = apply_process_map_operations(
        _empty_map(),
        _structure(),
        first["operations"],
        maximum_operations=500,
    )
    nodes = applied["map"]["canvasNodes"]
    assert nodes and all(node["positionMode"] == "auto" for node in nodes)
    assert {node["nodeKind"] for node in nodes} == {
        "product_occurrence",
        "process_step",
    }
    assert all(
        edge["from"]["port"] == "out" and edge["to"]["port"] == "in"
        for edge in applied["map"]["canvasEdges"]
    )
    assert not [
        item
        for item in validate_placement_map(
            applied["map"],
            {"root", "module", "part-a", "part-b"},
        )
        if item["severity"] == "error"
    ]


def test_semantic_plan_rejects_model_geometry_and_nonempty_authored_map():
    with_coordinates = _plan()
    with_coordinates["operations"][0]["position"] = {"x": 10, "y": 20}
    with pytest.raises(SemanticProcessPlanError) as coordinates:
        _compile(with_coordinates)
    assert {
        item["code"] for item in coordinates.value.findings
    } >= {"semantic_plan_contains_spatial_data"}

    nonempty = _empty_map()
    nonempty["canvasNodes"] = [
        {
            "nodeId": "authored-node",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "part-a",
            "position": {"x": 25, "y": 40},
            "positionMode": "manual",
        }
    ]
    with pytest.raises(SemanticProcessPlanError) as authored:
        _compile(_plan(), nonempty)
    assert {
        item["code"] for item in authored.value.findings
    } >= {"semantic_generation_requires_empty_map"}


def test_semantic_plan_does_not_promote_assembly_evidence_to_authored_order():
    plan = _plan()
    operation = plan["operations"][0]
    operation["knowledgeStatus"] = "derived"
    operation["evidence"] = [
        {
            "sourceType": "assembly_structure",
            "sourceRef": STRUCTURE_REVISION,
            "supports": "component-membership",
        }
    ]
    with pytest.raises(SemanticProcessPlanError) as error:
        _compile(plan)
    assert {
        item["code"] for item in error.value.findings
    } >= {"assembly_evidence_does_not_prove_order"}


def test_semantic_plan_enforces_intermediate_and_junction_meaning():
    mismatched = _plan()
    mismatched["intermediateResults"][0]["producedBy"] = "op-join"
    with pytest.raises(SemanticProcessPlanError) as intermediate:
        _compile(mismatched)
    assert {
        item["code"] for item in intermediate.value.findings
    } >= {"intermediate_result_producer_mismatch"}

    junction_work = _plan()
    junction_work["junctions"] = [
        {
            "id": "junction-merge",
            "junctionType": "merge",
            "inputs": ["part-a", "part-b"],
            "outputs": ["op-join"],
            "properties": {"description": "Assemble the parts"},
        }
    ]
    with pytest.raises(SemanticProcessPlanError) as junction:
        _compile(junction_work)
    assert {
        item["code"] for item in junction.value.findings
    } >= {"junction_cannot_represent_work"}


def test_parallel_branches_compile_through_a_real_junction():
    plan = _plan()
    plan["operations"].insert(
        1,
        {
            "id": "op-prepare-b",
            "operationType": "operation",
            "label": "Prepare part B",
            "inputs": [{"ref": "part-b", "type": "occurrence"}],
            "output": {
                "ref": "state-prepared-b",
                "type": "intermediateResult",
                "label": "Prepared part B",
            },
            "branchId": "branch-b",
            "stageIndex": 1,
            "knowledgeStatus": "inferred",
            "evidence": [
                {
                    "sourceType": "domain_heuristic",
                    "sourceRef": "fixture-preparation-b",
                    "supports": "candidate-operation",
                }
            ],
            "assumptionIds": ["assumption-sequence"],
            "properties": {},
        },
    )
    plan["operations"][2]["inputs"] = [
        {"ref": "state-prepared-a", "type": "intermediateResult"},
        {"ref": "state-prepared-b", "type": "intermediateResult"},
    ]
    plan["intermediateResults"].append(
        {
            "id": "state-prepared-b",
            "label": "Prepared part B",
            "producedBy": "op-prepare-b",
        }
    )
    plan["junctions"] = [
        {
            "id": "junction-ready-parts",
            "junctionType": "parallel_and",
            "inputs": ["state-prepared-a", "state-prepared-b"],
            "outputs": ["op-join"],
            "knowledgeStatus": "inferred",
            "evidence": [
                {
                    "sourceType": "domain_heuristic",
                    "sourceRef": "fixture-convergence",
                    "supports": "candidate-flow-topology",
                }
            ],
            "assumptionIds": ["assumption-sequence"],
        }
    ]
    plan["branches"].insert(
        1,
        {"id": "branch-b", "label": "Preparation B"},
    )
    plan["layoutHints"].insert(
        1,
        {"ref": "op-prepare-b", "branchId": "branch-b", "stageIndex": 1},
    )

    compiled = _compile(plan)
    assert compiled["summary"]["operationCount"] == 3
    assert compiled["summary"]["junctionCount"] == 1
    assert compiled["summary"]["connectionCount"] == 6

    node_ids = {
        operation["semantic"]["semanticRef"]: operation["nodeId"]
        for operation in compiled["operations"]
        if operation["op"] in {
            "add_process_step",
            "add_junction",
            "place_occurrence",
        }
    }
    connections = {
        (operation["fromNodeId"], operation["toNodeId"])
        for operation in compiled["operations"]
        if operation["op"] == "connect"
    }
    junction_id = node_ids["junction-ready-parts"]
    join_id = node_ids["op-join"]
    assert (node_ids["op-prepare-a"], junction_id) in connections
    assert (node_ids["op-prepare-b"], junction_id) in connections
    assert (junction_id, join_id) in connections
    assert (node_ids["op-prepare-a"], join_id) not in connections
    assert (node_ids["op-prepare-b"], join_id) not in connections


def test_position_ownership_blocks_locked_moves_and_user_moves_become_manual():
    process_map = _empty_map()
    created = apply_process_map_operations(
        process_map,
        _structure(),
        [
            {
                "op": "place_occurrence",
                "nodeId": "node-a",
                "occurrenceId": "part-a",
                "position": {"x": 10, "y": 20},
                "positionMode": "auto",
            },
            {
                "op": "set_node_position_mode",
                "nodeId": "node-a",
                "positionMode": "locked",
            },
        ],
    )["map"]
    node = created["canvasNodes"][0]
    assert node["positionMode"] == "locked"
    assert node["locked"] is True
    with pytest.raises(ProcessMapOperationError, match="position-locked"):
        apply_process_map_operations(
            created,
            _structure(),
            [
                {
                    "op": "move_node",
                    "nodeId": "node-a",
                    "position": {"x": 50, "y": 60},
                }
            ],
        )


def test_trusted_state_uses_saved_geometry_and_sanitizes_live_editor_facts():
    compiled = _compile(_plan())
    applied = apply_process_map_operations(
        _empty_map(),
        _structure(),
        compiled["operations"],
        maximum_operations=500,
    )["map"]
    known_node = applied["canvasNodes"][0]["nodeId"]
    known_edge = applied["canvasEdges"][0]["edgeId"]
    loaded = {
        "productId": "fixture-product",
        "map": applied,
        "revision": REVISION,
        "structureRevision": STRUCTURE_REVISION,
    }
    state = build_process_map_state(
        loaded,
        live_facts={
            "dirty": True,
            "conflict": False,
            "editable": True,
            "selection": {
                "nodeIds": [known_node, "attacker-node"],
                "edgeIds": [known_edge, "attacker-edge"],
            },
            "activeProposal": {"proposalId": "proposal-current"},
            "nodes": [
                {
                    "nodeId": known_node,
                    "position": {"x": 999999, "y": 999999},
                }
            ],
        },
        capabilities={"semanticPreview": True, "builderWrite": True},
        active_proposal={
            "proposalId": "proposal-current",
            "productId": "fixture-product",
            "mapId": "default",
            "baseRevision": REVISION,
            "semanticBindingHash": "c" * 64,
            "semanticSummary": {"operationCount": 2},
        },
        receipts=[
            {
                "receiptId": "receipt-current",
                "proposalId": "proposal-current",
                "productId": "fixture-product",
                "mapId": "default",
                "baseRevision": "old",
                "revision": REVISION,
                "semanticBindingHash": "c" * 64,
                "createdIds": {"nodeIds": [known_node]},
                "warnings": [],
                "unresolvedItems": [],
            },
            {
                "receiptId": "receipt-stale",
                "productId": "fixture-product",
                "mapId": "default",
                "revision": "stale",
            },
        ],
    )
    saved_node = next(item for item in applied["canvasNodes"] if item["nodeId"] == known_node)
    observed_node = next(item for item in state["nodes"] if item["id"] == known_node)
    assert observed_node["position"] == saved_node["position"]
    assert state["selection"] == {
        "nodeIds": [known_node],
        "edgeIds": [known_edge],
    }
    assert state["savedStateCurrent"] is False
    assert state["activeProposal"] == {
        "proposalId": "proposal-current",
        "type": "semantic_process_map",
        "baseRevision": REVISION,
        "summary": {"operationCount": 2},
        "pendingApproval": True,
    }
    assert [item["receiptId"] for item in state["recentReceipts"]] == [
        "receipt-current"
    ]
    assert state["recentReceipts"][0]["createdIds"] == {
        "nodeIds": [known_node]
    }
    assert state["coordinateContract"] == {
        "persisted": "world",
        "cameraIsNotGeometry": True,
        "screenPixelsAcceptedForWrites": False,
    }
