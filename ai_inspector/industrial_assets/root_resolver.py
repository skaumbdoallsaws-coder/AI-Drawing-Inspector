"""Fail-closed dependency and root resolution for discovered CAD sources."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import PurePosixPath
import re
from typing import Iterable

from .schema_v1 import (
    DependencyEdge,
    DependencyGraphResult,
    DependencyReference,
    DiscoveryResult,
    IntakeFinding,
    SourceFileRecord,
    canonical_path_key,
    canonical_relative_path,
    sort_findings,
)


def _portable_reference(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    if (
        not raw
        or raw.startswith("/")
        or raw.startswith("//")
        or re.match(r"^[A-Za-z]:", raw)
    ):
        raise ValueError("dependency reference must be portable and relative")
    return canonical_relative_path(raw)


def _resolve_requested_root(
    requested_root: str,
    *,
    by_path: dict[str, SourceFileRecord],
    by_basename: dict[str, list[SourceFileRecord]],
) -> tuple[SourceFileRecord | None, IntakeFinding | None]:
    try:
        portable = _portable_reference(requested_root)
    except ValueError:
        return None, IntakeFinding(
            "error",
            "requested_root_invalid",
            "The requested root must be a portable relative source path.",
            reference=requested_root,
        )
    if "/" in portable:
        record = by_path.get(canonical_path_key(portable))
        if record is None:
            return None, IntakeFinding(
                "error",
                "requested_root_missing",
                "The requested root was not found in the source inventory.",
                reference=portable,
            )
        return record, None
    candidates = by_basename.get(portable.casefold(), [])
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, IntakeFinding(
            "error",
            "requested_root_missing",
            "The requested root was not found in the source inventory.",
            reference=portable,
        )
    return None, IntakeFinding(
        "error",
        "requested_root_ambiguous",
        "The requested root matches more than one source; select an exact path.",
        reference=portable,
        candidates=tuple(item.relative_path for item in candidates),
    )


def _reference_candidates(
    owner: SourceFileRecord,
    reference: str,
    *,
    by_path: dict[str, SourceFileRecord],
    by_basename: dict[str, list[SourceFileRecord]],
) -> tuple[list[SourceFileRecord], str]:
    portable = _portable_reference(reference)
    if "/" not in portable:
        return list(by_basename.get(portable.casefold(), [])), portable

    owner_directory = PurePosixPath(owner.relative_path).parent
    candidates: dict[str, SourceFileRecord] = {}
    for candidate_path in (
        str(owner_directory / PurePosixPath(portable)),
        portable,
    ):
        try:
            key = canonical_path_key(candidate_path)
        except ValueError:
            continue
        record = by_path.get(key)
        if record is not None:
            candidates[record.path_key] = record
    return (
        sorted(candidates.values(), key=lambda item: item.path_key),
        portable,
    )


def _reachable(
    root: str,
    outgoing: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    seen: set[str] = set()
    queue: deque[str] = deque([root])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(outgoing.get(current, ()))
    return tuple(sorted(seen, key=lambda item: (item.casefold(), item)))


def _cycle_nodes(
    nodes: Iterable[str],
    edges: Iterable[DependencyEdge],
) -> tuple[str, ...]:
    selected = set(nodes)
    indegree = {node: 0 for node in selected}
    outgoing: dict[str, set[str]] = {node: set() for node in selected}
    for edge in edges:
        if edge.owner_path not in selected or edge.target_path not in selected:
            continue
        if edge.target_path not in outgoing[edge.owner_path]:
            outgoing[edge.owner_path].add(edge.target_path)
            indegree[edge.target_path] += 1
    queue = deque(
        sorted(
            (node for node, degree in indegree.items() if degree == 0),
            key=lambda item: (item.casefold(), item),
        )
    )
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for target in sorted(
            outgoing[node],
            key=lambda item: (item.casefold(), item),
        ):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited == len(selected):
        return ()
    return tuple(
        sorted(
            (node for node, degree in indegree.items() if degree > 0),
            key=lambda item: (item.casefold(), item),
        )
    )


def resolve_dependency_graph(
    discovery: DiscoveryResult,
    references: Iterable[DependencyReference],
    *,
    requested_root: str | None = None,
    reference_graph_complete: bool = False,
) -> DependencyGraphResult:
    """Resolve dependencies without inferring a target from ambiguous names."""

    records = tuple(discovery.records)
    by_path = {record.path_key: record for record in records}
    by_basename: dict[str, list[SourceFileRecord]] = defaultdict(list)
    for record in records:
        by_basename[record.basename_key].append(record)
    for matches in by_basename.values():
        matches.sort(key=lambda item: item.path_key)

    findings: list[IntakeFinding] = list(discovery.findings)
    for basename, matches in sorted(by_basename.items()):
        if len(matches) > 1:
            findings.append(
                IntakeFinding(
                    "warning",
                    "duplicate_source_basename",
                    "Multiple sources share a basename; basename-only references are ambiguous.",
                    relative_path=matches[0].relative_path,
                    reference=basename,
                    candidates=tuple(item.relative_path for item in matches),
                )
            )

    edges: list[DependencyEdge] = []
    normalized_references = sorted(
        tuple(references),
        key=lambda item: (
            item.owner_path.casefold(),
            item.owner_path,
            item.reference.casefold(),
            item.reference,
            item.reference_kind,
        ),
    )
    for dependency in normalized_references:
        owner = by_path.get(canonical_path_key(dependency.owner_path))
        if owner is None:
            findings.append(
                IntakeFinding(
                    "error",
                    "dependency_owner_missing",
                    "A dependency record names an owner absent from the source inventory.",
                    relative_path=dependency.owner_path,
                    reference=dependency.reference,
                )
            )
            continue
        try:
            candidates, portable = _reference_candidates(
                owner,
                dependency.reference,
                by_path=by_path,
                by_basename=by_basename,
            )
        except ValueError:
            findings.append(
                IntakeFinding(
                    "error",
                    "dependency_reference_invalid",
                    "A dependency reference is absolute or escapes the source package.",
                    relative_path=owner.relative_path,
                    reference=dependency.reference,
                )
            )
            continue
        if not candidates:
            findings.append(
                IntakeFinding(
                    "error",
                    "dependency_missing",
                    "A referenced CAD dependency is missing from the source inventory.",
                    relative_path=owner.relative_path,
                    reference=portable,
                )
            )
            continue
        if len(candidates) > 1:
            findings.append(
                IntakeFinding(
                    "error",
                    "dependency_ambiguous",
                    "A dependency reference matches multiple sources and was not resolved.",
                    relative_path=owner.relative_path,
                    reference=portable,
                    candidates=tuple(item.relative_path for item in candidates),
                )
            )
            continue
        target = candidates[0]
        edges.append(
            DependencyEdge(
                owner_path=owner.relative_path,
                target_path=target.relative_path,
                reference=portable,
                reference_kind=dependency.reference_kind,
            )
        )

    edge_by_identity: dict[tuple[str, str, str], DependencyEdge] = {}
    for edge in edges:
        edge_by_identity[
            (edge.owner_path, edge.target_path, edge.reference_kind)
        ] = edge
    edges = sorted(
        edge_by_identity.values(),
        key=lambda item: (
            item.owner_path.casefold(),
            item.owner_path,
            item.target_path.casefold(),
            item.target_path,
            item.reference_kind,
        ),
    )
    referenced_paths = {edge.target_path for edge in edges}
    preferred_roots = [
        record.relative_path
        for record in records
        if record.source_kind == "assembly"
        and record.relative_path not in referenced_paths
    ]
    if not preferred_roots:
        preferred_roots = [
            record.relative_path
            for record in records
            if record.relative_path not in referenced_paths
        ]
    root_candidates = tuple(
        sorted(set(preferred_roots), key=lambda item: (item.casefold(), item))
    )

    selected: SourceFileRecord | None = None
    if requested_root is not None:
        selected, requested_finding = _resolve_requested_root(
            requested_root,
            by_path=by_path,
            by_basename=by_basename,
        )
        if requested_finding is not None:
            findings.append(requested_finding)
    elif len(root_candidates) == 1:
        selected = by_path[canonical_path_key(root_candidates[0])]

    outgoing_lists: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing_lists[edge.owner_path].append(edge.target_path)
    outgoing = {
        owner: tuple(
            sorted(set(targets), key=lambda item: (item.casefold(), item))
        )
        for owner, targets in outgoing_lists.items()
    }
    source_paths: tuple[str, ...] = ()
    if selected is not None:
        source_paths = _reachable(selected.relative_path, outgoing)
        cycles = _cycle_nodes(source_paths, edges)
        if cycles:
            findings.append(
                IntakeFinding(
                    "error",
                    "dependency_cycle",
                    "The selected CAD dependency graph contains a cycle.",
                    relative_path=selected.relative_path,
                    candidates=cycles,
                )
            )

    sorted_findings = sort_findings(findings)
    has_errors = any(item.severity == "error" for item in sorted_findings)
    if selected is None:
        status = "quarantined" if has_errors else "selection_required"
    else:
        # One intake tree is one trust boundary. A dependency or discovery
        # error anywhere in that tree quarantines the candidate rather than
        # silently treating the selected root as an isolated clean subset.
        if has_errors:
            status = "quarantined"
        elif reference_graph_complete:
            status = "resolved"
        else:
            status = "candidate_only"

    return DependencyGraphResult(
        schema_version=1,
        status=status,
        reference_graph_complete=reference_graph_complete,
        root_candidates=root_candidates,
        selected_root=selected.relative_path if selected is not None else None,
        source_paths=source_paths,
        edges=tuple(edges),
        findings=sorted_findings,
    )
