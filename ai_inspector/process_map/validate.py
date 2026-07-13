"""Deterministic schema migration and validation for process maps."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


PROCESS_MAP_SCHEMA_VERSION = 2
NODE_TYPES = frozenset(
    {
        "assembly",
        "subassembly",
        "operation",
        "inspection",
        "decision",
        "input",
        "output",
    }
)
EDGE_KINDS = frozenset({"precedence", "rework", "feedback", "material"})


Finding = Dict[str, Any]


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
) -> Finding:
    result: Finding = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if node_id is not None:
        result["nodeId"] = node_id
    if edge_id is not None:
        result["edgeId"] = edge_id
    return result


def _is_schema_v2(value: Any) -> bool:
    return value == PROCESS_MAP_SCHEMA_VERSION or value == str(PROCESS_MAP_SCHEMA_VERSION)


def _migrated_node_type(node: Dict[str, Any]) -> str:
    level = node.get("level")
    try:
        numeric_level = int(level)
    except (TypeError, ValueError):
        numeric_level = 3
    if numeric_level <= 0:
        return "assembly"
    if numeric_level <= 2:
        return "subassembly"
    return "input"


def migrate_process_map(process_map: Any) -> Tuple[Any, List[Finding]]:
    """Return a schema-v2 copy and informational migration findings.

    Schema-v2 maps are copied but otherwise left alone. Older maps gain the
    additive v2 fields in memory; callers decide whether to persist them.
    """
    if not isinstance(process_map, dict):
        return copy.deepcopy(process_map), []

    migrated = copy.deepcopy(process_map)
    if _is_schema_v2(migrated.get("schemaVersion")):
        migrated["schemaVersion"] = PROCESS_MAP_SCHEMA_VERSION
        return migrated, []

    migrated["schemaVersion"] = PROCESS_MAP_SCHEMA_VERSION
    migrated.setdefault("layoutVersion", 1)
    migrated.setdefault("edges", [])

    counts: Counter[str] = Counter()
    nodes = migrated.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict) or node.get("type"):
                continue
            node_type = _migrated_node_type(node)
            node["type"] = node_type
            counts[node_type] += 1

    findings = [
        _finding(
            "info",
            "migration_auto_typed_nodes",
            f"Schema v2 migration auto-typed {count} node(s) as {node_type}; review these assignments.",
        )
        for node_type, count in sorted(counts.items())
    ]
    return migrated, findings


def _node_id(node: Any) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    value = node.get("nodeId")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _edge_endpoint(edge: Dict[str, Any], side: str) -> Tuple[Optional[str], Optional[str]]:
    endpoint = edge.get(side)
    if not isinstance(endpoint, dict):
        return None, None
    node_id = endpoint.get("nodeId")
    port = endpoint.get("port")
    clean_node_id = node_id.strip() if isinstance(node_id, str) and node_id.strip() else None
    clean_port = port.strip() if isinstance(port, str) and port.strip() else None
    return clean_node_id, clean_port


def _precedence_cycles(adjacency: Dict[str, Set[str]]) -> List[List[str]]:
    colors: Dict[str, int] = {}
    stack: List[str] = []
    stack_index: Dict[str, int] = {}
    cycles: List[List[str]] = []
    seen: Set[Tuple[str, ...]] = set()

    def canonical_cycle(nodes: List[str]) -> Tuple[str, ...]:
        ring = nodes[:-1] if len(nodes) > 1 and nodes[0] == nodes[-1] else nodes
        if not ring:
            return tuple()
        rotations = [tuple(ring[index:] + ring[:index]) for index in range(len(ring))]
        return min(rotations)

    def visit(node_id: str) -> None:
        colors[node_id] = 1
        stack_index[node_id] = len(stack)
        stack.append(node_id)
        for target_id in sorted(adjacency.get(node_id, set())):
            color = colors.get(target_id, 0)
            if color == 0:
                visit(target_id)
            elif color == 1:
                start = stack_index[target_id]
                cycle = stack[start:] + [target_id]
                signature = canonical_cycle(cycle)
                if signature and signature not in seen:
                    seen.add(signature)
                    cycles.append(cycle)
        stack.pop()
        stack_index.pop(node_id, None)
        colors[node_id] = 2

    all_nodes = set(adjacency)
    for targets in adjacency.values():
        all_nodes.update(targets)
    for node_id in sorted(all_nodes):
        if colors.get(node_id, 0) == 0:
            visit(node_id)
    return cycles


def _containment_reachability(
    nodes_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[Set[str], List[str]]:
    children: Dict[str, List[str]] = defaultdict(list)
    roots: List[str] = []
    for node_id, node in nodes_by_id.items():
        parent_id = node.get("parentNodeId")
        if parent_id is None:
            roots.append(node_id)
        elif isinstance(parent_id, str) and parent_id in nodes_by_id:
            children[parent_id].append(node_id)

    reached: Set[str] = set()
    pending = list(sorted(roots))
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(children.get(node_id, []))
    return reached, roots


def validate_process_map(
    process_map: Any,
    known_part_ids: Optional[Iterable[str]] = None,
) -> List[Finding]:
    """Validate a schema-v2 process map without modifying it."""
    findings: List[Finding] = []
    if not isinstance(process_map, dict):
        return [_finding("error", "map_not_object", "Process map must be a JSON object.")]

    if not _is_schema_v2(process_map.get("schemaVersion")):
        findings.append(
            _finding(
                "error",
                "unsupported_schema_version",
                f"Process map schemaVersion must be {PROCESS_MAP_SCHEMA_VERSION}.",
            )
        )

    nodes = process_map.get("nodes")
    if not isinstance(nodes, list):
        findings.append(_finding("error", "nodes_not_array", "Process map nodes must be an array."))
        nodes = []
    edges = process_map.get("edges")
    if not isinstance(edges, list):
        findings.append(_finding("error", "edges_not_array", "Process map edges must be an array."))
        edges = []

    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    duplicate_node_ids: Set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            findings.append(
                _finding("error", "node_not_object", f"Node at index {index} must be an object.")
            )
            continue
        node_id = _node_id(node)
        if node_id is None:
            findings.append(
                _finding("error", "node_id_missing", f"Node at index {index} has no valid nodeId.")
            )
            continue
        if node_id in nodes_by_id:
            duplicate_node_ids.add(node_id)
            findings.append(
                _finding(
                    "error",
                    "duplicate_node_id",
                    f"Node id '{node_id}' is duplicated.",
                    node_id=node_id,
                )
            )
            continue
        nodes_by_id[node_id] = node

        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            findings.append(
                _finding(
                    "error",
                    "unknown_node_type",
                    f"Node '{node_id}' has unsupported type '{node_type}'.",
                    node_id=node_id,
                )
            )

        position = node.get("position")
        if position is not None:
            valid_position = isinstance(position, dict)
            if valid_position:
                for axis in ("x", "y"):
                    value = position.get(axis)
                    valid_position = (
                        valid_position
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(float(value))
                    )
            if not valid_position:
                findings.append(
                    _finding(
                        "error",
                        "invalid_node_position",
                        f"Node '{node_id}' position must contain finite numeric x and y values.",
                        node_id=node_id,
                    )
                )

        part_ids = node.get("partIds", [])
        if not isinstance(part_ids, list) or any(not isinstance(value, str) for value in part_ids):
            findings.append(
                _finding(
                    "error",
                    "invalid_part_ids",
                    f"Node '{node_id}' partIds must be an array of strings.",
                    node_id=node_id,
                )
            )

    for node_id, node in nodes_by_id.items():
        parent_id = node.get("parentNodeId")
        if parent_id is None:
            continue
        if not isinstance(parent_id, str) or parent_id not in nodes_by_id:
            findings.append(
                _finding(
                    "error",
                    "dangling_parent",
                    f"Node '{node_id}' references missing parent '{parent_id}'.",
                    node_id=node_id,
                )
            )

    known_parts = set(known_part_ids) if known_part_ids is not None else None
    if known_parts is not None:
        for node_id, node in nodes_by_id.items():
            part_ids = node.get("partIds", [])
            if not isinstance(part_ids, list):
                continue
            for part_id in sorted({value for value in part_ids if isinstance(value, str)}):
                if part_id not in known_parts:
                    findings.append(
                        _finding(
                            "warning",
                            "unknown_part_reference",
                            f"Node '{node_id}' references unknown product part '{part_id}'.",
                            node_id=node_id,
                        )
                    )

    seen_edge_ids: Set[str] = set()
    seen_edge_shapes: Set[Tuple[str, str, str]] = set()
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            findings.append(
                _finding("error", "edge_not_object", f"Edge at index {index} must be an object.")
            )
            continue
        edge_id_raw = edge.get("edgeId")
        edge_id = edge_id_raw.strip() if isinstance(edge_id_raw, str) and edge_id_raw.strip() else None
        if edge_id is None:
            findings.append(
                _finding("error", "edge_id_missing", f"Edge at index {index} has no valid edgeId.")
            )
        elif edge_id in seen_edge_ids:
            findings.append(
                _finding(
                    "error",
                    "duplicate_edge_id",
                    f"Edge id '{edge_id}' is duplicated.",
                    edge_id=edge_id,
                )
            )
        else:
            seen_edge_ids.add(edge_id)

        kind = edge.get("kind")
        if kind not in EDGE_KINDS:
            findings.append(
                _finding(
                    "error",
                    "unknown_edge_kind",
                    f"Edge '{edge_id or index}' has unsupported kind '{kind}'.",
                    edge_id=edge_id,
                )
            )

        from_id, from_port = _edge_endpoint(edge, "from")
        to_id, to_port = _edge_endpoint(edge, "to")
        if from_id is None or from_port is None or to_id is None or to_port is None:
            findings.append(
                _finding(
                    "error",
                    "invalid_edge_endpoint",
                    f"Edge '{edge_id or index}' must have from/to nodeId and port values.",
                    edge_id=edge_id,
                )
            )
            continue

        missing_ids = [node_id for node_id in (from_id, to_id) if node_id not in nodes_by_id]
        if missing_ids:
            findings.append(
                _finding(
                    "error",
                    "dangling_edge_endpoint",
                    f"Edge '{edge_id or index}' references missing node(s): {', '.join(missing_ids)}.",
                    edge_id=edge_id,
                )
            )
            continue
        if from_id == to_id:
            findings.append(
                _finding(
                    "error",
                    "self_edge",
                    f"Edge '{edge_id or index}' connects node '{from_id}' to itself.",
                    edge_id=edge_id,
                )
            )
            continue

        shape = (from_id, to_id, str(kind))
        if shape in seen_edge_shapes:
            findings.append(
                _finding(
                    "error",
                    "duplicate_edge",
                    f"Duplicate {kind} edge from '{from_id}' to '{to_id}'.",
                    edge_id=edge_id,
                )
            )
            continue
        seen_edge_shapes.add(shape)

        if kind == "precedence":
            adjacency[from_id].add(to_id)
            outgoing[from_id] += 1
            incoming[to_id] += 1

    for cycle in _precedence_cycles(adjacency):
        findings.append(
            _finding(
                "error",
                "precedence_cycle",
                "Precedence edges contain a cycle: " + " -> ".join(cycle) + ".",
                node_id=cycle[0] if cycle else None,
            )
        )

    reached, roots = _containment_reachability(nodes_by_id)
    for node_id in sorted(set(nodes_by_id) - reached):
        findings.append(
            _finding(
                "warning",
                "unreachable_node",
                f"Node '{node_id}' is not reachable from a containment root.",
                node_id=node_id,
            )
        )
    for node_id in sorted(roots):
        node = nodes_by_id[node_id]
        level = node.get("level")
        if level not in (0, "0", None):
            findings.append(
                _finding(
                    "warning",
                    "orphan_root",
                    f"Node '{node_id}' has no parent but is not a level-0 root.",
                    node_id=node_id,
                )
            )

    for node_id, node in nodes_by_id.items():
        node_type = node.get("type")
        if node_type == "input" and incoming[node_id] > 0:
            findings.append(
                _finding(
                    "warning",
                    "input_has_incoming_precedence",
                    f"Input node '{node_id}' has an incoming precedence edge.",
                    node_id=node_id,
                )
            )
        if node_type == "output" and outgoing[node_id] > 0:
            findings.append(
                _finding(
                    "warning",
                    "output_has_outgoing_precedence",
                    f"Output node '{node_id}' has an outgoing precedence edge.",
                    node_id=node_id,
                )
            )
        if node_type == "decision" and outgoing[node_id] < 2:
            findings.append(
                _finding(
                    "warning",
                    "decision_has_fewer_than_two_outputs",
                    f"Decision node '{node_id}' has fewer than two outgoing precedence edges.",
                    node_id=node_id,
                )
            )

    return findings


def has_structural_errors(findings: Iterable[Finding]) -> bool:
    return any(finding.get("severity") == "error" for finding in findings)
