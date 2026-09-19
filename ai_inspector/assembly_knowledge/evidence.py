"""Deterministic Assembly Knowledge evidence compiler."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .glb_masks import GlbMaskError, summarize_glb_occurrences
from .identity import finding_id
from .manifest import canonical_json_sha256, refresh_package_revision
from .visuals import occurrence_alias_map


EVIDENCE_COMPILER_VERSION = "1.0.0"
MAX_EVIDENCE_SOURCES = 5_000
MAX_DETERMINISTIC_CLAIMS = 5_000
MAX_EVIDENCE_BYTES = 5_000_000
_ALIGNMENT_PREDICATES = {
    "concentric": "concentric_alignment",
    "coincident": "coincident_alignment",
    "parallel": "parallel_alignment",
}
_FORBIDDEN_PROCESS_PREDICATES = {
    "manufacturing_order",
    "precedes",
    "assembly_sequence",
    "operation",
    "operation_family",
}


class EvidenceCompilationError(ValueError):
    pass


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _evidence(
    source_type: str,
    *,
    subject_refs: Iterable[str],
    source_refs: Iterable[str],
    details: Mapping[str, Any],
) -> Dict[str, Any]:
    subjects = sorted(set(str(value) for value in subject_refs if value))
    sources = sorted(set(str(value) for value in source_refs if value))
    normalized_details = copy.deepcopy(dict(details))
    identity = {
        "sourceType": source_type,
        "subjectRefs": subjects,
        "sourceRefs": sources,
        "details": normalized_details,
    }
    return {
        "evidenceId": _stable_id("evidence", identity),
        "sourceType": source_type,
        "authority": "supporting",
        "subjectRefs": subjects,
        "sourceRefs": sources,
        "details": normalized_details,
    }


def _claim(
    *,
    subject_ref: str,
    predicate: str,
    object_refs: Iterable[str],
    value: Any,
    evidence_refs: Iterable[str],
) -> Dict[str, Any]:
    if predicate in _FORBIDDEN_PROCESS_PREDICATES:
        raise EvidenceCompilationError(
            f"Deterministic compiler cannot emit process predicate: {predicate}"
        )
    objects = sorted(set(str(value) for value in object_refs if value))
    evidence = sorted(set(str(value) for value in evidence_refs if value))
    identity = {
        "subjectRef": subject_ref,
        "predicate": predicate,
        "objectRefs": objects,
        "value": value,
        "evidenceRefs": evidence,
        "version": EVIDENCE_COMPILER_VERSION,
    }
    return {
        "claimId": _stable_id("claim", identity),
        "subjectRef": subject_ref,
        "predicate": predicate,
        "objectRefs": objects,
        "value": copy.deepcopy(value),
        "knowledgeStatus": "derived",
        "authority": "supporting",
        "evidenceRefs": evidence,
        "assumptionIds": [],
        "generatedBy": {
            "kind": "deterministic",
            "generatorId": "assembly-knowledge-evidence-compiler",
            "version": EVIDENCE_COMPILER_VERSION,
        },
        "reviewStatus": "confirmed",
    }


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject_refs: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized = dict(details or {})
    refs = sorted(set(subject_refs))
    result: Dict[str, Any] = {
        "findingId": finding_id(code, subject_refs=refs, details=normalized),
        "severity": severity,
        "code": code,
        "message": message,
    }
    if refs:
        result["subjectRefs"] = refs
    if normalized:
        result["details"] = normalized
    return result


def _upsert_findings(
    existing: Iterable[Mapping[str, Any]],
    additions: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_id = {
        str(item["findingId"]): copy.deepcopy(dict(item))
        for item in existing
        if isinstance(item, dict) and item.get("findingId")
    }
    for item in additions:
        by_id[str(item["findingId"])] = copy.deepcopy(dict(item))
    return sorted(by_id.values(), key=lambda item: item["findingId"])


def _property_rows(occurrence: Mapping[str, Any]) -> Iterable[Tuple[str, Any]]:
    properties = occurrence.get("properties")
    if not isinstance(properties, dict):
        return ()
    rows = []
    for key, value in sorted(properties.items()):
        if key == "customProperties" and isinstance(value, dict):
            for custom_key, custom_value in sorted(value.items()):
                if custom_value not in (None, ""):
                    rows.append((f"custom.{custom_key}", custom_value))
        elif value not in (None, "", {}, []):
            rows.append((str(key), value))
    return rows


def _compile_geometry(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    package_dir: Path | None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    previous = copy.deepcopy(dict(documents["geometry_summary.json"]))
    findings = [
        copy.deepcopy(item)
        for item in previous.get("findings", [])
        if item.get("code") != "geometry_enrichment_pending"
    ]
    aliases = occurrence_alias_map(documents["product_structure.json"])
    summary_by_alias: Dict[str, Dict[str, Any]] = {}
    glb_relative = "visuals/assembly.glb"
    if (
        package_dir is not None
        and glb_relative in documents["package.json"].get("assetHashes", {})
    ):
        glb_path = package_dir / glb_relative
        try:
            summary_by_alias = summarize_glb_occurrences(glb_path)
        except (OSError, GlbMaskError) as exc:
            findings.append(
                _finding(
                    "warning",
                    "geometry_glb_summary_failed",
                    "Assembly GLB could not provide deterministic occurrence bounds.",
                    details={"error": str(exc)[:500]},
                )
            )
    rows = []
    root_id = documents["product_structure.json"]["rootOccurrenceId"]
    previous_by_id = {
        item.get("occurrenceId"): item
        for item in previous.get("occurrences", [])
        if isinstance(item, dict)
    }
    for occurrence in documents["product_structure.json"]["occurrences"]:
        occurrence_id = occurrence["occurrenceId"]
        prior = previous_by_id.get(occurrence_id, {})
        geometry = summary_by_alias.get(occurrence.get("name"))
        if occurrence_id == root_id:
            geometry = None
        rows.append(
            {
                "occurrenceId": occurrence_id,
                "bounds": copy.deepcopy(
                    geometry["bounds"] if geometry else prior.get("bounds", {})
                ),
                "massProperties": copy.deepcopy(prior.get("massProperties", {})),
                "featureSummary": (
                    {
                        "vertexCount": geometry["vertexCount"],
                        "triangleCount": geometry["triangleCount"],
                        "source": "assembly.glb",
                    }
                    if geometry
                    else copy.deepcopy(prior.get("featureSummary", {}))
                ),
                "candidateInterfaces": copy.deepcopy(
                    prior.get("candidateInterfaces", [])
                ),
            }
        )
    if not summary_by_alias:
        findings.append(
            _finding(
                "warning",
                "geometry_enrichment_pending",
                "Bounds and mesh summaries require a valid assembly GLB.",
            )
        )
    return (
        {
            "schemaVersion": 1,
            "sourceRevision": documents["package.json"]["sourceRevision"],
            "occurrences": rows,
            "findings": sorted(findings, key=lambda item: item["findingId"]),
        },
        findings,
    )


def compile_deterministic_evidence(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    package_dir: str | Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Compile trusted CAD facts without manufacturing-order inference."""
    updated = {name: copy.deepcopy(dict(value)) for name, value in documents.items()}
    source_revision = updated["package.json"]["sourceRevision"]
    geometry, geometry_findings = _compile_geometry(
        updated,
        package_dir=Path(package_dir) if package_dir is not None else None,
    )
    updated["geometry_summary.json"] = geometry

    occurrences = updated["product_structure.json"]["occurrences"]
    occurrences_by_id = {item["occurrenceId"]: item for item in occurrences}
    sources: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []

    for occurrence in sorted(occurrences, key=lambda item: item["occurrenceId"]):
        occurrence_id = occurrence["occurrenceId"]
        parent_id = occurrence.get("parentOccurrenceId")
        membership = _evidence(
            "assembly_structure",
            subject_refs=[occurrence_id],
            source_refs=[occurrence.get("sourceId"), parent_id],
            details={
                "fact": "component_membership",
                "parentOccurrenceId": parent_id,
                "quantity": occurrence.get("quantity", 1),
                "kind": occurrence.get("kind"),
            },
        )
        sources.append(membership)
        claims.append(
            _claim(
                subject_ref=occurrence_id,
                predicate="component_membership",
                object_refs=[parent_id] if parent_id else [],
                value={"quantity": occurrence.get("quantity", 1)},
                evidence_refs=[membership["evidenceId"]],
            )
        )
        transform = occurrence.get("transform")
        if isinstance(transform, dict):
            transform_evidence = _evidence(
                "geometry",
                subject_refs=[occurrence_id],
                source_refs=[occurrence.get("sourceId")],
                details={"fact": "relative_transform", "transform": transform},
            )
            sources.append(transform_evidence)
            claims.append(
                _claim(
                    subject_ref=occurrence_id,
                    predicate="relative_transform",
                    object_refs=[parent_id] if parent_id else [],
                    value=transform,
                    evidence_refs=[transform_evidence["evidenceId"]],
                )
            )
        for property_name, property_value in _property_rows(occurrence):
            property_evidence = _evidence(
                "property",
                subject_refs=[occurrence_id],
                source_refs=[occurrence.get("sourceId")],
                details={
                    "fact": "property_value",
                    "property": property_name,
                    "value": property_value,
                },
            )
            sources.append(property_evidence)
            claims.append(
                _claim(
                    subject_ref=occurrence_id,
                    predicate="property_value",
                    object_refs=[],
                    value={"property": property_name, "value": property_value},
                    evidence_refs=[property_evidence["evidenceId"]],
                )
            )

    by_source: Dict[str, List[str]] = {}
    for occurrence in occurrences:
        source_id = occurrence.get("sourceId")
        if source_id:
            by_source.setdefault(source_id, []).append(occurrence["occurrenceId"])
    for source_id, occurrence_ids in sorted(by_source.items()):
        if len(occurrence_ids) < 2:
            continue
        repeated = _evidence(
            "assembly_structure",
            subject_refs=occurrence_ids,
            source_refs=[source_id],
            details={"fact": "same_source_part", "occurrenceCount": len(occurrence_ids)},
        )
        sources.append(repeated)
        for occurrence_id in sorted(occurrence_ids):
            claims.append(
                _claim(
                    subject_ref=occurrence_id,
                    predicate="same_source_part",
                    object_refs=[
                        value for value in occurrence_ids if value != occurrence_id
                    ],
                    value=None,
                    evidence_refs=[repeated["evidenceId"]],
                )
            )

    evidence_by_mate: Dict[str, str] = {}
    for mate in sorted(
        updated["interface_graph.json"]["mates"],
        key=lambda item: item["mateId"],
    ):
        participants = sorted(set(mate.get("occurrenceRefs", [])))
        mate_type = mate.get("type") or mate.get("mateType")
        mate_evidence = _evidence(
            "mate_relationship",
            subject_refs=participants,
            source_refs=[mate["mateId"]],
            details={
                "fact": "mate_relationship",
                "mateType": mate_type,
                "displayName": mate.get("displayName"),
                "identityStrength": (
                    mate.get("identityStrength") or mate.get("identityStability")
                ),
                "suppressed": mate.get("suppressed", False),
            },
        )
        sources.append(mate_evidence)
        evidence_by_mate[mate["mateId"]] = mate_evidence["evidenceId"]
        for subject in sorted(participants):
            others = [value for value in participants if value != subject]
            claims.append(
                _claim(
                    subject_ref=subject,
                    predicate="mate_relationship",
                    object_refs=others,
                    value={"mateType": mate_type},
                    evidence_refs=[mate_evidence["evidenceId"]],
                )
            )
            predicate = _ALIGNMENT_PREDICATES.get(
                str(mate_type or "").lower()
            )
            if predicate:
                claims.append(
                    _claim(
                        subject_ref=subject,
                        predicate=predicate,
                        object_refs=others,
                        value=None,
                        evidence_refs=[mate_evidence["evidenceId"]],
                    )
                )

    relationships = []
    for interface in sorted(
        updated["interface_graph.json"]["interfaces"],
        key=lambda item: item["interfaceId"],
    ):
        evidence_refs = sorted(
            evidence_by_mate[mate_id]
            for mate_id in interface.get("mateRefs", [])
            if mate_id in evidence_by_mate
        )
        interface_evidence = _evidence(
            "mate_relationship",
            subject_refs=interface.get("occurrenceRefs", []),
            source_refs=[interface["interfaceId"], *interface.get("mateRefs", [])],
            details={
                "fact": "interface_adjacency_candidate",
                "doesNotEstablish": "manufacturing_order",
            },
        )
        sources.append(interface_evidence)
        evidence_refs.append(interface_evidence["evidenceId"])
        relationships.append(
            {
                "relationshipId": _stable_id(
                    "relationship",
                    {
                        "interfaceId": interface["interfaceId"],
                        "occurrenceRefs": interface.get("occurrenceRefs", []),
                    },
                ),
                "kind": "physical_interface_candidate",
                "occurrenceRefs": sorted(interface.get("occurrenceRefs", [])),
                "mateRefs": sorted(interface.get("mateRefs", [])),
                "evidenceRefs": sorted(set(evidence_refs)),
                "knowledgeStatus": "derived",
                "authority": "supporting",
            }
        )

    geometry_by_id = {
        item["occurrenceId"]: item
        for item in geometry["occurrences"]
        if item.get("bounds")
    }
    for occurrence_id, item in sorted(geometry_by_id.items()):
        geometry_evidence = _evidence(
            "geometry",
            subject_refs=[occurrence_id],
            source_refs=["asset:assembly-glb"],
            details={
                "fact": "geometry_bounds",
                "assetPath": "visuals/assembly.glb",
                "bounds": item["bounds"],
                "featureSummary": item["featureSummary"],
            },
        )
        sources.append(geometry_evidence)
        claims.append(
            _claim(
                subject_ref=occurrence_id,
                predicate="geometry_bounds_available",
                object_refs=[],
                value=item["bounds"],
                evidence_refs=[geometry_evidence["evidenceId"]],
            )
        )

    for view in sorted(
        updated["visual_manifest.json"].get("views", []),
        key=lambda item: item["viewId"],
    ):
        visible = [
            value
            for value in view.get("visibleOccurrenceIds", [])
            if value in occurrences_by_id
        ]
        if not visible:
            continue
        visual_evidence = _evidence(
            "visual",
            subject_refs=visible,
            source_refs=[view["viewId"]],
            details={
                "fact": "visible_together_in_view",
                "assetHash": view.get("assetHash"),
                "maskAssetHash": view.get("maskAssetHash"),
            },
        )
        sources.append(visual_evidence)
        claims.append(
            _claim(
                subject_ref=updated["product_structure.json"]["rootOccurrenceId"],
                predicate="visible_together_in_view",
                object_refs=visible,
                value={"viewId": view["viewId"]},
                evidence_refs=[visual_evidence["evidenceId"]],
            )
        )

    sources = sorted(sources, key=lambda item: item["evidenceId"])
    claims = sorted(claims, key=lambda item: item["claimId"])
    if len(sources) > MAX_EVIDENCE_SOURCES:
        raise EvidenceCompilationError("Evidence source budget exceeded.")
    if len(claims) > MAX_DETERMINISTIC_CLAIMS:
        raise EvidenceCompilationError("Deterministic claim budget exceeded.")
    evidence_bytes = len(
        json.dumps(
            sources,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )
    if evidence_bytes > MAX_EVIDENCE_BYTES:
        raise EvidenceCompilationError("Evidence byte budget exceeded.")
    evidence_fingerprint = canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": source_revision,
            "sources": sources,
        }
    )
    updated["evidence_catalog.json"] = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "sources": sources,
    }
    updated["functional_context.json"] = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "claims": claims,
        "relationships": relationships,
    }
    process_candidates = copy.deepcopy(updated["process_candidates.json"])
    process_candidates["evidenceFingerprint"] = evidence_fingerprint
    # P3 cannot derive process order, operations, or branches from CAD facts.
    process_candidates["claims"] = []
    process_candidates["branches"] = []
    process_candidates["intermediateResults"] = []
    process_candidates["operationFamilies"] = []
    process_candidates["assumptions"] = []
    process_candidates["unresolvedQuestions"] = []
    updated["process_candidates.json"] = process_candidates

    readiness_findings = [
        _finding(
            "warning",
            "manufacturing_sequence_not_established",
            "Assembly structure, mates, geometry, and names do not establish manufacturing order.",
            subject_refs=[updated["product_structure.json"]["rootOccurrenceId"]],
        ),
        _finding(
            "warning",
            "production_authority_missing",
            "CAD-only evidence does not provide approved process requirements.",
            subject_refs=[updated["product_structure.json"]["rootOccurrenceId"]],
        ),
    ]
    unresolved = copy.deepcopy(updated["unresolved.json"])
    unresolved["findings"] = _upsert_findings(
        unresolved.get("findings", []),
        [*geometry_findings, *readiness_findings],
    )
    updated["unresolved.json"] = unresolved
    updated["package.json"]["readiness"] = "function_ready"
    updated["package.json"]["productionEligible"] = False
    return refresh_package_revision(
        updated,
        asset_hashes=updated["package.json"].get("assetHashes", {}),
    )


def build_process_map_evidence_context(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    maximum_occurrences: int = 300,
    maximum_interfaces: int = 500,
    maximum_functional_claims: int = 160,
    maximum_relationships: int = 160,
    maximum_process_candidates: int = 160,
    maximum_views: int = 12,
    maximum_findings: int = 20,
    maximum_characters: int = 96_000,
) -> Dict[str, Any]:
    """Build a compact trusted context for Sage process-map planning."""
    from .validation import validate_assembly_knowledge_package

    validation_errors = [
        item
        for item in validate_assembly_knowledge_package(documents)
        if item.get("severity") == "error"
    ]
    if validation_errors:
        codes = ", ".join(
            sorted({str(item.get("code") or "invalid_package") for item in validation_errors})
        )
        raise EvidenceCompilationError(
            f"Assembly knowledge package is invalid: {codes}."
        )
    package = documents["package.json"]
    structure = documents["product_structure.json"]
    process_document = documents["process_candidates.json"]
    presentation = process_document.get("presentation")
    high_level_presentation = bool(
        isinstance(presentation, Mapping)
        and presentation.get("mode") == "high_level"
        and presentation.get("showOccurrenceInputs") is False
    )
    geometry_by_id = {
        item["occurrenceId"]: item
        for item in documents["geometry_summary.json"]["occurrences"]
    }
    occurrence_rows = []
    occurrence_source = structure["occurrences"][:maximum_occurrences]
    if high_level_presentation:
        occurrence_source = [
            item
            for item in structure["occurrences"]
            if item.get("occurrenceId") == structure["rootOccurrenceId"]
        ][:1]
    for item in occurrence_source:
        geometry = geometry_by_id.get(item["occurrenceId"], {})
        occurrence_rows.append(
            {
                "occurrenceId": item["occurrenceId"],
                "parentOccurrenceId": item.get("parentOccurrenceId"),
                "itemId": item.get("itemId"),
                "name": item.get("name"),
                "kind": item.get("kind"),
                "quantity": item.get("quantity", 1),
                "size": (
                    geometry["bounds"].get("size")
                    if geometry.get("bounds")
                    else None
                ),
            }
        )
    mate_by_id = {
        item["mateId"]: item for item in documents["interface_graph.json"]["mates"]
    }
    interface_rows = []
    for item in documents["interface_graph.json"]["interfaces"][:maximum_interfaces]:
        interface_rows.append(
            {
                "interfaceId": item["interfaceId"],
                "occurrenceRefs": item.get("occurrenceRefs", []),
                "mateTypes": sorted(
                    {
                        mate_by_id[ref].get("mateType")
                        or mate_by_id[ref].get("type")
                        for ref in item.get("mateRefs", [])
                        if ref in mate_by_id
                    }
                ),
            }
        )
    all_findings = [
        item
        for item in documents["unresolved.json"].get("findings", [])
        if item.get("severity") in {"error", "warning"}
    ]
    finding_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in all_findings:
        key = (str(item.get("severity")), str(item.get("code")))
        group = finding_groups.setdefault(
            key,
            {
                "severity": key[0],
                "code": key[1],
                "count": 0,
                "subjectRefs": [],
            },
        )
        group["count"] += 1
        group["subjectRefs"] = sorted(
            set(group["subjectRefs"]) | set(item.get("subjectRefs", []))
        )[:8]
    findings = [
        finding_groups[key]
        for key in sorted(finding_groups)[:maximum_findings]
    ]

    def compact_claim(item: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "claimId": item.get("claimId"),
            "predicate": item.get("predicate"),
            "subjectRef": item.get("subjectRef"),
            "objectRefs": list(item.get("objectRefs", [])),
            "value": item.get("value"),
            "knowledgeStatus": item.get("knowledgeStatus"),
            "authority": item.get("authority"),
            "reviewStatus": item.get("reviewStatus"),
            "evidenceRefs": list(item.get("evidenceRefs", [])),
            "assumptionIds": list(item.get("assumptionIds", [])),
        }

    functional_document = documents["functional_context.json"]
    priority_predicates = {
        "occurrence_role",
        "functional_relationship",
        "joint_archetype",
    }
    functional_claims = [
        compact_claim(item)
        for item in functional_document.get("claims", [])
        if isinstance(item, Mapping)
        and (
            item.get("predicate") in priority_predicates
            or item.get("reviewStatus") in {"edited", "rejected", "unknown"}
        )
    ][:maximum_functional_claims]
    relationships = [
        {
            "relationshipId": item.get("relationshipId"),
            "claimId": item.get("claimId"),
            "relationshipType": item.get("relationshipType"),
            "description": item.get("description"),
            "occurrenceRefs": list(item.get("occurrenceRefs", [])),
            "knowledgeStatus": item.get("knowledgeStatus"),
            "authority": item.get("authority"),
            "reviewStatus": item.get("reviewStatus"),
            "evidenceRefs": list(item.get("evidenceRefs", [])),
            "assumptionIds": list(item.get("assumptionIds", [])),
        }
        for item in functional_document.get("relationships", [])
        if isinstance(item, Mapping)
    ][:maximum_relationships]

    def candidate_rows(field: str, identifier: str) -> list[Dict[str, Any]]:
        rows = []
        for item in process_document.get(field, []):
            if not isinstance(item, Mapping):
                continue
            copied = {
                key: item.get(key)
                for key in (
                    identifier,
                    "claimId",
                    "label",
                    "description",
                    "family",
                    "operationType",
                    "evidenceSourceType",
                    "occurrenceRefs",
                    "inputOccurrenceRefs",
                    "inputRefs",
                    "outputRef",
                    "branchId",
                    "predecessorOperationIds",
                    "resourceRefs",
                    "requirementRefs",
                    "properties",
                    "stageDetailAvailable",
                    "stageDetailStepCount",
                    "stageDetailHash",
                    "knowledgeStatus",
                    "authority",
                    "reviewStatus",
                    "evidenceRefs",
                    "assumptionIds",
                )
                if item.get(key) is not None
            }
            rows.append(copied)
        return rows[:maximum_process_candidates]

    assumptions = [
        {
            "id": item.get("id"),
            "text": item.get("text"),
            "status": item.get("status"),
            "subjectRefs": list(item.get("subjectRefs", [])),
        }
        for item in process_document.get("assumptions", [])
        if isinstance(item, Mapping)
    ][:maximum_process_candidates]
    unresolved_questions = [
        {
            "id": item.get("id"),
            "text": item.get("text"),
            "status": item.get("status"),
            "subjectRefs": list(item.get("subjectRefs", [])),
        }
        for item in process_document.get("unresolvedQuestions", [])
        if isinstance(item, Mapping)
    ][:maximum_process_candidates]
    process_candidates = {
        "presentation": copy.deepcopy(
            process_document.get(
                "presentation",
                {"mode": "detailed", "showOccurrenceInputs": True},
            )
        ),
        "branches": candidate_rows("branches", "branchId"),
        "intermediateResults": candidate_rows(
            "intermediateResults", "intermediateResultId"
        ),
        "operationFamilies": candidate_rows(
            "operationFamilies", "operationId"
        ),
        "stageDetailIndex": [
            {
                "stageOperationId": item.get("stageOperationId"),
                "detailMapLabel": item.get("detailMapLabel"),
                "resultLabel": item.get("resultLabel"),
                "suboperationCount": len(item.get("operationFamilies", [])),
                "stageDetailHash": item.get("stageDetailHash"),
                "available": True,
            }
            for item in process_document.get("stageDetails", [])
            if isinstance(item, Mapping)
        ],
    }
    views = [
        {
            "viewId": item.get("viewId"),
            "assetPath": item.get("assetPath"),
            "viewName": item.get("viewName"),
            "visibleOccurrenceIds": list(item.get("visibleOccurrenceIds", [])),
        }
        for item in documents["visual_manifest.json"].get("views", [])
        if isinstance(item, Mapping)
    ][:maximum_views]
    pending_claim_count = sum(
        1
        for document_name in ("functional_context.json", "process_candidates.json")
        for item in documents[document_name].get("claims", [])
        if isinstance(item, Mapping) and item.get("reviewStatus") == "pending"
    )
    result = {
        "schemaVersion": 1,
        "origin": {
            "kind": "server",
            "provider": "assembly_knowledge_repository",
        },
        "identity": {
            "packageId": package["packageId"],
            "productId": package["productId"],
            "sourceRevision": package["sourceRevision"],
            "packageRevision": package["packageRevision"],
            "evidenceFingerprint": documents["evidence_catalog.json"][
                "evidenceFingerprint"
            ],
            "readiness": package["readiness"],
            "productionEligible": package["productionEligible"],
        },
        "scope": {
            "rootOccurrenceId": structure["rootOccurrenceId"],
            "configuration": structure["configuration"],
            "occurrenceCount": len(structure["occurrences"]),
            "requiredOccurrenceCount": sum(
                1
                for item in structure["occurrences"]
                if item.get("kind") == "part"
            ),
            "occurrenceCatalogMode": (
                "high_level_inputs"
                if high_level_presentation
                else "detailed"
            ),
            "interfaceCount": len(documents["interface_graph.json"]["interfaces"]),
        },
        "occurrences": occurrence_rows,
        "interfaces": interface_rows,
        "functionalClaims": functional_claims,
        "relationships": relationships,
        "processCandidates": process_candidates,
        "assumptions": assumptions,
        "unresolvedQuestions": unresolved_questions,
        "requirements": list(process_document.get("requirements", [])),
        "resources": list(process_document.get("resources", [])),
        "views": views,
        "review": {
            "pendingClaimCount": pending_claim_count,
            "reviewEventCount": len(
                documents["review_receipt.json"].get("events", [])
            ),
        },
        "findings": findings,
        "semanticBoundary": {
            "cadFactsMaySupport": [
                "component_membership",
                "physical_adjacency",
                "alignment",
                "relative_transform",
                "geometry",
                "co_visibility",
            ],
            "cadFactsDoNotEstablish": [
                "manufacturing_order",
                "operation_sequence",
                "torque",
                "tooling",
                "inspection_limits",
                "approved_process_requirements",
            ],
        },
        "truncated": {
            "occurrences": (
                False
                if high_level_presentation
                else len(structure["occurrences"]) > maximum_occurrences
            ),
            "interfaces": len(documents["interface_graph.json"]["interfaces"])
            > maximum_interfaces,
            "functionalClaims": len(
                functional_document.get("claims", [])
            ) > len(functional_claims),
            "relationships": len(
                functional_document.get("relationships", [])
            ) > len(relationships),
            "processCandidates": any(
                len(process_document.get(field, []))
                > len(process_candidates[target])
                for field, target in (
                    ("branches", "branches"),
                    ("intermediateResults", "intermediateResults"),
                    ("operationFamilies", "operationFamilies"),
                )
            ),
            "views": len(documents["visual_manifest.json"].get("views", []))
            > len(views),
            "findings": len(finding_groups) > maximum_findings,
        },
    }
    def serialized_size() -> int:
        return len(
            json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )

    while serialized_size() > maximum_characters and result["findings"]:
        result["findings"].pop()
        result["truncated"]["findings"] = True
    while serialized_size() > maximum_characters and result["views"]:
        result["views"].pop()
        result["truncated"]["views"] = True
    while serialized_size() > maximum_characters and result["functionalClaims"]:
        result["functionalClaims"].pop()
        result["truncated"]["functionalClaims"] = True
    while serialized_size() > maximum_characters and result["interfaces"]:
        result["interfaces"].pop()
        result["truncated"]["interfaces"] = True
    while serialized_size() > maximum_characters and result["relationships"]:
        result["relationships"].pop()
        result["truncated"]["relationships"] = True
    has_process_plan = bool(result["processCandidates"]["operationFamilies"])
    if not has_process_plan:
        process_fields = (
            "branches",
            "intermediateResults",
            "operationFamilies",
        )
        while serialized_size() > maximum_characters and any(
            result["processCandidates"][field] for field in process_fields
        ):
            for field in process_fields:
                if result["processCandidates"][field]:
                    result["processCandidates"][field].pop()
                    result["truncated"]["processCandidates"] = True
                    break
        while serialized_size() > maximum_characters and result["unresolvedQuestions"]:
            result["unresolvedQuestions"].pop()
        while serialized_size() > maximum_characters and result["assumptions"]:
            result["assumptions"].pop()
    if serialized_size() > maximum_characters:
        for occurrence in result["occurrences"]:
            occurrence["size"] = None
    if not has_process_plan:
        while (
            serialized_size() > maximum_characters
            and len(result["occurrences"]) > 1
        ):
            result["occurrences"].pop()
            result["truncated"]["occurrences"] = True
    if serialized_size() > maximum_characters:
        raise EvidenceCompilationError("Trusted evidence context budget exceeded.")
    fingerprint_payload = {
        key: value
        for key, value in result.items()
        if key not in {"contextCharacters"}
    }
    result["identity"]["contextFingerprint"] = canonical_json_sha256(
        fingerprint_payload
    )
    result["contextCharacters"] = 0
    for _ in range(3):
        result["contextCharacters"] = serialized_size()
    return result


def resolve_process_map_evidence_package(
    training_root: str | Path,
    product_id: str,
    *,
    package_id: str | None = None,
    expected_binding: Mapping[str, Any] | None = None,
    require_planning_ready: bool = False,
    require_current_sources: bool = False,
) -> Dict[str, Any] | None:
    """Resolve and verify one server-owned package plus its trusted context."""
    from .repository import AssemblyKnowledgeRepository

    repository = AssemblyKnowledgeRepository(training_root)
    packages = repository.list_packages(product_id)
    if package_id:
        matching = [item for item in packages if item["packageId"] == package_id]
        if not matching:
            raise EvidenceCompilationError(
                "Assembly knowledge package was not found."
            )
        selected_id = package_id
    else:
        if not packages:
            return None
        if len(packages) > 1:
            raise EvidenceCompilationError(
                "Multiple assembly knowledge packages require an explicit packageId."
            )
        selected_id = str(packages[0]["packageId"])
    documents = repository.read(product_id, selected_id)
    context = build_process_map_evidence_context(documents)
    identity = context["identity"]
    expected = dict(expected_binding or {})
    for field in (
        "packageId",
        "packageRevision",
        "sourceRevision",
        "evidenceFingerprint",
    ):
        if expected and expected.get(field) != identity.get(field):
            raise EvidenceCompilationError(
                f"Assembly knowledge {field} is stale or does not match."
            )
    if require_planning_ready and identity.get("readiness") not in {
        "planning_ready",
        "production_ready",
    }:
        raise EvidenceCompilationError(
            "Assembly knowledge package is not planning-ready."
        )
    source_status = repository.source_status(product_id, selected_id)
    if require_current_sources and not source_status["current"]:
        codes = ", ".join(
            sorted(
                {
                    str(item.get("code") or "source_not_current")
                    for item in source_status.get("findings", [])
                }
            )
        )
        raise EvidenceCompilationError(
            f"Assembly source currency could not be verified: {codes}."
        )
    return {
        "documents": documents,
        "context": context,
        "binding": {
            "packageId": identity["packageId"],
            "packageRevision": identity["packageRevision"],
            "sourceRevision": identity["sourceRevision"],
            "evidenceFingerprint": identity["evidenceFingerprint"],
            "contextFingerprint": identity["contextFingerprint"],
            "readiness": identity["readiness"],
            "productionEligible": identity["productionEligible"],
        },
        "sourceStatus": source_status,
    }


def resolve_process_map_evidence_context(
    training_root: str | Path,
    product_id: str,
    *,
    package_id: str | None = None,
    require_current_sources: bool = False,
) -> Dict[str, Any] | None:
    """Resolve one server-owned evidence package for a process-map product."""
    resolved = resolve_process_map_evidence_package(
        training_root,
        product_id,
        package_id=package_id,
        require_current_sources=require_current_sources,
    )
    return resolved["context"] if resolved else None
