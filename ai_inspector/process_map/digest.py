"""Deterministic, revision-bound process-map context for Sage."""

from __future__ import annotations

import copy
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from .repository import ProcessMapConflictError, load_named_process_map
from .spatial import (
    PROCESS_MAP_SPATIAL_VERSION,
    SpatialGeometryError,
    compile_spatial_scene,
    diagnose_spatial_scene,
)


PROCESS_MAP_DIGEST_VERSION = 3
PROCESS_MAP_DIGEST_MAX_TOKENS = 3500


def estimate_digest_tokens(value: Mapping[str, Any]) -> int:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return (len(encoded) + 3) // 4


def _text(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _node_name(node: Mapping[str, Any], occurrence: Mapping[str, Any] | None) -> str:
    return _text(
        node.get("labelOverride")
        or node.get("name")
        or node.get("nameSnapshot")
        or (occurrence or {}).get("name")
        or node.get("nodeId"),
        160,
    )


def _sorted_records(values: Any, key: str) -> list[dict[str, Any]]:
    return sorted(
        [copy.deepcopy(item) for item in values or [] if isinstance(item, dict)],
        key=lambda item: str(item.get(key) or ""),
    )


def _edge_nodes(edge: Mapping[str, Any]) -> tuple[str, str]:
    source = edge.get("from") if isinstance(edge.get("from"), Mapping) else {}
    target = edge.get("to") if isinstance(edge.get("to"), Mapping) else {}
    return str(source.get("nodeId") or ""), str(target.get("nodeId") or "")


def _collapsed_precedence_pairs(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    junctions = {
        str(node.get("nodeId"))
        for node in nodes
        if node.get("nodeKind") == "junction" and node.get("nodeId")
    }
    authored = {
        str(node.get("nodeId"))
        for node in nodes
        if node.get("nodeKind") != "junction" and node.get("nodeId")
    }
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.get("kind", "precedence") != "precedence":
            continue
        source, target = _edge_nodes(edge)
        if source and target:
            outgoing[source].add(target)

    pairs: set[tuple[str, str]] = set()
    for source in sorted(authored):
        queue = deque(sorted(outgoing.get(source, set())))
        visited: set[str] = set()
        while queue:
            target = queue.popleft()
            if target in visited:
                continue
            visited.add(target)
            if target in junctions:
                queue.extend(sorted(outgoing.get(target, set())))
            elif target in authored and target != source:
                pairs.add((source, target))
    return sorted(pairs)


def _cycles(adjacency: Mapping[str, set[str]]) -> list[list[str]]:
    colors: dict[str, int] = {}
    stack: list[str] = []
    stack_index: dict[str, int] = {}
    found: set[tuple[str, ...]] = set()

    def visit(node_id: str) -> None:
        colors[node_id] = 1
        stack_index[node_id] = len(stack)
        stack.append(node_id)
        for target_id in sorted(adjacency.get(node_id, set())):
            color = colors.get(target_id, 0)
            if color == 0:
                visit(target_id)
            elif color == 1:
                cycle = stack[stack_index[target_id]:] + [target_id]
                found.add(tuple(cycle))
        stack.pop()
        stack_index.pop(node_id, None)
        colors[node_id] = 2

    all_nodes = set(adjacency)
    for targets in adjacency.values():
        all_nodes.update(targets)
    for node_id in sorted(all_nodes):
        if colors.get(node_id, 0) == 0:
            visit(node_id)
    return [list(cycle) for cycle in sorted(found)]


def _weak_regions(node_ids: Iterable[str], pairs: Sequence[tuple[str, str]]) -> list[list[str]]:
    neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for source, target in pairs:
        neighbors.setdefault(source, set()).add(target)
        neighbors.setdefault(target, set()).add(source)
    regions: list[list[str]] = []
    remaining = set(neighbors)
    while remaining:
        start = min(remaining)
        queue = deque([start])
        region: set[str] = set()
        while queue:
            node_id = queue.popleft()
            if node_id in region:
                continue
            region.add(node_id)
            queue.extend(sorted(neighbors.get(node_id, set()) - region))
        remaining -= region
        regions.append(sorted(region))
    return sorted(regions, key=lambda region: (region[0] if region else "", len(region)))


def _distances(start: str, adjacency: Mapping[str, set[str]]) -> dict[str, int]:
    result = {start: 0}
    queue = deque([start])
    while queue:
        node_id = queue.popleft()
        for target_id in sorted(adjacency.get(node_id, set())):
            if target_id not in result:
                result[target_id] = result[node_id] + 1
                queue.append(target_id)
    return result


def _parallel_branches(adjacency: Mapping[str, set[str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for fork in sorted(adjacency):
        branches = sorted(adjacency.get(fork, set()))
        if len(branches) < 2:
            continue
        branch_distances = {branch: _distances(branch, adjacency) for branch in branches}
        common = set.intersection(
            *(set(distances) for distances in branch_distances.values())
        ) if branch_distances else set()
        common.discard(fork)
        if not common:
            continue
        join = min(
            common,
            key=lambda node_id: (
                max(branch_distances[branch][node_id] for branch in branches),
                sum(branch_distances[branch][node_id] for branch in branches),
                node_id,
            ),
        )
        result.append({"fork": fork, "branches": branches, "join": join})
    return result


def _references_for_target(
    target: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    result = []
    for reference_id in target.get("referenceIds") or []:
        item = catalog.get(str(reference_id))
        if not item:
            continue
        label = f"{_text(item.get('kind'), 40)}:{_text(item.get('name'), 160)}"
        identifier = _text(item.get("identifier"), 120)
        if identifier:
            label += f" ({identifier})"
        result.append(label)
    return sorted(set(result))


def _logical_connections(
    edges: Sequence[Mapping[str, Any]],
    junction_ids: set[str],
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in edges:
        logical_id = str(edge.get("logicalConnectionId") or edge.get("edgeId") or "")
        if logical_id:
            grouped[logical_id].append(edge)
    result = []
    for logical_id in sorted(grouped):
        segments = grouped[logical_id]
        sources: set[str] = set()
        targets: set[str] = set()
        touched_junctions: set[str] = set()
        kinds: set[str] = set()
        labels: set[str] = set()
        references: set[str] = set()
        for edge in segments:
            source, target = _edge_nodes(edge)
            if source in junction_ids:
                touched_junctions.add(source)
            elif source:
                sources.add(source)
            if target in junction_ids:
                touched_junctions.add(target)
            elif target:
                targets.add(target)
            kinds.add(str(edge.get("kind") or "precedence"))
            if _text(edge.get("label"), 160):
                labels.add(_text(edge.get("label"), 160))
            references.update(_references_for_target(edge, catalog))
        record: dict[str, Any] = {
            "logicalConnectionId": logical_id,
            "kinds": sorted(kinds),
            "fromNodeIds": sorted(sources),
            "toNodeIds": sorted(targets),
            "segmentCount": len(segments),
            "junctionCount": len(touched_junctions),
        }
        if labels:
            record["labels"] = sorted(labels)
        if references:
            record["references"] = sorted(references)
        result.append(record)
    return result


def _bounded_list(
    values: Sequence[Any],
    limit: int,
    path: str,
    truncation: dict[str, str],
) -> list[Any]:
    kept = list(values[:limit])
    omitted = len(values) - len(kept)
    if omitted:
        truncation[path] = f"and {omitted} more"
    return kept


def _source_occurrence_records(
    occurrences: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    children: dict[str | None, list[str]] = defaultdict(list)
    for occurrence_id, occurrence in occurrences.items():
        parent_id = occurrence.get("parentOccurrenceId")
        parent_key = str(parent_id) if parent_id else None
        children[parent_key].append(occurrence_id)
    for child_ids in children.values():
        child_ids.sort()

    memo: dict[str, int] = {}

    def descendant_part_count(occurrence_id: str, visiting: set[str]) -> int:
        if occurrence_id in memo:
            return memo[occurrence_id]
        if occurrence_id in visiting:
            return 0
        occurrence = occurrences.get(occurrence_id) or {}
        if str(occurrence.get("kind") or "").lower() == "part":
            memo[occurrence_id] = 1
            return 1
        next_visiting = set(visiting)
        next_visiting.add(occurrence_id)
        count = sum(
            descendant_part_count(child_id, next_visiting)
            for child_id in children.get(occurrence_id, [])
        )
        memo[occurrence_id] = count
        return count

    records: list[dict[str, Any]] = []
    for occurrence_id in sorted(occurrences):
        occurrence = occurrences[occurrence_id]
        record: dict[str, Any] = {
            "id": occurrence_id,
            "parentId": str(occurrence.get("parentOccurrenceId") or ""),
            "name": _text(occurrence.get("name") or occurrence_id, 160),
            "kind": _text(occurrence.get("kind") or "unknown", 40),
            "descendantPartCount": descendant_part_count(occurrence_id, set()),
        }
        if isinstance(occurrence.get("level"), int):
            record["level"] = occurrence["level"]
        item_id = _text(occurrence.get("itemId"), 120)
        if item_id:
            record["itemId"] = item_id
        records.append(record)
    return records, children.get(None, [])


def _compact_spatial_digest(
    process_map: Mapping[str, Any],
    revision: str,
) -> dict[str, Any]:
    """Compile bounded trusted spatial facts without exposing route geometry."""

    try:
        scene = compile_spatial_scene(process_map, revision=revision)
        diagnostics = diagnose_spatial_scene(scene)
    except SpatialGeometryError as exc:
        reason = (
            "spatial_limit_exceeded"
            if "spatial" in str(exc) and "limit" in str(exc)
            else "invalid_spatial_geometry"
        )
        return {
            "spatial_version": PROCESS_MAP_SPATIAL_VERSION,
            "status": "not_computed",
            "reason": reason,
            "node_count": len(process_map.get("canvasNodes") or []),
            "edge_count": len(process_map.get("canvasEdges") or []),
            "group_count": len(process_map.get("canvasGroups") or []),
        }

    metrics = diagnostics["metrics"]
    metric_names = {
        "nodeOverlaps": "node_overlaps",
        "nodeClearanceViolations": "node_clearance_violations",
        "minimumNodeClearance": "minimum_node_clearance",
        "nodeGroupHeaderIntersections": "node_group_header_intersections",
        "edgeNodeIntersections": "edge_node_intersections",
        "edgeGroupHeaderIntersections": "edge_group_header_intersections",
        "edgeCrossings": "edge_crossings",
        "backwardEdges": "backward_edges",
        "routeLength": "route_length",
        "routeBends": "route_bends",
        "routeDetourOpportunities": "route_detour_opportunities",
        "meanDetourRatio": "mean_detour_ratio",
        "alignmentDeviation": "alignment_deviation",
        "alignmentWarnings": "alignment_warnings",
        "denseRegions": "dense_regions",
        "openRegions": "open_regions",
    }
    always_include_metrics = {
        "nodeOverlaps",
        "edgeNodeIntersections",
        "edgeCrossings",
        "backwardEdges",
    }
    conditional_metrics = {
        "minimumNodeClearance": bool(
            metrics["nodeOverlaps"] or metrics["nodeClearanceViolations"]
        ),
        "routeLength": bool(metrics["routeDetourOpportunities"]),
        "routeBends": bool(metrics["routeDetourOpportunities"]),
        "meanDetourRatio": bool(metrics["routeDetourOpportunities"]),
        "alignmentDeviation": bool(metrics["alignmentWarnings"]),
    }
    compact_metrics = {
        target: metrics[source]
        for source, target in metric_names.items()
        if source in always_include_metrics
        or (source in conditional_metrics and conditional_metrics[source])
        or (
            source not in conditional_metrics
            and metrics[source] not in (0, 0.0, None)
        )
    }
    layout_policy = diagnostics["layoutPolicy"]
    regions = diagnostics["regions"]
    compact_policy: dict[str, Any] = {
        "flow_direction": layout_policy["flowDirection"],
    }
    if metrics["nodeClearanceViolations"]:
        compact_policy["node_clearance"] = layout_policy["nodeClearance"]
    if metrics["alignmentWarnings"]:
        compact_policy["grid_size"] = layout_policy["gridSize"]
    result: dict[str, Any] = {
        "spatial_version": diagnostics["spatialVersion"],
        "status": "computed",
        "layout_policy": compact_policy,
        "world_region_count": metrics["worldRegionCount"],
        "layout_metrics": compact_metrics,
        "problem_ids": [
            str(item.get("problemId") or "")
            for item in diagnostics["problems"]
            if item.get("problemId")
        ],
        "open_regions": [
            {
                "region_id": item["regionId"],
                "relative_location": item["relativeLocation"],
            }
            for item in regions
            if item["classification"] == "open"
        ],
        "dense_regions": [
            {
                "region_id": item["regionId"],
                "relative_location": item["relativeLocation"],
                "node_count": len(item["nodeIds"]),
            }
            for item in regions
            if item["classification"] == "dense"
        ],
    }
    if diagnostics["truncatedProblems"]:
        result["truncation"] = {
            "problem_ids": f"and {diagnostics['truncatedProblems']} more"
        }
    return result


def _fit_budget(digest: dict[str, Any], maximum_tokens: int) -> dict[str, Any]:
    result = copy.deepcopy(digest)
    truncation = result.setdefault("truncation", {})
    # Lower-priority records are trimmed first. The complete product catalog is
    # the authority for scopes that have not yet been placed on the canvas, so
    # it must outlive duplicated summaries such as typed edge lists.
    paths: list[tuple[int, dict[str, Any], str, str, int]] = []
    paths.append((5, result, "nodes", "nodes", 12))
    paths.append((3, result, "groups", "groups", 4))
    paths.append((5, result, "logical_connections", "logical_connections", 10))
    source_structure = result.get("product_structure")
    if isinstance(source_structure, dict):
        paths.append(
            (
                6,
                source_structure,
                "occurrences",
                "product_structure.occurrences",
                12,
            )
        )
    findings = result.get("validator_findings")
    if isinstance(findings, list):
        paths.append((2, result, "validator_findings", "validator_findings", 8))
    references = result.get("references")
    if isinstance(references, dict):
        paths.append((1, references, "nodes", "references.nodes", 4))
        paths.append((1, references, "edges", "references.edges", 4))
    typed = result.get("typed_edges")
    if isinstance(typed, dict):
        for kind in sorted(typed):
            paths.append((0, typed, kind, f"typed_edges.{kind}", 0))
    derived = result.get("derived")
    if isinstance(derived, dict):
        for key in (
            "entry_nodes",
            "terminal_nodes",
            "weakly_connected_regions",
            "parallel_branch_sets",
            "bottleneck_candidates",
            "precedence_cycles",
            "sequence_conflicts",
        ):
            if isinstance(derived.get(key), list):
                minimum = 8 if key in {"entry_nodes", "terminal_nodes"} else 2
                paths.append((4, derived, key, f"derived.{key}", minimum))
    spatial = result.get("spatial")
    if isinstance(spatial, dict):
        for key, minimum in (
            ("problem_ids", 4),
            ("open_regions", 2),
            ("dense_regions", 2),
        ):
            if isinstance(spatial.get(key), list):
                priority = 3 if key == "problem_ids" else 1
                paths.append((priority, spatial, key, f"spatial.{key}", minimum))

    result["estimated_tokens"] = 0
    while True:
        for _attempt in range(4):
            estimate = estimate_digest_tokens(result)
            if result["estimated_tokens"] == estimate:
                break
            result["estimated_tokens"] = estimate
        if estimate_digest_tokens(result) <= maximum_tokens:
            break
        candidate = min(
            (
                (priority, -len(container.get(key) or []), path, container, key, minimum)
                for priority, container, key, path, minimum in paths
                if isinstance(container.get(key), list)
                and len(container[key]) > minimum
            ),
            default=None,
            key=lambda item: (item[0], item[1], item[2]),
        )
        if candidate is None:
            raise ValueError("process-map digest cannot fit its configured token budget")
        _priority, _negative_length, path, container, key, _minimum = candidate
        container[key].pop()
        previous = truncation.get(path, "and 0 more")
        count = int(previous.split()[1]) + 1
        truncation[path] = f"and {count} more"
    if not truncation:
        result.pop("truncation", None)
    for _attempt in range(4):
        estimate = estimate_digest_tokens(result)
        if result["estimated_tokens"] == estimate:
            break
        result["estimated_tokens"] = estimate
    if estimate_digest_tokens(result) > maximum_tokens:
        raise ValueError("process-map digest exceeds its configured token budget")
    return result


def build_process_map_digest(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    *,
    revision: str,
    structure_revision: str,
    findings: Sequence[Mapping[str, Any]] = (),
    maximum_tokens: int = PROCESS_MAP_DIGEST_MAX_TOKENS,
) -> dict[str, Any]:
    """Compile a stable, bounded graph digest from trusted saved assets."""
    nodes = _sorted_records(process_map.get("canvasNodes"), "nodeId")
    edges = _sorted_records(process_map.get("canvasEdges"), "edgeId")
    groups = _sorted_records(process_map.get("canvasGroups"), "groupId")
    occurrences = {
        str(item.get("occurrenceId")): item
        for item in product_structure.get("occurrences") or []
        if isinstance(item, Mapping) and item.get("occurrenceId")
    }
    group_by_node: dict[str, str] = {}
    for group in groups:
        for node_id in group.get("memberNodeIds") or []:
            group_by_node[str(node_id)] = str(group.get("groupId") or "")
    catalog = {
        str(item.get("referenceId")): item
        for item in process_map.get("referenceCatalog") or []
        if isinstance(item, Mapping) and item.get("referenceId")
    }
    junction_ids = {
        str(node.get("nodeId"))
        for node in nodes
        if node.get("nodeKind") == "junction" and node.get("nodeId")
    }
    source_occurrences, source_roots = _source_occurrence_records(occurrences)

    node_records: list[dict[str, Any]] = []
    suggested_orders: dict[str, float] = {}
    for node in nodes:
        node_id = str(node.get("nodeId") or "")
        occurrence_id = str(node.get("sourceOccurrenceId") or "")
        occurrence = occurrences.get(occurrence_id)
        record: dict[str, Any] = {
            "id": node_id,
            "kind": str(node.get("nodeKind") or "unknown"),
            "name": _node_name(node, occurrence),
        }
        if node.get("nodeKind") == "process_step":
            record["processType"] = str(node.get("processType") or "operation")
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                compact_properties = {
                    str(key): str(value)
                    for key, value in sorted(properties.items())
                    if isinstance(value, str) and value.strip()
                }
                if compact_properties:
                    record["properties"] = compact_properties
        elif node.get("nodeKind") == "product_occurrence":
            record["occurrenceId"] = occurrence_id
            if occurrence and occurrence.get("kind"):
                record["productKind"] = str(occurrence.get("kind"))
            order = (occurrence or {}).get("suggestedBuildOrder")
            if isinstance(order, (int, float)) and not isinstance(order, bool):
                record["suggestedBuildOrder"] = order
                suggested_orders[node_id] = float(order)
        elif node.get("nodeKind") == "junction":
            record["junctionType"] = str(node.get("junctionType") or "wire_branch")
        if group_by_node.get(node_id):
            record["groupId"] = group_by_node[node_id]
        references = _references_for_target(node, catalog)
        if references:
            record["references"] = references
        node_records.append(record)

    pairs = _collapsed_precedence_pairs(nodes, edges)
    authored_ids = sorted(
        str(node.get("nodeId"))
        for node in nodes
        if node.get("nodeKind") != "junction" and node.get("nodeId")
    )
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in authored_ids}
    incoming: dict[str, set[str]] = {node_id: set() for node_id in authored_ids}
    for source, target in pairs:
        adjacency.setdefault(source, set()).add(target)
        incoming.setdefault(target, set()).add(source)
    entry_nodes = sorted(node_id for node_id in authored_ids if not incoming.get(node_id))
    terminal_nodes = sorted(node_id for node_id in authored_ids if not adjacency.get(node_id))
    sequence_conflicts = [
        {
            "from": source,
            "to": target,
            "fromOrder": suggested_orders[source],
            "toOrder": suggested_orders[target],
        }
        for source, target in pairs
        if source in suggested_orders
        and target in suggested_orders
        and suggested_orders[source] > suggested_orders[target]
    ]
    bottlenecks = [
        {"nodeId": node_id, "fanIn": len(incoming.get(node_id, set()))}
        for node_id in authored_ids
        if len(incoming.get(node_id, set())) >= 3
    ]

    truncation: dict[str, str] = {}
    typed_edges: dict[str, list[dict[str, Any]]] = {}
    for kind in sorted({str(edge.get("kind") or "precedence") for edge in edges}):
        values = []
        for edge in edges:
            if str(edge.get("kind") or "precedence") != kind:
                continue
            source, target = _edge_nodes(edge)
            values.append(
                {
                    "id": str(edge.get("edgeId") or ""),
                    "from": source,
                    "to": target,
                    "logicalConnectionId": str(
                        edge.get("logicalConnectionId") or edge.get("edgeId") or ""
                    ),
                }
            )
        typed_edges[kind] = _bounded_list(values, 160, f"typed_edges.{kind}", truncation)

    node_reference_records = [
        {"targetId": record["id"], "items": record["references"]}
        for record in node_records
        if record.get("references")
    ]
    edge_reference_records = []
    for edge in edges:
        references = _references_for_target(edge, catalog)
        if references:
            edge_reference_records.append(
                {"targetId": str(edge.get("edgeId") or ""), "items": references}
            )

    digest: dict[str, Any] = {
        "digest_version": PROCESS_MAP_DIGEST_VERSION,
        "identity": {
            "mapId": str(process_map.get("mapId") or ""),
            "displayName": _text(process_map.get("displayName") or "Process Map", 160),
            "productId": str(process_map.get("productId") or ""),
            "revision": revision,
            "structureRevision": structure_revision,
        },
        "nodes": _bounded_list(node_records, 160, "nodes", truncation),
        "product_structure": {
            "rootOccurrenceIds": source_roots,
            "occurrenceCount": len(source_occurrences),
            "partOccurrenceCount": sum(
                1 for item in source_occurrences if item.get("kind") == "part"
            ),
            "occurrences": _bounded_list(
                source_occurrences,
                240,
                "product_structure.occurrences",
                truncation,
            ),
        },
        "groups": [
            {
                "groupId": str(group.get("groupId") or ""),
                "label": _text(group.get("label"), 160),
                "memberCount": len(group.get("memberNodeIds") or []),
            }
            for group in groups
        ],
        "logical_connections": _bounded_list(
            _logical_connections(edges, junction_ids, catalog),
            160,
            "logical_connections",
            truncation,
        ),
        "junction_count": len(junction_ids),
        "typed_edges": typed_edges,
        "references": {
            "nodes": _bounded_list(node_reference_records, 120, "references.nodes", truncation),
            "edges": _bounded_list(edge_reference_records, 120, "references.edges", truncation),
        },
        "validator_findings": _bounded_list(
            [
                {
                    key: item[key]
                    for key in (
                        "severity",
                        "code",
                        "message",
                        "nodeId",
                        "edgeId",
                        "groupId",
                    )
                    if key in item
                }
                for item in sorted(
                    [item for item in findings if isinstance(item, Mapping)],
                    key=lambda item: (
                        str(item.get("severity") or ""),
                        str(item.get("code") or ""),
                        str(item.get("nodeId") or item.get("edgeId") or item.get("groupId") or ""),
                    ),
                )
            ],
            100,
            "validator_findings",
            truncation,
        ),
        "derived": {
            "entry_nodes": entry_nodes,
            "terminal_nodes": terminal_nodes,
            "weakly_connected_regions": _weak_regions(authored_ids, pairs),
            "bottleneck_candidates": bottlenecks,
            "parallel_branch_sets": _parallel_branches(adjacency),
            "precedence_cycles": _cycles(adjacency),
            "sequence_conflicts": sequence_conflicts,
        },
        "spatial": _compact_spatial_digest(process_map, revision),
    }
    if truncation:
        digest["truncation"] = truncation
    return _fit_budget(digest, maximum_tokens)


def normalize_process_map_reference(value: Any) -> dict[str, str] | None:
    """Accept identity fields only; all browser-supplied graph data is ignored."""
    if not isinstance(value, Mapping):
        return None
    product_id = _text(value.get("productId") or value.get("product_id"), 96)
    map_id = _text(value.get("mapId") or value.get("map_id"), 63)
    revision = _text(value.get("revision"), 128)
    if not product_id or not map_id or not revision:
        return None
    return {"productId": product_id, "mapId": map_id, "revision": revision}


def resolve_process_map_digest(
    training_root: Path,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Load a named map at an exact revision and compile its trusted digest."""
    normalized = normalize_process_map_reference(reference)
    if normalized is None:
        raise ValueError("process map reference requires productId, mapId, and revision")
    loaded = load_named_process_map(
        training_root,
        normalized["productId"],
        normalized["mapId"],
    )
    if normalized["revision"] != loaded["revision"]:
        raise ProcessMapConflictError(loaded["revision"])
    graph = build_process_map_digest(
        loaded["map"],
        loaded["productStructure"],
        revision=loaded["revision"],
        structure_revision=loaded["structureRevision"],
        findings=[*(loaded.get("findings") or []), *(loaded.get("registryFindings") or [])],
    )
    return {
        "reference": normalized,
        "graph": graph,
        "revision": loaded["revision"],
        "structureRevision": loaded["structureRevision"],
    }
