"""Trusted runtime state snapshot for Process Map skills.

Saved graph geometry is compiled server-side. The browser may contribute only
ephemeral editor facts, and every identifier is checked against the saved map.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence

from .schema_v3 import node_position_mode
from .spatial import compile_spatial_scene, diagnose_spatial_scene


PROCESS_MAP_STATE_VERSION = 1
MAX_STATE_RECEIPTS = 6


def _ids(values: Any, known: set[str], limit: int = 250) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(
        {
            value
            for value in values[:limit]
            if isinstance(value, str) and value in known
        }
    )


def sanitize_process_map_live_facts(
    value: Any,
    *,
    node_ids: set[str],
    edge_ids: set[str],
) -> Dict[str, Any]:
    """Accept only non-authoritative editor facts from the active browser."""

    source = value if isinstance(value, Mapping) else {}
    selection = source.get("selection")
    selection = selection if isinstance(selection, Mapping) else {}
    proposal = source.get("activeProposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    return {
        "dirty": bool(source.get("dirty")),
        "conflict": bool(source.get("conflict")),
        "editable": bool(source.get("editable")),
        "selection": {
            "nodeIds": _ids(selection.get("nodeIds"), node_ids),
            "edgeIds": _ids(selection.get("edgeIds"), edge_ids),
        },
        "activeProposalId": (
            str(proposal.get("proposalId")).strip()
            if isinstance(proposal.get("proposalId"), str)
            and str(proposal.get("proposalId")).strip()
            else None
        ),
    }


def _receipt(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    result: Dict[str, Any] = {}
    for key in (
        "receiptId",
        "proposalId",
        "productId",
        "mapId",
        "baseRevision",
        "revision",
        "diffHash",
        "semanticBindingHash",
        "action",
    ):
        item = value.get(key)
        if isinstance(item, str) and item:
            result[key] = item[:256]
    for key in (
        "semanticBinding",
        "createdIds",
        "warnings",
        "unresolvedItems",
        "outcome",
    ):
        if key in value:
            result[key] = deepcopy(value[key])
    return result or None


def build_process_map_state(
    loaded: Mapping[str, Any],
    *,
    live_facts: Optional[Mapping[str, Any]] = None,
    capabilities: Optional[Mapping[str, Any]] = None,
    active_proposal: Optional[Mapping[str, Any]] = None,
    receipts: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compile saved world geometry plus validated live editor facts."""

    process_map = loaded["map"]
    association = (
        process_map.get("association")
        if isinstance(process_map.get("association"), Mapping)
        else {}
    )
    product_id = str(
        loaded.get("productId")
        or process_map.get("productId")
        or association.get("productId")
        or ""
    )
    scene = compile_spatial_scene(process_map, revision=str(loaded["revision"]))
    diagnostics = diagnose_spatial_scene(scene)
    raw_nodes = {
        str(node.get("nodeId")): node
        for node in process_map.get("canvasNodes", [])
        if isinstance(node, Mapping) and node.get("nodeId")
    }
    raw_edges = {
        str(edge.get("edgeId")): edge
        for edge in process_map.get("canvasEdges", [])
        if isinstance(edge, Mapping) and edge.get("edgeId")
    }
    product_structure = (
        loaded.get("productStructure")
        if isinstance(loaded.get("productStructure"), Mapping)
        else {}
    )
    occurrences = {
        str(item.get("occurrenceId")): item
        for item in product_structure.get("occurrences", [])
        if isinstance(item, Mapping) and item.get("occurrenceId")
    }
    node_ids = set(raw_nodes)
    edge_ids = set(raw_edges)
    live = sanitize_process_map_live_facts(
        live_facts,
        node_ids=node_ids,
        edge_ids=edge_ids,
    )

    nodes = []
    for compiled in scene.get("nodes", []):
        node_id = str(compiled["nodeId"])
        raw = raw_nodes[node_id]
        occurrence = occurrences.get(str(raw.get("sourceOccurrenceId") or ""))
        nodes.append(
            {
                "id": node_id,
                "kind": raw.get("nodeKind"),
                "name": str(
                    raw.get("labelOverride")
                    or raw.get("name")
                    or raw.get("nameSnapshot")
                    or (occurrence or {}).get("name")
                    or node_id
                ),
                "processType": raw.get("processType"),
                "junctionType": raw.get("junctionType"),
                "sourceOccurrenceId": raw.get("sourceOccurrenceId"),
                "positionMode": node_position_mode(raw),
                "position": deepcopy(raw.get("position")),
                "dimensions": {
                    "width": compiled["rect"]["width"],
                    "height": compiled["rect"]["height"],
                },
                "ports": {
                    "input": deepcopy(compiled["ports"]["input"]),
                    "output": deepcopy(compiled["ports"]["output"]),
                },
                "groupId": compiled.get("groupId"),
                "referenceIds": sorted(
                    str(value) for value in raw.get("referenceIds", []) if value
                ),
            }
        )

    edges = [
        {
            "id": edge_id,
            "kind": raw.get("kind", "precedence"),
            "from": deepcopy(raw.get("from")),
            "to": deepcopy(raw.get("to")),
            "routeMode": (
                raw.get("routing", {}).get("mode", "bezier_legacy")
                if isinstance(raw.get("routing"), Mapping)
                else "bezier_legacy"
            ),
            "referenceIds": sorted(
                str(value) for value in raw.get("referenceIds", []) if value
            ),
        }
        for edge_id, raw in sorted(raw_edges.items())
    ]
    groups = [
        {
            "id": str(group.get("groupId")),
            "label": group.get("label"),
            "position": deepcopy(group.get("position")),
            "size": deepcopy(group.get("size")),
            "memberNodeIds": sorted(group.get("memberNodeIds") or []),
        }
        for group in sorted(
            (
                item
                for item in process_map.get("canvasGroups", [])
                if isinstance(item, Mapping) and item.get("groupId")
            ),
            key=lambda item: str(item.get("groupId")),
        )
    ]
    proposal_summary = None
    if (
        active_proposal
        and live.get("activeProposalId")
        and active_proposal.get("proposalId") == live["activeProposalId"]
        and active_proposal.get("productId") == product_id
        and active_proposal.get("mapId") == process_map.get("mapId")
        and active_proposal.get("baseRevision") == loaded["revision"]
    ):
        proposal_summary = {
            "proposalId": active_proposal.get("proposalId"),
            "type": (
                active_proposal.get("managedProposalType")
                or (
                    "semantic_process_map"
                    if active_proposal.get("semanticBindingHash")
                    else None
                )
                or active_proposal.get("spatialTool")
            ),
            "baseRevision": active_proposal.get("baseRevision"),
            "summary": deepcopy(
                active_proposal.get("semanticSummary")
                or active_proposal.get("spatialSummary")
                or active_proposal.get("managedSummary")
                or {}
            ),
            "pendingApproval": True,
        }
        semantic_binding = active_proposal.get("semanticBinding")
        if (
            isinstance(semantic_binding, Mapping)
            and isinstance(
                semantic_binding.get("assemblyKnowledge"),
                Mapping,
            )
        ):
            proposal_summary["evidenceBinding"] = deepcopy(
                semantic_binding["assemblyKnowledge"]
            )
    safe_receipts = []
    for item in list(receipts or [])[-MAX_STATE_RECEIPTS:]:
        if (
            not isinstance(item, Mapping)
            or item.get("productId") != product_id
            or item.get("mapId") != process_map.get("mapId")
            or item.get("revision") != loaded["revision"]
        ):
            continue
        sanitized = _receipt(item)
        if sanitized:
            safe_receipts.append(sanitized)
    return {
        "stateVersion": PROCESS_MAP_STATE_VERSION,
        "identity": {
            "productId": product_id,
            "mapId": process_map.get("mapId"),
            "revision": loaded["revision"],
            "structureRevision": loaded.get("structureRevision"),
        },
        "savedStateCurrent": not live["dirty"] and not live["conflict"],
        "editor": {
            "dirty": live["dirty"],
            "conflict": live["conflict"],
            "editable": live["editable"],
        },
        "selection": live["selection"],
        "capabilities": {
            key: bool(value) for key, value in sorted((capabilities or {}).items())
        },
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "spatialDiagnostics": {
            "problemCount": diagnostics.get("problemCount", 0),
            "metrics": deepcopy(diagnostics.get("metrics") or {}),
        },
        "activeProposal": proposal_summary,
        "recentReceipts": safe_receipts,
        "coordinateContract": {
            "persisted": "world",
            "cameraIsNotGeometry": True,
            "screenPixelsAcceptedForWrites": False,
        },
    }
