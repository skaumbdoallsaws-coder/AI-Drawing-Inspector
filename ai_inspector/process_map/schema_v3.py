"""Placement-only process-map schema and product-structure helpers."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


PROCESS_MAP_PLACEMENT_SCHEMA_VERSION = 3
PRODUCT_STRUCTURE_SCHEMA_VERSION = 1
PRODUCT_KINDS = frozenset({"assembly", "subassembly", "part"})
CANVAS_NODE_KINDS = frozenset({"product_occurrence", "process_step", "junction"})
JUNCTION_TYPES = frozenset({"wire_branch"})
PORT_ORIENTATIONS = frozenset({"horizontal", "vertical"})
PORT_ORDERS = frozenset({"input_first", "output_first"})
PROCESS_STEP_TYPES = frozenset({"operation", "inspection", "decision", "input", "output"})
EDGE_KINDS = frozenset({"precedence", "rework", "feedback", "material"})
REFERENCE_KINDS = frozenset({"machine", "tool", "requirement", "standard"})
MAX_NODE_LABEL_LENGTH = 120
MAX_NODE_NOTE_LENGTH = 2000
MAX_REFERENCE_NAME_LENGTH = 160
MAX_REFERENCE_IDENTIFIER_LENGTH = 120
MAX_REFERENCE_REVISION_LENGTH = 80
MAX_REFERENCE_CLAUSE_LENGTH = 120
MAX_REFERENCE_DETAILS_LENGTH = 1000
MAX_REFERENCES_PER_TARGET = 24
MAX_REFERENCE_CATALOG_ITEMS = 500


Finding = Dict[str, Any]


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
    occurrence_id: Optional[str] = None,
) -> Finding:
    result: Finding = {"severity": severity, "code": code, "message": message}
    if node_id is not None:
        result["nodeId"] = node_id
    if edge_id is not None:
        result["edgeId"] = edge_id
    if occurrence_id is not None:
        result["occurrenceId"] = occurrence_id
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
        migrated.setdefault("layoutVersion", 1)
        migrated.setdefault("canvasNodes", [])
        migrated.setdefault("canvasEdges", [])
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
        "layoutVersion": 1,
        "canvasNodes": canvas_nodes,
        "canvasEdges": canvas_edges,
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
    if not isinstance(nodes, list):
        findings.append(_finding("error", "canvas_nodes_not_array", "canvasNodes must be an array."))
        nodes = []
    if not isinstance(edges, list):
        findings.append(_finding("error", "canvas_edges_not_array", "canvasEdges must be an array."))
        edges = []

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
        elif node_kind == "junction" and node.get("junctionType") not in JUNCTION_TYPES:
            findings.append(_finding("error", "unknown_junction_type", f"Junction node '{node_id}' has unsupported type '{node.get('junctionType')}'.", node_id=node_id))

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
        edge_reference_findings, edge_references = _validate_reference_ids(
            edge.get("referenceIds"),
            reference_ids,
            target_label=f"Canvas edge '{edge_id or index}'",
            edge_id=edge_id,
        )
        findings.extend(edge_reference_findings)
        used_reference_ids.update(edge_references)
        from_id, from_port = _edge_endpoint(edge, "from")
        to_id, to_port = _edge_endpoint(edge, "to")
        if from_id is None or to_id is None or from_port is None or to_port is None:
            findings.append(_finding("error", "invalid_edge_endpoint", f"Canvas edge '{edge_id or index}' requires nodeId and port on both endpoints.", edge_id=edge_id))
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
        if node.get("nodeKind") != "process_step":
            continue
        process_type = node.get("processType")
        if process_type == "input" and incoming[node_id]:
            findings.append(_finding("warning", "input_has_incoming_precedence", f"Input node '{node_id}' has an incoming precedence connection.", node_id=node_id))
        if process_type == "output" and outgoing[node_id]:
            findings.append(_finding("warning", "output_has_outgoing_precedence", f"Output node '{node_id}' has an outgoing precedence connection.", node_id=node_id))
        if process_type == "decision" and outgoing[node_id] < 2:
            findings.append(_finding("warning", "decision_has_fewer_than_two_outputs", f"Decision node '{node_id}' has fewer than two outgoing precedence connections.", node_id=node_id))
    for reference_id in sorted(reference_ids - used_reference_ids):
        findings.append(
            _finding(
                "info",
                "unused_process_reference",
                f"Catalog reference '{reference_id}' is not attached to a card or connection.",
            )
        )
    return findings
