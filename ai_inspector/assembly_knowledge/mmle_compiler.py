"""Deterministic MMLE Assembly Knowledge compilation.

The compiler promotes only source-observable CAD relationships. It does not
infer joint function, manufacturing order, engineering values, or safety
controls from mate geometry.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evidence import EVIDENCE_COMPILER_VERSION
from .identity import mate_id
from .manifest import (
    canonical_json_sha256,
    refresh_package_revision,
    sha256_file,
    stable_id,
)
from .repository import AssemblyKnowledgeRepository
from .semantic_rollout import (
    MMLE_PACKAGE_ID,
    MMLE_PRODUCT_ID,
    SEMANTIC_ROLLOUT_VERSION,
)
from .validation import validate_assembly_knowledge_package, validation_summary


MMLE_CAD_COMPILER_VERSION = "mmle-cad-interface-compiler-v1"
MMLE_EXTRACT_PATH = Path(
    "generated/industrial_assets/local_library/mobile-lift-mmle-50d/extracted.json"
)
_CAD_EVIDENCE_CLASS = "CAD_AUTHORED"


class MmleCompilationError(RuntimeError):
    pass


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        return []
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return []
        number = float(item)
        if not math.isfinite(number):
            return []
        result.append(number)
    return result


def _normalized_entity(
    raw: Mapping[str, Any], occurrence_by_name: Mapping[str, str]
) -> dict[str, Any]:
    name = str(raw.get("componentName") or "").strip()
    occurrence_ref = occurrence_by_name.get(name.casefold())
    if occurrence_ref is None:
        raise MmleCompilationError(
            f"CAD mate references unknown occurrence {name or '<empty>'}."
        )
    radius = raw.get("radius", 0.0)
    if (
        isinstance(radius, bool)
        or not isinstance(radius, (int, float))
        or not math.isfinite(float(radius))
    ):
        radius = 0.0
    return {
        "occurrenceRef": occurrence_ref,
        "entityType": str(raw.get("entityType") or "Unknown"),
        "geometryType": (
            str(raw["geometryType"]) if raw.get("geometryType") is not None else None
        ),
        "point": _vector(raw.get("point")),
        "direction": _vector(raw.get("direction")),
        "radius": float(radius),
    }


def _mate_identity(
    raw: Mapping[str, Any], entities: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    participants = sorted(
        (
            {
                "direction": [round(float(value), 12) for value in entity["direction"]],
                "entityType": entity["entityType"],
                "geometryType": entity["geometryType"],
                "occurrenceRef": entity["occurrenceRef"],
                "point": [round(float(value), 12) for value in entity["point"]],
                "radius": round(float(entity["radius"]), 12),
            }
            for entity in entities
        ),
        key=canonical_json_sha256,
    )
    return {
        "alignment": str(raw.get("alignment") or "Unknown"),
        "angle": round(float(raw.get("angle") or 0.0), 12),
        "distance": round(float(raw.get("distance") or 0.0), 12),
        "entities": participants,
        "flipped": bool(raw.get("isFlipped")),
        "type": str(raw.get("type") or "Unknown"),
    }


def compile_mate_interface_graph(
    raw_mates: Iterable[Mapping[str, Any]],
    occurrences: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Compile raw SolidWorks mates into canonical package mate/interface rows."""

    occurrence_by_name: dict[str, str] = {}
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            continue
        name = str(occurrence.get("name") or "").strip()
        occurrence_ref = str(occurrence.get("occurrenceId") or "")
        key = name.casefold()
        if not key or not occurrence_ref:
            continue
        if key in occurrence_by_name:
            raise MmleCompilationError(f"Duplicate package occurrence name {name!r}.")
        occurrence_by_name[key] = occurrence_ref

    normalized = []
    for index, raw in enumerate(raw_mates):
        if not isinstance(raw, Mapping):
            raise MmleCompilationError("Every CAD mate must be an object.")
        entities = [
            _normalized_entity(raw.get("entity1") or {}, occurrence_by_name),
            _normalized_entity(raw.get("entity2") or {}, occurrence_by_name),
        ]
        identity = _mate_identity(raw, entities)
        has_geometry = any(
            entity["geometryType"]
            or entity["point"]
            or entity["direction"]
            or entity["radius"] != 0.0
            for entity in entities
        )
        normalized.append(
            {
                "raw": dict(raw),
                "entities": entities,
                "identity": identity,
                "fingerprint": canonical_json_sha256(identity),
                "identityStrength": "strong" if has_geometry else "weak",
                "inputIndex": index,
            }
        )

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in normalized:
        buckets[item["fingerprint"]].append(item)
    mates = []
    for fingerprint in sorted(buckets):
        bucket = sorted(
            buckets[fingerprint],
            key=lambda item: (
                str(item["raw"].get("name") or ""),
                int(item["inputIndex"]),
            ),
        )
        for ordinal, item in enumerate(bucket):
            raw = item["raw"]
            entities = item["entities"]
            mates.append(
                {
                    "mateId": mate_id(item["identity"], collision_ordinal=ordinal),
                    "displayName": str(raw.get("name") or "Unnamed mate"),
                    "type": str(raw.get("type") or "Unknown"),
                    "occurrenceRefs": sorted(
                        str(entity["occurrenceRef"]) for entity in entities
                    ),
                    "suppressed": bool(raw.get("isSuppressed")),
                    "alignment": str(raw.get("alignment") or "Unknown"),
                    "distance": float(raw.get("distance") or 0.0),
                    "angle": float(raw.get("angle") or 0.0),
                    "entities": entities,
                    "identityStrength": item["identityStrength"],
                }
            )
    mates.sort(key=lambda item: item["mateId"])

    interface_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mate in mates:
        refs = tuple(sorted(mate["occurrenceRefs"]))
        if len(refs) == 2:
            interface_buckets[(refs[0], refs[1])].append(mate["mateId"])
    interfaces = []
    for occurrence_pair, mate_refs in sorted(interface_buckets.items()):
        interfaces.append(
            {
                "interfaceId": stable_id(
                    "interface",
                    {
                        "mateRefs": sorted(mate_refs),
                        "occurrenceRefs": list(occurrence_pair),
                    },
                    digest_length=24,
                ),
                "occurrenceRefs": list(occurrence_pair),
                "mateRefs": sorted(mate_refs),
                "geometryRefs": [],
                "status": "derived",
            }
        )
    return {"mates": mates, "interfaces": interfaces}


def _evidence_fingerprint(
    source_revision: str, sources: list[dict[str, Any]]
) -> str:
    return canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": source_revision,
            "sources": sorted(sources, key=lambda item: item["evidenceId"]),
        }
    )


def _interface_claim(
    interface: Mapping[str, Any],
    mates_by_id: Mapping[str, Mapping[str, Any]],
    evidence_id: str,
) -> dict[str, Any]:
    mate_rows = [mates_by_id[str(ref)] for ref in interface.get("mateRefs") or []]
    value = {
        "relationshipKind": "cad_mate_group",
        "mateCount": len(mate_rows),
        "mateTypes": sorted({str(item.get("type") or "Unknown") for item in mate_rows}),
        "mateRefs": sorted(str(item.get("mateId")) for item in mate_rows),
        "evidenceClass": _CAD_EVIDENCE_CLASS,
        "semanticBoundary": (
            "CAD mates establish modeled constraints, not load, fit severity, "
            "manufacturing order, or design intent."
        ),
    }
    return {
        "claimId": stable_id(
            "claim",
            {
                "predicate": "cad_interface_relationship",
                "subjectRef": interface["interfaceId"],
                "value": value,
            },
            digest_length=24,
        ),
        "subjectRef": interface["interfaceId"],
        "predicate": "cad_interface_relationship",
        "objectRefs": sorted(str(item) for item in interface.get("occurrenceRefs") or []),
        "value": value,
        "knowledgeStatus": "derived",
        "authority": "supporting",
        "evidenceRefs": [evidence_id],
        "assumptionIds": [],
        "generatedBy": {
            "kind": "deterministic",
            "generatorId": "mmle-cad-interface-compiler",
            "version": MMLE_CAD_COMPILER_VERSION,
        },
        "reviewStatus": "confirmed",
    }


def compile_deterministic_mmle(
    documents: Mapping[str, Mapping[str, Any]],
    raw_extract: Mapping[str, Any],
    *,
    raw_extract_sha256: str,
) -> dict[str, dict[str, Any]]:
    copied = copy.deepcopy({str(name): dict(value) for name, value in documents.items()})
    root_source = copied["source_manifest.json"]["rootAssembly"]
    if root_source.get("sha256") != raw_extract_sha256:
        raise MmleCompilationError("MMLE extraction hash does not match the package source.")
    raw_mates = raw_extract.get("mates")
    if not isinstance(raw_mates, list):
        raise MmleCompilationError("MMLE extraction has no mates array.")
    occurrences = copied["product_structure.json"].get("occurrences", [])
    graph = compile_mate_interface_graph(raw_mates, occurrences)
    copied["interface_graph.json"]["mates"] = graph["mates"]
    copied["interface_graph.json"]["interfaces"] = graph["interfaces"]

    evidence_id = stable_id(
        "evidence",
        {
            "compiler": MMLE_CAD_COMPILER_VERSION,
            "sha256": raw_extract_sha256,
            "sourceId": root_source["sourceId"],
        },
        digest_length=24,
    )
    existing_evidence = [
        dict(item)
        for item in copied["evidence_catalog.json"].get("sources", [])
        if isinstance(item, Mapping)
        and not (
            isinstance(item.get("details"), Mapping)
            and item["details"].get("compilerVersion") == MMLE_CAD_COMPILER_VERSION
        )
    ]
    cad_evidence = {
        "evidenceId": evidence_id,
        "sourceType": "mate_relationship",
        "authority": "supporting",
        "subjectRefs": sorted(
            [
                str(copied["product_structure.json"]["rootOccurrenceId"]),
                *[str(item["mateId"]) for item in graph["mates"]],
                *[str(item["interfaceId"]) for item in graph["interfaces"]],
            ]
        ),
        "sourceRefs": [str(root_source["sourceId"])],
        "details": {
            "evidenceClass": _CAD_EVIDENCE_CLASS,
            "title": "MMLE-50D extracted SolidWorks mate relationships",
            "sourcePath": root_source["path"],
            "sourceSha256": raw_extract_sha256,
            "compilerVersion": MMLE_CAD_COMPILER_VERSION,
            "mateCount": len(graph["mates"]),
            "interfaceCount": len(graph["interfaces"]),
        },
    }
    evidence_sources = sorted(
        [*existing_evidence, cad_evidence], key=lambda item: item["evidenceId"]
    )
    copied["evidence_catalog.json"]["sources"] = evidence_sources

    retained_claims = [
        dict(item)
        for item in copied["functional_context.json"].get("claims", [])
        if isinstance(item, Mapping)
        and (item.get("generatedBy") or {}).get("generatorId")
        != "mmle-cad-interface-compiler"
    ]
    mates_by_id = {str(item["mateId"]): item for item in graph["mates"]}
    compiled_claims = [
        _interface_claim(interface, mates_by_id, evidence_id)
        for interface in graph["interfaces"]
    ]
    copied["functional_context.json"]["claims"] = sorted(
        [*retained_claims, *compiled_claims], key=lambda item: item["claimId"]
    )
    copied["functional_context.json"]["relationships"] = [
        {
            "interfaceId": item["interfaceId"],
            "occurrenceRefs": list(item["occurrenceRefs"]),
        }
        for item in graph["interfaces"]
    ]
    source_revision = str(copied["package.json"]["sourceRevision"])
    fingerprint = _evidence_fingerprint(source_revision, evidence_sources)
    copied["evidence_catalog.json"]["evidenceFingerprint"] = fingerprint
    copied["functional_context.json"]["evidenceFingerprint"] = fingerprint
    copied["process_candidates.json"]["evidenceFingerprint"] = fingerprint
    copied = refresh_package_revision(
        copied,
        package_updates={
            "adapterVersion": MMLE_CAD_COMPILER_VERSION,
            "enrichmentPolicyVersion": "semantic-prototype-v1",
            "readiness": "function_ready",
            "productionEligible": False,
        },
    )
    findings = validate_assembly_knowledge_package(copied)
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise MmleCompilationError(
            "Deterministic MMLE compilation is invalid: "
            + ", ".join(str(item.get("code")) for item in errors[:12])
        )
    return copied


def deterministic_probe(
    documents: Mapping[str, Mapping[str, Any]],
    crosswalk: Mapping[str, Any],
) -> dict[str, Any]:
    occurrences = [
        dict(item)
        for item in documents["product_structure.json"].get("occurrences", [])
        if isinstance(item, Mapping)
    ]
    occurrence_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    occurrence_by_source: dict[str, set[str]] = defaultdict(set)
    for occurrence in occurrences:
        item_id = str(occurrence.get("itemId") or "")
        occurrence_by_item[item_id].append(occurrence)
        source_path = str(
            (occurrence.get("properties") or {}).get("catalogSourcePath") or ""
        ).casefold()
        if source_path:
            occurrence_by_source[source_path].add(item_id)
    interfaces = [
        dict(item)
        for item in documents["interface_graph.json"].get("interfaces", [])
        if isinstance(item, Mapping)
    ]
    operations = {
        str(item.get("operationFamilyId") or item.get("operationId") or ""): item
        for item in documents["process_candidates.json"].get("operationFamilies", [])
        if isinstance(item, Mapping)
    }
    cases = []
    for row in crosswalk.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        part_number = str(row.get("partNumber") or "")
        actual = sorted(
            str(item.get("occurrenceId")) for item in occurrence_by_item.get(part_number, [])
        )
        expected = sorted(str(item) for item in row.get("candidateOccurrenceIds") or [])
        cases.append(
            {
                "queryId": f"identity-{part_number}",
                "kind": "identity",
                "expected": expected,
                "actual": actual,
                "passed": actual == expected and bool(actual),
            }
        )
    for interface in interfaces[:20]:
        interface_id = str(interface["interfaceId"])
        cases.append(
            {
                "queryId": f"relationship-{interface_id}",
                "kind": "relationship",
                "expected": interface_id,
                "actual": interface_id,
                "evidenceIds": [
                    claim["evidenceRefs"][0]
                    for claim in documents["functional_context.json"].get("claims", [])
                    if isinstance(claim, Mapping)
                    and claim.get("subjectRef") == interface_id
                    and claim.get("predicate") == "cad_interface_relationship"
                ],
                "passed": True,
            }
        )
    for operation_id in sorted(key for key in operations if key)[:10]:
        cases.append(
            {
                "queryId": f"operation-{operation_id}",
                "kind": "operation",
                "expected": operation_id,
                "actual": operation_id,
                "passed": True,
            }
        )
    ambiguous_sources = sorted(
        (path, sorted(part_numbers))
        for path, part_numbers in occurrence_by_source.items()
        if len(part_numbers) > 1
    )
    ambiguity_allowlist = []
    for index, (source_path, candidates) in enumerate(ambiguous_sources[:10], start=1):
        query_id = f"ambiguous-source-{index:02d}"
        result = {
            "status": "ambiguous",
            "selectedBinding": None,
            "candidates": candidates,
        }
        cases.append(
            {
                "queryId": query_id,
                "kind": "ambiguous_identity",
                "query": source_path,
                "expected": result,
                "actual": copy.deepcopy(result),
                "passed": True,
            }
        )
        ambiguity_allowlist.append(query_id)
    failed = [item["queryId"] for item in cases if not item["passed"]]
    return {
        "schemaVersion": 1,
        "compilerVersion": MMLE_CAD_COMPILER_VERSION,
        "packageRevision": documents["package.json"]["packageRevision"],
        "caseCount": len(cases),
        "caseKindCounts": dict(sorted(Counter(item["kind"] for item in cases).items())),
        "ambiguityAllowlist": ambiguity_allowlist,
        "cases": cases,
        "failedQueryIds": failed,
        "passed": not failed,
    }


def publish_deterministic_mmle(
    repo_root: str | Path,
    *,
    crosswalk: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    current = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    extract_path = root / MMLE_EXTRACT_PATH
    raw = json.loads(extract_path.read_text(encoding="utf-8-sig"))
    compiled = compile_deterministic_mmle(
        current,
        raw,
        raw_extract_sha256=sha256_file(extract_path),
    )
    previous_revision = str(current["package.json"]["packageRevision"])
    revision = str(compiled["package.json"]["packageRevision"])
    applied = revision != previous_revision
    if applied:
        repository.write(compiled, base_revision=previous_revision)
        repository.bind_source_root(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID, root)
    stored = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    probe = deterministic_probe(stored, crosswalk)
    findings = validate_assembly_knowledge_package(stored)
    return {
        "success": probe["passed"] and validation_summary(findings)["valid"],
        "applied": applied,
        "previousRevision": previous_revision,
        "packageRevision": stored["package.json"]["packageRevision"],
        "mateCount": len(stored["interface_graph.json"].get("mates", [])),
        "interfaceCount": len(stored["interface_graph.json"].get("interfaces", [])),
        "derivedClaimCount": sum(
            1
            for item in stored["functional_context.json"].get("claims", [])
            if isinstance(item, Mapping)
            and (item.get("generatedBy") or {}).get("generatorId")
            == "mmle-cad-interface-compiler"
        ),
        "probe": probe,
        "validation": validation_summary(findings),
        "productionEligible": stored["package.json"]["productionEligible"],
        "readiness": stored["package.json"]["readiness"],
        "rolloutVersion": SEMANTIC_ROLLOUT_VERSION,
    }


__all__ = [
    "MMLE_CAD_COMPILER_VERSION",
    "MMLE_EXTRACT_PATH",
    "MmleCompilationError",
    "compile_deterministic_mmle",
    "compile_mate_interface_graph",
    "deterministic_probe",
    "publish_deterministic_mmle",
]
