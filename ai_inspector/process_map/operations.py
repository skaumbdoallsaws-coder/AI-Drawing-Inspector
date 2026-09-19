"""Deterministic, in-memory process-map domain operations.

Builder and other agents may request these operations, but this module never
writes files. Callers must validate the returned map and pass it through the
revision-aware repository save boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .repository import canonical_process_map_bytes, process_map_revision
from .schema_v3 import (
    EDGE_ROUTE_MODES,
    GROUP_COLOR_KEYS,
    JUNCTION_TYPES,
    LAYOUT_FLOW_DIRECTIONS,
    LAYOUT_POLICY_NUMERIC_FIELDS,
    LAYOUT_POLICY_ROUTE_MODES,
    MAX_GROUP_DESCRIPTION_LENGTH,
    MAX_GROUP_LABEL_LENGTH,
    MAX_NODE_LABEL_LENGTH,
    MAX_NODE_NOTE_LENGTH,
    MAX_ROUTE_POINTS,
    MAX_REFERENCE_CATALOG_ITEMS,
    MAX_REFERENCE_CLAUSE_LENGTH,
    MAX_REFERENCE_DETAILS_LENGTH,
    MAX_REFERENCE_IDENTIFIER_LENGTH,
    MAX_REFERENCE_NAME_LENGTH,
    MAX_REFERENCE_POPULATED_AT_LENGTH,
    MAX_REFERENCE_POPULATED_BY_LENGTH,
    MAX_REFERENCE_REVISION_LENGTH,
    MAX_REFERENCE_SOURCE_HASH_LENGTH,
    MAX_REFERENCE_SOURCE_ID_LENGTH,
    MAX_REFERENCES_PER_TARGET,
    MAX_PROCESS_PLAN_DISCLAIMER_LENGTH,
    MAX_PROCESS_PLAN_IMPORTS,
    MIN_GROUP_HEIGHT,
    MIN_GROUP_WIDTH,
    PORT_ORDERS,
    PORT_ORIENTATIONS,
    POSITION_MODES,
    PROCESS_STEP_TYPES,
    PROCESS_STEP_PROPERTY_LIMITS,
    REFERENCE_KNOWLEDGE_STATUSES,
    REFERENCE_KINDS,
    node_position_mode,
    validate_placement_map,
)


MAX_OPERATION_BATCH = 100
MAX_INTERNAL_OPERATION_BATCH = 500
MAX_DOMAIN_ID_LENGTH = 128
PROCESS_MAP_OPERATION_SCHEMA_VERSION = 1


class ProcessMapOperationError(ValueError):
    """One requested operation is malformed or cannot be applied."""

    def __init__(self, code: str, message: str, *, operation_index: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.operation_index = operation_index

    def finding(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "severity": "error",
            "code": self.code,
            "message": str(self),
        }
        if self.operation_index is not None:
            result["operationIndex"] = self.operation_index
        return result


def _fail(code: str, message: str) -> None:
    raise ProcessMapOperationError(code, message)


def _clean_text(value: Any, maximum: int, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        if required:
            _fail("invalid_operation_field", f"{field} must be a string.")
        return ""
    cleaned = value.strip()
    if required and not cleaned:
        _fail("invalid_operation_field", f"{field} is required.")
    if len(cleaned) > maximum:
        _fail("invalid_operation_field", f"{field} exceeds {maximum} characters.")
    return cleaned


def _clean_id(value: Any, field: str) -> str:
    return _clean_text(value, MAX_DOMAIN_ID_LENGTH, field)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _position(value: Any, field: str = "position") -> Dict[str, float]:
    if not isinstance(value, Mapping) or not _finite_number(value.get("x")) or not _finite_number(value.get("y")):
        _fail("invalid_operation_field", f"{field} requires finite x and y values.")
    return {"x": float(value["x"]), "y": float(value["y"])}


def _size(value: Any) -> Dict[str, float]:
    if (
        not isinstance(value, Mapping)
        or not _finite_number(value.get("width"))
        or not _finite_number(value.get("height"))
        or float(value["width"]) < MIN_GROUP_WIDTH
        or float(value["height"]) < MIN_GROUP_HEIGHT
    ):
        _fail(
            "invalid_operation_field",
            f"size requires width >= {MIN_GROUP_WIDTH} and height >= {MIN_GROUP_HEIGHT}.",
        )
    return {"width": float(value["width"]), "height": float(value["height"])}


def _nodes(process_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = process_map.setdefault("canvasNodes", [])
    if not isinstance(value, list):
        _fail("invalid_map_shape", "canvasNodes must be an array.")
    return value


def _edges(process_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = process_map.setdefault("canvasEdges", [])
    if not isinstance(value, list):
        _fail("invalid_map_shape", "canvasEdges must be an array.")
    return value


def _groups(process_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = process_map.setdefault("canvasGroups", [])
    if not isinstance(value, list):
        _fail("invalid_map_shape", "canvasGroups must be an array.")
    return value


def _catalog(process_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = process_map.get("referenceCatalog")
    if value is None:
        value = []
        process_map["referenceCatalog"] = value
    if not isinstance(value, list):
        _fail("invalid_map_shape", "referenceCatalog must be an array.")
    return value


def _find(records: Iterable[Dict[str, Any]], key: str, value: str, label: str) -> Dict[str, Any]:
    match = next((record for record in records if isinstance(record, dict) and record.get(key) == value), None)
    if match is None:
        _fail("operation_target_not_found", f"{label} '{value}' was not found.")
    return match


def _all_ids(process_map: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for collection, key in (
        (_nodes(process_map), "nodeId"),
        (_edges(process_map), "edgeId"),
        (_groups(process_map), "groupId"),
        (_catalog(process_map), "referenceId"),
    ):
        ids.update(
            str(record.get(key))
            for record in collection
            if isinstance(record, dict) and record.get(key)
        )
    ids.update(
        str(edge.get("logicalConnectionId"))
        for edge in _edges(process_map)
        if isinstance(edge, dict) and edge.get("logicalConnectionId")
    )
    return ids


def _generated_id(
    process_map: Dict[str, Any],
    prefix: str,
    operation: Mapping[str, Any],
    operation_index: int,
) -> str:
    seed = json.dumps(
        {
            "mapRevision": process_map_revision(process_map),
            "operationIndex": operation_index,
            "operation": operation,
            "prefix": prefix,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(seed).hexdigest()
    used = _all_ids(process_map)
    for width in (12, 16, 20, 24, 32):
        candidate = f"{prefix}-{digest[:width]}"
        if candidate not in used:
            return candidate
    _fail("id_allocation_failed", f"Could not allocate a unique {prefix} identifier.")
    raise AssertionError("unreachable")


def _requested_or_generated_id(
    process_map: Dict[str, Any],
    operation: Mapping[str, Any],
    operation_index: int,
    field: str,
    prefix: str,
) -> str:
    value = operation.get(field)
    identifier = _clean_id(value, field) if value is not None else _generated_id(
        process_map, prefix, operation, operation_index
    )
    if identifier in _all_ids(process_map):
        _fail("duplicate_operation_id", f"{field} '{identifier}' is already in use.")
    return identifier


def _occurrence_index(product_structure: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    occurrences = product_structure.get("occurrences")
    if not isinstance(occurrences, list):
        _fail("invalid_product_structure", "Product structure has no occurrence catalog.")
    return {
        str(item["occurrenceId"]): item
        for item in occurrences
        if isinstance(item, dict) and isinstance(item.get("occurrenceId"), str)
    }


def _logical_edge_records(process_map: Dict[str, Any], edge: Dict[str, Any]) -> List[Dict[str, Any]]:
    logical_id = edge.get("logicalConnectionId") or edge.get("edgeId")
    return [
        item
        for item in _edges(process_map)
        if isinstance(item, dict)
        and (item.get("logicalConnectionId") or item.get("edgeId")) == logical_id
    ]


def _prune_references(process_map: Dict[str, Any]) -> None:
    used = {
        reference_id
        for record in [*_nodes(process_map), *_edges(process_map)]
        if isinstance(record, dict)
        for reference_id in (
            record.get("referenceIds") if isinstance(record.get("referenceIds"), list) else []
        )
        if isinstance(reference_id, str)
    }
    catalog = [
        item for item in _catalog(process_map)
        if isinstance(item, dict) and item.get("referenceId") in used
    ]
    if catalog:
        process_map["referenceCatalog"] = catalog
    else:
        process_map.pop("referenceCatalog", None)


def _remove_membership(process_map: Dict[str, Any], node_ids: Set[str]) -> None:
    for group in _groups(process_map):
        if not isinstance(group, dict):
            continue
        members = group.get("memberNodeIds") if isinstance(group.get("memberNodeIds"), list) else []
        group["memberNodeIds"] = [member for member in members if member not in node_ids]


def _junction_has_metadata(node: Dict[str, Any]) -> bool:
    return any(node.get(key) not in (None, "", [], {}) for key in ("label", "name", "description", "metadata"))


def _collapse_redundant_junctions(process_map: Dict[str, Any]) -> None:
    while True:
        nodes = _nodes(process_map)
        edges = _edges(process_map)
        collapsed = False
        for node in list(nodes):
            if (
                not isinstance(node, dict)
                or node.get("nodeKind") != "junction"
                or node.get("junctionType") != "wire_branch"
                or _junction_has_metadata(node)
            ):
                continue
            node_id = node.get("nodeId")
            incident = [
                edge for edge in edges
                if isinstance(edge, dict)
                and isinstance(edge.get("from"), dict)
                and isinstance(edge.get("to"), dict)
                and (edge["from"].get("nodeId") == node_id or edge["to"].get("nodeId") == node_id)
            ]
            incoming = [edge for edge in incident if edge["to"].get("nodeId") == node_id]
            outgoing = [edge for edge in incident if edge["from"].get("nodeId") == node_id]
            if len(incoming) != 1 or len(outgoing) != 1 or len(incident) != 2:
                continue
            left, right = incoming[0], outgoing[0]
            logical_id = left.get("logicalConnectionId")
            if (
                not logical_id
                or logical_id != right.get("logicalConnectionId")
                or left.get("kind", "precedence") != right.get("kind", "precedence")
                or left["from"].get("nodeId") == right["to"].get("nodeId")
            ):
                continue
            merged = deepcopy(left)
            remaining_ids = {edge.get("edgeId") for edge in edges if edge not in incident}
            preferred = str(logical_id)
            edge_id = preferred
            suffix = 2
            while edge_id in remaining_ids:
                edge_id = f"{preferred}-{suffix}"
                suffix += 1
            merged["edgeId"] = edge_id
            merged["to"] = deepcopy(right["to"])
            if "label" not in merged and "label" in right:
                merged["label"] = right["label"]
            process_map["canvasEdges"] = [edge for edge in edges if edge not in incident] + [merged]
            process_map["canvasNodes"] = [item for item in nodes if item is not node]
            _remove_membership(process_map, {str(node_id)})
            collapsed = True
            break
        if not collapsed:
            return


def _reference_identity(reference: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(
        str(reference.get(key) or "").strip().lower()
        for key in ("kind", "name", "identifier", "revision", "clause")
    )


def _normalized_reference(
    process_map: Dict[str, Any],
    operation: Mapping[str, Any],
    operation_index: int,
) -> Dict[str, Any]:
    value = operation.get("reference")
    if not isinstance(value, Mapping):
        _fail("invalid_operation_field", "reference must be an object.")
    kind = _clean_text(value.get("kind"), 40, "reference.kind")
    if kind not in REFERENCE_KINDS:
        _fail("invalid_operation_field", f"Unsupported reference kind '{kind}'.")
    result: Dict[str, Any] = {
        "kind": kind,
        "name": _clean_text(value.get("name"), MAX_REFERENCE_NAME_LENGTH, "reference.name"),
    }
    for key, maximum in (
        ("identifier", MAX_REFERENCE_IDENTIFIER_LENGTH),
        ("revision", MAX_REFERENCE_REVISION_LENGTH),
        ("clause", MAX_REFERENCE_CLAUSE_LENGTH),
        ("details", MAX_REFERENCE_DETAILS_LENGTH),
    ):
        cleaned = _clean_text(value.get(key), maximum, f"reference.{key}", required=False)
        if cleaned:
            result[key] = cleaned
    knowledge_status = value.get("knowledgeStatus")
    if knowledge_status is not None:
        knowledge_status = _clean_text(
            knowledge_status, 40, "reference.knowledgeStatus"
        )
        if knowledge_status not in REFERENCE_KNOWLEDGE_STATUSES:
            _fail(
                "invalid_operation_field",
                f"Unsupported reference knowledgeStatus '{knowledge_status}'.",
            )
        result["knowledgeStatus"] = knowledge_status
    demo_data = value.get("demoData")
    if demo_data is not None:
        if not isinstance(demo_data, bool):
            _fail("invalid_operation_field", "reference.demoData must be a boolean.")
        result["demoData"] = demo_data
    for key, maximum in (
        ("sourcePlanId", MAX_REFERENCE_SOURCE_ID_LENGTH),
        ("sourceRevision", MAX_REFERENCE_REVISION_LENGTH),
        ("sourcePlanHash", MAX_REFERENCE_SOURCE_HASH_LENGTH),
        ("sourceRequirementId", MAX_REFERENCE_SOURCE_ID_LENGTH),
        ("sourceResourceId", MAX_REFERENCE_SOURCE_ID_LENGTH),
        ("populatedBy", MAX_REFERENCE_POPULATED_BY_LENGTH),
        ("populatedAt", MAX_REFERENCE_POPULATED_AT_LENGTH),
    ):
        cleaned = _clean_text(
            value.get(key), maximum, f"reference.{key}", required=False
        )
        if cleaned:
            result[key] = cleaned
    if kind == "standard" and not result.get("identifier"):
        _fail("invalid_operation_field", "A standard reference requires an identifier.")
    requested = value.get("referenceId")
    result["referenceId"] = (
        _clean_id(requested, "reference.referenceId")
        if requested is not None
        else _generated_id(process_map, "pmr", operation, operation_index)
    )
    return result


def _target_records(process_map: Dict[str, Any], target_type: str, target_id: str) -> List[Dict[str, Any]]:
    if target_type == "node":
        node = _find(_nodes(process_map), "nodeId", target_id, "Node")
        if node.get("nodeKind") == "junction":
            _fail("junction_references_not_allowed", "Junction nodes cannot carry references.")
        return [node]
    if target_type == "edge":
        edge = _find(_edges(process_map), "edgeId", target_id, "Edge")
        return _logical_edge_records(process_map, edge)
    _fail("invalid_operation_field", "targetType must be 'node' or 'edge'.")
    raise AssertionError("unreachable")


def _op_place_occurrence(
    process_map: Dict[str, Any],
    structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    occurrence_id = _clean_id(operation.get("occurrenceId"), "occurrenceId")
    occurrence = _occurrence_index(structure).get(occurrence_id)
    if occurrence is None:
        _fail("operation_target_not_found", f"Occurrence '{occurrence_id}' was not found.")
    if any(node.get("sourceOccurrenceId") == occurrence_id for node in _nodes(process_map) if isinstance(node, dict)):
        _fail("duplicate_occurrence_placement", f"Occurrence '{occurrence_id}' is already placed.")
    node_id = _requested_or_generated_id(process_map, operation, index, "nodeId", "pmn")
    node: Dict[str, Any] = {
        "nodeId": node_id,
        "nodeKind": "product_occurrence",
        "sourceOccurrenceId": occurrence_id,
        "position": _position(operation.get("position")),
        "positionMode": operation.get("positionMode", "manual"),
        "portOrientation": operation.get("portOrientation", "horizontal"),
        "portOrder": operation.get("portOrder", "input_first"),
    }
    if operation.get("label") is not None:
        node["labelOverride"] = _clean_text(operation.get("label"), MAX_NODE_LABEL_LENGTH, "label")
    if operation.get("note") is not None:
        node["note"] = _clean_text(operation.get("note"), MAX_NODE_NOTE_LENGTH, "note")
    if node["positionMode"] not in POSITION_MODES:
        _fail("invalid_operation_field", "positionMode must be auto, manual, or locked.")
    if node["positionMode"] == "locked":
        node["locked"] = True
    if operation.get("semantic") is not None:
        node["semantic"] = deepcopy(operation["semantic"])
    _nodes(process_map).append(node)
    return {"nodeId": node_id, "occurrenceId": occurrence_id}


def _process_step_properties(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("invalid_operation_field", "properties must be an object.")
    unknown = sorted(set(value) - set(PROCESS_STEP_PROPERTY_LIMITS))
    if unknown:
        _fail(
            "invalid_operation_field",
            "Unsupported process-step properties: " + ", ".join(unknown) + ".",
        )
    result: Dict[str, str] = {}
    for field, maximum in PROCESS_STEP_PROPERTY_LIMITS.items():
        cleaned = _clean_text(value.get(field), maximum, field, required=False)
        if cleaned:
            result[field] = cleaned
    return result


def _op_add_process_step(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    process_type = _clean_text(operation.get("processType"), 32, "processType")
    if process_type not in PROCESS_STEP_TYPES:
        _fail("invalid_operation_field", f"Unsupported process step type '{process_type}'.")
    node_id = _requested_or_generated_id(process_map, operation, index, "nodeId", "pmn")
    node: Dict[str, Any] = {
        "nodeId": node_id,
        "nodeKind": "process_step",
        "processType": process_type,
        "name": _clean_text(operation.get("name"), MAX_NODE_LABEL_LENGTH, "name"),
        "position": _position(operation.get("position")),
        "positionMode": operation.get("positionMode", "manual"),
        "portOrientation": operation.get("portOrientation", "horizontal"),
        "portOrder": operation.get("portOrder", "input_first"),
    }
    note = _clean_text(operation.get("note"), MAX_NODE_NOTE_LENGTH, "note", required=False)
    if note:
        node["note"] = note
    if operation.get("properties") is not None:
        properties = _process_step_properties(operation.get("properties"))
        if properties:
            node["properties"] = properties
    if node["positionMode"] not in POSITION_MODES:
        _fail("invalid_operation_field", "positionMode must be auto, manual, or locked.")
    if node["positionMode"] == "locked":
        node["locked"] = True
    if operation.get("semantic") is not None:
        node["semantic"] = deepcopy(operation["semantic"])
    _nodes(process_map).append(node)
    return {"nodeId": node_id}


def _op_add_junction(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    node_id = _requested_or_generated_id(process_map, operation, index, "nodeId", "pmj")
    junction_type = _clean_text(
        operation.get("junctionType", "wire_branch"),
        32,
        "junctionType",
    )
    if junction_type not in JUNCTION_TYPES:
        _fail("invalid_operation_field", f"Unsupported junction type '{junction_type}'.")
    position_mode = operation.get("positionMode", "manual")
    if position_mode not in POSITION_MODES:
        _fail("invalid_operation_field", "positionMode must be auto, manual, or locked.")
    node = {
        "nodeId": node_id,
        "nodeKind": "junction",
        "junctionType": junction_type,
        "position": _position(operation.get("position")),
        "positionMode": position_mode,
    }
    if position_mode == "locked":
        node["locked"] = True
    if operation.get("semantic") is not None:
        node["semantic"] = deepcopy(operation["semantic"])
    _nodes(process_map).append(node)
    return {"nodeId": node_id}


def _op_move_node(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node_position_mode(node) == "locked":
        _fail("locked_node_movement", f"Node '{node_id}' is position-locked.")
    node["position"] = _position(operation.get("position"))
    requested_mode = operation.get("positionMode")
    if requested_mode is not None:
        if requested_mode not in POSITION_MODES:
            _fail("invalid_operation_field", "positionMode must be auto, manual, or locked.")
        node["positionMode"] = requested_mode
        if requested_mode == "locked":
            node["locked"] = True
        else:
            node.pop("locked", None)
    return {"nodeId": node_id}


def _op_set_node_locked(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    locked = operation.get("locked")
    if not isinstance(locked, bool):
        _fail("invalid_operation_field", "locked must be a boolean.")
    if locked:
        node["locked"] = True
        node["positionMode"] = "locked"
    else:
        node.pop("locked", None)
        node["positionMode"] = "manual"
    return {"nodeId": node_id, "locked": locked}


def _op_set_node_position_mode(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    mode = _clean_text(operation.get("positionMode"), 16, "positionMode")
    if mode not in POSITION_MODES:
        _fail("invalid_operation_field", "positionMode must be auto, manual, or locked.")
    node["positionMode"] = mode
    if mode == "locked":
        node["locked"] = True
    else:
        node.pop("locked", None)
    return {"nodeId": node_id, "positionMode": mode}


def _op_set_layout_policy(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    requested = operation.get("policy")
    if not isinstance(requested, Mapping) or not requested:
        _fail("invalid_operation_field", "set_layout_policy requires a non-empty policy object.")
    allowed = {
        "flowDirection",
        "gridSize",
        "nodeClearance",
        "edgeClearance",
        "portLeadLength",
        "routeMode",
    }
    unknown = sorted(set(requested) - allowed)
    if unknown:
        _fail(
            "invalid_operation_field",
            "Unsupported layout policy fields: " + ", ".join(unknown) + ".",
        )
    policy = deepcopy(
        process_map.get("layoutPolicy")
        if isinstance(process_map.get("layoutPolicy"), Mapping)
        else {}
    )
    if "flowDirection" in requested:
        value = _clean_text(requested.get("flowDirection"), 40, "policy.flowDirection")
        if value not in LAYOUT_FLOW_DIRECTIONS:
            _fail("invalid_operation_field", f"Unsupported flow direction '{value}'.")
        policy["flowDirection"] = value
    if "routeMode" in requested:
        value = _clean_text(requested.get("routeMode"), 40, "policy.routeMode")
        if value not in LAYOUT_POLICY_ROUTE_MODES:
            _fail("invalid_operation_field", f"Unsupported route mode '{value}'.")
        policy["routeMode"] = value
    for field, (minimum, maximum) in LAYOUT_POLICY_NUMERIC_FIELDS.items():
        if field not in requested:
            continue
        value = requested.get(field)
        if (
            not _finite_number(value)
            or float(value) < minimum
            or float(value) > maximum
        ):
            _fail(
                "invalid_operation_field",
                f"policy.{field} must be between {minimum:g} and {maximum:g}.",
            )
        policy[field] = float(value)
    process_map["layoutPolicy"] = policy
    return {"policyFields": sorted(requested)}


def _normalized_edge_routing(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_operation_field", "routing must be an object.")
    allowed = {"mode", "routerVersion", "waypoints", "obstacleFingerprint"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(
            "invalid_operation_field",
            "Unsupported routing fields: " + ", ".join(unknown) + ".",
        )
    mode = _clean_text(value.get("mode"), 40, "routing.mode")
    if mode not in EDGE_ROUTE_MODES:
        _fail("invalid_operation_field", f"Unsupported route mode '{mode}'.")
    if mode == "bezier_legacy":
        return {"mode": mode}
    router_version = value.get("routerVersion")
    if (
        not isinstance(router_version, int)
        or isinstance(router_version, bool)
        or router_version < 1
    ):
        _fail("invalid_operation_field", "routing.routerVersion must be a positive integer.")
    waypoints = value.get("waypoints")
    if not isinstance(waypoints, list) or len(waypoints) > MAX_ROUTE_POINTS:
        _fail(
            "invalid_operation_field",
            f"routing.waypoints must contain at most {MAX_ROUTE_POINTS} points.",
        )
    normalized_waypoints = [
        _position(point, f"routing.waypoints[{index}]")
        for index, point in enumerate(waypoints)
    ]
    if mode == "polyline_manual":
        return {
            "mode": mode,
            "routerVersion": router_version,
            "waypoints": normalized_waypoints,
        }
    fingerprint = _clean_text(
        value.get("obstacleFingerprint"),
        128,
        "routing.obstacleFingerprint",
    )
    return {
        "mode": mode,
        "routerVersion": router_version,
        "waypoints": normalized_waypoints,
        "obstacleFingerprint": fingerprint,
    }


def _op_set_edge_routing(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    edge_id = _clean_id(operation.get("edgeId"), "edgeId")
    edge = _find(_edges(process_map), "edgeId", edge_id, "Edge")
    edge["routing"] = _normalized_edge_routing(operation.get("routing"))
    if edge["routing"].get("mode") != "bezier_legacy":
        process_map["layoutVersion"] = max(
            3,
            int(process_map.get("layoutVersion") or 1),
        )
    return {"edgeId": edge_id, "routeMode": edge["routing"]["mode"]}


def _op_clear_edge_routing(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    edge_id = _clean_id(operation.get("edgeId"), "edgeId")
    edge = _find(_edges(process_map), "edgeId", edge_id, "Edge")
    edge.pop("routing", None)
    return {"edgeId": edge_id}


def _op_retype_step(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node.get("nodeKind") != "process_step":
        _fail("operation_target_kind_mismatch", "Only process steps can be retyped.")
    process_type = _clean_text(operation.get("processType"), 32, "processType")
    if process_type not in PROCESS_STEP_TYPES:
        _fail("invalid_operation_field", f"Unsupported process step type '{process_type}'.")
    node["processType"] = process_type
    return {"nodeId": node_id, "processType": process_type}


def _op_set_port_layout(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node.get("nodeKind") == "junction":
        _fail("operation_target_kind_mismatch", "Junctions do not have card port layouts.")
    if "orientation" in operation:
        orientation = _clean_text(operation.get("orientation"), 32, "orientation")
        if orientation not in PORT_ORIENTATIONS:
            _fail("invalid_operation_field", f"Unsupported port orientation '{orientation}'.")
        node["portOrientation"] = orientation
    if "order" in operation:
        order = _clean_text(operation.get("order"), 32, "order")
        if order not in PORT_ORDERS:
            _fail("invalid_operation_field", f"Unsupported port order '{order}'.")
        node["portOrder"] = order
    if "orientation" not in operation and "order" not in operation:
        _fail("invalid_operation_field", "set_port_layout requires orientation or order.")
    return {"nodeId": node_id}


def _op_set_label(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node.get("nodeKind") == "junction":
        _fail("operation_target_kind_mismatch", "Junctions cannot have card labels.")
    label = _clean_text(operation.get("label"), MAX_NODE_LABEL_LENGTH, "label", required=False)
    if node.get("nodeKind") == "product_occurrence":
        if label:
            node["labelOverride"] = label
        else:
            node.pop("labelOverride", None)
    else:
        if not label:
            _fail("invalid_operation_field", "A process-step name cannot be empty.")
        node["name"] = label
    return {"nodeId": node_id}


def _op_set_edge_label(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    edge_id = _clean_id(operation.get("edgeId"), "edgeId")
    edge = _find(_edges(process_map), "edgeId", edge_id, "Edge")
    label = _clean_text(
        operation.get("label"), MAX_NODE_LABEL_LENGTH, "label", required=False
    )
    records = _logical_edge_records(process_map, edge)
    for record in records:
        if label:
            record["label"] = label
        else:
            record.pop("label", None)
    return {
        "edgeId": edge_id,
        "logicalConnectionId": edge.get("logicalConnectionId") or edge_id,
    }


def _op_set_note(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node.get("nodeKind") == "junction":
        _fail("operation_target_kind_mismatch", "Junctions cannot have notes.")
    note = _clean_text(operation.get("note"), MAX_NODE_NOTE_LENGTH, "note", required=False)
    if note:
        node["note"] = note
    else:
        node.pop("note", None)
    return {"nodeId": node_id}


def _op_set_process_properties(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    node = _find(_nodes(process_map), "nodeId", node_id, "Node")
    if node.get("nodeKind") != "process_step":
        _fail("operation_target_kind_mismatch", "Only process steps have manufacturing properties.")
    properties = _process_step_properties(operation.get("properties"))
    if properties:
        node["properties"] = properties
    else:
        node.pop("properties", None)
    return {"nodeId": node_id, "properties": properties}


def _op_connect(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    from_id = _clean_id(operation.get("fromNodeId"), "fromNodeId")
    to_id = _clean_id(operation.get("toNodeId"), "toNodeId")
    _find(_nodes(process_map), "nodeId", from_id, "Source node")
    _find(_nodes(process_map), "nodeId", to_id, "Target node")
    if from_id == to_id:
        _fail("invalid_operation_field", "A connection cannot target its source node.")
    edge_id = _requested_or_generated_id(process_map, operation, index, "edgeId", "pme")
    logical_id = operation.get("logicalConnectionId")
    logical_id = _clean_id(logical_id, "logicalConnectionId") if logical_id is not None else edge_id
    kind = _clean_text(operation.get("kind", "precedence"), 32, "kind")
    edge: Dict[str, Any] = {
        "edgeId": edge_id,
        "from": {"nodeId": from_id, "port": _clean_text(operation.get("fromPort", "out"), 32, "fromPort")},
        "to": {"nodeId": to_id, "port": _clean_text(operation.get("toPort", "in"), 32, "toPort")},
        "kind": kind,
        "logicalConnectionId": logical_id,
    }
    label = _clean_text(operation.get("label"), MAX_NODE_LABEL_LENGTH, "label", required=False)
    if label:
        edge["label"] = label
    if operation.get("semantic") is not None:
        edge["semantic"] = deepcopy(operation["semantic"])
    _edges(process_map).append(edge)
    return {"edgeId": edge_id, "logicalConnectionId": logical_id}


def _op_split_edge_with_junction(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    target_edge_id = _clean_id(operation.get("targetEdgeId"), "targetEdgeId")
    source_node_id = _clean_id(operation.get("sourceNodeId"), "sourceNodeId")
    edge = _find(_edges(process_map), "edgeId", target_edge_id, "Edge")
    _find(_nodes(process_map), "nodeId", source_node_id, "Branch source node")
    if source_node_id in {edge.get("from", {}).get("nodeId"), edge.get("to", {}).get("nodeId")}:
        _fail("invalid_operation_field", "The branch source must not be an endpoint of the split edge.")
    junction_id = _requested_or_generated_id(process_map, operation, index, "junctionNodeId", "pmj")
    first_id = _requested_or_generated_id(process_map, operation, index, "firstEdgeId", "pme")
    working = deepcopy(operation)
    working["firstEdgeId"] = first_id
    second_id = _requested_or_generated_id(process_map, working, index, "secondEdgeId", "pme")
    working["secondEdgeId"] = second_id
    branch_id = _requested_or_generated_id(process_map, working, index, "branchEdgeId", "pme")
    if len({junction_id, first_id, second_id, branch_id}) != 4:
        _fail("duplicate_operation_id", "Split-edge identifiers must be unique.")
    logical_id = str(edge.get("logicalConnectionId") or edge.get("edgeId"))
    first = deepcopy(edge)
    first["edgeId"] = first_id
    first["to"] = {"nodeId": junction_id, "port": "in"}
    first["logicalConnectionId"] = logical_id
    second = deepcopy(edge)
    second["edgeId"] = second_id
    second["from"] = {"nodeId": junction_id, "port": "out"}
    second["logicalConnectionId"] = logical_id
    second.pop("label", None)
    branch_logical_id = operation.get("branchLogicalConnectionId")
    branch_logical_id = (
        _clean_id(branch_logical_id, "branchLogicalConnectionId")
        if branch_logical_id is not None else branch_id
    )
    direction = operation.get("branchDirection", "to_junction")
    if direction not in {"to_junction", "from_junction"}:
        _fail("invalid_operation_field", "branchDirection must be to_junction or from_junction.")
    branch_from = source_node_id if direction == "to_junction" else junction_id
    branch_to = junction_id if direction == "to_junction" else source_node_id
    branch = {
        "edgeId": branch_id,
        "from": {"nodeId": branch_from, "port": "out"},
        "to": {"nodeId": branch_to, "port": "in"},
        "kind": _clean_text(operation.get("kind", "precedence"), 32, "kind"),
        "logicalConnectionId": branch_logical_id,
    }
    process_map["canvasEdges"] = [item for item in _edges(process_map) if item is not edge] + [first, second, branch]
    _nodes(process_map).append({
        "nodeId": junction_id,
        "nodeKind": "junction",
        "junctionType": "wire_branch",
        "position": _position(operation.get("position")),
    })
    return {
        "junctionNodeId": junction_id,
        "edgeIds": [first_id, second_id, branch_id],
    }


def _op_delete_node(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    node_id = _clean_id(operation.get("nodeId"), "nodeId")
    _find(_nodes(process_map), "nodeId", node_id, "Node")
    process_map["canvasNodes"] = [node for node in _nodes(process_map) if node.get("nodeId") != node_id]
    process_map["canvasEdges"] = [
        edge for edge in _edges(process_map)
        if edge.get("from", {}).get("nodeId") != node_id and edge.get("to", {}).get("nodeId") != node_id
    ]
    _remove_membership(process_map, {node_id})
    _collapse_redundant_junctions(process_map)
    _prune_references(process_map)
    return {"nodeId": node_id}


def _op_delete_edge(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    edge_id = _clean_id(operation.get("edgeId"), "edgeId")
    _find(_edges(process_map), "edgeId", edge_id, "Edge")
    process_map["canvasEdges"] = [edge for edge in _edges(process_map) if edge.get("edgeId") != edge_id]
    _collapse_redundant_junctions(process_map)
    _prune_references(process_map)
    return {"edgeId": edge_id}


def _op_add_group(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    group_id = _requested_or_generated_id(process_map, operation, index, "groupId", "pmg")
    color_key = _clean_text(operation.get("colorKey", "orange"), 32, "colorKey")
    if color_key not in GROUP_COLOR_KEYS:
        _fail("invalid_operation_field", f"Unsupported group color '{color_key}'.")
    member_ids = operation.get("memberNodeIds", [])
    if not isinstance(member_ids, list):
        _fail("invalid_operation_field", "memberNodeIds must be an array.")
    known = {node.get("nodeId") for node in _nodes(process_map)}
    cleaned_members: List[str] = []
    for member in member_ids:
        member_id = _clean_id(member, "memberNodeIds")
        if member_id not in known:
            _fail("operation_target_not_found", f"Node '{member_id}' was not found.")
        if member_id not in cleaned_members:
            cleaned_members.append(member_id)
    for group in _groups(process_map):
        if isinstance(group, dict):
            group["memberNodeIds"] = [
                member for member in group.get("memberNodeIds", []) if member not in cleaned_members
            ]
    group: Dict[str, Any] = {
        "groupId": group_id,
        "label": _clean_text(operation.get("label"), MAX_GROUP_LABEL_LENGTH, "label"),
        "position": _position(operation.get("position")),
        "size": _size(operation.get("size")),
        "colorKey": color_key,
        "memberNodeIds": cleaned_members,
        "collapsed": False,
    }
    description = _clean_text(
        operation.get("description"), MAX_GROUP_DESCRIPTION_LENGTH, "description", required=False
    )
    if description:
        group["description"] = description
    _groups(process_map).append(group)
    return {"groupId": group_id}


def _op_set_group_members(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    group_id = _clean_id(operation.get("groupId"), "groupId")
    target = _find(_groups(process_map), "groupId", group_id, "Group")
    members = operation.get("memberNodeIds")
    if not isinstance(members, list):
        _fail("invalid_operation_field", "memberNodeIds must be an array.")
    known = {node.get("nodeId") for node in _nodes(process_map)}
    desired: List[str] = []
    for raw in members:
        member = _clean_id(raw, "memberNodeIds")
        if member not in known:
            _fail("operation_target_not_found", f"Node '{member}' was not found.")
        if member not in desired:
            desired.append(member)
    for group in _groups(process_map):
        if not isinstance(group, dict):
            continue
        if group is target:
            group["memberNodeIds"] = desired
        else:
            group["memberNodeIds"] = [
                member for member in group.get("memberNodeIds", []) if member not in desired
            ]
    return {"groupId": group_id, "memberNodeIds": desired}


def _op_edit_group(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    group_id = _clean_id(operation.get("groupId"), "groupId")
    group = _find(_groups(process_map), "groupId", group_id, "Group")
    if "label" in operation:
        group["label"] = _clean_text(operation.get("label"), MAX_GROUP_LABEL_LENGTH, "label")
    if "description" in operation:
        description = _clean_text(
            operation.get("description"), MAX_GROUP_DESCRIPTION_LENGTH, "description", required=False
        )
        if description:
            group["description"] = description
        else:
            group.pop("description", None)
    if "position" in operation:
        group["position"] = _position(operation.get("position"))
    if "size" in operation:
        group["size"] = _size(operation.get("size"))
    if "colorKey" in operation:
        color_key = _clean_text(operation.get("colorKey"), 32, "colorKey")
        if color_key not in GROUP_COLOR_KEYS:
            _fail("invalid_operation_field", f"Unsupported group color '{color_key}'.")
        group["colorKey"] = color_key
    return {"groupId": group_id}


def _op_delete_group(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    group_id = _clean_id(operation.get("groupId"), "groupId")
    _find(_groups(process_map), "groupId", group_id, "Group")
    process_map["canvasGroups"] = [group for group in _groups(process_map) if group.get("groupId") != group_id]
    return {"groupId": group_id}


def _op_attach_reference(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
) -> Dict[str, Any]:
    target_type = _clean_text(operation.get("targetType"), 16, "targetType")
    target_id = _clean_id(operation.get("targetId"), "targetId")
    records = _target_records(process_map, target_type, target_id)
    reference = _normalized_reference(process_map, operation, index)
    catalog = _catalog(process_map)
    existing = next(
        (item for item in catalog if isinstance(item, dict) and _reference_identity(item) == _reference_identity(reference)),
        None,
    )
    if existing is None:
        if any(item.get("referenceId") == reference["referenceId"] for item in catalog if isinstance(item, dict)):
            _fail("duplicate_operation_id", f"referenceId '{reference['referenceId']}' is already in use.")
        if len(catalog) >= MAX_REFERENCE_CATALOG_ITEMS:
            _fail("reference_catalog_limit", "The reference catalog is full.")
        catalog.append(reference)
        existing = reference
    reference_id = str(existing["referenceId"])
    for record in records:
        ids = list(record.get("referenceIds", [])) if isinstance(record.get("referenceIds"), list) else []
        if reference_id not in ids:
            if len(ids) >= MAX_REFERENCES_PER_TARGET:
                _fail("target_reference_limit", f"Target '{target_id}' already has the maximum references.")
            ids.append(reference_id)
        record["referenceIds"] = ids
    return {"targetType": target_type, "targetId": target_id, "referenceId": reference_id}


def _op_detach_reference(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    target_type = _clean_text(operation.get("targetType"), 16, "targetType")
    target_id = _clean_id(operation.get("targetId"), "targetId")
    reference_id = _clean_id(operation.get("referenceId"), "referenceId")
    records = _target_records(process_map, target_type, target_id)
    if not any(reference_id in record.get("referenceIds", []) for record in records):
        _fail("operation_target_not_found", f"Reference '{reference_id}' is not attached to the target.")
    for record in records:
        ids = [item for item in record.get("referenceIds", []) if item != reference_id]
        if ids:
            record["referenceIds"] = ids
        else:
            record.pop("referenceIds", None)
    _prune_references(process_map)
    return {"targetType": target_type, "targetId": target_id, "referenceId": reference_id}


def _op_record_process_plan_import(
    process_map: Dict[str, Any],
    _structure: Mapping[str, Any],
    operation: Mapping[str, Any],
    _index: int,
) -> Dict[str, Any]:
    record = {
        "sourcePlanId": _clean_text(
            operation.get("sourcePlanId"),
            MAX_REFERENCE_SOURCE_ID_LENGTH,
            "sourcePlanId",
        ),
        "sourceRevision": _clean_text(
            operation.get("sourceRevision"),
            MAX_REFERENCE_REVISION_LENGTH,
            "sourceRevision",
        ),
        "sourcePlanHash": _clean_text(
            operation.get("sourcePlanHash"),
            MAX_REFERENCE_SOURCE_HASH_LENGTH,
            "sourcePlanHash",
        ),
        "populatedBy": _clean_text(
            operation.get("populatedBy"),
            MAX_REFERENCE_POPULATED_BY_LENGTH,
            "populatedBy",
        ),
        "populatedAt": _clean_text(
            operation.get("populatedAt"),
            MAX_REFERENCE_POPULATED_AT_LENGTH,
            "populatedAt",
        ),
        "disclaimer": _clean_text(
            operation.get("disclaimer"),
            MAX_PROCESS_PLAN_DISCLAIMER_LENGTH,
            "disclaimer",
        ),
    }
    demo_data = operation.get("demoData")
    if not isinstance(demo_data, bool):
        _fail("invalid_operation_field", "demoData must be a boolean.")
    record["demoData"] = demo_data
    imports = process_map.get("processPlanImports")
    if imports is None:
        imports = []
        process_map["processPlanImports"] = imports
    if not isinstance(imports, list):
        _fail("invalid_map_shape", "processPlanImports must be an array.")
    identity = tuple(
        record[field] for field in ("sourcePlanId", "sourceRevision", "sourcePlanHash")
    )
    if any(
        isinstance(item, dict)
        and tuple(item.get(field) for field in ("sourcePlanId", "sourceRevision", "sourcePlanHash")) == identity
        for item in imports
    ):
        return {"sourcePlanId": record["sourcePlanId"], "alreadyRecorded": True}
    if len(imports) >= MAX_PROCESS_PLAN_IMPORTS:
        _fail("process_plan_import_limit", "The process-plan import history is full.")
    imports.append(record)
    return {"sourcePlanId": record["sourcePlanId"], "alreadyRecorded": False}


_HANDLERS: Dict[str, Callable[[Dict[str, Any], Mapping[str, Any], Mapping[str, Any], int], Dict[str, Any]]] = {
    "place_occurrence": _op_place_occurrence,
    "add_process_step": _op_add_process_step,
    "add_junction": _op_add_junction,
    "move_node": _op_move_node,
    "set_node_locked": _op_set_node_locked,
    "set_node_position_mode": _op_set_node_position_mode,
    "set_layout_policy": _op_set_layout_policy,
    "retype_step": _op_retype_step,
    "set_port_layout": _op_set_port_layout,
    "set_label": _op_set_label,
    "set_edge_label": _op_set_edge_label,
    "set_note": _op_set_note,
    "set_process_properties": _op_set_process_properties,
    "connect": _op_connect,
    "set_edge_routing": _op_set_edge_routing,
    "clear_edge_routing": _op_clear_edge_routing,
    "split_edge_with_junction": _op_split_edge_with_junction,
    "delete_node": _op_delete_node,
    "delete_edge": _op_delete_edge,
    "add_group": _op_add_group,
    "set_group_members": _op_set_group_members,
    "edit_group": _op_edit_group,
    "delete_group": _op_delete_group,
    "attach_reference": _op_attach_reference,
    "detach_reference": _op_detach_reference,
    "record_process_plan_import": _op_record_process_plan_import,
}


def supported_process_map_operations() -> Tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


def _records_by_id(process_map: Mapping[str, Any], key: str, collection: str) -> Dict[str, Any]:
    value = process_map.get(collection)
    return {
        str(record[key]): record
        for record in value if isinstance(record, dict) and record.get(key)
    } if isinstance(value, list) else {}


def build_process_map_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a compact deterministic diff suitable for exact user approval."""
    result: Dict[str, Any] = {"schemaVersion": 1}
    for label, collection, key in (
        ("nodes", "canvasNodes", "nodeId"),
        ("edges", "canvasEdges", "edgeId"),
        ("groups", "canvasGroups", "groupId"),
        ("references", "referenceCatalog", "referenceId"),
    ):
        old = _records_by_id(before, key, collection)
        new = _records_by_id(after, key, collection)
        result[label] = {
            "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)),
            "modified": sorted(
                identifier for identifier in set(old) & set(new)
                if canonical_process_map_bytes(old[identifier]) != canonical_process_map_bytes(new[identifier])
            ),
        }
    metadata_keys = (
        "displayName", "association", "status", "viewport", "dismissedSuggestions",
        "layoutPolicy", "processPlanImports",
    )
    result["metadata"] = [key for key in metadata_keys if before.get(key) != after.get(key)]
    return result


def diff_hash(
    *,
    map_id: str,
    base_revision: str,
    operations: Sequence[Mapping[str, Any]],
    after: Mapping[str, Any],
    diff: Mapping[str, Any],
) -> str:
    payload = {
        "mapId": map_id,
        "baseRevision": base_revision,
        "operations": list(operations),
        "afterContentHash": process_map_revision(after),
        "diff": diff,
    }
    return hashlib.sha256(canonical_process_map_bytes(payload)).hexdigest()


def apply_process_map_operations(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    maximum_operations: int = MAX_OPERATION_BATCH,
) -> Dict[str, Any]:
    """Apply an operation batch in memory and return validation plus a diff."""
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
        raise ProcessMapOperationError("operations_not_array", "operations must be an array.")
    if not operations:
        raise ProcessMapOperationError("operations_empty", "At least one operation is required.")
    limit = max(1, min(MAX_INTERNAL_OPERATION_BATCH, int(maximum_operations)))
    if len(operations) > limit:
        raise ProcessMapOperationError(
            "operations_too_large",
            f"An operation batch can contain at most {limit} operations.",
        )
    before = deepcopy(dict(process_map))
    after = deepcopy(before)
    results: List[Dict[str, Any]] = []
    for index, raw_operation in enumerate(operations):
        if not isinstance(raw_operation, Mapping):
            raise ProcessMapOperationError(
                "operation_not_object",
                f"Operation {index} must be an object.",
                operation_index=index,
            )
        operation = deepcopy(dict(raw_operation))
        operation_name = operation.get("op")
        handler = _HANDLERS.get(operation_name) if isinstance(operation_name, str) else None
        if handler is None:
            raise ProcessMapOperationError(
                "unknown_process_map_operation",
                f"Operation {index} has unsupported op '{operation_name}'.",
                operation_index=index,
            )
        try:
            result = handler(after, product_structure, operation, index)
        except ProcessMapOperationError as exc:
            if exc.operation_index is None:
                exc.operation_index = index
            raise
        results.append({"index": index, "op": operation_name, **result})

    occurrence_ids = set(_occurrence_index(product_structure))
    findings = validate_placement_map(after, occurrence_ids)
    diff = build_process_map_diff(before, after)
    changed = canonical_process_map_bytes(before) != canonical_process_map_bytes(after)
    return {
        "schemaVersion": PROCESS_MAP_OPERATION_SCHEMA_VERSION,
        "map": after,
        "findings": findings,
        "diff": diff,
        "changed": changed,
        "operationResults": results,
    }


def find_process_map_records(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    query: str,
    *,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search map records and source occurrences without exposing file paths."""
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Dict[str, Any]] = []

    def add(kind: str, identifier: str, label: str, record: Mapping[str, Any]) -> None:
        haystack = " ".join((identifier, label, json.dumps(record, ensure_ascii=True))).lower()
        if needle in haystack and len(matches) < max(1, min(200, int(limit))):
            matches.append({"kind": kind, "id": identifier, "label": label})

    for node in process_map.get("canvasNodes", []) if isinstance(process_map.get("canvasNodes"), list) else []:
        if isinstance(node, dict) and node.get("nodeId"):
            add("node", str(node["nodeId"]), str(node.get("name") or node.get("labelOverride") or node["nodeId"]), node)
    for edge in process_map.get("canvasEdges", []) if isinstance(process_map.get("canvasEdges"), list) else []:
        if isinstance(edge, dict) and edge.get("edgeId"):
            add("edge", str(edge["edgeId"]), str(edge.get("label") or edge["edgeId"]), edge)
    for group in process_map.get("canvasGroups", []) if isinstance(process_map.get("canvasGroups"), list) else []:
        if isinstance(group, dict) and group.get("groupId"):
            add("group", str(group["groupId"]), str(group.get("label") or group["groupId"]), group)
    for reference in process_map.get("referenceCatalog", []) if isinstance(process_map.get("referenceCatalog"), list) else []:
        if isinstance(reference, dict) and reference.get("referenceId"):
            add("reference", str(reference["referenceId"]), str(reference.get("name") or reference["referenceId"]), reference)
    for occurrence in product_structure.get("occurrences", []) if isinstance(product_structure.get("occurrences"), list) else []:
        if isinstance(occurrence, dict) and occurrence.get("occurrenceId"):
            add("occurrence", str(occurrence["occurrenceId"]), str(occurrence.get("name") or occurrence["occurrenceId"]), occurrence)
    return matches
