"""Deterministic tests for process-map schema migration and validation."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.process_map import migrate_process_map, validate_process_map


def _node(
    node_id: str,
    node_type: str,
    *,
    parent_id: str | None = "root",
    level: int = 1,
    part_ids: list[str] | None = None,
) -> dict:
    return {
        "nodeId": node_id,
        "type": node_type,
        "level": level,
        "name": node_id,
        "parentNodeId": parent_id,
        "partIds": list(part_ids or []),
    }


def _edge(edge_id: str, from_id: str, to_id: str, kind: str = "precedence") -> dict:
    return {
        "edgeId": edge_id,
        "from": {"nodeId": from_id, "port": "out"},
        "to": {"nodeId": to_id, "port": "in"},
        "kind": kind,
    }


def _map() -> dict:
    return {
        "schemaVersion": 2,
        "layoutVersion": 1,
        "nodes": [
            _node("root", "assembly", parent_id=None, level=0),
            _node("cut", "operation"),
            _node("inspect", "inspection"),
            _node("done", "output"),
        ],
        "edges": [
            _edge("e1", "cut", "inspect"),
            _edge("e2", "inspect", "done"),
        ],
    }


def _codes(findings: list[dict], severity: str | None = None) -> list[str]:
    return [
        finding["code"]
        for finding in findings
        if severity is None or finding["severity"] == severity
    ]


def test_valid_map_has_no_findings():
    assert validate_process_map(_map(), known_part_ids=set()) == []


def test_v1_migration_assigns_types_without_inventing_process_steps():
    v1 = {
        "schemaVersion": "working-draft-1",
        "nodes": [
            {"nodeId": "root", "level": 0, "parentNodeId": None, "partIds": []},
            {"nodeId": "module", "level": 1, "parentNodeId": "root", "partIds": []},
            {"nodeId": "group", "level": 2, "parentNodeId": "module", "partIds": []},
            {"nodeId": "part", "level": 3, "parentNodeId": "group", "partIds": ["P1"]},
        ],
    }
    migrated, findings = migrate_process_map(v1)
    assert migrated["schemaVersion"] == 2
    assert migrated["layoutVersion"] == 1
    assert migrated["edges"] == []
    assert [node["type"] for node in migrated["nodes"]] == [
        "assembly",
        "subassembly",
        "subassembly",
        "input",
    ]
    assert len(findings) == 3
    assert set(_codes(findings)) == {"migration_auto_typed_nodes"}
    assert all(finding["severity"] == "info" for finding in findings)
    assert "type" not in v1["nodes"][0]


def test_precedence_cycle_is_error_but_rework_loop_is_allowed():
    process_map = _map()
    process_map["edges"] = [
        _edge("e1", "cut", "inspect"),
        _edge("e2", "inspect", "cut"),
    ]
    assert "precedence_cycle" in _codes(validate_process_map(process_map), "error")

    process_map["edges"][1]["kind"] = "rework"
    assert "precedence_cycle" not in _codes(validate_process_map(process_map), "error")


def test_duplicate_and_dangling_structure_is_rejected():
    process_map = _map()
    duplicate = deepcopy(process_map["nodes"][1])
    process_map["nodes"].append(duplicate)
    process_map["nodes"][2]["parentNodeId"] = "missing"
    codes = _codes(validate_process_map(process_map), "error")
    assert "duplicate_node_id" in codes
    assert "dangling_parent" in codes


def test_edge_identity_shape_and_endpoints_are_validated():
    process_map = _map()
    process_map["edges"] = [
        _edge("same", "cut", "inspect"),
        _edge("same", "cut", "inspect"),
        _edge("self", "cut", "cut"),
        _edge("missing", "cut", "unknown"),
        _edge("kind", "inspect", "done", "teleport"),
    ]
    process_map["edges"].append(
        {
            "edgeId": "malformed",
            "from": {"nodeId": "cut"},
            "to": {"nodeId": "done", "port": "in"},
            "kind": "precedence",
        }
    )
    codes = _codes(validate_process_map(process_map), "error")
    for expected in [
        "duplicate_edge_id",
        "duplicate_edge",
        "self_edge",
        "dangling_edge_endpoint",
        "unknown_edge_kind",
        "invalid_edge_endpoint",
    ]:
        assert expected in codes


def test_unknown_type_position_and_part_shape_are_errors():
    process_map = _map()
    process_map["nodes"][1]["type"] = "component"
    process_map["nodes"][1]["position"] = {"x": 1, "y": float("inf")}
    process_map["nodes"][1]["partIds"] = "P1"
    codes = _codes(validate_process_map(process_map), "error")
    assert "unknown_node_type" in codes
    assert "invalid_node_position" in codes
    assert "invalid_part_ids" in codes


def test_unknown_product_parts_are_saveable_warnings():
    process_map = _map()
    process_map["nodes"][1]["partIds"] = ["KNOWN", "UNKNOWN"]
    findings = validate_process_map(process_map, known_part_ids={"KNOWN"})
    assert _codes(findings, "error") == []
    assert _codes(findings, "warning") == ["unknown_part_reference"]
    assert findings[0]["nodeId"] == "cut"


def test_type_shape_findings_are_warnings_not_errors():
    process_map = _map()
    process_map["nodes"].extend(
        [
            _node("material", "input"),
            _node("choice", "decision"),
        ]
    )
    process_map["edges"] = [
        _edge("e1", "cut", "material"),
        _edge("e2", "done", "choice"),
    ]
    findings = validate_process_map(process_map)
    assert _codes(findings, "error") == []
    warning_codes = set(_codes(findings, "warning"))
    assert warning_codes == {
        "input_has_incoming_precedence",
        "output_has_outgoing_precedence",
        "decision_has_fewer_than_two_outputs",
    }


def test_containment_cycle_is_reported_as_unreachable_warning():
    process_map = _map()
    process_map["nodes"].extend(
        [
            _node("loop-a", "subassembly", parent_id="loop-b"),
            _node("loop-b", "subassembly", parent_id="loop-a"),
        ]
    )
    findings = validate_process_map(process_map)
    assert _codes(findings, "error") == []
    unreachable = [f for f in findings if f["code"] == "unreachable_node"]
    assert {finding["nodeId"] for finding in unreachable} == {"loop-a", "loop-b"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
