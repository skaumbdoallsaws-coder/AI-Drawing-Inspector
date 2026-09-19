"""Package-backed functional context with measured catalog compatibility."""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Optional, Sequence

from ai_inspector.product_intelligence.functional_relationships import (
    FunctionalRelationshipError,
    FunctionalRelationshipRegistry,
    build_functional_context,
    validate_functional_relationship_graph,
)

from .functional_catalog import reconstruct_functional_catalog
from .repository import AssemblyKnowledgeRepository, AssemblyKnowledgeRepositoryError
from .semantic_contract import bounded_retrieval_claims, package_retrieval_decision


PACKAGE_FUNCTIONAL_PROVIDER_VERSION = "package-functional-context-v1"
_READINESS_RANK = {
    "structure_ready": 1,
    "function_ready": 2,
    "planning_ready": 3,
    "production_ready": 4,
}


class PackageFunctionalContextProvider:
    """Resolve package semantics first while retaining a catalog fallback."""

    def __init__(
        self,
        training_root: str | Path,
        *,
        catalog_registry: FunctionalRelationshipRegistry | None = None,
    ):
        self.training_root = Path(training_root).resolve()
        self.repository = AssemblyKnowledgeRepository(self.training_root)
        self.catalog_registry = catalog_registry or FunctionalRelationshipRegistry()
        self._resolution_cache: dict[str, tuple[str, str, str] | None] = {}
        self._documents_cache: dict[
            tuple[str, str], tuple[tuple[int, int], dict[str, Any]]
        ] = {}
        self._source_status_cache: dict[
            tuple[str, str, str], tuple[tuple[Any, ...], dict[str, Any]]
        ] = {}
        self._lock = RLock()

    def clear_cache(self) -> None:
        with self._lock:
            self._resolution_cache.clear()
            self._documents_cache.clear()
            self._source_status_cache.clear()

    def _read_documents(self, product_id: str, package_id: str) -> dict[str, Any]:
        index_path = self.repository.package_dir(product_id, package_id) / "package.json"
        stat = index_path.stat()
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        key = (product_id, package_id)
        with self._lock:
            cached = self._documents_cache.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]
        documents = self.repository.read(product_id, package_id)
        with self._lock:
            self._documents_cache[key] = (signature, documents)
        return documents

    def _source_signature(
        self,
        product_id: str,
        package_id: str,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> tuple[Any, ...]:
        package_dir = self.repository.package_dir(product_id, package_id)
        binding_path = package_dir / ".source-root.json"
        try:
            binding_stat = binding_path.stat()
            binding = json.loads(binding_path.read_text("ascii"))
            source_root = Path(str(binding["sourceRoot"])).resolve()
            signature: list[Any] = [
                int(binding_stat.st_mtime_ns),
                int(binding_stat.st_size),
                str(source_root),
            ]
        except Exception:
            return ("binding_unavailable",)
        for record in documents.get("source_manifest.json", {}).get("sources", []):
            if not isinstance(record, Mapping) or record.get("available") is False:
                continue
            target = source_root / str(record.get("path") or "")
            try:
                stat = target.stat()
                signature.extend(
                    (str(target), int(stat.st_mtime_ns), int(stat.st_size))
                )
            except OSError:
                signature.extend((str(target), None, None))
        return tuple(signature)

    def _source_status(
        self,
        product_id: str,
        package_id: str,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        revision = str(documents["package.json"]["packageRevision"])
        key = (product_id, package_id, revision)
        signature = self._source_signature(
            product_id, package_id, documents
        )
        with self._lock:
            cached = self._source_status_cache.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]
        status = self.repository.source_status(product_id, package_id)
        with self._lock:
            self._source_status_cache[key] = (signature, status)
        return status

    def _resolve_package(self, assembly_number: str) -> tuple[str, str, dict[str, Any]] | None:
        normalized = str(assembly_number or "").strip().lower()
        if not normalized:
            return None
        with self._lock:
            cached = self._resolution_cache.get(normalized)
        if cached is not None:
            product_id, package_id, revision = cached
            documents = self._read_documents(product_id, package_id)
            if documents["package.json"]["packageRevision"] == revision:
                return product_id, package_id, documents
            with self._lock:
                self._resolution_cache.pop(normalized, None)

        candidates: list[tuple[int, int, str, str, dict[str, Any]]] = []
        if not self.training_root.is_dir():
            return None
        for product_root in sorted(self.training_root.iterdir(), key=lambda path: path.name):
            if not product_root.is_dir():
                continue
            product_id = product_root.name
            try:
                package_rows = self.repository.list_packages(product_id)
            except AssemblyKnowledgeRepositoryError:
                continue
            for row in package_rows:
                package_id = str(row["packageId"])
                documents = self._read_documents(product_id, package_id)
                package = documents["package.json"]
                root_id = documents["product_structure.json"].get("rootOccurrenceId")
                root = next(
                    (
                        item
                        for item in documents["product_structure.json"].get("occurrences", [])
                        if isinstance(item, Mapping)
                        and item.get("occurrenceId") == root_id
                    ),
                    {},
                )
                identities = {
                    product_id.lower(),
                    str(root.get("itemId") or "").strip().lower(),
                    str(root.get("name") or "").strip().lower(),
                    str(
                        documents.get("source_manifest.json", {}).get("productId")
                        or ""
                    ).strip().lower(),
                }
                exact = 2 if normalized in identities else 0
                contains = 1 if any(normalized in value for value in identities if value) else 0
                if not exact and not contains:
                    continue
                candidates.append(
                    (
                        exact + contains,
                        _READINESS_RANK.get(str(package.get("readiness")), 0),
                        product_id,
                        package_id,
                        documents,
                    )
                )
        if not candidates:
            with self._lock:
                self._resolution_cache[normalized] = None
            return None
        _, _, product_id, package_id, documents = sorted(
            candidates,
            key=lambda item: (-item[0], -item[1], item[2], item[3]),
        )[0]
        with self._lock:
            self._resolution_cache[normalized] = (
                product_id,
                package_id,
                str(documents["package.json"]["packageRevision"]),
            )
        return product_id, package_id, documents

    @staticmethod
    def _available_parts(documents: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
        by_number: dict[str, str] = {}
        for item in documents.get("product_structure.json", {}).get("occurrences", []):
            if not isinstance(item, Mapping) or item.get("kind") == "assembly":
                continue
            part_number = str(item.get("itemId") or "").strip()
            if not part_number or part_number.startswith("item-"):
                continue
            name = str(item.get("name") or "").split("/")[-1].strip()
            by_number.setdefault(part_number, name)
        return [
            {"part_number": part_number, "description": by_number[part_number]}
            for part_number in sorted(by_number)
        ]

    @staticmethod
    def _source_references(
        documents: Mapping[str, Mapping[str, Any]],
        claims: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence = {
            item["evidenceId"]: item
            for item in documents.get("evidence_catalog.json", {}).get("sources", [])
            if isinstance(item, Mapping) and isinstance(item.get("evidenceId"), str)
        }
        manifest = {
            item["sourceId"]: item
            for item in documents.get("source_manifest.json", {}).get("sources", [])
            if isinstance(item, Mapping) and isinstance(item.get("sourceId"), str)
        }
        references: dict[str, dict[str, Any]] = {}
        for claim in claims:
            for evidence_id in claim.get("evidenceRefs", []):
                row = evidence.get(str(evidence_id))
                if not isinstance(row, Mapping):
                    continue
                details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
                source_rows = [
                    manifest[ref]
                    for ref in row.get("sourceRefs", [])
                    if ref in manifest
                ]
                references[str(evidence_id)] = {
                    "evidenceId": evidence_id,
                    "authority": row.get("authority"),
                    "sourceType": row.get("sourceType"),
                    "title": details.get("title") or details.get("candidateKind"),
                    "paths": sorted(
                        {
                            str(source.get("path"))
                            for source in source_rows
                            if source.get("path")
                        }
                    ),
                    "sourceIds": sorted(
                        {
                            str(source.get("sourceId"))
                            for source in source_rows
                            if source.get("sourceId")
                        }
                    ),
                }
        return [references[key] for key in sorted(references)]

    @staticmethod
    def _native_package_context(
        documents: Mapping[str, Mapping[str, Any]],
        *,
        assembly_number: str,
        part_number: str | None,
        prototype_mode: bool,
        controlled_use: bool,
        source_current: bool,
        include_available_parts: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        occurrences = [
            item
            for item in documents["product_structure.json"].get("occurrences", [])
            if isinstance(item, Mapping)
        ]
        requested_part = str(part_number or "").strip()
        occurrence_ids = {
            str(item.get("occurrenceId"))
            for item in occurrences
            if requested_part
            and str(item.get("itemId") or "").strip() == requested_part
        }
        relevant_interfaces = [
            item
            for item in documents["interface_graph.json"].get("interfaces", [])
            if isinstance(item, Mapping)
            and (
                not occurrence_ids
                or occurrence_ids
                & {
                    str(ref)
                    for ref in item.get("occurrenceRefs", [])
                    if isinstance(ref, str)
                }
            )
        ]
        subject_refs = set(occurrence_ids)
        subject_refs.update(
            str(item.get("interfaceId"))
            for item in relevant_interfaces
            if isinstance(item.get("interfaceId"), str)
        )
        claims, retrieval = bounded_retrieval_claims(
            documents,
            prototype_mode=prototype_mode,
            controlled_use=controlled_use,
            source_current=source_current,
            subject_refs=subject_refs or None,
        )
        names = {
            str(item.get("occurrenceId")): {
                "part_number": item.get("itemId"),
                "name": str(item.get("name") or "").split("/")[-1],
            }
            for item in occurrences
            if isinstance(item.get("occurrenceId"), str)
        }
        relationship_rows = []
        for row in documents["functional_context.json"].get("relationships", []):
            if not isinstance(row, Mapping):
                continue
            refs = [str(ref) for ref in row.get("occurrenceRefs", [])]
            if occurrence_ids and not (occurrence_ids & set(refs)):
                continue
            relationship_rows.append(
                {
                    "pattern_id": row.get("relationshipId") or row.get("interfaceId"),
                    "name": row.get("description") or row.get("relationshipType") or "CAD interface",
                    "interface_classification": row.get("relationshipType") or "cad_constraint",
                    "participants": [
                        {
                            "part_number": names.get(ref, {}).get("part_number"),
                            "name": names.get(ref, {}).get("name") or ref,
                            "role": "interface participant",
                            "external": False,
                            "presence": "present",
                        }
                        for ref in refs
                    ],
                    "qualitative_requirements": [],
                    "confidence": None,
                    "review_status": row.get("reviewStatus") or "derived",
                    "missing_external_evidence": [],
                    "evidence_refs": list(row.get("evidenceRefs", [])),
                }
            )
            if len(relationship_rows) >= 16:
                break
        package = documents["package.json"]
        context: dict[str, Any] = {
            "functional_relationship_summary": {
                "graph_id": f"assembly-knowledge:{package['packageId']}",
                "graph_version": package["packageRevision"],
                "assembly_number": assembly_number,
                "assembly_name": next(
                    (
                        str(item.get("name"))
                        for item in occurrences
                        if item.get("occurrenceId")
                        == documents["product_structure.json"].get("rootOccurrenceId")
                    ),
                    assembly_number,
                ),
                "inspected_part_number": requested_part or None,
                "interface_pattern_count": len(relationship_rows),
                "physical_instance_count": len(occurrences) - 1,
                "covered_instance_count": len(
                    {
                        ref
                        for row in relevant_interfaces
                        for ref in row.get("occurrenceRefs", [])
                    }
                ),
                "external_entities": [],
            },
            "functional_relationships": relationship_rows,
            "affected_functional_interfaces": [],
            "functional_relationship_provenance": [
                {
                    "evidence_id": reference["evidenceId"],
                    "classification": reference["authority"],
                    "value": reference["title"],
                    "source_refs": reference["sourceIds"],
                    "source_paths": reference["paths"],
                }
                for reference in PackageFunctionalContextProvider._source_references(
                    documents, claims
                )
            ],
            "assembly_semantic_claims": claims,
            "assembly_semantic_sources": PackageFunctionalContextProvider._source_references(
                documents, claims
            ),
        }
        if include_available_parts:
            context["available_parts"] = PackageFunctionalContextProvider._available_parts(
                documents
            )
        return context, retrieval

    def _catalog_context(
        self,
        assembly_number: str,
        *,
        part_number: str | None,
        fai_characteristics: Sequence[Mapping[str, Any]],
        include_available_parts: bool,
        assembly_data: Mapping[str, Any] | None,
        strict: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        graph, report = self.catalog_registry.load(
            assembly_number,
            assembly_data=assembly_data,
            strict=strict,
        )
        context = build_functional_context(
            graph,
            part_number=part_number,
            fai_characteristics=fai_characteristics,
        )
        if include_available_parts:
            context["available_parts"] = [
                {
                    "part_number": str(item.get("part_number") or "").strip(),
                    "description": str(item.get("name") or item.get("description") or "").strip(),
                }
                for item in graph.get("component_types", [])
                if isinstance(item, Mapping) and str(item.get("part_number") or "").strip()
            ]
            context["available_parts"].sort(key=lambda item: item["part_number"])
        return context, report.as_dict(), graph

    def context_for_asset(
        self,
        *,
        assembly_number: str,
        part_number: str | None = None,
        fai_characteristics: Sequence[Mapping[str, Any]] = (),
        include_available_parts: bool = False,
        assembly_data: Mapping[str, Any] | None = None,
        strict: bool = True,
        prototype_mode: bool = False,
        controlled_use: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.perf_counter()
        resolved = self._resolve_package(assembly_number)
        package_diagnostics: dict[str, Any] = {
            "providerVersion": PACKAGE_FUNCTIONAL_PROVIDER_VERSION,
            "packageFound": resolved is not None,
            "prototypeMode": bool(prototype_mode),
            "controlledUse": bool(controlled_use),
        }
        if resolved is not None:
            product_id, package_id, documents = resolved
            source_status = self._source_status(product_id, package_id, documents)
            decision = package_retrieval_decision(
                documents["package.json"],
                prototype_mode=prototype_mode,
                controlled_use=controlled_use,
                source_current=bool(source_status["current"]),
            )
            package_diagnostics.update(
                {
                    "productId": product_id,
                    "packageId": package_id,
                    "packageRevision": documents["package.json"]["packageRevision"],
                    "readiness": documents["package.json"]["readiness"],
                    "productionEligible": documents["package.json"]["productionEligible"],
                    "sourceStatus": source_status,
                    "eligibility": {
                        "eligible": decision.eligible,
                        "code": decision.code,
                        "message": decision.message,
                    },
                }
            )
            if decision.eligible:
                try:
                    graph = reconstruct_functional_catalog(documents)
                except Exception:
                    graph = None
                if graph is not None:
                    report = validate_functional_relationship_graph(
                        graph, assembly_data=assembly_data
                    )
                    if not strict or report.ok:
                        context = build_functional_context(
                            graph,
                            part_number=part_number,
                            fai_characteristics=fai_characteristics,
                        )
                        if include_available_parts:
                            context["available_parts"] = self._available_parts(documents)
                        package_diagnostics.update(
                            {
                                "provider": "assembly_knowledge_package_catalog_adapter",
                                "fallbackUsed": False,
                                "validation": report.as_dict(),
                                "latencyMs": round((time.perf_counter() - started) * 1000, 3),
                            }
                        )
                        return context, package_diagnostics
                context, retrieval = self._native_package_context(
                    documents,
                    assembly_number=assembly_number,
                    part_number=part_number,
                    prototype_mode=prototype_mode,
                    controlled_use=controlled_use,
                    source_current=bool(source_status["current"]),
                    include_available_parts=include_available_parts,
                )
                package_diagnostics.update(
                    {
                        "provider": "assembly_knowledge_package_native",
                        "fallbackUsed": False,
                        "retrieval": retrieval,
                        "latencyMs": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
                return context, package_diagnostics

        try:
            context, report, _ = self._catalog_context(
                assembly_number,
                part_number=part_number,
                fai_characteristics=fai_characteristics,
                include_available_parts=include_available_parts,
                assembly_data=assembly_data,
                strict=strict,
            )
        except FunctionalRelationshipError:
            if resolved is not None:
                raise FunctionalRelationshipError(
                    "Assembly Knowledge Package is not retrieval-eligible and no "
                    f"catalog fallback exists ({package_diagnostics.get('eligibility', {}).get('code')})."
                )
            raise
        package_diagnostics.update(
            {
                "provider": "functional_catalog_fallback",
                "fallbackUsed": True,
                "validation": report,
                "latencyMs": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        return context, package_diagnostics

    def graph_for_assembly(
        self,
        assembly_number: str,
        *,
        assembly_data: Mapping[str, Any] | None = None,
        strict: bool = True,
        prototype_mode: bool = False,
    ) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        resolved = self._resolve_package(assembly_number)
        if resolved is not None:
            product_id, package_id, documents = resolved
            source_status = self._source_status(product_id, package_id, documents)
            decision = package_retrieval_decision(
                documents["package.json"],
                prototype_mode=prototype_mode,
                source_current=bool(source_status["current"]),
            )
            if decision.eligible:
                try:
                    graph = reconstruct_functional_catalog(documents)
                except Exception:
                    graph = None
                if graph is not None:
                    report = validate_functional_relationship_graph(
                        graph, assembly_data=assembly_data
                    )
                    if strict and not report.ok:
                        raise FunctionalRelationshipError("; ".join(report.errors))
                    return graph, report, {
                        "provider": "assembly_knowledge_package_catalog_adapter",
                        "fallbackUsed": False,
                        "packageRevision": documents["package.json"]["packageRevision"],
                    }
        graph, report = self.catalog_registry.load(
            assembly_number,
            assembly_data=assembly_data,
            strict=strict,
        )
        return graph, report, {
            "provider": "functional_catalog_fallback",
            "fallbackUsed": True,
        }


__all__ = [
    "PACKAGE_FUNCTIONAL_PROVIDER_VERSION",
    "PackageFunctionalContextProvider",
]
