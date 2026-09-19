"""Lossless FunctionalRelationshipRegistry to AKP adapter.

The adapter stores behavior-bearing catalog collections as typed claim values,
not prose. Reconstructing the source graph from the package is therefore an
explicit migration invariant and lets the existing deterministic reasoning
code remain the compatibility oracle.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from ai_inspector.product_intelligence.functional_relationships import (
    build_functional_context,
    validate_functional_relationship_graph,
)

from .evidence import EVIDENCE_COMPILER_VERSION
from .manifest import (
    canonical_json_sha256,
    make_package_id,
    refresh_package_revision,
    sha256_file,
    stable_id,
)
from .repository import AssemblyKnowledgeRepository
from .schema import ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION
from .semantic_contract import (
    SEMANTIC_CONTRACT_VERSION,
    translate_legacy_authority,
)
from .validation import validate_assembly_knowledge_package


FUNCTIONAL_CATALOG_ADAPTER_VERSION = "functional-catalog-adapter-v1"
_IDENTITY_ROTATION = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
_WORD_RE = re.compile(r"[a-z0-9]+")


class FunctionalCatalogAdapterError(ValueError):
    pass


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def catalog_inventory(graph: Mapping[str, Any]) -> dict[str, int]:
    component_types = _rows(graph.get("component_types"))
    external_entities = _rows(graph.get("external_entities"))
    all_entities = [*component_types, *external_entities]
    features = [
        dict(feature)
        for entity in all_entities
        for feature in entity.get("functional_features") or []
        if isinstance(feature, Mapping)
    ]
    return {
        "componentTypes": len(component_types),
        "componentInstances": len(_rows(graph.get("component_instances"))),
        "interfaces": len(_rows(graph.get("interfaces"))),
        "externalEntities": len(external_entities),
        "sourceEvidence": len(_rows(graph.get("source_evidence"))),
        "functionalRoles": sum(
            len(entity.get("functional_roles") or []) for entity in all_entities
        ),
        "functionalFeatures": len(features),
        "semanticTags": sum(len(feature.get("semantic_tags") or []) for feature in features),
        "aliases": sum(len(feature.get("aliases") or []) for feature in features),
        "componentMobilityValues": sum(
            1 for entity in component_types if entity.get("mobility") not in (None, "")
        ),
        "externalPresenceValues": sum(
            1 for entity in external_entities if entity.get("presence") not in (None, "")
        ),
    }


def functional_catalog_migration_matrix(graph: Mapping[str, Any]) -> dict[str, Any]:
    inventory = catalog_inventory(graph)
    mappings = [
        ("schema_version", "functional_catalog_metadata.value.record.schema_version"),
        ("graph_id", "functional_catalog_metadata.value.record.graph_id"),
        ("version", "functional_catalog_metadata.value.record.version"),
        ("assembly", "functional_catalog_metadata.value.record.assembly"),
        ("source_evidence", "evidence_catalog.sources[].details.catalogRecord"),
        ("component_types", "component_type_definition.value.record"),
        ("component_instances", "component_instance_definition.value.record"),
        ("external_entities", "external_entity_definition.value.record"),
        ("interfaces", "functional_interface_definition.value.record"),
        ("coverage", "functional_coverage_snapshot.value.record"),
    ]
    return {
        "contractVersion": SEMANTIC_CONTRACT_VERSION,
        "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
        "inventory": inventory,
        "mappings": [
            {
                "sourceField": source,
                "destination": destination,
                "lossPolicy": "lossless_structured",
            }
            for source, destination in mappings
        ],
        "unmappedSourceFields": sorted(set(graph) - {item[0] for item in mappings}),
        "freeFormNarrativeMappings": [],
    }


def _source_type(value: str) -> str:
    return {
        "assembly_extract": "assembly_structure",
        "part_profile": "property",
        "motion_summary": "geometry",
    }.get(value, "property")


def _source_kind(value: str) -> str:
    return {
        "assembly_extract": "assembly",
        "part_profile": "part",
        "motion_summary": "stage_details",
    }.get(value, "resource_register")


def _claim(
    *,
    predicate: str,
    subject_ref: str,
    object_refs: Iterable[str],
    value: Mapping[str, Any],
    evidence_refs: Iterable[str],
) -> dict[str, Any]:
    identity = {
        "predicate": predicate,
        "subjectRef": subject_ref,
        "value": value,
    }
    return {
        "claimId": stable_id("claim", identity, digest_length=24),
        "subjectRef": subject_ref,
        "predicate": predicate,
        "objectRefs": sorted({str(item) for item in object_refs if str(item)}),
        "value": copy.deepcopy(dict(value)),
        "knowledgeStatus": "derived",
        "authority": "supporting",
        "evidenceRefs": sorted({str(item) for item in evidence_refs if str(item)}),
        "assumptionIds": [],
        "generatedBy": {
            "kind": "deterministic",
            "generatorId": "functional-catalog-adapter",
            "version": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
        },
        "reviewStatus": "confirmed",
    }


def _source_record(
    source: Mapping[str, Any], repo_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id = str(source.get("source_id") or "")
    path_text = str(source.get("path") or "")
    target = (repo_root / path_text).resolve()
    available = target.is_file()
    recorded_hash = str(source.get("sha256") or "")
    if available:
        actual_hash = sha256_file(target)
        if actual_hash != recorded_hash:
            raise FunctionalCatalogAdapterError(
                f"Catalog source hash mismatch for {source_id}: {path_text}"
            )
        size = target.stat().st_size
    else:
        size = 0
    manifest = {
        "sourceId": source_id,
        "path": path_text,
        "sha256": recorded_hash,
        "size": int(size),
        "kind": _source_kind(str(source.get("type") or "")),
        "available": bool(available),
    }
    knowledge_status, authority = translate_legacy_authority(
        str(source.get("authority") or "")
    )
    evidence_id = stable_id("evidence", source_id, digest_length=24)
    evidence = {
        "evidenceId": evidence_id,
        "sourceType": _source_type(str(source.get("type") or "")),
        "authority": authority,
        "subjectRefs": [],
        "sourceRefs": [source_id],
        "details": {
            "catalogRecord": copy.deepcopy(dict(source)),
            "knowledgeStatus": knowledge_status,
            "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
        },
    }
    return manifest, evidence


def _evidence_fingerprint(source_revision: str, sources: list[dict[str, Any]]) -> str:
    return canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": source_revision,
            "sources": sorted(sources, key=lambda item: item["evidenceId"]),
        }
    )


def _evidence_refs_for_entity(
    record: Mapping[str, Any], evidence_by_source: Mapping[str, str]
) -> list[str]:
    refs = {
        str(ref)
        for feature in record.get("functional_features") or []
        if isinstance(feature, Mapping)
        for ref in feature.get("source_refs") or []
    }
    refs.update(str(ref) for ref in record.get("evidence_refs") or [])
    return sorted(evidence_by_source[ref] for ref in refs if ref in evidence_by_source)


def _identity_transform() -> dict[str, Any]:
    return {
        "translation": [0.0, 0.0, 0.0],
        "rotation": list(_IDENTITY_ROTATION),
        "scale": 1.0,
    }


def adapt_functional_catalog(
    graph: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> dict[str, dict[str, Any]]:
    """Build a complete, non-production AKP from a validated catalog."""

    report = validate_functional_relationship_graph(graph)
    if not report.ok:
        raise FunctionalCatalogAdapterError("; ".join(report.errors))
    matrix = functional_catalog_migration_matrix(graph)
    if matrix["unmappedSourceFields"]:
        raise FunctionalCatalogAdapterError(
            "Unmapped functional catalog fields: "
            + ", ".join(matrix["unmappedSourceFields"])
        )

    root = Path(repo_root).resolve()
    assembly = dict(graph.get("assembly") or {})
    product_id = str(assembly.get("part_number") or "").strip()
    if not product_id:
        raise FunctionalCatalogAdapterError("Catalog assembly part number is missing.")
    configuration = str(assembly.get("configuration") or "Default")
    catalog_sources = _rows(graph.get("source_evidence"))
    source_revision = canonical_json_sha256(
        {
            "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
            "graph": graph,
            "sourceHashes": {
                str(item.get("source_id")): str(item.get("sha256"))
                for item in catalog_sources
            },
        }
    )

    manifest_sources: list[dict[str, Any]] = []
    evidence_sources: list[dict[str, Any]] = []
    evidence_by_source: dict[str, str] = {}
    for ordinal, source in enumerate(catalog_sources):
        manifest, evidence = _source_record(source, root)
        evidence["details"]["ordinal"] = ordinal
        manifest_sources.append(manifest)
        evidence_sources.append(evidence)
        evidence_by_source[manifest["sourceId"]] = evidence["evidenceId"]
    assembly_source = next(
        (
            item
            for item in manifest_sources
            if item["sourceId"] == f"assembly:{product_id}"
        ),
        manifest_sources[0] if manifest_sources else None,
    )
    if assembly_source is None:
        raise FunctionalCatalogAdapterError("Catalog has no source evidence.")

    root_occurrence_id = stable_id(
        "occ", {"productId": product_id, "kind": "root"}, digest_length=24
    )
    instance_rows = _rows(graph.get("component_instances"))
    occurrence_by_instance = {
        str(item.get("instance_id")): stable_id(
            "occ",
            {"productId": product_id, "instanceId": item.get("instance_id")},
            digest_length=24,
        )
        for item in instance_rows
    }
    component_types = {
        str(item.get("part_number")): item
        for item in _rows(graph.get("component_types"))
    }
    source_by_id = {item["sourceId"]: item for item in manifest_sources}
    occurrences = [
        {
            "occurrenceId": root_occurrence_id,
            "sourceOccurrenceId": stable_id("sourceocc", product_id, digest_length=24),
            "parentOccurrenceId": None,
            "itemId": product_id,
            "name": str(assembly.get("name") or product_id),
            "kind": "assembly",
            "level": 0,
            "sourceId": assembly_source["sourceId"],
            "sourcePath": assembly_source["path"],
            "sourceHash": assembly_source["sha256"],
            "configuration": configuration,
            "quantity": 1,
            "state": {
                "resolved": True,
                "lightweight": False,
                "suppressed": False,
                "hidden": None,
                "virtual": False,
            },
            "transform": _identity_transform(),
            "properties": {"functionalCatalogRoot": True},
        }
    ]

    def level_for(instance: Mapping[str, Any]) -> int:
        level = 1
        parent = instance.get("parent_instance_id")
        seen: set[str] = set()
        by_id = {str(item.get("instance_id")): item for item in instance_rows}
        while parent not in (None, "") and str(parent) not in seen:
            seen.add(str(parent))
            level += 1
            parent_row = by_id.get(str(parent))
            if parent_row is None:
                break
            parent = parent_row.get("parent_instance_id")
        return level

    for instance in instance_rows:
        instance_id = str(instance.get("instance_id") or "")
        part_number = str(instance.get("part_number") or "").strip()
        component_type = component_types.get(part_number, {})
        source_id = f"profile:{part_number}" if part_number else assembly_source["sourceId"]
        source = source_by_id.get(source_id, assembly_source)
        parent_id = str(instance.get("parent_instance_id") or "")
        occurrences.append(
            {
                "occurrenceId": occurrence_by_instance[instance_id],
                "sourceOccurrenceId": stable_id("sourceocc", instance_id, digest_length=24),
                "parentOccurrenceId": occurrence_by_instance.get(
                    parent_id, root_occurrence_id
                ),
                "itemId": part_number or stable_id("item", instance_id, digest_length=16),
                "name": str(
                    component_type.get("name")
                    or instance.get("source_component_name")
                    or instance_id
                ),
                "kind": "part" if part_number else "subassembly",
                "level": level_for(instance),
                "sourceId": source["sourceId"],
                "sourcePath": source["path"],
                "sourceHash": source["sha256"],
                "configuration": configuration,
                "quantity": 1,
                "state": {
                    "resolved": True,
                    "lightweight": False,
                    "suppressed": False,
                    "hidden": None,
                    "virtual": False,
                },
                "transform": None,
                "properties": {"functionalCatalogRecord": copy.deepcopy(instance)},
            }
        )

    interface_rows = _rows(graph.get("interfaces"))
    akp_interfaces = []
    for item in interface_rows:
        occurrence_refs = [
            occurrence_by_instance[str(participant.get("participant_id"))]
            for participant in item.get("participants") or []
            if isinstance(participant, Mapping)
            and str(participant.get("participant_id")) in occurrence_by_instance
        ]
        geometry_refs = sorted(
            {
                str(ref)
                for participant in item.get("participants") or []
                if isinstance(participant, Mapping)
                for ref in participant.get("feature_refs") or []
            }
        )
        akp_interfaces.append(
            {
                "interfaceId": str(item.get("interface_id")),
                "occurrenceRefs": occurrence_refs,
                "mateRefs": [],
                "geometryRefs": geometry_refs,
                "status": "derived"
                if item.get("review_status") == "verified"
                else "candidate",
            }
        )

    all_evidence = sorted(evidence_by_source.values())
    claims: list[dict[str, Any]] = []
    claims.append(
        _claim(
            predicate="functional_catalog_metadata",
            subject_ref=root_occurrence_id,
            object_refs=[],
            value={
                "ordinal": 0,
                "record": {
                    "schema_version": graph.get("schema_version"),
                    "graph_id": graph.get("graph_id"),
                    "version": graph.get("version"),
                    "assembly": copy.deepcopy(assembly),
                },
            },
            evidence_refs=all_evidence,
        )
    )
    occurrences_by_part: dict[str, list[str]] = {}
    for instance in instance_rows:
        part_number = str(instance.get("part_number") or "").strip()
        if part_number:
            occurrences_by_part.setdefault(part_number, []).append(
                occurrence_by_instance[str(instance.get("instance_id"))]
            )
    for ordinal, item in enumerate(_rows(graph.get("component_types"))):
        claims.append(
            _claim(
                predicate="component_type_definition",
                subject_ref=root_occurrence_id,
                object_refs=occurrences_by_part.get(str(item.get("part_number")), []),
                value={"ordinal": ordinal, "record": item},
                evidence_refs=_evidence_refs_for_entity(item, evidence_by_source),
            )
        )
    for ordinal, item in enumerate(instance_rows):
        instance_id = str(item.get("instance_id"))
        claims.append(
            _claim(
                predicate="component_instance_definition",
                subject_ref=occurrence_by_instance[instance_id],
                object_refs=[],
                value={"ordinal": ordinal, "record": item},
                evidence_refs=[evidence_by_source[assembly_source["sourceId"]]],
            )
        )
    for ordinal, item in enumerate(_rows(graph.get("external_entities"))):
        claims.append(
            _claim(
                predicate="external_entity_definition",
                subject_ref=root_occurrence_id,
                object_refs=[],
                value={"ordinal": ordinal, "record": item},
                evidence_refs=_evidence_refs_for_entity(item, evidence_by_source),
            )
        )
    interface_by_id = {item["interfaceId"]: item for item in akp_interfaces}
    for ordinal, item in enumerate(interface_rows):
        evidence_refs = [
            evidence_by_source[str(evidence.get("source_ref"))]
            for evidence in item.get("evidence") or []
            if isinstance(evidence, Mapping)
            and str(evidence.get("source_ref")) in evidence_by_source
        ]
        interface_id = str(item.get("interface_id"))
        claims.append(
            _claim(
                predicate="functional_interface_definition",
                subject_ref=interface_id,
                object_refs=interface_by_id[interface_id]["occurrenceRefs"],
                value={"ordinal": ordinal, "record": item},
                evidence_refs=evidence_refs,
            )
        )
    claims.append(
        _claim(
            predicate="functional_coverage_snapshot",
            subject_ref=root_occurrence_id,
            object_refs=[],
            value={"ordinal": 0, "record": copy.deepcopy(dict(graph.get("coverage") or {}))},
            evidence_refs=[evidence_by_source[assembly_source["sourceId"]]],
        )
    )
    claims.sort(key=lambda item: item["claimId"])

    evidence_sources.sort(key=lambda item: item["evidenceId"])
    evidence_fingerprint = _evidence_fingerprint(source_revision, evidence_sources)
    package_id = make_package_id(
        product_id,
        source_revision,
        configuration,
        FUNCTIONAL_CATALOG_ADAPTER_VERSION,
    )
    source_manifest = {
        "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
        "productId": product_id,
        "rootAssembly": copy.deepcopy(assembly_source),
        "configuration": {"active": configuration, "available": [configuration]},
        "sources": sorted(manifest_sources, key=lambda item: item["sourceId"]),
        "extractor": {
            "name": "FunctionalRelationshipRegistry",
            "version": str(graph.get("version") or "unknown"),
            "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
            "packageSchemaVersion": str(ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION),
            "solidWorksVersion": "not-applicable",
        },
        "sourceRevision": source_revision,
        "preflightFingerprint": canonical_json_sha256(matrix),
        "findings": [],
    }
    documents: dict[str, dict[str, Any]] = {
        "package.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "packageId": package_id,
            "productId": product_id,
            "sourceRevision": source_revision,
            "packageRevision": "0" * 64,
            "extractorVersion": str(graph.get("version") or "unknown"),
            "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
            "bridgePackageSchemaVersion": "functional-catalog-v1",
            "enrichmentPolicyVersion": "semantic-prototype-v1",
            "promptVersion": "none",
            "modelProvider": None,
            "modelId": None,
            "readiness": "function_ready",
            "productionEligible": False,
            "documentHashes": {},
            "assetHashes": {},
        },
        "source_manifest.json": source_manifest,
        "product_structure.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "productId": product_id,
            "sourceRevision": source_revision,
            "configuration": configuration,
            "rootOccurrenceId": root_occurrence_id,
            "occurrences": occurrences,
        },
        "interface_graph.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "mates": [],
            "interfaces": akp_interfaces,
        },
        "geometry_summary.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "occurrences": [],
            "findings": [],
        },
        "visual_manifest.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "views": [],
            "contactSheets": [],
            "findings": [],
        },
        "functional_context.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "claims": claims,
            "relationships": [
                {
                    "interfaceId": item["interfaceId"],
                    "occurrenceRefs": list(item["occurrenceRefs"]),
                }
                for item in akp_interfaces
            ],
        },
        "process_candidates.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "claims": [],
            "branches": [],
            "intermediateResults": [],
            "operationFamilies": [],
            "assumptions": [],
            "unresolvedQuestions": [],
        },
        "evidence_catalog.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "sources": evidence_sources,
        },
        "unresolved.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "findings": [],
            "assumptions": [],
            "questions": [],
        },
        "review_receipt.json": {
            "schemaVersion": ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION,
            "sourceRevision": source_revision,
            "packageRevision": "0" * 64,
            "events": [],
        },
    }
    documents = refresh_package_revision(documents)
    errors = [
        item
        for item in validate_assembly_knowledge_package(documents)
        if item.get("severity") == "error"
    ]
    if errors:
        raise FunctionalCatalogAdapterError(
            "; ".join(str(item.get("code")) for item in errors[:12])
        )
    return documents


def _claim_records(
    documents: Mapping[str, Mapping[str, Any]], predicate: str
) -> list[dict[str, Any]]:
    records: list[tuple[int, dict[str, Any]]] = []
    for claim in documents.get("functional_context.json", {}).get("claims", []):
        if not isinstance(claim, Mapping) or claim.get("predicate") != predicate:
            continue
        value = claim.get("value")
        if not isinstance(value, Mapping) or not isinstance(value.get("record"), Mapping):
            raise FunctionalCatalogAdapterError(
                f"Malformed {predicate} claim in package."
            )
        records.append((int(value.get("ordinal") or 0), copy.deepcopy(dict(value["record"]))))
    records.sort(key=lambda item: item[0])
    return [item[1] for item in records]


def reconstruct_functional_catalog(
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    metadata = _claim_records(documents, "functional_catalog_metadata")
    if len(metadata) != 1:
        raise FunctionalCatalogAdapterError("Package has no unique catalog metadata claim.")
    evidence_rows: list[tuple[int, dict[str, Any]]] = []
    for source in documents.get("evidence_catalog.json", {}).get("sources", []):
        if not isinstance(source, Mapping):
            continue
        details = source.get("details")
        record = details.get("catalogRecord") if isinstance(details, Mapping) else None
        if isinstance(record, Mapping):
            evidence_rows.append((int(details.get("ordinal") or 0), copy.deepcopy(dict(record))))
    evidence_rows.sort(key=lambda item: item[0])
    record = metadata[0]
    return {
        "schema_version": record.get("schema_version"),
        "graph_id": record.get("graph_id"),
        "version": record.get("version"),
        "assembly": copy.deepcopy(record.get("assembly") or {}),
        "source_evidence": [item[1] for item in evidence_rows],
        "component_types": _claim_records(documents, "component_type_definition"),
        "component_instances": _claim_records(documents, "component_instance_definition"),
        "external_entities": _claim_records(documents, "external_entity_definition"),
        "interfaces": _claim_records(documents, "functional_interface_definition"),
        "coverage": _claim_records(documents, "functional_coverage_snapshot")[0],
    }


def catalog_parity_report(
    source: Mapping[str, Any], reconstructed: Mapping[str, Any]
) -> dict[str, Any]:
    source_inventory = catalog_inventory(source)
    reconstructed_inventory = catalog_inventory(reconstructed)
    part_numbers = sorted(
        str(item.get("part_number"))
        for item in _rows(source.get("component_types"))
    )
    context_results = []
    for part_number in part_numbers:
        before = build_functional_context(source, part_number=part_number)
        after = build_functional_context(reconstructed, part_number=part_number)
        context_results.append(
            {
                "partNumber": part_number,
                "sourceHash": canonical_json_sha256(before),
                "packageHash": canonical_json_sha256(after),
                "passed": before == after,
            }
        )
    return {
        "adapterVersion": FUNCTIONAL_CATALOG_ADAPTER_VERSION,
        "sourceHash": canonical_json_sha256(source),
        "reconstructedHash": canonical_json_sha256(reconstructed),
        "exactGraphParity": source == reconstructed,
        "sourceInventory": source_inventory,
        "reconstructedInventory": reconstructed_inventory,
        "inventoryParity": source_inventory == reconstructed_inventory,
        "contextCases": context_results,
        "contextParity": all(item["passed"] for item in context_results),
        "passed": source == reconstructed
        and source_inventory == reconstructed_inventory
        and all(item["passed"] for item in context_results),
    }


def _words(value: Any) -> set[str]:
    return set(_WORD_RE.findall(str(value or "").lower()))


def lookup_functional_terms(
    graph: Mapping[str, Any], query: str
) -> list[dict[str, Any]]:
    query_words = _words(query)
    if not query_words:
        return []
    matches = []
    for collection, identifier_field in (
        ("component_types", "part_number"),
        ("external_entities", "entity_id"),
    ):
        for entity in _rows(graph.get(collection)):
            entity_ref = str(entity.get(identifier_field) or "")
            for feature in _rows(entity.get("functional_features")):
                terms = [
                    str(feature.get("label") or ""),
                    *[str(item) for item in feature.get("aliases") or []],
                    *[str(item).replace("_", " ") for item in feature.get("semantic_tags") or []],
                ]
                best: tuple[float, str] | None = None
                for term in terms:
                    term_words = _words(term)
                    if not term_words:
                        continue
                    if term_words == query_words:
                        score = 1.0
                    elif term_words <= query_words:
                        score = len(term_words) / len(query_words)
                    else:
                        overlap = len(term_words & query_words)
                        score = overlap / len(term_words | query_words)
                    if score >= 0.5 and (best is None or score > best[0]):
                        best = (score, term)
                if best is not None:
                    matches.append(
                        {
                            "entityRef": entity_ref,
                            "entityKind": "component_type"
                            if collection == "component_types"
                            else "external_entity",
                            "featureRef": feature.get("feature_ref"),
                            "matchedTerm": best[1],
                            "score": round(best[0], 6),
                        }
                    )
    matches.sort(key=lambda item: (-item["score"], item["entityRef"], str(item["featureRef"])))
    return matches


def publish_functional_catalog_package(
    *,
    graph: Mapping[str, Any],
    repo_root: str | Path,
    training_root: str | Path,
) -> dict[str, Any]:
    documents = adapt_functional_catalog(graph, repo_root=repo_root)
    package = documents["package.json"]
    repository = AssemblyKnowledgeRepository(training_root)
    package_dir = repository.package_dir(
        str(package["productId"]), str(package["packageId"])
    )
    if package_dir.is_dir():
        current = repository.read(
            str(package["productId"]), str(package["packageId"])
        )
        if (
            current["package.json"]["packageRevision"]
            == package["packageRevision"]
        ):
            revision = str(package["packageRevision"])
        else:
            revision = repository.write(
                documents,
                base_revision=current["package.json"]["packageRevision"],
            )
    else:
        revision = repository.write(documents)
    source_status = repository.bind_source_root(
        str(package["productId"]), str(package["packageId"]), repo_root
    )
    reconstructed = reconstruct_functional_catalog(documents)
    return {
        "success": True,
        "productId": package["productId"],
        "packageId": package["packageId"],
        "packageRevision": revision,
        "sourceStatus": source_status,
        "migrationMatrix": functional_catalog_migration_matrix(graph),
        "parity": catalog_parity_report(graph, reconstructed),
    }
