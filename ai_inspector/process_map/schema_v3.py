"""Placement-only process-map schema and product-structure helpers."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple


PROCESS_MAP_PLACEMENT_SCHEMA_VERSION = 3
PROCESS_MAP_LAYOUT_VERSION = 3
PROCESS_MAP_GROUP_LAYOUT_VERSION = 2
PRODUCT_STRUCTURE_SCHEMA_VERSION = 1
PRODUCT_KINDS = frozenset({"assembly", "subassembly", "part"})
CANVAS_NODE_KINDS = frozenset({"product_occurrence", "process_step", "junction"})
JUNCTION_TYPES = frozenset({"wire_branch", "parallel_and", "merge", "split"})
PORT_ORIENTATIONS = frozenset({"horizontal", "vertical"})
PORT_ORDERS = frozenset({"input_first", "output_first"})
POSITION_MODES = frozenset({"auto", "manual", "locked"})
PROCESS_STEP_TYPES = frozenset({"operation", "inspection", "decision", "input", "output"})
EDGE_KINDS = frozenset({"precedence", "rework", "feedback", "material"})
EDGE_ROUTE_MODES = frozenset(
    {"bezier_legacy", "orthogonal_auto", "orthogonal_manual", "polyline_manual"}
)
LAYOUT_FLOW_DIRECTIONS = frozenset(
    {"left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"}
)
LAYOUT_POLICY_ROUTE_MODES = frozenset(
    {"bezier_legacy", "orthogonal_auto", "orthogonal_manual"}
)
LAYOUT_POLICY_NUMERIC_FIELDS = {
    "gridSize": (4.0, 200.0),
    "nodeClearance": (0.0, 500.0),
    "edgeClearance": (0.0, 200.0),
    "portLeadLength": (0.0, 240.0),
}
MAX_ROUTE_POINTS = 128
REFERENCE_KINDS = frozenset({"machine", "tool", "requirement", "standard"})
REFERENCE_KNOWLEDGE_STATUSES = frozenset(
    {"authored", "derived", "inferred", "unknown", "illustrative"}
)
MAX_NODE_LABEL_LENGTH = 120
MAX_NODE_NOTE_LENGTH = 2000
PROCESS_STEP_PROPERTY_LIMITS = {
    "description": 2000,
    "resultLabel": 160,
    "duration": 80,
    "fastenersConsumables": 1000,
    "torqueRequirements": 1000,
    "inspectionRequirements": 1000,
    "constraints": 1000,
}
MAX_REFERENCE_NAME_LENGTH = 160
MAX_REFERENCE_IDENTIFIER_LENGTH = 120
MAX_REFERENCE_REVISION_LENGTH = 80
MAX_REFERENCE_CLAUSE_LENGTH = 120
MAX_REFERENCE_DETAILS_LENGTH = 1000
MAX_REFERENCE_SOURCE_ID_LENGTH = 160
MAX_REFERENCE_SOURCE_HASH_LENGTH = 128
MAX_REFERENCE_POPULATED_BY_LENGTH = 80
MAX_REFERENCE_POPULATED_AT_LENGTH = 64
MAX_REFERENCES_PER_TARGET = 24
MAX_REFERENCE_CATALOG_ITEMS = 500
MAX_PROCESS_PLAN_IMPORTS = 16
MAX_PROCESS_PLAN_DISCLAIMER_LENGTH = 1000
MAX_DISMISSED_SUGGESTIONS = 500
MAX_SUGGESTION_ID_LENGTH = 128
GROUP_COLOR_KEYS = frozenset(
    {"orange", "blue", "green", "purple", "red", "teal", "gray", "yellow"}
)
MAX_GROUP_LABEL_LENGTH = 120
MAX_GROUP_DESCRIPTION_LENGTH = 2000
MIN_GROUP_WIDTH = 220
MIN_GROUP_HEIGHT = 112
SEMANTIC_KNOWLEDGE_STATUSES = frozenset({"authored", "derived", "inferred", "unknown"})
SEMANTIC_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "procedure",
        "work_instruction",
        "standard",
        "user_authored_map",
        "assembly_structure",
        "mate_relationship",
        "geometry",
        "domain_heuristic",
        "user_statement",
    }
)
MAX_SEMANTIC_EVIDENCE_ITEMS = 24
MAX_SEMANTIC_ASSUMPTION_IDS = 24
_AUTHORITATIVE_PROCESS_PROPERTIES = frozenset(
    {
        "duration",
        "fastenersConsumables",
        "torqueRequirements",
        "inspectionRequirements",
        "constraints",
    }
)


Finding = Dict[str, Any]


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
    occurrence_id: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Finding:
    result: Finding = {"severity": severity, "code": code, "message": message}
    if node_id is not None:
        result["nodeId"] = node_id
    if edge_id is not None:
        result["edgeId"] = edge_id
    if occurrence_id is not None:
        result["occurrenceId"] = occurrence_id
    if group_id is not None:
        result["groupId"] = group_id
    return result


def _clean_id(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _finite_position(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and all(
            isinstance(value.get(axis), (int, float))
            and not isinstance(value.get(axis), bool)
            and math.isfinite(float(value[axis]))
            for axis in ("x", "y")
        )
    )


def _finite_group_size(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and all(
            isinstance(value.get(axis), (int, float))
            and not isinstance(value.get(axis), bool)
            and math.isfinite(float(value[axis]))
            and float(value[axis]) >= minimum
            for axis, minimum in (
                ("width", MIN_GROUP_WIDTH),
                ("height", MIN_GROUP_HEIGHT),
            )
        )
    )


def node_position_mode(node: Mapping[str, Any]) -> str:
    """Return the effective position owner for old and current map records."""

    mode = node.get("positionMode")
    if mode in POSITION_MODES:
        return str(mode)
    return "locked" if node.get("locked") is True else "manual"


def _validate_semantic_metadata(
    value: Any,
    *,
    target_label: str,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
) -> List[Finding]:
    findings: List[Finding] = []
    if value is None:
        return findings
    if not isinstance(value, dict):
        return [
            _finding(
                "error",
                "invalid_semantic_metadata",
                f"{target_label} semantic metadata must be an object.",
                node_id=node_id,
                edge_id=edge_id,
            )
        ]
    unknown = sorted(
        set(value)
        - {
            "planId",
            "semanticRef",
            "knowledgeStatus",
            "evidence",
            "assumptionIds",
            "branchId",
            "stageIndex",
            "intermediateResultId",
        }
    )
    if unknown:
        findings.append(
            _finding(
                "error",
                "unknown_semantic_metadata_field",
                f"{target_label} has unsupported semantic fields: {', '.join(unknown)}.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    for field in ("planId", "semanticRef"):
        if _clean_id(value.get(field)) is None:
            findings.append(
                _finding(
                    "error",
                    "semantic_identity_missing",
                    f"{target_label} semantic {field} is required.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
    status = value.get("knowledgeStatus")
    if status not in SEMANTIC_KNOWLEDGE_STATUSES:
        findings.append(
            _finding(
                "error",
                "invalid_semantic_knowledge_status",
                f"{target_label} has unsupported semantic knowledgeStatus '{status}'.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > MAX_SEMANTIC_EVIDENCE_ITEMS:
        findings.append(
            _finding(
                "error",
                "invalid_semantic_evidence",
                (
                    f"{target_label} semantic evidence must be an array of at most "
                    f"{MAX_SEMANTIC_EVIDENCE_ITEMS} items."
                ),
                node_id=node_id,
                edge_id=edge_id,
            )
        )
        evidence = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            findings.append(
                _finding(
                    "error",
                    "invalid_semantic_evidence",
                    f"{target_label} semantic evidence item {index} must be an object.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
            continue
        source_type = item.get("sourceType")
        if source_type not in SEMANTIC_EVIDENCE_SOURCE_TYPES:
            findings.append(
                _finding(
                    "error",
                    "invalid_semantic_evidence_source",
                    f"{target_label} has unsupported evidence sourceType '{source_type}'.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
        if _clean_id(item.get("sourceRef")) is None:
            findings.append(
                _finding(
                    "error",
                    "semantic_evidence_source_missing",
                    f"{target_label} evidence item {index} requires sourceRef.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
    assumption_ids = value.get("assumptionIds", [])
    if (
        not isinstance(assumption_ids, list)
        or len(assumption_ids) > MAX_SEMANTIC_ASSUMPTION_IDS
        or any(_clean_id(item) is None for item in assumption_ids)
    ):
        findings.append(
            _finding(
                "error",
                "invalid_semantic_assumptions",
                (
                    f"{target_label} semantic assumptionIds must contain at most "
                    f"{MAX_SEMANTIC_ASSUMPTION_IDS} non-empty ids."
                ),
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    if status in {"authored", "derived"} and not evidence:
        findings.append(
            _finding(
                "error",
                "authoritative_evidence_required",
                f"{target_label} cannot be '{status}' without evidence.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    if status == "inferred" and not evidence and not assumption_ids:
        findings.append(
            _finding(
                "error",
                "inference_basis_required",
                f"{target_label} inferred semantics require evidence or an assumption.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    return findings


def _validate_reference_ids(
    value: Any,
    known_reference_ids: Set[str],
    *,
    target_label: str,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
) -> Tuple[List[Finding], Set[str]]:
    findings: List[Finding] = []
    used: Set[str] = set()
    if value is None:
        return findings, used
    if not isinstance(value, list):
        findings.append(
            _finding(
                "error",
                "reference_ids_not_array",
                f"{target_label} referenceIds must be an array.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
        return findings, used
    if len(value) > MAX_REFERENCES_PER_TARGET:
        findings.append(
            _finding(
                "error",
                "too_many_target_references",
                f"{target_label} can reference at most {MAX_REFERENCES_PER_TARGET} catalog items.",
                node_id=node_id,
                edge_id=edge_id,
            )
        )
    seen: Set[str] = set()
    for raw_reference_id in value:
        reference_id = _clean_id(raw_reference_id)
        if reference_id is None:
            findings.append(
                _finding(
                    "error",
                    "invalid_target_reference_id",
                    f"{target_label} contains an invalid reference id.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
            continue
        if reference_id in seen:
            findings.append(
                _finding(
                    "error",
                    "duplicate_target_reference",
                    f"{target_label} references '{reference_id}' more than once.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
            continue
        seen.add(reference_id)
        used.add(reference_id)
        if reference_id not in known_reference_ids:
            findings.append(
                _finding(
                    "error",
                    "unknown_target_reference",
                    f"{target_label} references unknown catalog item '{reference_id}'.",
                    node_id=node_id,
                    edge_id=edge_id,
                )
            )
    return findings, used


def _legacy_product_kind(node: Dict[str, Any]) -> str:
    level = node.get("level")
    try:
        numeric_level = int(level)
    except (TypeError, ValueError):
        numeric_level = 3
    if numeric_level <= 0:
        return "assembly"
    if numeric_level <= 2:
        return "subassembly"
    return "part"


def _legacy_node_is_product_occurrence(node: Dict[str, Any]) -> bool:
    node_type = node.get("type")
    if node_type in {"operation", "inspection", "decision", "output"}:
        return False
    return (
        node_type in {"assembly", "subassembly"}
        or isinstance(node.get("componentId"), str)
        or "level" in node
    )


def product_structure_from_legacy(
    process_map: Dict[str, Any],
    product_id: str,
) -> Tuple[Dict[str, Any], List[Finding]]:
    """Extract the read-only product catalog from a legacy hierarchy map."""
    occurrences: List[Dict[str, Any]] = []
    findings: List[Finding] = []
    for node in process_map.get("nodes", []):
        if not isinstance(node, dict) or not _legacy_node_is_product_occurrence(node):
            continue
        occurrence_id = _clean_id(node.get("nodeId"))
        if occurrence_id is None:
            continue
        part_ids = [
            value for value in node.get("partIds", [])
            if isinstance(value, str) and value.strip()
        ]
        item_id = _clean_id(node.get("componentId"))
        if item_id is None and len(part_ids) == 1:
            item_id = part_ids[0]
        occurrence = {
            "occurrenceId": occurrence_id,
            "parentOccurrenceId": _clean_id(node.get("parentNodeId")),
            "itemId": item_id,
            "name": str(node.get("name") or occurrence_id),
            "kind": _legacy_product_kind(node),
            "level": node.get("level", 0),
            "partIds": part_ids,
            "partNames": [
                value for value in node.get("partNames", [])
                if isinstance(value, str)
            ],
        }
        for key in (
            "purpose",
            "suggestedBuildOrder",
            "reviewRequired",
            "module",
            "subassembly",
        ):
            if key in node:
                occurrence[key] = copy.deepcopy(node[key])
        occurrences.append(occurrence)

    structure = {
        "schemaVersion": PRODUCT_STRUCTURE_SCHEMA_VERSION,
        "productId": product_id,
        "productName": str(process_map.get("productName") or product_id),
        "occurrences": occurrences,
    }
    findings.extend(validate_product_structure(structure))
    findings.append(
        _finding(
            "info",
            "product_structure_derived_from_legacy_map",
            f"Derived {len(occurrences)} product occurrence(s) from the legacy hierarchy.",
        )
    )
    return structure, findings


def validate_product_structure(structure: Any) -> List[Finding]:
    findings: List[Finding] = []
    if not isinstance(structure, dict):
        return [_finding("error", "structure_not_object", "Product structure must be an object.")]
    if structure.get("schemaVersion") != PRODUCT_STRUCTURE_SCHEMA_VERSION:
        findings.append(
            _finding(
                "error",
                "unsupported_structure_schema",
                f"Product structure schemaVersion must be {PRODUCT_STRUCTURE_SCHEMA_VERSION}.",
            )
        )
    occurrences = structure.get("occurrences")
    if not isinstance(occurrences, list):
        return findings + [
            _finding("error", "occurrences_not_array", "Product occurrences must be an array.")
        ]

    by_id: Dict[str, Dict[str, Any]] = {}
    for index, occurrence in enumerate(occurrences):
        if not isinstance(occurrence, dict):
            findings.append(
                _finding("error", "occurrence_not_object", f"Occurrence at index {index} must be an object.")
            )
            continue
        occurrence_id = _clean_id(occurrence.get("occurrenceId"))
        if occurrence_id is None:
            findings.append(
                _finding("error", "occurrence_id_missing", f"Occurrence at index {index} has no valid id.")
            )
            continue
        if occurrence_id in by_id:
            findings.append(
                _finding(
                    "error",
                    "duplicate_occurrence_id",
                    f"Product occurrence '{occurrence_id}' is duplicated.",
                    occurrence_id=occurrence_id,
                )
            )
            continue
        by_id[occurrence_id] = occurrence
        if occurrence.get("kind") not in PRODUCT_KINDS:
            findings.append(
                _finding(
                    "error",
                    "unknown_product_kind",
                    f"Product occurrence '{occurrence_id}' has unsupported kind '{occurrence.get('kind')}'.",
                    occurrence_id=occurrence_id,
                )
            )

    adjacency: Dict[str, List[str]] = defaultdict(list)
    roots: List[str] = []
    for occurrence_id, occurrence in by_id.items():
        parent_id = _clean_id(occurrence.get("parentOccurrenceId"))
        if parent_id is None:
            roots.append(occurrence_id)
        elif parent_id not in by_id:
            findings.append(
                _finding(
                    "error",
                    "dangling_parent_occurrence",
                    f"Product occurrence '{occurrence_id}' references missing parent '{parent_id}'.",
                    occurrence_id=occurrence_id,
                )
            )
        else:
            adjacency[parent_id].append(occurrence_id)

    reached: Set[str] = set()
    pending = list(roots)
    while pending:
        occurrence_id = pending.pop()
        if occurrence_id in reached:
            continue
        reached.add(occurrence_id)
        pending.extend(adjacency.get(occurrence_id, []))
    for occurrence_id in sorted(set(by_id) - reached):
        findings.append(
            _finding(
                "error",
                "unreachable_product_occurrence",
                f"Product occurrence '{occurrence_id}' is unreachable from a root occurrence.",
                occurrence_id=occurrence_id,
            )
        )
    return findings


def _default_position(index: int) -> Dict[str, float]:
    return {
        "x": float(80 + (index % 4) * 440),
        "y": float(80 + (index // 4) * 230),
    }


def migrate_to_placement_map(
    process_map: Dict[str, Any],
    *,
    product_id: str,
    structure_revision: str,
    product_structure: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Finding]]:
    """Convert v1/v2 hierarchy maps into placement-only schema v3."""
    if process_map.get("schemaVersion") == PROCESS_MAP_PLACEMENT_SCHEMA_VERSION:
        migrated = copy.deepcopy(process_map)
        migrated.setdefault("mapId", "default")
        migrated.setdefault("productId", product_id)
        migrated.setdefault("sourceStructureRevision", structure_revision)
        layout_version = migrated.get("layoutVersion")
        if (
            not isinstance(layout_version, int)
            or isinstance(layout_version, bool)
            or layout_version < PROCESS_MAP_LAYOUT_VERSION
        ):
            migrated["layoutVersion"] = PROCESS_MAP_LAYOUT_VERSION
        migrated.setdefault("canvasNodes", [])
        migrated.setdefault("canvasEdges", [])
        migrated.setdefault("canvasGroups", [])
        for node in migrated["canvasNodes"]:
            if not isinstance(node, dict):
                continue
            mode = node_position_mode(node)
            node["positionMode"] = mode
            if mode == "locked":
                node["locked"] = True
            else:
                node.pop("locked", None)
        return migrated, []

    occurrences = {
        occurrence.get("occurrenceId"): occurrence
        for occurrence in product_structure.get("occurrences", [])
        if isinstance(occurrence, dict) and _clean_id(occurrence.get("occurrenceId"))
    }
    legacy_nodes = [node for node in process_map.get("nodes", []) if isinstance(node, dict)]
    legacy_edges = [edge for edge in process_map.get("edges", []) if isinstance(edge, dict)]
    edge_node_ids = {
        node_id
        for edge in legacy_edges
        for node_id in (
            _clean_id((edge.get("from") or {}).get("nodeId")),
            _clean_id((edge.get("to") or {}).get("nodeId")),
        )
        if node_id
    }

    canvas_nodes: List[Dict[str, Any]] = []
    placement_ids: Set[str] = set()
    for node in legacy_nodes:
        node_id = _clean_id(node.get("nodeId"))
        if node_id is None:
            continue
        source_occurrence = occurrences.get(node_id)
        process_type = node.get("type") if node.get("type") in PROCESS_STEP_TYPES else None
        authored_process_step = source_occurrence is None and process_type is not None
        placed = _finite_position(node.get("position")) or node_id in edge_node_ids or authored_process_step
        if not placed:
            continue
        placement: Dict[str, Any] = {
            "nodeId": node_id,
            "position": copy.deepcopy(node.get("position"))
            if _finite_position(node.get("position"))
            else _default_position(len(canvas_nodes)),
            "positionMode": "locked" if node.get("locked") is True else "manual",
        }
        if source_occurrence is not None:
            placement.update(
                {
                    "nodeKind": "product_occurrence",
                    "sourceOccurrenceId": node_id,
                    "nameSnapshot": source_occurrence.get("name") or node_id,
                    "itemIdSnapshot": source_occurrence.get("itemId"),
                }
            )
        else:
            placement.update(
                {
                    "nodeKind": "process_step",
                    "processType": process_type or "operation",
                    "name": str(node.get("name") or node_id),
                    "description": str(node.get("purpose") or ""),
                }
            )
        canvas_nodes.append(placement)
        placement_ids.add(node_id)

    canvas_edges = []
    for edge in legacy_edges:
        from_id = _clean_id((edge.get("from") or {}).get("nodeId"))
        to_id = _clean_id((edge.get("to") or {}).get("nodeId"))
        if from_id in placement_ids and to_id in placement_ids:
            canvas_edges.append(copy.deepcopy(edge))

    migrated = {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "mapId": "default",
        "productId": product_id,
        "productName": str(process_map.get("productName") or product_structure.get("productName") or product_id),
        "sourceStructureRevision": structure_revision,
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": canvas_nodes,
        "canvasEdges": canvas_edges,
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    findings = [
        _finding(
            "info",
            "placement_map_migrated",
            f"Migrated {len(canvas_nodes)} authored placement(s); unplaced hierarchy items remain in the product tree.",
        )
    ]
    return migrated, findings


def _edge_endpoint(edge: Dict[str, Any], side: str) -> Tuple[Optional[str], Optional[str]]:
    endpoint = edge.get(side)
    if not isinstance(endpoint, dict):
        return None, None
    return _clean_id(endpoint.get("nodeId")), _clean_id(endpoint.get("port"))


def _precedence_cycles(adjacency: Dict[str, Set[str]]) -> List[List[str]]:
    colors: Dict[str, int] = {}
    stack: List[str] = []
    stack_index: Dict[str, int] = {}
    cycles: List[List[str]] = []

    def visit(node_id: str) -> None:
        colors[node_id] = 1
        stack_index[node_id] = len(stack)
        stack.append(node_id)
        for target_id in sorted(adjacency.get(node_id, set())):
            color = colors.get(target_id, 0)
            if color == 0:
                visit(target_id)
            elif color == 1:
                cycles.append(stack[stack_index[target_id]:] + [target_id])
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


def validate_placement_map(
    process_map: Any,
    known_occurrence_ids: Optional[Iterable[str]] = None,
) -> List[Finding]:
    findings: List[Finding] = []
    if not isinstance(process_map, dict):
        return [_finding("error", "map_not_object", "Process map must be an object.")]
    if process_map.get("schemaVersion") != PROCESS_MAP_PLACEMENT_SCHEMA_VERSION:
        findings.append(
            _finding(
                "error",
                "unsupported_schema_version",
                f"Process map schemaVersion must be {PROCESS_MAP_PLACEMENT_SCHEMA_VERSION}.",
            )
        )
    nodes = process_map.get("canvasNodes")
    edges = process_map.get("canvasEdges")
    groups = process_map.get("canvasGroups", [])
    if not isinstance(nodes, list):
        findings.append(_finding("error", "canvas_nodes_not_array", "canvasNodes must be an array."))
        nodes = []
    if not isinstance(edges, list):
        findings.append(_finding("error", "canvas_edges_not_array", "canvasEdges must be an array."))
        edges = []
    if not isinstance(groups, list):
        findings.append(_finding("error", "canvas_groups_not_array", "canvasGroups must be an array."))
        groups = []
    layout_version = process_map.get("layoutVersion")
    if layout_version is not None and (
        not isinstance(layout_version, int)
        or isinstance(layout_version, bool)
        or layout_version < 1
    ):
        findings.append(
            _finding(
                "error",
                "invalid_layout_version",
                "layoutVersion must be a positive integer when provided.",
            )
        )
    if groups and (
        not isinstance(layout_version, int)
        or isinstance(layout_version, bool)
        or layout_version < PROCESS_MAP_GROUP_LAYOUT_VERSION
    ):
        findings.append(
            _finding(
                "error",
                "groups_require_layout_version_2",
                f"canvasGroups require layoutVersion {PROCESS_MAP_GROUP_LAYOUT_VERSION} or newer.",
            )
        )

    layout_policy = process_map.get("layoutPolicy")
    if layout_policy is not None:
        if not isinstance(layout_policy, dict):
            findings.append(
                _finding(
                    "error",
                    "invalid_layout_policy",
                    "layoutPolicy must be an object when provided.",
                )
            )
        else:
            unknown_policy_fields = sorted(
                set(layout_policy)
                - {
                    "flowDirection",
                    "gridSize",
                    "nodeClearance",
                    "edgeClearance",
                    "portLeadLength",
                    "routeMode",
                }
            )
            if unknown_policy_fields:
                findings.append(
                    _finding(
                        "error",
                        "unknown_layout_policy_field",
                        "layoutPolicy contains unsupported fields: "
                        + ", ".join(unknown_policy_fields)
                        + ".",
                    )
                )
            flow_direction = layout_policy.get("flowDirection")
            if (
                flow_direction is not None
                and flow_direction not in LAYOUT_FLOW_DIRECTIONS
            ):
                findings.append(
                    _finding(
                        "error",
                        "invalid_layout_flow_direction",
                        f"layoutPolicy flowDirection '{flow_direction}' is unsupported.",
                    )
                )
            route_mode = layout_policy.get("routeMode")
            if (
                route_mode is not None
                and route_mode not in LAYOUT_POLICY_ROUTE_MODES
            ):
                findings.append(
                    _finding(
                        "error",
                        "invalid_layout_route_mode",
                        f"layoutPolicy routeMode '{route_mode}' is unsupported.",
                    )
                )
            for field, (minimum, maximum) in LAYOUT_POLICY_NUMERIC_FIELDS.items():
                value = layout_policy.get(field)
                if value is None:
                    continue
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) < minimum
                    or float(value) > maximum
                ):
                    findings.append(
                        _finding(
                            "error",
                            "invalid_layout_policy_value",
                            f"layoutPolicy {field} must be between {minimum:g} and {maximum:g}.",
                        )
                    )

    dismissed_suggestions = process_map.get("dismissedSuggestions", [])
    if not isinstance(dismissed_suggestions, list):
        findings.append(
            _finding(
                "error",
                "dismissed_suggestions_not_array",
                "dismissedSuggestions must be an array.",
            )
        )
        dismissed_suggestions = []
    if len(dismissed_suggestions) > MAX_DISMISSED_SUGGESTIONS:
        findings.append(
            _finding(
                "error",
                "dismissed_suggestions_too_large",
                (
                    "dismissedSuggestions can contain at most "
                    f"{MAX_DISMISSED_SUGGESTIONS} items."
                ),
            )
        )
    seen_dismissed_suggestions: Set[str] = set()
    for index, value in enumerate(dismissed_suggestions):
        suggestion_id = _clean_id(value)
        if suggestion_id is None or len(suggestion_id) > MAX_SUGGESTION_ID_LENGTH:
            findings.append(
                _finding(
                    "error",
                    "invalid_dismissed_suggestion",
                    (
                        f"Dismissed suggestion at index {index} must contain 1 to "
                        f"{MAX_SUGGESTION_ID_LENGTH} characters."
                    ),
                )
            )
            continue
        if suggestion_id in seen_dismissed_suggestions:
            findings.append(
                _finding(
                    "error",
                    "duplicate_dismissed_suggestion",
                    f"Dismissed suggestion id '{suggestion_id}' is duplicated.",
                )
            )
            continue
        seen_dismissed_suggestions.add(suggestion_id)

    catalog = process_map.get("referenceCatalog", [])
    if not isinstance(catalog, list):
        findings.append(
            _finding("error", "reference_catalog_not_array", "referenceCatalog must be an array.")
        )
        catalog = []
    if len(catalog) > MAX_REFERENCE_CATALOG_ITEMS:
        findings.append(
            _finding(
                "error",
                "reference_catalog_too_large",
                f"referenceCatalog can contain at most {MAX_REFERENCE_CATALOG_ITEMS} items.",
            )
        )
    reference_ids: Set[str] = set()
    reference_identity_keys: Set[Tuple[str, str, str, str, str]] = set()
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            findings.append(
                _finding("error", "reference_not_object", f"Catalog item at index {index} must be an object.")
            )
            continue
        reference_id = _clean_id(item.get("referenceId"))
        if reference_id is None:
            findings.append(
                _finding("error", "reference_id_missing", f"Catalog item at index {index} has no valid referenceId.")
            )
            continue
        if reference_id in reference_ids:
            findings.append(
                _finding("error", "duplicate_reference_id", f"Catalog reference id '{reference_id}' is duplicated.")
            )
            continue
        reference_ids.add(reference_id)
        kind = item.get("kind")
        if kind not in REFERENCE_KINDS:
            findings.append(
                _finding("error", "unknown_reference_kind", f"Catalog reference '{reference_id}' has unsupported kind '{kind}'.")
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_REFERENCE_NAME_LENGTH:
            findings.append(
                _finding(
                    "error",
                    "invalid_reference_name",
                    f"Catalog reference '{reference_id}' name must contain 1 to {MAX_REFERENCE_NAME_LENGTH} characters.",
                )
            )
        for field, maximum, code in (
            ("identifier", MAX_REFERENCE_IDENTIFIER_LENGTH, "invalid_reference_identifier"),
            ("revision", MAX_REFERENCE_REVISION_LENGTH, "invalid_reference_revision"),
            ("clause", MAX_REFERENCE_CLAUSE_LENGTH, "invalid_reference_clause"),
            ("details", MAX_REFERENCE_DETAILS_LENGTH, "invalid_reference_details"),
        ):
            value = item.get(field)
            if value is not None and (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > maximum
            ):
                findings.append(
                    _finding(
                        "error",
                        code,
                        f"Catalog reference '{reference_id}' {field} must contain 1 to {maximum} characters when provided.",
                    )
                )
        knowledge_status = item.get("knowledgeStatus")
        if (
            knowledge_status is not None
            and knowledge_status not in REFERENCE_KNOWLEDGE_STATUSES
        ):
            findings.append(
                _finding(
                    "error",
                    "invalid_reference_knowledge_status",
                    f"Catalog reference '{reference_id}' has unsupported knowledgeStatus '{knowledge_status}'.",
                )
            )
        demo_data = item.get("demoData")
        if demo_data is not None and not isinstance(demo_data, bool):
            findings.append(
                _finding(
                    "error",
                    "invalid_reference_demo_data",
                    f"Catalog reference '{reference_id}' demoData must be a boolean.",
                )
            )
        for field, maximum, code in (
            ("sourcePlanId", MAX_REFERENCE_SOURCE_ID_LENGTH, "invalid_reference_source_plan_id"),
            ("sourceRevision", MAX_REFERENCE_REVISION_LENGTH, "invalid_reference_source_revision"),
            ("sourcePlanHash", MAX_REFERENCE_SOURCE_HASH_LENGTH, "invalid_reference_source_plan_hash"),
            ("sourceRequirementId", MAX_REFERENCE_SOURCE_ID_LENGTH, "invalid_reference_source_requirement_id"),
            ("sourceResourceId", MAX_REFERENCE_SOURCE_ID_LENGTH, "invalid_reference_source_resource_id"),
            ("populatedBy", MAX_REFERENCE_POPULATED_BY_LENGTH, "invalid_reference_populated_by"),
            ("populatedAt", MAX_REFERENCE_POPULATED_AT_LENGTH, "invalid_reference_populated_at"),
        ):
            value = item.get(field)
            if value is not None and (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > maximum
            ):
                findings.append(
                    _finding(
                        "error",
                        code,
                        f"Catalog reference '{reference_id}' {field} must contain 1 to {maximum} characters when provided.",
                    )
                )
        if kind == "standard" and _clean_id(item.get("identifier")) is None:
            findings.append(
                _finding(
                    "error",
                    "standard_identifier_required",
                    f"Standard reference '{reference_id}' requires an identifier.",
                )
            )
        identity = (
            str(kind or "").lower(),
            str(name or "").strip().lower(),
            str(item.get("identifier") or "").strip().lower(),
            str(item.get("revision") or "").strip().lower(),
            str(item.get("clause") or "").strip().lower(),
        )
        if identity in reference_identity_keys:
            findings.append(
                _finding(
                    "warning",
                    "duplicate_reference_definition",
                    f"Catalog reference '{reference_id}' duplicates another reference definition.",
                )
            )
        reference_identity_keys.add(identity)

    process_plan_imports = process_map.get("processPlanImports", [])
    if not isinstance(process_plan_imports, list):
        findings.append(
            _finding(
                "error",
                "process_plan_imports_not_array",
                "processPlanImports must be an array.",
            )
        )
        process_plan_imports = []
    if len(process_plan_imports) > MAX_PROCESS_PLAN_IMPORTS:
        findings.append(
            _finding(
                "error",
                "too_many_process_plan_imports",
                f"processPlanImports can contain at most {MAX_PROCESS_PLAN_IMPORTS} records.",
            )
        )
    seen_plan_imports: Set[Tuple[str, str, str]] = set()
    for index, item in enumerate(process_plan_imports):
        if not isinstance(item, dict):
            findings.append(
                _finding(
                    "error",
                    "process_plan_import_not_object",
                    f"Process-plan import at index {index} must be an object.",
                )
            )
            continue
        for field, maximum, code in (
            ("sourcePlanId", MAX_REFERENCE_SOURCE_ID_LENGTH, "invalid_process_plan_id"),
            ("sourceRevision", MAX_REFERENCE_REVISION_LENGTH, "invalid_process_plan_revision"),
            ("sourcePlanHash", MAX_REFERENCE_SOURCE_HASH_LENGTH, "invalid_process_plan_hash"),
            ("populatedBy", MAX_REFERENCE_POPULATED_BY_LENGTH, "invalid_process_plan_populated_by"),
            ("populatedAt", MAX_REFERENCE_POPULATED_AT_LENGTH, "invalid_process_plan_populated_at"),
            ("disclaimer", MAX_PROCESS_PLAN_DISCLAIMER_LENGTH, "invalid_process_plan_disclaimer"),
        ):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                findings.append(
                    _finding(
                        "error",
                        code,
                        f"Process-plan import at index {index} {field} must contain 1 to {maximum} characters.",
                    )
                )
        if not isinstance(item.get("demoData"), bool):
            findings.append(
                _finding(
                    "error",
                    "invalid_process_plan_demo_data",
                    f"Process-plan import at index {index} demoData must be a boolean.",
                )
            )
        identity = tuple(
            str(item.get(field) or "").strip().lower()
            for field in ("sourcePlanId", "sourceRevision", "sourcePlanHash")
        )
        if identity in seen_plan_imports:
            findings.append(
                _finding(
                    "error",
                    "duplicate_process_plan_import",
                    f"Process-plan import at index {index} duplicates an earlier import.",
                )
            )
        seen_plan_imports.add(identity)

    known_occurrences = set(known_occurrence_ids) if known_occurrence_ids is not None else None
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    placed_occurrences: Set[str] = set()
    used_reference_ids: Set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            findings.append(_finding("error", "node_not_object", f"Canvas node at index {index} must be an object."))
            continue
        node_id = _clean_id(node.get("nodeId"))
        if node_id is None:
            findings.append(_finding("error", "node_id_missing", f"Canvas node at index {index} has no valid nodeId."))
            continue
        if node_id in nodes_by_id:
            findings.append(_finding("error", "duplicate_node_id", f"Canvas node id '{node_id}' is duplicated.", node_id=node_id))
            continue
        nodes_by_id[node_id] = node
        if not _finite_position(node.get("position")):
            findings.append(_finding("error", "invalid_node_position", f"Canvas node '{node_id}' requires finite x and y coordinates.", node_id=node_id))
        node_kind = node.get("nodeKind")
        if node_kind not in CANVAS_NODE_KINDS:
            findings.append(_finding("error", "unknown_canvas_node_kind", f"Canvas node '{node_id}' has unsupported kind '{node_kind}'.", node_id=node_id))
            continue
        port_orientation = node.get("portOrientation")
        port_order = node.get("portOrder")
        if node_kind == "junction" and (port_orientation is not None or port_order is not None):
            findings.append(_finding("error", "junction_port_layout_not_allowed", f"Junction node '{node_id}' cannot define a card port layout.", node_id=node_id))
        elif port_orientation is not None and port_orientation not in PORT_ORIENTATIONS:
            findings.append(_finding("error", "unknown_port_orientation", f"Canvas node '{node_id}' has unsupported port orientation '{port_orientation}'.", node_id=node_id))
        if node_kind != "junction" and port_order is not None and port_order not in PORT_ORDERS:
            findings.append(_finding("error", "unknown_port_order", f"Canvas node '{node_id}' has unsupported port order '{port_order}'.", node_id=node_id))
        locked = node.get("locked")
        if locked is not None and not isinstance(locked, bool):
            findings.append(_finding("error", "invalid_node_locked", f"Canvas node '{node_id}' locked must be a boolean.", node_id=node_id))
        position_mode = node.get("positionMode")
        if position_mode is not None and position_mode not in POSITION_MODES:
            findings.append(
                _finding(
                    "error",
                    "invalid_node_position_mode",
                    f"Canvas node '{node_id}' has unsupported positionMode '{position_mode}'.",
                    node_id=node_id,
                )
            )
        effective_mode = node_position_mode(node)
        if locked is True and effective_mode != "locked":
            findings.append(
                _finding(
                    "error",
                    "node_position_lock_mismatch",
                    f"Canvas node '{node_id}' locked and positionMode values disagree.",
                    node_id=node_id,
                )
            )
        if effective_mode == "locked" and locked is False:
            findings.append(
                _finding(
                    "error",
                    "node_position_lock_mismatch",
                    f"Canvas node '{node_id}' positionMode is locked but locked is false.",
                    node_id=node_id,
                )
            )
        findings.extend(
            _validate_semantic_metadata(
                node.get("semantic"),
                target_label=f"Canvas node '{node_id}'",
                node_id=node_id,
            )
        )
        label_override = node.get("labelOverride")
        note = node.get("note")
        if node_kind == "junction" and (label_override is not None or note is not None):
            findings.append(_finding("error", "junction_card_metadata_not_allowed", f"Junction node '{node_id}' cannot define a card label or note.", node_id=node_id))
        elif label_override is not None:
            if node_kind != "product_occurrence":
                findings.append(_finding("error", "label_override_not_allowed", f"Canvas node '{node_id}' cannot define labelOverride.", node_id=node_id))
            elif not isinstance(label_override, str) or not label_override.strip() or len(label_override.strip()) > MAX_NODE_LABEL_LENGTH:
                findings.append(_finding("error", "invalid_node_label_override", f"Canvas node '{node_id}' labelOverride must contain 1 to {MAX_NODE_LABEL_LENGTH} characters.", node_id=node_id))
        if node_kind != "junction" and note is not None and (
            not isinstance(note, str)
            or not note.strip()
            or len(note.strip()) > MAX_NODE_NOTE_LENGTH
        ):
            findings.append(_finding("error", "invalid_node_note", f"Canvas node '{node_id}' note must contain 1 to {MAX_NODE_NOTE_LENGTH} characters.", node_id=node_id))
        node_reference_findings, node_references = _validate_reference_ids(
            node.get("referenceIds"),
            reference_ids,
            target_label=f"Canvas node '{node_id}'",
            node_id=node_id,
        )
        findings.extend(node_reference_findings)
        used_reference_ids.update(node_references)
        if node_kind == "junction" and node.get("referenceIds") is not None:
            findings.append(
                _finding(
                    "error",
                    "junction_references_not_allowed",
                    f"Junction node '{node_id}' cannot carry process references.",
                    node_id=node_id,
                )
            )
        if node_kind == "product_occurrence":
            occurrence_id = _clean_id(node.get("sourceOccurrenceId"))
            if occurrence_id is None:
                findings.append(_finding("error", "source_occurrence_missing", f"Canvas node '{node_id}' has no source occurrence.", node_id=node_id))
            elif occurrence_id in placed_occurrences:
                findings.append(_finding("error", "duplicate_occurrence_placement", f"Product occurrence '{occurrence_id}' is already placed on the canvas.", node_id=node_id, occurrence_id=occurrence_id))
            else:
                placed_occurrences.add(occurrence_id)
                if known_occurrences is not None and occurrence_id not in known_occurrences:
                    findings.append(_finding("error", "dangling_source_occurrence", f"Canvas node '{node_id}' references unknown occurrence '{occurrence_id}'.", node_id=node_id, occurrence_id=occurrence_id))
        elif node_kind == "process_step":
            if node.get("processType") not in PROCESS_STEP_TYPES:
                findings.append(_finding("error", "unknown_process_step_type", f"Process node '{node_id}' has unsupported type '{node.get('processType')}'.", node_id=node_id))
            name = node.get("name")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NODE_LABEL_LENGTH:
                findings.append(_finding("error", "invalid_process_step_name", f"Process node '{node_id}' name must contain 1 to {MAX_NODE_LABEL_LENGTH} characters.", node_id=node_id))
            properties = node.get("properties")
            if properties is not None:
                if not isinstance(properties, dict):
                    findings.append(_finding(
                        "error",
                        "invalid_process_step_properties",
                        f"Process node '{node_id}' properties must be an object.",
                        node_id=node_id,
                    ))
                else:
                    unknown_properties = sorted(set(properties) - set(PROCESS_STEP_PROPERTY_LIMITS))
                    if unknown_properties:
                        findings.append(_finding(
                            "error",
                            "unknown_process_step_property",
                            f"Process node '{node_id}' has unsupported properties: {', '.join(unknown_properties)}.",
                            node_id=node_id,
                        ))
                    for property_name, maximum in PROCESS_STEP_PROPERTY_LIMITS.items():
                        value = properties.get(property_name)
                        if value is not None and (
                            not isinstance(value, str)
                            or not value.strip()
                            or len(value.strip()) > maximum
                        ):
                            findings.append(_finding(
                                "error",
                                "invalid_process_step_property",
                                f"Process node '{node_id}' property '{property_name}' must contain 1 to {maximum} characters.",
                                node_id=node_id,
                            ))
                    semantic = node.get("semantic")
                    status = semantic.get("knowledgeStatus") if isinstance(semantic, dict) else None
                    if status in {"inferred", "unknown"} and any(
                        properties.get(name) for name in _AUTHORITATIVE_PROCESS_PROPERTIES
                    ):
                        findings.append(
                            _finding(
                                "error",
                                "unsupported_authoritative_manufacturing_value",
                                (
                                    f"Process node '{node_id}' cannot present manufacturing "
                                    "parameters as authoritative from inferred or unknown evidence."
                                ),
                                node_id=node_id,
                            )
                        )
        elif node_kind == "junction" and node.get("junctionType") not in JUNCTION_TYPES:
            findings.append(_finding("error", "unknown_junction_type", f"Junction node '{node_id}' has unsupported type '{node.get('junctionType')}'.", node_id=node_id))
        if node_kind != "process_step" and node.get("properties") is not None:
            findings.append(_finding(
                "error",
                "process_step_properties_not_allowed",
                f"Canvas node '{node_id}' cannot define process-step properties.",
                node_id=node_id,
            ))

    seen_group_ids: Set[str] = set()
    member_group_ids: Dict[str, str] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            findings.append(
                _finding(
                    "error",
                    "group_not_object",
                    f"Canvas group at index {index} must be an object.",
                )
            )
            continue
        group_id = _clean_id(group.get("groupId"))
        if group_id is None:
            findings.append(
                _finding(
                    "error",
                    "group_id_missing",
                    f"Canvas group at index {index} has no valid groupId.",
                )
            )
            continue
        if group_id in seen_group_ids:
            findings.append(
                _finding(
                    "error",
                    "duplicate_group_id",
                    f"Canvas group id '{group_id}' is duplicated.",
                    group_id=group_id,
                )
            )
            continue
        seen_group_ids.add(group_id)

        label = group.get("label")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label.strip()) > MAX_GROUP_LABEL_LENGTH
        ):
            findings.append(
                _finding(
                    "error",
                    "invalid_group_label",
                    f"Canvas group '{group_id}' label must contain 1 to {MAX_GROUP_LABEL_LENGTH} characters.",
                    group_id=group_id,
                )
            )
        description = group.get("description")
        if description is not None and (
            not isinstance(description, str)
            or len(description.strip()) > MAX_GROUP_DESCRIPTION_LENGTH
        ):
            findings.append(
                _finding(
                    "error",
                    "invalid_group_description",
                    f"Canvas group '{group_id}' description must contain at most {MAX_GROUP_DESCRIPTION_LENGTH} characters.",
                    group_id=group_id,
                )
            )
        if not _finite_position(group.get("position")):
            findings.append(
                _finding(
                    "error",
                    "invalid_group_position",
                    f"Canvas group '{group_id}' requires finite x and y coordinates.",
                    group_id=group_id,
                )
            )
        if not _finite_group_size(group.get("size")):
            findings.append(
                _finding(
                    "error",
                    "invalid_group_size",
                    f"Canvas group '{group_id}' requires width >= {MIN_GROUP_WIDTH} and height >= {MIN_GROUP_HEIGHT}.",
                    group_id=group_id,
                )
            )
        color_key = group.get("colorKey")
        if color_key not in GROUP_COLOR_KEYS:
            findings.append(
                _finding(
                    "error",
                    "unknown_group_color",
                    f"Canvas group '{group_id}' has unsupported color key '{color_key}'.",
                    group_id=group_id,
                )
            )
        collapsed = group.get("collapsed", False)
        if not isinstance(collapsed, bool) or collapsed:
            findings.append(
                _finding(
                    "error",
                    "group_collapse_not_supported",
                    f"Canvas group '{group_id}' must set collapsed to false in layout version {PROCESS_MAP_LAYOUT_VERSION}.",
                    group_id=group_id,
                )
            )

        member_node_ids = group.get("memberNodeIds")
        if not isinstance(member_node_ids, list):
            findings.append(
                _finding(
                    "error",
                    "group_members_not_array",
                    f"Canvas group '{group_id}' memberNodeIds must be an array.",
                    group_id=group_id,
                )
            )
            continue
        if not member_node_ids:
            findings.append(
                _finding(
                    "warning",
                    "empty_group",
                    f"Canvas group '{group_id}' has no members.",
                    group_id=group_id,
                )
            )
        seen_members: Set[str] = set()
        for raw_node_id in member_node_ids:
            member_node_id = _clean_id(raw_node_id)
            if member_node_id is None or member_node_id in seen_members:
                findings.append(
                    _finding(
                        "error",
                        "invalid_group_member",
                        f"Canvas group '{group_id}' contains an invalid or duplicate member id.",
                        group_id=group_id,
                    )
                )
                continue
            seen_members.add(member_node_id)
            if member_node_id not in nodes_by_id:
                findings.append(
                    _finding(
                        "error",
                        "dangling_group_member",
                        f"Canvas group '{group_id}' references missing node '{member_node_id}'.",
                        node_id=member_node_id,
                        group_id=group_id,
                    )
                )
                continue
            prior_group_id = member_group_ids.get(member_node_id)
            if prior_group_id is not None:
                findings.append(
                    _finding(
                        "error",
                        "node_in_multiple_groups",
                        f"Canvas node '{member_node_id}' belongs to both '{prior_group_id}' and '{group_id}'.",
                        node_id=member_node_id,
                        group_id=group_id,
                    )
                )
                continue
            member_group_ids[member_node_id] = group_id

    seen_edge_ids: Set[str] = set()
    seen_shapes: Set[Tuple[str, str, str]] = set()
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    logical_edge_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            findings.append(_finding("error", "edge_not_object", f"Canvas edge at index {index} must be an object."))
            continue
        edge_id = _clean_id(edge.get("edgeId"))
        if edge_id is None:
            findings.append(_finding("error", "edge_id_missing", f"Canvas edge at index {index} has no valid edgeId."))
        elif edge_id in seen_edge_ids:
            findings.append(_finding("error", "duplicate_edge_id", f"Canvas edge id '{edge_id}' is duplicated.", edge_id=edge_id))
        else:
            seen_edge_ids.add(edge_id)
        kind = edge.get("kind")
        if kind not in EDGE_KINDS:
            findings.append(_finding("error", "unknown_edge_kind", f"Canvas edge '{edge_id or index}' has unsupported kind '{kind}'.", edge_id=edge_id))
        logical_connection_id = edge.get("logicalConnectionId")
        if logical_connection_id is not None and _clean_id(logical_connection_id) is None:
            findings.append(_finding("error", "invalid_logical_connection_id", f"Canvas edge '{edge_id or index}' has an invalid logicalConnectionId.", edge_id=edge_id))
        logical_group_id = _clean_id(logical_connection_id) or edge_id or f"edge-index-{index}"
        logical_edge_groups[logical_group_id].append(edge)
        label = edge.get("label")
        if label is not None and (
            not isinstance(label, str)
            or not label.strip()
            or len(label.strip()) > MAX_NODE_LABEL_LENGTH
        ):
            findings.append(
                _finding(
                    "error",
                    "invalid_edge_label",
                    f"Canvas edge '{edge_id or index}' label must contain 1 to {MAX_NODE_LABEL_LENGTH} characters.",
                    edge_id=edge_id,
                )
            )
        routing = edge.get("routing")
        if routing is not None:
            if not isinstance(routing, dict):
                findings.append(
                    _finding(
                        "error",
                        "invalid_edge_routing",
                        f"Canvas edge '{edge_id or index}' routing must be an object.",
                        edge_id=edge_id,
                    )
                )
            else:
                route_mode = routing.get("mode")
                if route_mode not in EDGE_ROUTE_MODES:
                    findings.append(
                        _finding(
                            "error",
                            "unknown_edge_route_mode",
                            f"Canvas edge '{edge_id or index}' has unsupported route mode '{route_mode}'.",
                            edge_id=edge_id,
                        )
                    )
                elif route_mode != "bezier_legacy":
                    if (
                        not isinstance(layout_version, int)
                        or isinstance(layout_version, bool)
                        or layout_version < PROCESS_MAP_LAYOUT_VERSION
                    ):
                        findings.append(
                            _finding(
                                "error",
                                "routing_requires_layout_version_3",
                                f"Routed canvas edges require layoutVersion {PROCESS_MAP_LAYOUT_VERSION} or newer.",
                                edge_id=edge_id,
                            )
                        )
                    router_version = routing.get("routerVersion")
                    if (
                        not isinstance(router_version, int)
                        or isinstance(router_version, bool)
                        or router_version < 1
                    ):
                        findings.append(
                            _finding(
                                "error",
                                "invalid_edge_router_version",
                                f"Canvas edge '{edge_id or index}' requires a positive routerVersion.",
                                edge_id=edge_id,
                            )
                        )
                    waypoints = routing.get("waypoints")
                    if not isinstance(waypoints, list) or len(waypoints) > MAX_ROUTE_POINTS:
                        findings.append(
                            _finding(
                                "error",
                                "invalid_edge_route_waypoints",
                                f"Canvas edge '{edge_id or index}' route waypoints must be an array of at most {MAX_ROUTE_POINTS} points.",
                                edge_id=edge_id,
                            )
                        )
                    elif any(not _finite_position(waypoint) for waypoint in waypoints):
                        findings.append(
                            _finding(
                                "error",
                                "invalid_edge_route_waypoint",
                                f"Canvas edge '{edge_id or index}' route waypoints require finite x and y values.",
                                edge_id=edge_id,
                            )
                        )
                    if route_mode in {"orthogonal_auto", "orthogonal_manual"}:
                        obstacle_fingerprint = routing.get("obstacleFingerprint")
                        if (
                            not isinstance(obstacle_fingerprint, str)
                            or not obstacle_fingerprint.strip()
                            or len(obstacle_fingerprint.strip()) > 128
                        ):
                            findings.append(
                                _finding(
                                    "error",
                                    "invalid_edge_obstacle_fingerprint",
                                    f"Canvas edge '{edge_id or index}' requires an obstacleFingerprint.",
                                    edge_id=edge_id,
                                )
                            )
        edge_reference_findings, edge_references = _validate_reference_ids(
            edge.get("referenceIds"),
            reference_ids,
            target_label=f"Canvas edge '{edge_id or index}'",
            edge_id=edge_id,
        )
        findings.extend(edge_reference_findings)
        used_reference_ids.update(edge_references)
        findings.extend(
            _validate_semantic_metadata(
                edge.get("semantic"),
                target_label=f"Canvas edge '{edge_id or index}'",
                edge_id=edge_id,
            )
        )
        from_id, from_port = _edge_endpoint(edge, "from")
        to_id, to_port = _edge_endpoint(edge, "to")
        if from_id is None or to_id is None or from_port is None or to_port is None:
            findings.append(_finding("error", "invalid_edge_endpoint", f"Canvas edge '{edge_id or index}' requires nodeId and port on both endpoints.", edge_id=edge_id))
            continue
        if from_port != "out" or to_port != "in":
            findings.append(
                _finding(
                    "error",
                    "incompatible_edge_ports",
                    (
                        f"Canvas edge '{edge_id or index}' must connect an output port "
                        "to an input port."
                    ),
                    edge_id=edge_id,
                )
            )
            continue
        if from_id not in nodes_by_id or to_id not in nodes_by_id:
            findings.append(_finding("error", "dangling_edge_endpoint", f"Canvas edge '{edge_id or index}' references a missing canvas node.", edge_id=edge_id))
            continue
        if from_id == to_id:
            findings.append(_finding("error", "self_edge", f"Canvas edge '{edge_id or index}' cannot connect a node to itself.", edge_id=edge_id))
            continue
        shape = (from_id, to_id, str(kind))
        if shape in seen_shapes:
            findings.append(_finding("error", "duplicate_edge", f"Canvas edge '{edge_id or index}' duplicates an existing connection.", edge_id=edge_id))
            continue
        seen_shapes.add(shape)
        if kind == "precedence":
            adjacency[from_id].add(to_id)
            incoming[to_id] += 1
            outgoing[from_id] += 1

    for logical_id, grouped_edges in logical_edge_groups.items():
        if len(grouped_edges) < 2:
            continue
        reference_sets = {
            tuple(sorted(str(reference_id) for reference_id in edge.get("referenceIds", [])))
            for edge in grouped_edges
            if isinstance(edge.get("referenceIds", []), list)
        }
        if len(reference_sets) > 1:
            findings.append(
                _finding(
                    "error",
                    "logical_connection_reference_mismatch",
                    f"Logical connection '{logical_id}' must carry the same references on every physical segment.",
                )
            )
        labels = {
            edge["label"].strip()
            for edge in grouped_edges
            if isinstance(edge.get("label"), str) and edge["label"].strip()
        }
        if len(labels) > 1:
            findings.append(
                _finding(
                    "error",
                    "logical_connection_label_conflict",
                    f"Logical connection '{logical_id}' has conflicting labels across its physical segments.",
                )
            )

    for cycle in _precedence_cycles(adjacency):
        findings.append(_finding("error", "precedence_cycle", "Precedence cycle detected: " + " -> ".join(cycle) + "."))

    for node_id, node in nodes_by_id.items():
        if node.get("nodeKind") == "process_step":
            process_type = node.get("processType")
            if process_type == "input" and incoming[node_id]:
                findings.append(_finding("warning", "input_has_incoming_precedence", f"Input node '{node_id}' has an incoming precedence connection.", node_id=node_id))
            if process_type == "output" and outgoing[node_id]:
                findings.append(_finding("warning", "output_has_outgoing_precedence", f"Output node '{node_id}' has an outgoing precedence connection.", node_id=node_id))
            if process_type == "decision" and outgoing[node_id] < 2:
                findings.append(_finding("warning", "decision_has_fewer_than_two_outputs", f"Decision node '{node_id}' has fewer than two outgoing precedence connections.", node_id=node_id))
            continue
        if node.get("nodeKind") != "junction":
            continue
        junction_type = node.get("junctionType")
        if junction_type in {"parallel_and", "merge"}:
            if incoming[node_id] < 2:
                findings.append(_finding(
                    "warning",
                    "junction_has_fewer_than_two_inputs",
                    f"Junction '{node_id}' has fewer than two incoming precedence connections.",
                    node_id=node_id,
                ))
            if outgoing[node_id] > 1:
                findings.append(_finding(
                    "warning",
                    "junction_has_multiple_outputs",
                    f"Junction '{node_id}' has more than one outgoing precedence connection.",
                    node_id=node_id,
                ))
        elif junction_type == "split":
            if incoming[node_id] > 1:
                findings.append(_finding(
                    "warning",
                    "split_junction_has_multiple_inputs",
                    f"Split junction '{node_id}' has more than one incoming precedence connection.",
                    node_id=node_id,
                ))
            if outgoing[node_id] < 2:
                findings.append(_finding(
                    "warning",
                    "split_junction_has_fewer_than_two_outputs",
                    f"Split junction '{node_id}' has fewer than two outgoing precedence connections.",
                    node_id=node_id,
                ))
    for reference_id in sorted(reference_ids - used_reference_ids):
        findings.append(
            _finding(
                "info",
                "unused_process_reference",
                f"Catalog reference '{reference_id}' is not attached to a card or connection.",
            )
        )
    return findings
