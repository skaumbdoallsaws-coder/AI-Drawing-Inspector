"""Outcome-only spatial tools for Sage and Builder process-map proposals."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence

from .operations import apply_process_map_operations
from .repository import canonical_process_map_bytes
from .schema_v3 import EDGE_KINDS, PROCESS_STEP_TYPES
from .spatial import (
    PROCESS_MAP_CANDIDATE_POLICY_VERSION,
    PROCESS_MAP_ROUTER_VERSION,
    PROCESS_MAP_SPATIAL_VERSION,
    compile_spatial_scene,
    diagnose_spatial_scene,
    generate_placement_candidates,
    route_orthogonal_edge,
    spatial_contract_for_process_map,
    spatial_obstacle_fingerprint,
)


PROCESS_MAP_SPATIAL_TOOL_CONTRACT_VERSION = 1
SPATIAL_INSPECTION_TOOL = "inspect_process_map_spatial_layout"
SPATIAL_PLACEMENT_TOOL = "propose_process_map_node_placement"
SPATIAL_ROUTE_TOOL = "propose_process_map_connection_route"
PROCESS_MAP_SPATIAL_TOOL_NAMES = frozenset(
    {SPATIAL_INSPECTION_TOOL, SPATIAL_PLACEMENT_TOOL, SPATIAL_ROUTE_TOOL}
)

_FORBIDDEN_GEOMETRY_KEYS = frozenset(
    {
        "x",
        "y",
        "position",
        "positions",
        "point",
        "points",
        "waypoint",
        "waypoints",
        "route",
        "routing",
        "coordinates",
        "viewport",
        "pan",
        "zoom",
        "transform",
    }
)


class ProcessMapSpatialToolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ProcessMapSpatialToolError(code, message)


def _clean_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        _fail("invalid_spatial_tool_request", f"{field} must be a non-empty stable ID.")
    return value.strip()


def _clean_optional_id(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    return _clean_id(value, field)


def _reject_model_geometry(value: Any, path: str = "request") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.lower() in _FORBIDDEN_GEOMETRY_KEYS:
                _fail(
                    "model_geometry_not_allowed",
                    f"{path}.{key} is not accepted; the deterministic planner owns geometry.",
                )
            _reject_model_geometry(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_model_geometry(item, f"{path}[{index}]")


def _exact_fields(request: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(request) - allowed)
    if unknown:
        _fail(
            "invalid_spatial_tool_request",
            "Unsupported spatial request fields: " + ", ".join(unknown) + ".",
        )


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_process_map_bytes(value)).hexdigest()


def _stable_graph_id(
    prefix: str,
    request: Mapping[str, Any],
    existing_ids: set[str],
) -> str:
    digest = _canonical_hash(request)
    for length in range(12, 65, 4):
        candidate = f"{prefix}-{digest[:length]}"
        if candidate not in existing_ids:
            return candidate
    _fail("spatial_id_collision", "A deterministic graph ID could not be allocated.")
    raise AssertionError("unreachable")


def _node_index(process_map: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(node["nodeId"]): node
        for node in process_map.get("canvasNodes", [])
        if isinstance(node, dict) and node.get("nodeId")
    }


def _edge_index(process_map: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(edge["edgeId"]): edge
        for edge in process_map.get("canvasEdges", [])
        if isinstance(edge, dict) and edge.get("edgeId")
    }


def _occurrence_index(product_structure: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item["occurrenceId"]): item
        for item in product_structure.get("occurrences", [])
        if isinstance(item, dict) and item.get("occurrenceId")
    }


def _routing_operation(edge_id: str, route: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "op": "set_edge_routing",
        "edgeId": edge_id,
        "routing": {
            "mode": "orthogonal_auto",
            "routerVersion": PROCESS_MAP_ROUTER_VERSION,
            "waypoints": deepcopy(list(route.get("waypoints") or [])),
            "obstacleFingerprint": str(route.get("obstacleFingerprint") or ""),
        },
    }


def _preview_records(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> Dict[str, Any]:
    def changed(collection: str, key: str) -> list[Dict[str, Any]]:
        old = {
            str(item[key]): item
            for item in before.get(collection, [])
            if isinstance(item, dict) and item.get(key)
        }
        result = []
        for item in after.get(collection, []):
            if not isinstance(item, dict) or not item.get(key):
                continue
            identifier = str(item[key])
            if identifier not in old or canonical_process_map_bytes(old[identifier]) != canonical_process_map_bytes(item):
                result.append(deepcopy(item))
        return sorted(result, key=lambda item: str(item.get(key) or ""))

    return {
        "nodes": changed("canvasNodes", "nodeId"),
        "edges": changed("canvasEdges", "edgeId"),
        "groups": changed("canvasGroups", "groupId"),
    }


def _binding_hash(binding: Mapping[str, Any]) -> str:
    return _canonical_hash(binding)


def inspect_process_map_spatial_layout(
    process_map: Mapping[str, Any],
    *,
    revision: str,
    scope_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return compact diagnostics without exposing world or viewport coordinates."""

    scope = {
        _clean_id(item, "scopeIds")
        for item in (scope_ids or [])
    }
    contract = spatial_contract_for_process_map(process_map)
    scene = compile_spatial_scene(process_map, revision=revision, contract=contract)
    diagnostics = diagnose_spatial_scene(scene, contract=contract)
    problems = []
    for raw in diagnostics.get("problems", []):
        if not isinstance(raw, Mapping):
            continue
        affected = {
            str(identifier)
            for field in ("nodeIds", "edgeIds", "groupIds")
            for identifier in (raw.get(field) or [])
        }
        if scope and not (scope & affected):
            continue
        problem = {
            key: deepcopy(raw[key])
            for key in (
                "problemId",
                "code",
                "severity",
                "nodeIds",
                "edgeIds",
                "groupIds",
                "clearance",
                "overlapArea",
                "detourRatio",
            )
            if key in raw
        }
        problems.append(problem)
    return {
        "toolContractVersion": PROCESS_MAP_SPATIAL_TOOL_CONTRACT_VERSION,
        "tool": SPATIAL_INSPECTION_TOOL,
        "identity": {
            "productId": str(process_map.get("productId") or ""),
            "mapId": str(process_map.get("mapId") or ""),
            "revision": revision,
        },
        "spatialVersion": PROCESS_MAP_SPATIAL_VERSION,
        "obstacleFingerprint": spatial_obstacle_fingerprint(scene),
        "scopeIds": sorted(scope),
        "metrics": deepcopy(diagnostics.get("metrics") or {}),
        "problems": problems,
        "problemCount": len(problems),
    }


def _placement_plan(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    revision: str,
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    _exact_fields(
        request,
        {
            "targetKind",
            "occurrenceId",
            "targetNodeId",
            "processType",
            "name",
            "anchorNodeId",
            "connectionDirection",
            "requiredGroupId",
            "preferredFlowDirection",
            "edgeKind",
        },
    )
    target_kind = str(request.get("targetKind") or "").strip()
    if target_kind not in {"product_occurrence", "process_step", "existing_node"}:
        _fail("invalid_spatial_tool_request", "targetKind is unsupported.")
    nodes = _node_index(process_map)
    existing_ids = set(nodes) | set(_edge_index(process_map))
    anchor_id = _clean_optional_id(request.get("anchorNodeId"), "anchorNodeId")
    if anchor_id is not None and anchor_id not in nodes:
        _fail("spatial_target_not_found", f"Anchor node '{anchor_id}' was not found.")
    group_id = _clean_optional_id(request.get("requiredGroupId"), "requiredGroupId")
    connection_direction = str(request.get("connectionDirection") or "none").strip()
    if connection_direction not in {"none", "incoming", "outgoing"}:
        _fail("invalid_spatial_tool_request", "connectionDirection is unsupported.")
    if connection_direction != "none" and anchor_id is None:
        _fail("invalid_spatial_tool_request", "A connected placement requires anchorNodeId.")
    preferred = str(request.get("preferredFlowDirection") or "left_to_right").strip()
    if preferred not in {"left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"}:
        _fail("invalid_spatial_tool_request", "preferredFlowDirection is unsupported.")

    operation_seed = {
        "tool": SPATIAL_PLACEMENT_TOOL,
        "revision": revision,
        "request": deepcopy(dict(request)),
    }
    is_new = target_kind != "existing_node"
    occurrence = None
    process_type = None
    name = None
    if target_kind == "product_occurrence":
        occurrence_id = _clean_id(request.get("occurrenceId"), "occurrenceId")
        occurrence = _occurrence_index(product_structure).get(occurrence_id)
        if occurrence is None:
            _fail("spatial_target_not_found", f"Occurrence '{occurrence_id}' was not found.")
        if any(node.get("sourceOccurrenceId") == occurrence_id for node in nodes.values()):
            _fail("duplicate_occurrence_placement", f"Occurrence '{occurrence_id}' is already placed.")
        target_node_id = _stable_graph_id("pmn-agent", operation_seed, existing_ids)
        candidate_kind = "product_occurrence"
        name = str(occurrence.get("name") or occurrence_id)
    elif target_kind == "process_step":
        process_type = str(request.get("processType") or "").strip()
        if process_type not in PROCESS_STEP_TYPES:
            _fail("invalid_spatial_tool_request", "processType is unsupported.")
        name = str(request.get("name") or "").strip()
        if not name or len(name) > 120:
            _fail("invalid_spatial_tool_request", "name must contain 1 to 120 characters.")
        target_node_id = _stable_graph_id("pmn-agent", operation_seed, existing_ids)
        candidate_kind = "process_step"
    else:
        target_node_id = _clean_id(request.get("targetNodeId"), "targetNodeId")
        target = nodes.get(target_node_id)
        if target is None or target.get("nodeKind") == "junction":
            _fail("spatial_target_not_found", f"Movable node '{target_node_id}' was not found.")
        if target.get("locked") is True:
            _fail("locked_node_movement", f"Node '{target_node_id}' is position-locked.")
        candidate_kind = str(target.get("nodeKind") or "process_step")
        name = str(target.get("name") or target.get("labelOverride") or target_node_id)

    contract = spatial_contract_for_process_map(process_map)
    scene = compile_spatial_scene(process_map, revision=revision, contract=contract)
    candidates = generate_placement_candidates(
        scene,
        target_kind=candidate_kind,
        target_node_id=None if is_new else target_node_id,
        anchor_node_id=anchor_id,
        connection_direction=None if connection_direction == "none" else connection_direction,
        required_group_id=group_id,
        preferred_flow_direction=preferred,
        contract=contract,
        limit=1,
    )
    if not candidates.get("candidates"):
        _fail("no_clean_spatial_candidate", "No clean deterministic placement is available.")
    candidate = candidates["candidates"][0]
    if target_kind == "product_occurrence":
        operations = [{
            "op": "place_occurrence",
            "occurrenceId": str(occurrence["occurrenceId"]),
            "nodeId": target_node_id,
            "position": deepcopy(candidate["position"]),
            "portOrientation": candidate["portOrientation"],
            "portOrder": candidate["portOrder"],
        }]
    elif target_kind == "process_step":
        operations = [{
            "op": "add_process_step",
            "nodeId": target_node_id,
            "processType": process_type,
            "name": name,
            "position": deepcopy(candidate["position"]),
            "portOrientation": candidate["portOrientation"],
            "portOrder": candidate["portOrder"],
        }]
    else:
        operations = [{
            "op": "move_node",
            "nodeId": target_node_id,
            "position": deepcopy(candidate["position"]),
        }]
        target = nodes[target_node_id]
        if (
            target.get("portOrientation", "horizontal") != candidate["portOrientation"]
            or target.get("portOrder", "input_first") != candidate["portOrder"]
        ):
            operations.append({
                "op": "set_port_layout",
                "nodeId": target_node_id,
                "orientation": candidate["portOrientation"],
                "order": candidate["portOrder"],
            })

    if group_id is not None and is_new:
        group = next(
            (
                item
                for item in process_map.get("canvasGroups", [])
                if isinstance(item, dict) and item.get("groupId") == group_id
            ),
            None,
        )
        if group is None:
            _fail("spatial_target_not_found", f"Group '{group_id}' was not found.")
        operations.append({
            "op": "set_group_members",
            "groupId": group_id,
            "memberNodeIds": [*list(group.get("memberNodeIds") or []), target_node_id],
        })

    edge_id = None
    route = None
    if connection_direction != "none":
        edge_kind = str(request.get("edgeKind") or "precedence").strip()
        if edge_kind not in EDGE_KINDS:
            _fail("invalid_spatial_tool_request", "edgeKind is unsupported.")
        edge_seed = {**operation_seed, "targetNodeId": target_node_id, "edge": True}
        edge_id = _stable_graph_id("pme-agent", edge_seed, existing_ids | {target_node_id})
        outgoing = connection_direction == "outgoing"
        operations.append({
            "op": "connect",
            "edgeId": edge_id,
            "fromNodeId": anchor_id if outgoing else target_node_id,
            "toNodeId": target_node_id if outgoing else anchor_id,
            "kind": edge_kind,
        })
        transient = apply_process_map_operations(
            process_map,
            product_structure,
            operations,
        )["map"]
        transient_contract = spatial_contract_for_process_map(transient, contract)
        transient_scene = compile_spatial_scene(
            transient,
            revision=revision,
            contract=transient_contract,
        )
        route = route_orthogonal_edge(transient_scene, edge_id, contract=transient_contract)
        if not route.get("accepted"):
            _fail("no_clean_spatial_route", "The proposed placement cannot be connected cleanly.")
        operations.append(_routing_operation(edge_id, route))

    applied = apply_process_map_operations(process_map, product_structure, operations)
    binding = {
        "toolContractVersion": PROCESS_MAP_SPATIAL_TOOL_CONTRACT_VERSION,
        "tool": SPATIAL_PLACEMENT_TOOL,
        "spatialVersion": PROCESS_MAP_SPATIAL_VERSION,
        "candidatePolicyVersion": PROCESS_MAP_CANDIDATE_POLICY_VERSION,
        "candidateId": str(candidate["candidateId"]),
        "placementObstacleFingerprint": str(candidates["obstacleFingerprint"]),
        "routeId": str(route.get("routeId") or "") if route else None,
        "routeObstacleFingerprint": str(route.get("obstacleFingerprint") or "") if route else None,
        "targetNodeId": target_node_id,
        "edgeId": edge_id,
    }
    summary = {
        "action": "move_card" if not is_new else "place_card",
        "label": name,
        "targetNodeId": target_node_id,
        "edgeCount": 1 if edge_id else 0,
        "message": (
            f"Moved {name} and routed its connection."
            if not is_new and edge_id
            else f"Moved {name}."
            if not is_new
            else f"Placed {name} and routed one connection."
            if edge_id
            else f"Placed {name}."
        ),
    }
    return {
        "operations": operations,
        "binding": binding,
        "bindingHash": _binding_hash(binding),
        "preview": _preview_records(process_map, applied["map"]),
        "summary": summary,
    }


def _route_plan(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    revision: str,
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    _exact_fields(request, {"edgeId"})
    edge_id = _clean_id(request.get("edgeId"), "edgeId")
    if edge_id not in _edge_index(process_map):
        _fail("spatial_target_not_found", f"Edge '{edge_id}' was not found.")
    contract = spatial_contract_for_process_map(process_map)
    scene = compile_spatial_scene(process_map, revision=revision, contract=contract)
    route = route_orthogonal_edge(scene, edge_id, contract=contract)
    if not route.get("accepted"):
        _fail("no_clean_spatial_route", f"Edge '{edge_id}' cannot be routed cleanly.")
    operations = [_routing_operation(edge_id, route)]
    applied = apply_process_map_operations(process_map, product_structure, operations)
    binding = {
        "toolContractVersion": PROCESS_MAP_SPATIAL_TOOL_CONTRACT_VERSION,
        "tool": SPATIAL_ROUTE_TOOL,
        "spatialVersion": PROCESS_MAP_SPATIAL_VERSION,
        "routerVersion": PROCESS_MAP_ROUTER_VERSION,
        "routeId": str(route["routeId"]),
        "routeObstacleFingerprint": str(route["obstacleFingerprint"]),
        "edgeId": edge_id,
    }
    return {
        "operations": operations,
        "binding": binding,
        "bindingHash": _binding_hash(binding),
        "preview": _preview_records(process_map, applied["map"]),
        "summary": {
            "action": "route_connection",
            "edgeId": edge_id,
            "edgeCount": 1,
            "message": f"Routed connection {edge_id} around the current map obstacles.",
        },
    }


def plan_process_map_spatial_tool(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    revision: str,
    tool_name: str,
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compile an outcome-only request into deterministic internal operations."""

    if tool_name not in {SPATIAL_PLACEMENT_TOOL, SPATIAL_ROUTE_TOOL}:
        _fail("unknown_spatial_tool", f"Spatial tool '{tool_name}' is unsupported.")
    if not isinstance(request, Mapping):
        _fail("invalid_spatial_tool_request", "The spatial request must be an object.")
    _reject_model_geometry(request)
    if tool_name == SPATIAL_PLACEMENT_TOOL:
        return _placement_plan(process_map, product_structure, revision, request)
    return _route_plan(process_map, product_structure, revision, request)


def process_map_spatial_tool_specs() -> list[Dict[str, Any]]:
    """Provider schemas expose semantic outcomes and no geometry fields."""

    return [
        {
            "name": SPATIAL_INSPECTION_TOOL,
            "description": "Inspect deterministic process-map layout findings without changing the map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "scope_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 50,
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "name": SPATIAL_PLACEMENT_TOOL,
            "description": "Request a deterministic card placement or move preview. Never accepts coordinates.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "targetKind": {
                        "type": "string",
                        "enum": ["product_occurrence", "process_step", "existing_node"],
                    },
                    "occurrenceId": {"type": "string"},
                    "targetNodeId": {"type": "string"},
                    "processType": {"type": "string", "enum": sorted(PROCESS_STEP_TYPES)},
                    "name": {"type": "string", "maxLength": 120},
                    "anchorNodeId": {"type": "string"},
                    "connectionDirection": {
                        "type": "string",
                        "enum": ["none", "incoming", "outgoing"],
                    },
                    "requiredGroupId": {"type": "string"},
                    "preferredFlowDirection": {
                        "type": "string",
                        "enum": [
                            "left_to_right",
                            "right_to_left",
                            "top_to_bottom",
                            "bottom_to_top",
                        ],
                    },
                    "edgeKind": {"type": "string", "enum": sorted(EDGE_KINDS)},
                },
                "required": ["targetKind"],
                "additionalProperties": False,
            },
        },
        {
            "name": SPATIAL_ROUTE_TOOL,
            "description": "Request a deterministic obstacle-aware route preview for one existing edge.",
            "input_schema": {
                "type": "object",
                "properties": {"edgeId": {"type": "string"}},
                "required": ["edgeId"],
                "additionalProperties": False,
            },
        },
    ]

