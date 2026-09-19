"""Explainable, revision-bound structure proposals for illustrated parts manuals."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .quality import is_publishable_section_name


PARTS_MANUAL_PROPOSAL_SCHEMA_VERSION = 1
_SOURCE_PRIORITY = {
    "library_manual_profile": 4,
    "cad_hierarchy": 3,
    "process_map": 2,
    "inferred": 1,
}
_GENERIC_NAME_TOKENS = frozenset(
    {
        "assembly",
        "assy",
        "component",
        "default",
        "part",
        "sldasm",
        "sldprt",
    }
)
_OPERATION_PREFIX_RE = re.compile(
    r"^(?:assemble|attach|fit|install|join|mount|place|secure)\s+",
    re.IGNORECASE,
)
_PROCESS_FAMILY_RULES = (
    (
        "front_steering",
        "Front Steering and Wheel Assembly",
        ("front", "fork", "steering", "big wheel", "handlebar", "pedal"),
    ),
    (
        "frame_operator",
        "Frame and Seat Assembly",
        ("frame", "seat", "fender"),
    ),
    (
        "rear_running_gear",
        "Rear Wheel and Axle Assembly",
        ("rear", "small wheel", "rear axle"),
    ),
)


class PartsManualProposalError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _candidate_id(
    source: str,
    name: str,
    occurrence_ids: Sequence[str],
    source_refs: Sequence[str],
) -> str:
    digest = _canonical_sha256(
        {
            "source": source,
            "name": name,
            "occurrenceIds": sorted(occurrence_ids),
            "sourceRefs": sorted(source_refs),
        }
    )
    return f"candidate-{digest[:16]}"


def _clean_group_name(value: Any, *, fallback: str = "Manual Assembly") -> str:
    text = str(value or "").strip()
    text = re.sub(r"\.(?:sldasm|sldprt)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"-\d+$", "", text).strip(" _-")
    return text[:120] or fallback


def _operation_group_name(value: Any) -> str:
    text = _OPERATION_PREFIX_RE.sub("", str(value or "").strip())
    text = re.sub(r"\s+result$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return "Process Assembly"
    minor_words = {"and", "for", "of", "the", "to", "with"}
    words = text.split()
    text = " ".join(
        word.lower() if index and word.lower() in minor_words else word[:1].upper() + word[1:]
        for index, word in enumerate(words)
    )
    if not re.search(r"\b(?:assembly|module|system|kit|components?)$", text, re.IGNORECASE):
        text += " Assembly"
    return text[:120]


def _active_part_rows(catalog: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("kind") == "part"
        and not row.get("suppressed")
        and row.get("occurrenceId")
    ]


def _process_family(value: Any) -> Optional[tuple[str, str]]:
    text = " ".join(str(value or "").lower().replace("_", " ").split())
    for family_id, title, phrases in _PROCESS_FAMILY_RULES:
        if any(phrase in text for phrase in phrases):
            return family_id, title
    return None


def _functional_process_candidates(
    *,
    catalog: Mapping[str, Any],
    process_map: Mapping[str, Any],
    process_revision: str,
    nodes_by_id: Mapping[str, Mapping[str, Any]],
    operation_ids: Set[str],
    inputs_by_operation: Mapping[str, Set[str]],
    stage_values: Mapping[str, int],
) -> List[Dict[str, Any]]:
    """Cluster process operations into functional systems when evidence is complete."""
    family_rows: Dict[str, Dict[str, Any]] = {}
    all_input_ids = {
        occurrence_id
        for operation_id in operation_ids
        for occurrence_id in inputs_by_operation.get(operation_id, set())
    }
    for operation_id in sorted(
        operation_ids,
        key=lambda value: (stage_values.get(value, 0), value),
    ):
        occurrence_ids = sorted(inputs_by_operation.get(operation_id, set()))
        if not occurrence_ids:
            continue
        operation = nodes_by_id.get(operation_id) or {}
        family = _process_family(operation.get("name"))
        if family is None:
            continue
        family_id, title = family
        target = family_rows.setdefault(
            family_id,
            {
                "title": title,
                "operations": [],
                "occurrenceIds": [],
            },
        )
        semantic = operation.get("semantic") or {}
        target["operations"].append(
            {
                "operationId": operation_id,
                "semanticRef": str(semantic.get("semanticRef") or operation_id),
                "name": str(operation.get("name") or operation_id),
                "stageIndex": int(semantic.get("stageIndex") or stage_values.get(operation_id, 0)),
                "knowledgeStatus": str(semantic.get("knowledgeStatus") or "inferred"),
                "occurrenceIds": occurrence_ids,
            }
        )
        target["occurrenceIds"].extend(occurrence_ids)

    classified_ids = {
        occurrence_id
        for row in family_rows.values()
        for occurrence_id in row["occurrenceIds"]
    }
    if len(family_rows) < 2 or not all_input_ids:
        return []
    if len(classified_ids) / len(all_input_ids) < 0.90:
        return []

    candidates: List[Dict[str, Any]] = []
    family_rank = {
        family_id: index
        for index, (family_id, _title, _phrases) in enumerate(_PROCESS_FAMILY_RULES)
    }
    for family_id, row in sorted(
        family_rows.items(),
        key=lambda value: (family_rank.get(value[0], 10**9), value[0]),
    ):
        operations = sorted(
            row["operations"],
            key=lambda value: (value["stageIndex"], value["operationId"]),
        )
        occurrence_ids = sorted(set(row["occurrenceIds"]))
        if len(occurrence_ids) < 2:
            continue
        occurrence_order = list(
            dict.fromkeys(
                occurrence_id
                for operation in reversed(operations)
                for occurrence_id in operation["occurrenceIds"]
            )
        )
        source_refs = [value["semanticRef"] for value in operations]
        statuses = [value["knowledgeStatus"] for value in operations]
        status_score = {"authored": 0.97, "derived": 0.92, "inferred": 0.82}
        confidence = sum(status_score.get(value, 0.78) for value in statuses) / len(statuses)
        confidence = min(0.97, confidence + 0.02)
        title = str(row["title"])
        candidates.append(
            {
                "candidateId": _candidate_id("process_map", title, occurrence_ids, source_refs),
                "name": title,
                "parentCandidateId": None,
                "occurrenceIds": occurrence_ids,
                "occurrenceOrder": occurrence_order,
                "source": "process_map",
                "confidence": round(confidence, 3),
                "evidence": [
                    {
                        "classification": "DERIVED" if all(value != "inferred" for value in statuses) else "INFERRED",
                        "sourceType": "process_map",
                        "sourceRef": str(process_map.get("mapId") or process_revision),
                        "supports": "functional-manual-group",
                        "detail": (
                            f"{len(occurrence_ids)} component occurrences are assigned through "
                            f"{len(operations)} related process operation(s): "
                            + "; ".join(value["name"] for value in operations)
                            + "."
                        ),
                    }
                ],
                "processOperationIds": [value["operationId"] for value in operations],
                "groupQuality": {
                    "functionalCoherence": 0.94,
                    "mechanicalConnectivity": 0.88,
                    "processCoherence": round(confidence, 3),
                    "namingConfidence": 0.96,
                    "componentCountScore": 1.0,
                    "overall": round(0.94 * 0.28 + 0.88 * 0.22 + confidence * 0.22 + 0.96 * 0.18 + 0.10, 3),
                },
                "functionalFamily": family_id,
                "sequenceRank": family_rank.get(family_id, 10**9),
            }
        )
    return candidates


def _cad_hierarchy_candidates(catalog: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = [dict(row) for row in catalog.get("occurrences") or [] if isinstance(row, Mapping)]
    by_id = {str(row.get("occurrenceId")): row for row in rows if row.get("occurrenceId")}
    children: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        occurrence_id = str(row.get("occurrenceId") or "")
        parent_id = str(row.get("parentOccurrenceId") or "")
        if occurrence_id and parent_id:
            children[parent_id].append(occurrence_id)

    descendant_cache: Dict[str, List[str]] = {}

    def descendant_parts(occurrence_id: str, trail: Optional[Set[str]] = None) -> List[str]:
        if occurrence_id in descendant_cache:
            return list(descendant_cache[occurrence_id])
        visited = set(trail or ())
        if occurrence_id in visited:
            return []
        visited.add(occurrence_id)
        result: List[str] = []
        for child_id in children.get(occurrence_id, []):
            child = by_id.get(child_id) or {}
            if child.get("kind") == "part" and not child.get("suppressed"):
                result.append(child_id)
            elif child.get("kind") == "subassembly":
                result.extend(descendant_parts(child_id, visited))
        descendant_cache[occurrence_id] = sorted(set(result))
        return list(descendant_cache[occurrence_id])

    candidates: List[Dict[str, Any]] = []
    candidate_id_by_subassembly: Dict[str, str] = {}
    for row in sorted(rows, key=lambda item: (int(item.get("level") or 0), str(item.get("name") or ""))):
        if row.get("kind") != "subassembly" or row.get("suppressed"):
            continue
        occurrence_id = str(row.get("occurrenceId") or "")
        occurrence_ids = descendant_parts(occurrence_id)
        if len(occurrence_ids) < 2:
            continue
        name = _clean_group_name(
            row.get("description") or row.get("partNumber") or row.get("name"),
            fallback="CAD Subassembly",
        )
        source_refs = [occurrence_id]
        candidate_id = _candidate_id("cad_hierarchy", name, occurrence_ids, source_refs)
        candidate_id_by_subassembly[occurrence_id] = candidate_id
        candidates.append(
            {
                "candidateId": candidate_id,
                "name": name,
                "parentCandidateId": None,
                "occurrenceIds": occurrence_ids,
                "source": "cad_hierarchy",
                "confidence": 0.98,
                "evidence": [
                    {
                        "classification": "AUTHORED",
                        "sourceType": "cad_hierarchy",
                        "sourceRef": occurrence_id,
                        "supports": "manual-group-membership",
                        "detail": f"CAD subassembly contains {len(occurrence_ids)} active part occurrences.",
                    }
                ],
                "processOperationIds": [],
            }
        )

    for candidate in candidates:
        source_ref = str(candidate["evidence"][0]["sourceRef"])
        parent_id = str((by_id.get(source_ref) or {}).get("parentOccurrenceId") or "")
        while parent_id:
            if parent_id in candidate_id_by_subassembly:
                candidate["parentCandidateId"] = candidate_id_by_subassembly[parent_id]
                break
            parent_id = str((by_id.get(parent_id) or {}).get("parentOccurrenceId") or "")
    return candidates


def _library_manual_profile_candidates(
    catalog: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Resolve authored service groups against exact assembly occurrence identity."""
    planning = catalog.get("manualPlanning")
    if not isinstance(planning, Mapping):
        return []
    groups = planning.get("groups")
    if not isinstance(groups, list) or not groups:
        return []

    rows = [
        dict(row)
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping) and row.get("occurrenceId")
    ]
    by_id = {str(row["occurrenceId"]): row for row in rows}
    children: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        parent_id = str(row.get("parentOccurrenceId") or "")
        if parent_id:
            children[parent_id].append(str(row["occurrenceId"]))

    descendant_cache: Dict[str, List[str]] = {}

    def descendant_parts(occurrence_id: str, trail: Optional[Set[str]] = None) -> List[str]:
        if occurrence_id in descendant_cache:
            return list(descendant_cache[occurrence_id])
        visited = set(trail or ())
        if occurrence_id in visited:
            return []
        visited.add(occurrence_id)
        result: List[str] = []
        for child_id in children.get(occurrence_id, []):
            child = by_id.get(child_id) or {}
            if child.get("kind") == "part" and not child.get("suppressed"):
                result.append(child_id)
            elif child.get("kind") == "subassembly":
                result.extend(descendant_parts(child_id, visited))
        descendant_cache[occurrence_id] = sorted(set(result))
        return list(descendant_cache[occurrence_id])

    all_part_ids = {
        str(row["occurrenceId"])
        for row in rows
        if row.get("kind") == "part" and not row.get("suppressed")
    }
    root_container_ids = {
        str(row["occurrenceId"])
        for row in rows
        if row.get("kind") == "subassembly" and int(row.get("level") or 0) == 0
    }
    if not root_container_ids:
        root_container_ids = {str(catalog.get("rootOccurrenceId") or "")}

    assigned: Set[str] = set()
    candidates: List[Dict[str, Any]] = []
    for index, raw_group in enumerate(groups):
        if not isinstance(raw_group, Mapping):
            raise PartsManualProposalError(
                f"manualPlanning group {index + 1} is not an object"
            )
        name = str(raw_group.get("name") or "").strip()
        if not is_publishable_section_name(name):
            raise PartsManualProposalError(
                f"manualPlanning group {index + 1} has a non-publishable name"
            )
        matched: Set[str] = set()
        source_refs: List[str] = []

        for reference_value in raw_group.get("subassemblyReferences") or []:
            reference = str(reference_value or "").strip()
            matching_rows = [
                row
                for row in rows
                if row.get("kind") == "subassembly"
                and str(row.get("referencedFileName") or "").casefold()
                == reference.casefold()
            ]
            if not matching_rows:
                raise PartsManualProposalError(
                    f"manualPlanning group {name!r} references unknown subassembly {reference!r}"
                )
            source_refs.append(f"subassembly:{reference}")
            for row in matching_rows:
                matched.update(descendant_parts(str(row["occurrenceId"])))

        for reference_value in raw_group.get("directPartReferences") or []:
            reference = str(reference_value or "").strip()
            matching_rows = [
                row
                for row in rows
                if row.get("kind") == "part"
                and not row.get("suppressed")
                and str(row.get("parentOccurrenceId") or "") in root_container_ids
                and str(row.get("referencedFileName") or "").casefold()
                == reference.casefold()
            ]
            if not matching_rows:
                raise PartsManualProposalError(
                    f"manualPlanning group {name!r} references unknown root part {reference!r}"
                )
            source_refs.append(f"direct-part:{reference}")
            matched.update(str(row["occurrenceId"]) for row in matching_rows)

        if bool(raw_group.get("includeRemaining", False)):
            source_refs.append("remaining-active-parts")
            matched.update(all_part_ids - assigned)

        overlap = matched & assigned
        if overlap:
            raise PartsManualProposalError(
                f"manualPlanning group {name!r} overlaps {len(overlap)} occurrence(s) already assigned"
            )
        if len(matched) < 2:
            raise PartsManualProposalError(
                f"manualPlanning group {name!r} resolves to fewer than two active parts"
            )
        occurrence_ids = sorted(matched)
        assigned.update(matched)
        candidates.append(
            {
                "candidateId": _candidate_id(
                    "library_manual_profile", name, occurrence_ids, source_refs
                ),
                "name": name,
                "parentCandidateId": None,
                "occurrenceIds": occurrence_ids,
                "source": "library_manual_profile",
                "confidence": 0.98,
                "evidence": [
                    {
                        "classification": "AUTHORED",
                        "sourceType": "industrial_asset_library",
                        "sourceRef": ";".join(source_refs),
                        "supports": "manual-group-membership",
                        "detail": (
                            f"Curated service structure assigns {len(occurrence_ids)} active "
                            "component occurrences to this functional assembly."
                        ),
                    }
                ],
                "processOperationIds": [],
                "sequenceRank": index,
                "groupQuality": {
                    "functionalCoherence": 0.97,
                    "mechanicalConnectivity": 0.94,
                    "processCoherence": 0.90,
                    "namingConfidence": 1.0,
                    "componentCountScore": 1.0,
                    "overall": 0.958,
                },
            }
        )
    return candidates


def _process_map_candidates(
    catalog: Mapping[str, Any],
    process_evidence: Optional[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not isinstance(process_evidence, Mapping):
        return [], None
    process_map = process_evidence.get("map")
    if not isinstance(process_map, Mapping):
        process_map = process_evidence
    nodes = [row for row in process_map.get("canvasNodes") or [] if isinstance(row, Mapping)]
    edges = [row for row in process_map.get("canvasEdges") or [] if isinstance(row, Mapping)]
    if not nodes or not edges:
        return [], str(process_evidence.get("revision") or "") or None

    process_revision = str(process_evidence.get("revision") or "").strip()
    if not process_revision:
        process_revision = _canonical_sha256(process_map)
    nodes_by_id = {str(row.get("nodeId")): row for row in nodes if row.get("nodeId")}
    process_node_ids = {
        node_id
        for node_id, row in nodes_by_id.items()
        if row.get("nodeKind") in {"process_step", "junction"}
    }
    operation_ids = {
        node_id
        for node_id, row in nodes_by_id.items()
        if row.get("nodeKind") == "process_step"
    }
    occurrence_node_ids = {
        node_id
        for node_id, row in nodes_by_id.items()
        if row.get("nodeKind") == "product_occurrence"
    }
    known_parts = {str(row["occurrenceId"]) for row in _active_part_rows(catalog)}

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    predecessors: Dict[str, Set[str]] = defaultdict(set)
    inputs_by_operation: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        source_id = str((edge.get("from") or {}).get("nodeId") or "")
        target_id = str((edge.get("to") or {}).get("nodeId") or "")
        if source_id in process_node_ids and target_id in process_node_ids:
            adjacency[source_id].add(target_id)
            predecessors[target_id].add(source_id)
        if source_id in occurrence_node_ids and target_id in operation_ids:
            occurrence_id = str((nodes_by_id.get(source_id) or {}).get("sourceOccurrenceId") or "")
            if occurrence_id in known_parts:
                inputs_by_operation[target_id].add(occurrence_id)

    stage_values = {
        node_id: int(((nodes_by_id[node_id].get("semantic") or {}).get("stageIndex") or 0))
        for node_id in operation_ids
    }
    functional_candidates = _functional_process_candidates(
        catalog=catalog,
        process_map=process_map,
        process_revision=process_revision,
        nodes_by_id=nodes_by_id,
        operation_ids=operation_ids,
        inputs_by_operation=inputs_by_operation,
        stage_values=stage_values,
    )
    if functional_candidates:
        return functional_candidates, process_revision
    positive_stages = [value for value in stage_values.values() if value > 0]
    if positive_stages:
        minimum_stage = min(positive_stages)
        roots = {node_id for node_id, stage in stage_values.items() if stage == minimum_stage}
    else:
        roots = {
            node_id
            for node_id in operation_ids
            if not any(predecessor in process_node_ids for predecessor in predecessors.get(node_id, set()))
        }
    if not roots:
        roots = set(operation_ids)

    reachable_roots: Dict[str, Set[str]] = {node_id: set() for node_id in process_node_ids}
    for root_id in roots:
        reachable_roots[root_id].add(root_id)
    for _ in range(max(1, len(process_node_ids) * 2)):
        changed = False
        for source_id, targets in adjacency.items():
            for target_id in targets:
                merged = reachable_roots[target_id] | reachable_roots[source_id]
                if merged != reachable_roots[target_id]:
                    reachable_roots[target_id] = merged
                    changed = True
        if not changed:
            break

    result: List[Dict[str, Any]] = []
    for root_id in sorted(roots):
        branch_operations = sorted(
            node_id
            for node_id in operation_ids
            if reachable_roots.get(node_id) == {root_id}
        )
        occurrence_ids = sorted(
            {
                occurrence_id
                for operation_id in branch_operations
                for occurrence_id in inputs_by_operation.get(operation_id, set())
            }
        )
        if len(occurrence_ids) < 2:
            continue
        root = nodes_by_id[root_id]
        name = _operation_group_name(root.get("name"))
        semantic_refs = [
            str((nodes_by_id[operation_id].get("semantic") or {}).get("semanticRef") or operation_id)
            for operation_id in branch_operations
        ]
        knowledge_states = [
            str((nodes_by_id[operation_id].get("semantic") or {}).get("knowledgeStatus") or "inferred")
            for operation_id in branch_operations
        ]
        state_score = {"authored": 0.95, "derived": 0.89, "inferred": 0.78}
        confidence = sum(state_score.get(value, 0.72) for value in knowledge_states) / max(len(knowledge_states), 1)
        if len(occurrence_ids) >= 3:
            confidence = min(0.96, confidence + 0.04)
        candidate_id = _candidate_id("process_map", name, occurrence_ids, semantic_refs)
        result.append(
            {
                "candidateId": candidate_id,
                "name": name,
                "parentCandidateId": None,
                "occurrenceIds": occurrence_ids,
                "source": "process_map",
                "confidence": round(confidence, 3),
                "evidence": [
                    {
                        "classification": "DERIVED" if all(value != "inferred" for value in knowledge_states) else "INFERRED",
                        "sourceType": "process_map",
                        "sourceRef": str(process_map.get("mapId") or process_revision),
                        "supports": "manual-group-membership",
                        "detail": (
                            f"{len(occurrence_ids)} component occurrences feed the independent assembly branch "
                            f"rooted at '{root.get('name') or name}' before branch convergence."
                        ),
                    }
                ],
                "processOperationIds": semantic_refs,
            }
        )
    return result, process_revision


def _tokenize_name(value: Any, assembly_number: str) -> Set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9]+", str(value or "").lower())
        if token not in _GENERIC_NAME_TOKENS and len(token) > 2
    }
    tokens -= set(re.findall(r"[a-z][a-z0-9]+", str(assembly_number or "").lower()))
    return tokens


def _name_inference_candidates(
    catalog: Mapping[str, Any],
    excluded_occurrence_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    excluded = set(excluded_occurrence_ids)
    rows = [row for row in _active_part_rows(catalog) if str(row["occurrenceId"]) not in excluded]
    token_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    assembly_number = str(catalog.get("assemblyNumber") or "")
    for row in rows:
        text = " ".join(
            str(row.get(key) or "")
            for key in ("description", "partNumber", "name")
        )
        for token in _tokenize_name(text, assembly_number):
            token_rows[token].append(row)

    selected: Set[str] = set()
    candidates: List[Dict[str, Any]] = []
    ranked_tokens = sorted(
        token_rows,
        key=lambda token: (-len({str(row["occurrenceId"]) for row in token_rows[token]}), token),
    )
    for token in ranked_tokens:
        occurrence_ids = sorted(
            {
                str(row["occurrenceId"])
                for row in token_rows[token]
                if str(row["occurrenceId"]) not in selected
            }
        )
        if len(occurrence_ids) < 2 or len(occurrence_ids) > 12:
            continue
        name = f"{token.title()} Components"
        candidate_id = _candidate_id("inferred", name, occurrence_ids, [f"name-token:{token}"])
        candidates.append(
            {
                "candidateId": candidate_id,
                "name": name,
                "parentCandidateId": None,
                "occurrenceIds": occurrence_ids,
                "source": "inferred",
                "confidence": 0.55,
                "evidence": [
                    {
                        "classification": "INFERRED",
                        "sourceType": "component_metadata",
                        "sourceRef": f"name-token:{token}",
                        "supports": "candidate-group-membership",
                        "detail": f"Component names share the functional term '{token}'.",
                    }
                ],
                "processOperationIds": [],
            }
        )
        selected.update(occurrence_ids)
    return candidates


def _deduplicate_candidates(candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_membership: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for candidate_value in candidates:
        candidate = dict(candidate_value)
        key = tuple(sorted(str(item) for item in candidate.get("occurrenceIds") or []))
        if not key:
            continue
        current = by_membership.get(key)
        if current is None or _SOURCE_PRIORITY.get(str(candidate.get("source")), 0) > _SOURCE_PRIORITY.get(str(current.get("source")), 0):
            if current is not None:
                candidate["evidence"] = list(candidate.get("evidence") or []) + list(current.get("evidence") or [])
                candidate["processOperationIds"] = sorted(
                    set(candidate.get("processOperationIds") or [])
                    | set(current.get("processOperationIds") or [])
                )
            by_membership[key] = candidate
        elif current is not None:
            current["evidence"] = list(current.get("evidence") or []) + list(candidate.get("evidence") or [])
            current["processOperationIds"] = sorted(
                set(current.get("processOperationIds") or [])
                | set(candidate.get("processOperationIds") or [])
            )
    return list(by_membership.values())


def _classify_against_existing(
    candidates: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    sections = [dict(row) for row in plan.get("sections") or [] if isinstance(row, Mapping)]
    result: List[Dict[str, Any]] = []
    for candidate_value in candidates:
        candidate = dict(candidate_value)
        candidate_ids = set(str(item) for item in candidate.get("occurrenceIds") or [])
        conflicts: List[Dict[str, Any]] = []
        containing_sections: List[Dict[str, Any]] = []
        exact_section: Optional[Dict[str, Any]] = None
        superseded_section_ids: List[str] = []
        for section in sections:
            section_ids = set(str(item) for item in section.get("occurrenceIds") or [])
            overlap = sorted(candidate_ids & section_ids)
            if not overlap:
                continue
            if not is_publishable_section_name(section.get("name")):
                superseded_section_ids.append(str(section.get("sectionId") or ""))
                continue
            if candidate_ids == section_ids:
                exact_section = section
                break
            if candidate_ids < section_ids:
                containing_sections.append(section)
                continue
            conflicts.append(
                {
                    "sectionId": str(section.get("sectionId") or ""),
                    "name": str(section.get("name") or "Existing section"),
                    "occurrenceIds": overlap,
                    "reason": "partial_or_parent_overlap",
                }
            )
        candidate["conflicts"] = conflicts
        candidate["supersedesSectionIds"] = sorted(
            value for value in set(superseded_section_ids) if value
        )
        candidate["suggestedParentSectionId"] = None
        if exact_section is not None:
            candidate["status"] = "already_authored"
            candidate["existingSectionId"] = exact_section.get("sectionId")
        elif conflicts:
            candidate["status"] = "conflict"
        else:
            if containing_sections:
                parent = min(containing_sections, key=lambda row: len(row.get("occurrenceIds") or []))
                candidate["suggestedParentSectionId"] = parent.get("sectionId")
            candidate["status"] = "ready"
        result.append(candidate)
    return result


def compile_manual_structure_proposal(
    *,
    catalog: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_revision: str,
    process_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a read-only proposal tied to the exact assembly, plan, and process state."""
    source_revision = str(catalog.get("sourceRevision") or "")
    if not source_revision or str(plan.get("sourceRevision") or "") != source_revision:
        raise PartsManualProposalError("manual plan and assembly source revisions do not match")

    library_candidates = _library_manual_profile_candidates(catalog)
    cad_candidates = _cad_hierarchy_candidates(catalog)
    process_candidates, process_revision = _process_map_candidates(catalog, process_evidence)
    if library_candidates:
        candidates = library_candidates
        strategy = "library_manual_profile"
    elif cad_candidates:
        candidates: List[Dict[str, Any]] = cad_candidates
        strategy = "cad_hierarchy"
    elif process_candidates:
        candidates = process_candidates
        strategy = "process_map"
    else:
        candidates = []
        strategy = "component_metadata"

    covered = {
        str(item)
        for candidate in candidates
        for item in candidate.get("occurrenceIds") or []
    }
    candidates.extend(_name_inference_candidates(catalog, covered))
    candidates = _deduplicate_candidates(candidates)
    candidates = _classify_against_existing(candidates, plan)
    candidates.sort(
        key=lambda row: (
            {"ready": 0, "conflict": 1, "already_authored": 2}.get(str(row.get("status")), 3),
            int(row["sequenceRank"]) if row.get("sequenceRank") is not None else 10**9,
            -float(row.get("confidence") or 0),
            str(row.get("name") or "").lower(),
            str(row.get("candidateId") or ""),
        )
    )

    all_parts = {str(row["occurrenceId"]) for row in _active_part_rows(catalog)}
    existing = {
        str(item)
        for section in plan.get("sections") or []
        if isinstance(section, Mapping)
        and is_publishable_section_name(section.get("name"))
        for item in section.get("occurrenceIds") or []
    }
    proposed = {
        str(item)
        for candidate in candidates
        if candidate.get("status") in {"ready", "already_authored"}
        for item in candidate.get("occurrenceIds") or []
    }
    warnings: List[str] = []
    if process_evidence is None and not library_candidates and not cad_candidates:
        warnings.append("No process map or explicit CAD subassembly hierarchy was available; metadata groups require close review.")
    conflict_count = sum(1 for candidate in candidates if candidate.get("status") == "conflict")
    if conflict_count:
        warnings.append(f"{conflict_count} candidate group(s) overlap existing authored sections and cannot be approved automatically.")
    superseded_ids = sorted(
        {
            section_id
            for candidate in candidates
            for section_id in candidate.get("supersedesSectionIds") or []
        }
    )
    if superseded_ids:
        warnings.append(
            f"{len(superseded_ids)} internal or non-publication section(s) will be replaced only after explicit approval."
        )
    if not candidates:
        warnings.append("No defensible multi-component manual groups could be derived from the available evidence.")

    unassigned_occurrence_ids = sorted(all_parts - existing - proposed)
    coverage_percent = (
        100.0
        if not all_parts
        else (len(all_parts) - len(unassigned_occurrence_ids)) / len(all_parts) * 100.0
    )
    proposal_core = {
        "schemaVersion": PARTS_MANUAL_PROPOSAL_SCHEMA_VERSION,
        "assemblyNumber": str(catalog.get("assemblyNumber") or ""),
        "sourceRevision": source_revision,
        "basePlanRevision": str(plan_revision),
        "processMapRevision": process_revision,
        "strategy": strategy,
        "candidates": candidates,
        "unassignedOccurrenceIds": unassigned_occurrence_ids,
        "supersededSectionIds": superseded_ids,
        "warnings": warnings,
    }
    return {
        **proposal_core,
        "proposalRevision": _canonical_sha256(proposal_core),
        "summary": {
            "candidateCount": len(candidates),
            "readyCount": sum(1 for row in candidates if row.get("status") == "ready"),
            "conflictCount": conflict_count,
            "alreadyAuthoredCount": sum(1 for row in candidates if row.get("status") == "already_authored"),
            "unassignedCount": len(proposal_core["unassignedOccurrenceIds"]),
            "eligibleOccurrenceCount": len(all_parts),
            "coveredOccurrenceCount": len(all_parts) - len(unassigned_occurrence_ids),
            "coveragePercent": round(coverage_percent, 3),
        },
    }


__all__ = [
    "PARTS_MANUAL_PROPOSAL_SCHEMA_VERSION",
    "PartsManualProposalError",
    "compile_manual_structure_proposal",
]
