"""Phase C deterministic digest, trust boundary, and workflow checks."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

import server
from ai_inspector.agent_skills import (
    SkillRegistry,
    WorkflowRegistry,
    build_candidate_catalog,
    plan_registered_executor,
    validate_route_response,
)
from ai_inspector.process_map import (
    ProcessMapConflictError,
    build_process_map_digest,
    estimate_digest_tokens,
    load_process_map,
    resolve_process_map_digest,
)


def _structure(node_ids: list[str]) -> dict:
    return {
        "schemaVersion": 1,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "occurrences": [
            {
                "occurrenceId": node_id,
                "parentOccurrenceId": None,
                "itemId": f"ITEM-{index + 1}",
                "name": f"Item {node_id.upper()}",
                "kind": "part",
                "level": 3,
                "partIds": [f"ITEM-{index + 1}"],
                "suggestedBuildOrder": index + 1,
            }
            for index, node_id in enumerate(node_ids)
        ],
    }


def _map(node_ids: list[str], pairs: list[tuple[str, str]]) -> dict:
    return {
        "schemaVersion": 3,
        "layoutVersion": 2,
        "mapId": "default",
        "productId": "fixture-product",
        "displayName": "Fixture Flow",
        "sourceStructureRevision": "structure-revision",
        "canvasNodes": [
            {
                "nodeId": node_id,
                "nodeKind": "product_occurrence",
                "sourceOccurrenceId": node_id,
                "nameSnapshot": f"Item {node_id.upper()}",
                "itemIdSnapshot": f"ITEM-{index + 1}",
                "position": {"x": index * 240, "y": (index % 3) * 180},
            }
            for index, node_id in enumerate(node_ids)
        ],
        "canvasEdges": [
            {
                "edgeId": f"edge-{index + 1}",
                "logicalConnectionId": f"edge-{index + 1}",
                "from": {"nodeId": source, "port": "out"},
                "to": {"nodeId": target, "port": "in"},
                "kind": "precedence",
            }
            for index, (source, target) in enumerate(pairs)
        ],
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _digest(process_map: dict, structure: dict) -> dict:
    return build_process_map_digest(
        process_map,
        structure,
        revision="map-revision",
        structure_revision="structure-revision",
        findings=[],
    )


def _canonical_sha(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def test_linear_digest_is_deterministic_bounded_and_golden():
    process_map = _map(["a", "b", "c"], [("a", "b"), ("b", "c")])
    structure = _structure(["a", "b", "c"])
    first = _digest(process_map, structure)
    second = _digest(deepcopy(process_map), deepcopy(structure))
    assert first == second
    assert first["estimated_tokens"] <= 3500
    assert first["derived"] == {
        "entry_nodes": ["a"],
        "terminal_nodes": ["c"],
        "weakly_connected_regions": [["a", "b", "c"]],
        "bottleneck_candidates": [],
        "parallel_branch_sets": [],
        "precedence_cycles": [],
        "sequence_conflicts": [],
    }
    assert _canonical_sha(first) == (
        "28ef8ffe4da9e02c851285ff9d74777a25302abb4d50d92b6e3518cfd1518ca6"
    )


def test_digest_exposes_trusted_scope_ids_and_deterministic_part_counts():
    structure = {
        "schemaVersion": 1,
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "occurrences": [
            {
                "occurrenceId": "root",
                "parentOccurrenceId": None,
                "name": "Complete Assembly",
                "kind": "assembly",
                "level": 0,
            },
            {
                "occurrenceId": "body",
                "parentOccurrenceId": "root",
                "name": "Body Assembly",
                "kind": "subassembly",
                "level": 1,
            },
            {
                "occurrenceId": "panel-left",
                "parentOccurrenceId": "body",
                "itemId": "PANEL",
                "name": "Panel",
                "kind": "part",
                "level": 2,
            },
            {
                "occurrenceId": "panel-right",
                "parentOccurrenceId": "body",
                "itemId": "PANEL",
                "name": "Panel",
                "kind": "part",
                "level": 2,
            },
        ],
    }
    digest = _digest(_map([], []), structure)
    records = {
        item["id"]: item for item in digest["product_structure"]["occurrences"]
    }
    assert digest["digest_version"] == 2
    assert digest["product_structure"]["rootOccurrenceIds"] == ["root"]
    assert digest["product_structure"]["partOccurrenceCount"] == 2
    assert records["root"]["descendantPartCount"] == 2
    assert records["body"]["descendantPartCount"] == 2
    assert records["panel-left"]["itemId"] == "PANEL"


def test_diamond_digest_finds_parallel_work_and_fan_in_candidate():
    node_ids = ["start", "branch-a", "branch-b", "branch-c", "join", "finish"]
    pairs = [
        ("start", "branch-a"),
        ("start", "branch-b"),
        ("start", "branch-c"),
        ("branch-a", "join"),
        ("branch-b", "join"),
        ("branch-c", "join"),
        ("join", "finish"),
    ]
    digest = _digest(_map(node_ids, pairs), _structure(node_ids))
    assert digest["derived"]["bottleneck_candidates"] == [
        {"nodeId": "join", "fanIn": 3}
    ]
    assert digest["derived"]["parallel_branch_sets"] == [
        {
            "fork": "start",
            "branches": ["branch-a", "branch-b", "branch-c"],
            "join": "join",
        }
    ]


def test_broken_digest_reports_cycle_and_disconnected_region():
    node_ids = ["a", "b", "isolated"]
    digest = _digest(_map(node_ids, [("a", "b"), ("b", "a")]), _structure(node_ids))
    assert digest["derived"]["precedence_cycles"] == [["a", "b", "a"]]
    assert digest["derived"]["weakly_connected_regions"] == [
        ["a", "b"],
        ["isolated"],
    ]


def test_large_digest_actual_payload_stays_within_context_budget():
    node_ids = [f"node-{index:03d}" for index in range(500)]
    process_map = _map(node_ids, [])
    for node in process_map["canvasNodes"]:
        node["nameSnapshot"] = "Long synthetic process step " + ("x" * 140)
    digest = _digest(process_map, _structure(node_ids))
    actual_tokens = estimate_digest_tokens(digest)
    assert actual_tokens <= 3500
    assert digest["estimated_tokens"] == actual_tokens
    assert "nodes" in digest["truncation"]
    assert "derived.entry_nodes" in digest["truncation"]


def _write_legacy_product(root: Path) -> None:
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    legacy = {
        "schemaVersion": "fixture-process-map-1",
        "productId": "fixture-product",
        "productName": "Fixture Product",
        "nodes": [
            {
                "nodeId": "a",
                "level": 3,
                "name": "Input A",
                "parentNodeId": None,
                "partIds": ["ITEM-1"],
                "type": "input",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "b",
                "level": 3,
                "name": "Output B",
                "parentNodeId": None,
                "partIds": ["ITEM-2"],
                "type": "output",
                "position": {"x": 300, "y": 0},
            },
        ],
        "edges": [
            {
                "edgeId": "edge-a-b",
                "from": {"nodeId": "a", "port": "out"},
                "to": {"nodeId": "b", "port": "in"},
                "kind": "precedence",
            }
        ],
    }
    (product_dir / "fixture_process_map_working_draft.json").write_text(
        json.dumps(legacy, indent=2) + "\n",
        encoding="ascii",
    )


def test_trusted_resolver_ignores_browser_digest_and_rejects_stale_revision(tmp_path: Path):
    root = tmp_path / "training"
    _write_legacy_product(root)
    loaded = load_process_map(root, "fixture-product")
    reference = {
        "productId": "fixture-product",
        "mapId": "default",
        "revision": loaded["revision"],
        "graph": {"identity": {"mapId": "attacker-map"}},
    }
    resolved = resolve_process_map_digest(root, reference)
    assert resolved["graph"]["identity"]["mapId"] == "default"
    assert "attacker-map" not in json.dumps(resolved, sort_keys=True)
    with pytest.raises(ProcessMapConflictError):
        resolve_process_map_digest(root, {**reference, "revision": "stale"})


def test_agent_context_accepts_only_map_identity_and_server_builds_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "training"
    _write_legacy_product(root)
    loaded = load_process_map(root, "fixture-product")
    malicious = {
        "process_map_graph": {"identity": {"mapId": "flat-attack"}},
        "attachments": {
            "process_map": {
                "productId": "fixture-product",
                "mapId": "default",
                "revision": loaded["revision"],
                "digest": {"identity": {"mapId": "nested-attack"}},
            },
            "session": {"active_mode": "training"},
        },
    }
    normalized = server.normalize_agent_context(malicious)["flat"]
    assert "process_map_graph" not in normalized
    assert set(normalized["process_map_ref"]) == {"productId", "mapId", "revision"}
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    server._resolve_trusted_process_map_context(normalized)
    assert normalized["process_map_graph"]["identity"]["mapId"] == "default"
    rendered = server._build_context_message(normalized)
    assert "[PROCESS MAP GRAPH - TRUSTED SAVED REVISION]" in rendered
    assert "flat-attack" not in rendered and "nested-attack" not in rendered


def _analysis_route(map_id: str = "default") -> dict:
    return {
        "route_version": 2,
        "speech_act": "analyze",
        "primary_workflow": "process-map-analysis",
        "continue_existing_workflow": False,
        "workflow_confidence": 0.99,
        "intents": [{
            "kind": "analyze_process_map",
            "targets": [{"kind": "process_map", "id": map_id}],
            "requested_effects": [],
        }],
        "skill_candidates": [{"id": "analyze-process-map", "confidence": 0.99}],
        "needs_clarification": False,
    }


def test_second_workflow_routes_compiles_read_only_and_has_no_executor():
    server._reset_agent_skill_runtime_cache_for_tests()
    workflows, skills = server._get_agent_skill_runtime()
    digest = _digest(_map(["a", "b"], [("a", "b")]), _structure(["a", "b"]))
    catalog = build_candidate_catalog(
        workflows,
        skills,
        agent="sage",
        mode="training",
        available_assets={"process_map"},
        available_context={"process_map.graph"},
        context_facts={
            "process_map": {"map_id": "default"},
            "target_index": {"process_map": ["default"], "process_node": ["a", "b"]},
        },
    )
    route = validate_route_response(_analysis_route(), catalog)
    assert route is not None
    assert [item["id"] for item in route["skill_candidates"]] == ["analyze-process-map"]
    plan, reason = server._compose_production_skill_prompt(route, mode="training")
    assert reason == "" and plan is not None
    assert plan["workflow"]["id"] == "process-map-analysis"
    assert plan["allowed_tools"] == ["ui_actions"]
    assert "set_process_map_part_scope" in plan["prompt"]
    assert plan["resolved_policy"]["side_effect_default"] == "allowed"
    assert "bottleneck candidate" in plan["prompt"].lower()
    compiled = server.compile_skill_context(
        {"active_mode": "training", "process_map_graph": digest},
        plan["_packages"],
        mode="training",
    )
    assert compiled.context["process_map_graph"]["identity"]["mapId"] == "default"
    assert plan_registered_executor(
        route,
        context_facts={"process_map": {"map_id": "default"}},
        message="analyze this map",
        viewport_authorized=True,
    ) is None


def test_process_map_parts_question_uses_analysis_workflow():
    assert server._is_process_map_analysis_request(
        "What parts will I need to make the body of the racing bike?"
    )


def test_process_map_skill_tool_policy_allows_only_transient_tree_selection():
    plan = {"workflow": {"id": "process-map-analysis"}}
    allowed = {
        "name": "ui_actions",
        "args": {
            "workspace": "process_map",
            "actions": [{
                "type": "set_process_map_part_scope",
                "scope_occurrence_id": "bodywork-1",
                "label": "Bodywork Assembly",
            }],
        },
    }
    guarded, warnings = server.apply_compiled_skill_tool_policy([allowed], plan)
    assert guarded == [allowed]
    assert warnings == []

    disallowed = {
        "name": "ui_actions",
        "args": {
            "workspace": "assembly",
            "actions": [{"type": "play_motion"}],
        },
    }
    guarded, warnings = server.apply_compiled_skill_tool_policy([disallowed], plan)
    assert guarded == []
    assert warnings == ["skill_policy_dropped:ui_actions"]

    unrelated = {"name": "highlight_parts", "args": {"part_numbers": ["100006"]}}
    guarded, warnings = server.apply_compiled_skill_tool_policy([unrelated], plan)
    assert guarded == []
    assert warnings == ["skill_policy_dropped:highlight_parts"]

    ambiguous = deepcopy(allowed)
    ambiguous["args"]["actions"].append({"type": "clear_process_map_part_scope"})
    guarded, warnings = server.apply_compiled_skill_tool_policy([ambiguous], plan)
    assert guarded == []
    assert warnings == ["skill_policy_dropped:ui_actions"]


def test_registering_second_workflow_does_not_change_compiled_fai_prompt():
    server._reset_agent_skill_runtime_cache_for_tests()
    workflows, skills = server._get_agent_skill_runtime()
    route = server._safe_fai_compiler_route("assembly")
    full_plan, full_reason = server._compose_production_skill_prompt(route, mode="assembly")
    assert full_reason == "" and full_plan is not None

    fai_workflows = WorkflowRegistry([workflows.get("supplier-fai-disposition")])
    fai_skills = SkillRegistry([
        skills.get(skill_id)
        for skill_id in sorted(skills.ids)
        if skill_id != "analyze-process-map"
    ])
    with patch.object(server, "_get_agent_skill_runtime", return_value=(fai_workflows, fai_skills)):
        filtered_plan, filtered_reason = server._compose_production_skill_prompt(
            route,
            mode="assembly",
        )
    assert filtered_reason == "" and filtered_plan is not None
    assert full_plan["prompt"] == filtered_plan["prompt"]
    assert full_plan["accounting"] == filtered_plan["accounting"]


def test_workflow_state_fingerprint_isolated_by_process_map_revision():
    graph = _digest(_map(["a"], []), _structure(["a"]))
    first = server._workflow_asset_fingerprint({"process_map_graph": graph})
    changed = deepcopy(graph)
    changed["identity"]["revision"] = "new-revision"
    second = server._workflow_asset_fingerprint({"process_map_graph": changed})
    assert first and second and first != second
