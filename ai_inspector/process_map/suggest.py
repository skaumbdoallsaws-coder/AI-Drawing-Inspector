"""Deterministic, evidence-backed process-map connection suggestions."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from itertools import combinations
from typing import Any, Iterable, Mapping


PROCESS_MAP_SUGGESTION_SCHEMA_VERSION = 1
PROCESS_MAP_SUGGESTION_LIMIT = 20
_MAX_LIMIT = 100
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
_RULES = {
    "sibling_sequence": "1.0.0",
    "inspection_after_operation": "1.0.0",
    "resource_contention": "1.0.0",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("ascii")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _endpoint(edge: Mapping[str, Any], key: str) -> str:
    value = edge.get(key)
    return _clean_id(value.get("nodeId")) if isinstance(value, Mapping) else ""


def _evidence_row(
    source: str,
    rule_id: str,
    *,
    detail: str,
    ids: Iterable[str],
) -> dict[str, Any]:
    return {
        "source": source,
        "ruleId": rule_id,
        "ruleVersion": _RULES[rule_id],
        "detail": detail,
        "ids": sorted({_clean_id(value) for value in ids if _clean_id(value)}),
    }


def _suggestion_id(
    rule_id: str,
    evidence: list[dict[str, Any]],
    from_id: str,
    to_id: str,
    edge_kind: str,
) -> tuple[str, str]:
    evidence_fingerprint = _sha256(evidence)
    identity = {
        "ruleId": rule_id,
        "ruleVersion": _RULES[rule_id],
        "evidenceFingerprint": evidence_fingerprint,
        "fromId": from_id,
        "toId": to_id,
        "edgeKind": edge_kind,
    }
    return "pms-" + _sha256(identity), evidence_fingerprint


def _logical_pairs(
    edges: list[Mapping[str, Any]],
    junction_ids: set[str],
) -> tuple[set[tuple[str, str, str]], dict[tuple[str, str, str], list[str]]]:
    pairs: set[tuple[str, str, str]] = set()
    evidence: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in edges:
        from_id = _endpoint(edge, "from")
        to_id = _endpoint(edge, "to")
        kind = _clean_id(edge.get("kind")) or "precedence"
        if not from_id or not to_id:
            continue
        pair = (from_id, to_id, kind)
        pairs.add(pair)
        edge_id = _clean_id(edge.get("edgeId"))
        if edge_id:
            evidence[pair].append(edge_id)
        logical_id = _clean_id(edge.get("logicalConnectionId")) or edge_id
        if logical_id:
            grouped[logical_id].append(edge)

    for logical_id, segments in grouped.items():
        from_ids = {_endpoint(edge, "from") for edge in segments}
        to_ids = {_endpoint(edge, "to") for edge in segments}
        sources = sorted((from_ids - to_ids) - junction_ids)
        targets = sorted((to_ids - from_ids) - junction_ids)
        kinds = {_clean_id(edge.get("kind")) or "precedence" for edge in segments}
        if len(sources) != 1 or len(targets) != 1 or len(kinds) != 1:
            continue
        pair = (sources[0], targets[0], next(iter(kinds)))
        pairs.add(pair)
        evidence[pair].append(logical_id)
    for values in evidence.values():
        values[:] = sorted(set(values))
    return pairs, evidence


def _precedence_adjacency(
    node_ids: Iterable[str], edges: Iterable[Mapping[str, Any]]
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if (_clean_id(edge.get("kind")) or "precedence") != "precedence":
            continue
        from_id = _endpoint(edge, "from")
        to_id = _endpoint(edge, "to")
        if from_id in adjacency and to_id in adjacency:
            adjacency[from_id].add(to_id)
    return adjacency


def _would_create_cycle(
    adjacency: Mapping[str, set[str]], from_id: str, to_id: str
) -> bool:
    if from_id == to_id:
        return True
    pending = [to_id]
    reached: set[str] = set()
    while pending:
        current = pending.pop()
        if current == from_id:
            return True
        if current in reached:
            continue
        reached.add(current)
        pending.extend(sorted(adjacency.get(current, set()), reverse=True))
    return False


def _functional_pairs(
    functional_graph: Mapping[str, Any] | None,
) -> dict[frozenset[str], list[str]]:
    pairs: dict[frozenset[str], list[str]] = defaultdict(list)
    if not isinstance(functional_graph, Mapping):
        return pairs
    for interface in functional_graph.get("interfaces") or []:
        if not isinstance(interface, Mapping):
            continue
        part_numbers = sorted({
            _clean_id(participant.get("part_number"))
            for participant in (interface.get("participants") or [])
            if isinstance(participant, Mapping)
            and _clean_id(participant.get("part_number"))
        })
        interface_id = _clean_id(interface.get("interface_id"))
        if len(part_numbers) < 2 or not interface_id:
            continue
        for left, right in combinations(part_numbers, 2):
            pairs[frozenset((left, right))].append(interface_id)
    return {key: sorted(set(value)) for key, value in pairs.items()}


def _occurrence_part_ids(occurrence: Mapping[str, Any]) -> set[str]:
    values = occurrence.get("partIds")
    part_ids = {
        _clean_id(value) for value in values or [] if _clean_id(value)
    } if isinstance(values, list) else set()
    item_id = _clean_id(occurrence.get("itemId"))
    if item_id:
        part_ids.add(item_id)
    return part_ids


def _pair_functional_evidence(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    functional_pairs: Mapping[frozenset[str], list[str]],
) -> list[str]:
    interface_ids: set[str] = set()
    for left_part in _occurrence_part_ids(left):
        for right_part in _occurrence_part_ids(right):
            interface_ids.update(
                functional_pairs.get(frozenset((left_part, right_part)), [])
            )
    return sorted(interface_ids)


def _subject_occurrence_ids(node: Mapping[str, Any]) -> list[str]:
    values = node.get("subjectOccurrenceIds")
    result = {
        _clean_id(value) for value in values or [] if _clean_id(value)
    } if isinstance(values, list) else set()
    for key in ("subjectOccurrenceId", "targetOccurrenceId", "sourceOccurrenceId"):
        value = _clean_id(node.get(key))
        if value:
            result.add(value)
    return sorted(result)


def _edge_suggestion(
    *,
    rule_id: str,
    from_id: str,
    to_id: str,
    confidence: str,
    provenance: list[dict[str, Any]],
    explanation: str,
    adjacency: Mapping[str, set[str]],
    affected_ids: Iterable[str],
) -> dict[str, Any]:
    suggestion_id, evidence_fingerprint = _suggestion_id(
        rule_id, provenance, from_id, to_id, "precedence"
    )
    edge_id = "pm-e-suggest-" + suggestion_id[4:20]
    return {
        "suggestionId": suggestion_id,
        "ruleId": rule_id,
        "ruleVersion": _RULES[rule_id],
        "evidenceFingerprint": evidence_fingerprint,
        "edge": {
            "edgeId": edge_id,
            "from": {"nodeId": from_id, "port": "out"},
            "to": {"nodeId": to_id, "port": "in"},
            "kind": "precedence",
            "logicalConnectionId": edge_id,
        },
        "confidence": confidence,
        "provenance": provenance,
        "explanation": explanation,
        "validation": {
            "wouldCreateCycle": _would_create_cycle(adjacency, from_id, to_id),
            "duplicateOfExisting": False,
        },
        "affectedIds": sorted(set(affected_ids)),
    }


def _annotation_suggestion(
    *,
    reference: Mapping[str, Any],
    affected_ids: list[str],
) -> dict[str, Any]:
    rule_id = "resource_contention"
    reference_id = _clean_id(reference.get("referenceId"))
    provenance = [
        _evidence_row(
            "process_reference",
            rule_id,
            detail=(
                f"{reference.get('kind')} '{reference.get('name')}' is assigned to "
                f"{len(affected_ids)} process targets."
            ),
            ids=[reference_id, *affected_ids],
        )
    ]
    suggestion_id, evidence_fingerprint = _suggestion_id(
        rule_id,
        provenance,
        affected_ids[0],
        affected_ids[-1],
        "annotation:resource_contention",
    )
    return {
        "suggestionId": suggestion_id,
        "ruleId": rule_id,
        "ruleVersion": _RULES[rule_id],
        "evidenceFingerprint": evidence_fingerprint,
        "annotation": {
            "kind": "resource_contention",
            "referenceId": reference_id,
        },
        "confidence": "medium",
        "provenance": provenance,
        "explanation": (
            f"{reference.get('name')} is shared by {len(affected_ids)} process targets; "
            "review resource availability before treating the paths as parallel."
        ),
        "validation": {
            "wouldCreateCycle": False,
            "duplicateOfExisting": False,
        },
        "affectedIds": affected_ids,
    }


def suggest_process_map_connections(
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    *,
    functional_graph: Mapping[str, Any] | None = None,
    limit: int = PROCESS_MAP_SUGGESTION_LIMIT,
) -> dict[str, Any]:
    """Return deterministic suggestions without mutating the supplied map."""
    if not isinstance(process_map, Mapping):
        raise ValueError("process_map must be an object")
    if not isinstance(product_structure, Mapping):
        raise ValueError("product_structure must be an object")
    safe_limit = max(1, min(_MAX_LIMIT, int(limit)))
    nodes = [
        node for node in (process_map.get("canvasNodes") or [])
        if isinstance(node, Mapping) and _clean_id(node.get("nodeId"))
    ]
    edges = [
        edge for edge in (process_map.get("canvasEdges") or [])
        if isinstance(edge, Mapping)
    ]
    node_by_id = {_clean_id(node.get("nodeId")): node for node in nodes}
    junction_ids = {
        node_id for node_id, node in node_by_id.items()
        if node.get("nodeKind") == "junction"
    }
    existing_pairs, pair_evidence = _logical_pairs(edges, junction_ids)
    adjacency = _precedence_adjacency(node_by_id, edges)
    occurrences = {
        _clean_id(item.get("occurrenceId")): item
        for item in (product_structure.get("occurrences") or [])
        if isinstance(item, Mapping) and _clean_id(item.get("occurrenceId"))
    }
    placed_occurrences: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for node_id, node in node_by_id.items():
        if node.get("nodeKind") != "product_occurrence":
            continue
        occurrence = occurrences.get(_clean_id(node.get("sourceOccurrenceId")))
        if occurrence is not None:
            placed_occurrences[node_id] = (node, occurrence)

    dismissed = {
        _clean_id(value)
        for value in (process_map.get("dismissedSuggestions") or [])
        if _clean_id(value)
    }
    candidates: list[dict[str, Any]] = []
    suppressed_duplicates = 0
    suppressed_dismissed = 0
    functional_pairs = _functional_pairs(functional_graph)

    siblings: dict[str, list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for node_id, (_node, occurrence) in placed_occurrences.items():
        parent_id = _clean_id(occurrence.get("parentOccurrenceId"))
        order = _finite_number(occurrence.get("suggestedBuildOrder"))
        if parent_id and order is not None:
            siblings[parent_id].append((node_id, occurrence))

    authored_by_parent: dict[str, list[str]] = defaultdict(list)
    for pair, evidence_ids in pair_evidence.items():
        from_id, to_id, kind = pair
        if kind != "precedence" or from_id not in placed_occurrences or to_id not in placed_occurrences:
            continue
        left = placed_occurrences[from_id][1]
        right = placed_occurrences[to_id][1]
        parent_id = _clean_id(left.get("parentOccurrenceId"))
        if not parent_id or parent_id != _clean_id(right.get("parentOccurrenceId")):
            continue
        left_order = _finite_number(left.get("suggestedBuildOrder"))
        right_order = _finite_number(right.get("suggestedBuildOrder"))
        if left_order is not None and right_order is not None and left_order < right_order:
            authored_by_parent[parent_id].extend(evidence_ids)

    for parent_id in sorted(siblings):
        ordered = sorted(
            siblings[parent_id],
            key=lambda item: (
                _finite_number(item[1].get("suggestedBuildOrder")) or 0.0,
                item[0],
            ),
        )
        for (from_id, left), (to_id, right) in zip(ordered, ordered[1:]):
            left_order = _finite_number(left.get("suggestedBuildOrder"))
            right_order = _finite_number(right.get("suggestedBuildOrder"))
            if left_order is None or right_order is None or left_order >= right_order:
                continue
            pair = (from_id, to_id, "precedence")
            if pair in existing_pairs:
                suppressed_duplicates += 1
                continue
            authored_ids = sorted(set(authored_by_parent.get(parent_id, [])))
            interface_ids = _pair_functional_evidence(
                left, right, functional_pairs
            )
            if not authored_ids and not interface_ids:
                continue
            rule_id = "sibling_sequence"
            provenance = [
                _evidence_row(
                    "product_containment",
                    rule_id,
                    detail=f"Both placed occurrences belong to parent '{parent_id}'.",
                    ids=[parent_id, left.get("occurrenceId"), right.get("occurrenceId")],
                ),
                _evidence_row(
                    "suggested_build_order",
                    rule_id,
                    detail=(
                        f"Suggested build order is {left.get('suggestedBuildOrder')} before "
                        f"{right.get('suggestedBuildOrder')}."
                    ),
                    ids=[left.get("occurrenceId"), right.get("occurrenceId")],
                ),
            ]
            if authored_ids:
                provenance.append(
                    _evidence_row(
                        "authored_precedence_pattern",
                        rule_id,
                        detail="The saved map already uses ascending sibling build order.",
                        ids=authored_ids,
                    )
                )
            if interface_ids:
                provenance.append(
                    _evidence_row(
                        "functional_relationship",
                        rule_id,
                        detail="Reviewed product evidence relates the two occurrences.",
                        ids=interface_ids,
                    )
                )
            candidate = _edge_suggestion(
                rule_id=rule_id,
                from_id=from_id,
                to_id=to_id,
                confidence="high" if authored_ids and interface_ids else "medium",
                provenance=provenance,
                explanation=(
                    f"Continue the authored sibling sequence from '{left.get('name')}' "
                    f"to '{right.get('name')}'."
                ),
                adjacency=adjacency,
                affected_ids=[from_id, to_id],
            )
            if candidate["suggestionId"] in dismissed:
                suppressed_dismissed += 1
            else:
                candidates.append(candidate)

    steps_by_subject: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for node_id, node in node_by_id.items():
        if node.get("nodeKind") != "process_step":
            continue
        process_type = _clean_id(node.get("processType"))
        if process_type not in {"operation", "inspection"}:
            continue
        for subject_id in _subject_occurrence_ids(node):
            steps_by_subject[subject_id][process_type].append(node_id)
    for subject_id in sorted(steps_by_subject):
        operation_ids = sorted(steps_by_subject[subject_id]["operation"])
        inspection_ids = sorted(steps_by_subject[subject_id]["inspection"])
        for from_id in operation_ids:
            for to_id in inspection_ids:
                pair = (from_id, to_id, "precedence")
                if pair in existing_pairs:
                    suppressed_duplicates += 1
                    continue
                rule_id = "inspection_after_operation"
                provenance = [
                    _evidence_row(
                        "process_step_compatibility",
                        rule_id,
                        detail="An inspection follows an operation for the same explicit subject.",
                        ids=[from_id, to_id],
                    ),
                    _evidence_row(
                        "subject_occurrence",
                        rule_id,
                        detail=f"Both steps explicitly reference occurrence '{subject_id}'.",
                        ids=[subject_id],
                    ),
                ]
                candidate = _edge_suggestion(
                    rule_id=rule_id,
                    from_id=from_id,
                    to_id=to_id,
                    confidence="high",
                    provenance=provenance,
                    explanation="Connect the operation to its inspection for the same product occurrence.",
                    adjacency=adjacency,
                    affected_ids=[from_id, to_id, subject_id],
                )
                if candidate["suggestionId"] in dismissed:
                    suppressed_dismissed += 1
                else:
                    candidates.append(candidate)

    catalog = {
        _clean_id(item.get("referenceId")): item
        for item in (process_map.get("referenceCatalog") or [])
        if isinstance(item, Mapping) and _clean_id(item.get("referenceId"))
    }
    reference_targets: dict[str, set[str]] = defaultdict(set)
    for node_id, node in node_by_id.items():
        if node.get("nodeKind") == "junction":
            continue
        for reference_id in node.get("referenceIds") or []:
            if _clean_id(reference_id):
                reference_targets[_clean_id(reference_id)].add(node_id)
    for edge in edges:
        target_id = _clean_id(edge.get("logicalConnectionId")) or _clean_id(edge.get("edgeId"))
        for reference_id in edge.get("referenceIds") or []:
            if target_id and _clean_id(reference_id):
                reference_targets[_clean_id(reference_id)].add(target_id)
    for reference_id in sorted(reference_targets):
        reference = catalog.get(reference_id)
        targets = sorted(reference_targets[reference_id])
        if (
            not isinstance(reference, Mapping)
            or reference.get("kind") not in {"machine", "tool"}
            or len(targets) < 2
        ):
            continue
        candidate = _annotation_suggestion(
            reference=reference,
            affected_ids=targets,
        )
        if candidate["suggestionId"] in dismissed:
            suppressed_dismissed += 1
        else:
            candidates.append(candidate)

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique.setdefault(candidate["suggestionId"], candidate)
    ranked = sorted(
        unique.values(),
        key=lambda item: (
            bool(item.get("validation", {}).get("wouldCreateCycle")),
            _CONFIDENCE_RANK.get(str(item.get("confidence")), 9),
            0 if "edge" in item else 1,
            item["suggestionId"],
        ),
    )
    returned = ranked[:safe_limit]
    return {
        "schemaVersion": PROCESS_MAP_SUGGESTION_SCHEMA_VERSION,
        "engineVersion": "1.0.0",
        "suggestions": returned,
        "summary": {
            "returned": len(returned),
            "edgeSuggestions": sum(1 for item in returned if "edge" in item),
            "annotations": sum(1 for item in returned if "annotation" in item),
            "cycleWarnings": sum(
                1
                for item in returned
                if item.get("validation", {}).get("wouldCreateCycle")
            ),
            "suppressedDuplicates": suppressed_duplicates,
            "suppressedDismissed": suppressed_dismissed,
            "truncated": max(0, len(ranked) - len(returned)),
        },
    }
