"""Cost-bounded AI enrichment and deterministic package compilation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .cache import (
    AssemblyKnowledgeEnrichmentCache,
    occurrence_dependency_fingerprints,
)
from .cost_policy import (
    assert_authorization_matches_plan,
    build_enrichment_semantic_input,
    enrichment_process_reference_map,
    required_process_input_occurrence_ids,
)
from .enrichment_schema import (
    EnrichmentOutputError,
    enrichment_output_json_schema,
    require_valid_enrichment_output,
)
from .evidence import EVIDENCE_COMPILER_VERSION
from .identity import finding_id
from .manifest import canonical_json_sha256, refresh_package_revision, stable_id
from .provider import EnrichmentProviderError, MultimodalEnrichmentProvider
from .schema import AssemblyKnowledgeSchemaError, validate_package_documents


ENRICHMENT_PROMPT_VERSION = "assembly-enrichment-economy-v7"
ENRICHMENT_COMPILER_VERSION = "1.0.0"

_SYSTEM_PROMPT = """\
You are preparing inferred semantic evidence for a manufacturing assembly.
Return only the required structured object.

Hard boundaries:
- CAD structure, mates, geometry, filenames, and visual proximity do not prove
  manufacturing order.
- Treat every proposed function, relationship, operation, branch, and
  intermediate result as an inferred candidate for human review.
- Do not provide coordinates, route geometry, torque, dimensions, tolerances,
  standards, tools, machine settings, process settings, or numeric requirements.
- Do not claim approval or production authority.
- Reference only occurrence, interface, and evidence IDs supplied in the input.
- Use operation/stage candidates for physical work. Use relationships only for
  functional or physical associations; do not disguise work as routing topology.
- Return at least one process branch and one operation family.
- Use each occurrence's compact processRef in model-output occurrence fields;
  do not copy the longer occurrenceId. Do not use an occRef-* value as a
  candidateKey.
- Cover every ref in semanticInput.requiredProcessInputRefs as an operation or
  intermediate-result input.
- Build an acyclic candidate process. Every terminal operation must produce
  semanticInput.rootProcessRef; parallel terminal branches are allowed.
- Return an empty intermediateResults array in this Economy pass. Operation
  stages carry the process sequence directly.
- Keep the process concise by combining parts consumed by the same plausible
  operation. Do not invent a separate operation merely to consume one part.
- This Economy pass is process-first. Return empty occurrenceRoles,
  functionalRelationships, and jointArchetypes arrays. Spend the bounded
  response on complete branches, operations, assumptions, and unresolved
  questions.
- If available evidence cannot place a required process ref in a plausible
  operation, add an unresolvedQuestions entry whose subjectRefs contains that
  ref. Never silently omit a required ref.
- Keep labels and descriptions concise so the complete process fits the bounded
  response.
- State uncertainty as assumptions or unresolved questions.
"""

_SEMANTIC_PILOT_PROMPT = """\
You are preparing bounded semantic candidates for a manufacturing assembly.
Return only the required structured object.

Hard boundaries:
- Work only from the selected occurrences, their supplied hierarchy, and their
  directly connected interfaces.
- Treat every role, functional relationship, and joint archetype as an inferred
  candidate for human review.
- Do not provide manufacturing order, operations, coordinates, route geometry,
  torque, dimensions, tolerances, standards, tools, settings, safety controls,
  or other numeric engineering requirements.
- Do not claim authored, approved, confirmed, production, or human authority.
- Reference only compact occurrence refs and interface IDs supplied in the
  semantic input. Do not use an occRef-* value as a candidateKey.
- Return empty processBranches, intermediateResults, and operationFamilies
  arrays. This pass does not create a process plan.
- Prefer a concise set of high-value candidates. Put uncertain interpretations
  in assumptions or unresolvedQuestions rather than presenting them as facts.
- An assembly mate establishes a geometric constraint, not design intent,
  loading, criticality, fit, or manufacturing sequence.
"""

_CORRECTION_PROMPT = """\
Correct the prior response to satisfy the supplied schema findings.
Preserve every valid row and the original semantic scope. Never replace a
non-empty candidate collection with an empty collection. Use compact processRef
values in model-output occurrence fields. Ensure every ref in
semanticInput.requiredProcessInputRefs is covered and the operation DAG has
one or more terminal operations, all producing semanticInput.rootProcessRef.
Correct only the reported shape, reference, coverage, final-output, or
precedence defects. Do not invent manufacturing values or unsupported
authority. Return only the corrected structured object.
"""

_SEMANTIC_PILOT_CORRECTION_PROMPT = """\
Correct the prior response to satisfy the supplied schema findings while
preserving the bounded semantic scope. Keep processBranches,
intermediateResults, and operationFamilies empty. Use only supplied compact
occurrence refs and interface IDs. Do not invent engineering values, process
steps, or authority. Return only the corrected structured object.
"""


class AssemblyEnrichmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Any = None):
        self.code = code
        self.details = details
        super().__init__(message)


def _known_ids(
    documents: Mapping[str, Mapping[str, Any]],
) -> Dict[str, set[str]]:
    structure = documents["product_structure.json"]
    interfaces = documents["interface_graph.json"]
    evidence = documents["evidence_catalog.json"]
    return {
        "occurrences": {
            item["occurrenceId"]
            for item in structure.get("occurrences", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("occurrenceId"), str)
        },
        "interfaces": {
            item["interfaceId"]
            for item in interfaces.get("interfaces", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("interfaceId"), str)
        },
        "evidence": {
            item["evidenceId"]
            for item in evidence.get("sources", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidenceId"), str)
        },
    }


def validate_output_for_package(
    output: Any,
    documents: Mapping[str, Mapping[str, Any]],
    *,
    task_mode: str = "process_planning",
    selected_occurrence_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    ids = _known_ids(documents)
    structure = documents["product_structure.json"]
    root_occurrence_id = str(structure.get("rootOccurrenceId") or "")
    require_process_plan = task_mode != "semantic_pilot"
    semantic_input = build_enrichment_semantic_input(
        documents,
        task_mode=task_mode,
        selected_occurrence_ids=selected_occurrence_ids,
    )
    if require_process_plan:
        required_input_occurrence_ids = required_process_input_occurrence_ids(
            structure
        )
    else:
        required_input_occurrence_ids = []
        ids["occurrences"] = {
            item["occurrenceId"]
            for item in semantic_input["occurrences"]
            if isinstance(item, Mapping)
            and isinstance(item.get("occurrenceId"), str)
        }
        ids["interfaces"] = {
            item["interfaceId"]
            for item in semantic_input["interfaces"]
            if isinstance(item, Mapping)
            and isinstance(item.get("interfaceId"), str)
        }
    process_refs = enrichment_process_reference_map(structure)
    occurrence_by_ref = {
        process_ref: occurrence_id
        for occurrence_id, process_ref in process_refs.items()
    }
    canonical = copy.deepcopy(output)
    if isinstance(canonical, dict):
        reserved_candidate_keys = []
        for field in (
            "functionalRelationships",
            "jointArchetypes",
            "processBranches",
            "intermediateResults",
            "operationFamilies",
            "assumptions",
            "unresolvedQuestions",
        ):
            rows = canonical.get(field)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if (
                    isinstance(row, dict)
                    and row.get("candidateKey") in occurrence_by_ref
                ):
                    reserved_candidate_keys.append(row["candidateKey"])
        if reserved_candidate_keys:
            raise EnrichmentOutputError(
                [
                    {
                        "severity": "error",
                        "path": "$",
                        "code": "reserved_process_ref_used_as_candidate_key",
                        "message": (
                            "Compact occurrence references cannot be used as "
                            "candidate keys."
                        ),
                        "details": {
                            "candidateKeys": sorted(
                                set(reserved_candidate_keys)
                            )
                        },
                    }
                ]
            )

        def resolve_ref(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            return occurrence_by_ref.get(value, value)

        occurrence_roles = canonical.get("occurrenceRoles")
        if isinstance(occurrence_roles, list):
            for row in occurrence_roles:
                if isinstance(row, dict):
                    row["occurrenceId"] = resolve_ref(
                        row.get("occurrenceId")
                    )
        for field in (
            "functionalRelationships",
            "processBranches",
            "intermediateResults",
            "operationFamilies",
            "assumptions",
            "unresolvedQuestions",
        ):
            rows = canonical.get(field)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for reference_field in (
                    "occurrenceRefs",
                    "inputOccurrenceRefs",
                    "inputRefs",
                    "subjectRefs",
                ):
                    if isinstance(row.get(reference_field), list):
                        row[reference_field] = [
                            resolve_ref(ref)
                            for ref in row[reference_field]
                        ]
                if "outputRef" in row:
                    row["outputRef"] = resolve_ref(row.get("outputRef"))
    validated = require_valid_enrichment_output(
        canonical,
        source_revision=documents["package.json"]["sourceRevision"],
        occurrence_ids=ids["occurrences"],
        interface_ids=ids["interfaces"],
        evidence_ids=ids["evidence"],
        root_occurrence_id=root_occurrence_id,
        required_input_occurrence_ids=required_input_occurrence_ids,
        require_process_plan=require_process_plan,
    )
    if not require_process_plan and not any(
        validated.get(field)
        for field in (
            "occurrenceRoles",
            "functionalRelationships",
            "jointArchetypes",
        )
    ):
        raise EnrichmentOutputError(
            [
                {
                    "severity": "error",
                    "path": "$",
                    "code": "semantic_candidate_required",
                    "message": (
                        "semantic_pilot must return at least one role, "
                        "relationship, or joint-archetype candidate."
                    ),
                }
            ]
        )
    return validated


def build_enrichment_provider_request(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    package_dir: str | Path,
    budget_plan: Mapping[str, Any],
    correction: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    package = documents["package.json"]
    if budget_plan.get("packageRevision") != package.get("packageRevision"):
        raise AssemblyEnrichmentError(
            "stale_package_revision",
            "The enrichment plan targets a different package revision.",
        )
    if budget_plan.get("sourceRevision") != package.get("sourceRevision"):
        raise AssemblyEnrichmentError(
            "stale_source_revision",
            "The enrichment plan targets a different source revision.",
        )
    task_mode = str(budget_plan.get("taskMode") or "process_planning")
    selected_occurrence_ids = budget_plan.get("selectedOccurrenceIds") or None
    semantic_input = build_enrichment_semantic_input(
        documents,
        task_mode=task_mode,
        selected_occurrence_ids=selected_occurrence_ids,
    )
    root = Path(package_dir).resolve()
    images = []
    if correction is None:
        for item in budget_plan.get("images", []):
            target = (root / str(item["assetPath"])).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise AssemblyEnrichmentError(
                    "image_path_escape",
                    "Approved image path escapes the package.",
                ) from exc
            images.append(
                {
                    **copy.deepcopy(dict(item)),
                    "absolutePath": str(target),
                }
            )
        user_payload = {
            "task": "Propose bounded assembly semantics for review.",
            "semanticInput": semantic_input,
        }
        system_prompt = (
            _SEMANTIC_PILOT_PROMPT
            if task_mode == "semantic_pilot"
            else _SYSTEM_PROMPT
        )
    else:
        user_payload = {
            "task": "Repair schema only.",
            "priorOutput": correction.get("priorOutput"),
            "validationFindings": correction.get("validationFindings"),
            "sourceRevision": package["sourceRevision"],
            "semanticInput": semantic_input,
        }
        system_prompt = (
            _SEMANTIC_PILOT_CORRECTION_PROMPT
            if task_mode == "semantic_pilot"
            else _CORRECTION_PROMPT
        )
    return {
        "provider": budget_plan["provider"],
        "model": budget_plan["model"],
        "requestFingerprint": budget_plan["requestFingerprint"],
        "cacheKey": budget_plan["cacheKey"],
        "systemPrompt": system_prompt,
        "userText": json.dumps(
            user_payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "images": images,
        "outputSchema": enrichment_output_json_schema(
            require_process_plan=task_mode != "semantic_pilot"
        ),
        "maximumOutputTokens": budget_plan["maximumOutputTokensPerCall"],
        "correctionOnly": correction is not None,
    }


def _model_evidence(
    *,
    candidate_kind: str,
    candidate_key: str,
    subject_refs: Iterable[str],
    request_fingerprint: str,
    provider: str,
    model: str,
    prompt_version: str,
) -> Dict[str, Any]:
    subjects = sorted(set(str(item) for item in subject_refs if item))
    details = {
        "candidateKind": candidate_kind,
        "candidateKey": candidate_key,
        "generatedBy": "assembly-knowledge-enrichment",
        "model": model,
        "promptVersion": prompt_version,
        "provider": provider,
    }
    identity = {
        "details": details,
        "sourceRefs": [request_fingerprint],
        "sourceType": "domain_heuristic",
        "subjectRefs": subjects,
    }
    return {
        "evidenceId": stable_id("evidence", identity, digest_length=24),
        "sourceType": "domain_heuristic",
        "authority": "supporting",
        "subjectRefs": subjects,
        "sourceRefs": [request_fingerprint],
        "details": details,
    }


def _model_claim(
    *,
    subject_ref: str,
    predicate: str,
    object_refs: Iterable[str],
    value: Any,
    evidence_refs: Iterable[str],
    assumption_ids: Iterable[str],
    evidence_fingerprint: str,
    provider: str,
    model: str,
    prompt_version: str,
) -> Dict[str, Any]:
    objects = sorted(set(str(item) for item in object_refs if item))
    evidence = sorted(set(str(item) for item in evidence_refs if item))
    assumptions = sorted(set(str(item) for item in assumption_ids if item))
    identity = {
        "evidenceFingerprint": evidence_fingerprint,
        "objectRefs": objects,
        "predicate": predicate,
        "subjectRef": subject_ref,
        "value": value,
    }
    return {
        "claimId": stable_id("claim", identity, digest_length=24),
        "subjectRef": subject_ref,
        "predicate": predicate,
        "objectRefs": objects,
        "value": copy.deepcopy(value),
        "knowledgeStatus": "inferred",
        "authority": "supporting",
        "evidenceRefs": evidence,
        "assumptionIds": assumptions,
        "generatedBy": {
            "kind": "model",
            "generatorId": f"{provider}:{model}",
            "version": prompt_version,
        },
        "reviewStatus": "pending",
    }


def _is_model_generated_claim(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and isinstance(item.get("generatedBy"), Mapping)
        and item["generatedBy"].get("kind") == "model"
    )


def compile_enrichment_output(
    documents: Mapping[str, Mapping[str, Any]],
    output: Mapping[str, Any],
    *,
    budget_plan: Mapping[str, Any],
    authorization: Mapping[str, Any],
    usage: Mapping[str, Any],
    from_cache: bool,
) -> Dict[str, Dict[str, Any]]:
    task_mode = str(budget_plan.get("taskMode") or "process_planning")
    selected_occurrence_ids = budget_plan.get("selectedOccurrenceIds") or None
    validated = validate_output_for_package(
        output,
        documents,
        task_mode=task_mode,
        selected_occurrence_ids=selected_occurrence_ids,
    )
    copied = {
        str(name): copy.deepcopy(dict(document))
        for name, document in documents.items()
    }
    package = copied["package.json"]
    provider = str(budget_plan["provider"])
    model = str(budget_plan["model"])
    prompt_version = str(budget_plan["promptVersion"])
    request_fingerprint = str(budget_plan["requestFingerprint"])

    previous_process = copied["process_candidates.json"]
    old_model_assumption_ids = {
        item.get("id")
        for item in previous_process.get("assumptions", [])
        if isinstance(item, Mapping)
    }
    old_model_question_ids = {
        item.get("id")
        for item in previous_process.get("unresolvedQuestions", [])
        if isinstance(item, Mapping)
    }
    semantic_candidate_kinds = {
        "occurrence_role",
        "functional_relationship",
        "joint_archetype",
    }
    evidence_sources = [
        copy.deepcopy(item)
        for item in copied["evidence_catalog.json"].get("sources", [])
        if not (
            isinstance(item, Mapping)
            and item.get("sourceType") == "domain_heuristic"
            and isinstance(item.get("details"), Mapping)
            and item["details"].get("generatedBy")
            == "assembly-knowledge-enrichment"
            and (
                task_mode != "semantic_pilot"
                or item["details"].get("candidateKind")
                in semantic_candidate_kinds
            )
        )
    ]

    assumption_id_by_key = {
        item["candidateKey"]: stable_id(
            "assumption",
            {
                "candidateKey": item["candidateKey"],
                "requestFingerprint": request_fingerprint,
                "text": item["text"],
            },
            digest_length=24,
        )
        for item in validated["assumptions"]
    }
    branch_id_by_key = {
        item["candidateKey"]: stable_id(
            "branch",
            {
                "candidateKey": item["candidateKey"],
                "requestFingerprint": request_fingerprint,
            },
            digest_length=24,
        )
        for item in validated["processBranches"]
    }
    intermediate_id_by_key = {
        item["candidateKey"]: stable_id(
            "state",
            {
                "candidateKey": item["candidateKey"],
                "requestFingerprint": request_fingerprint,
            },
            digest_length=24,
        )
        for item in validated["intermediateResults"]
    }
    operation_id_by_key = {
        item["candidateKey"]: stable_id(
            "operation",
            {
                "candidateKey": item["candidateKey"],
                "requestFingerprint": request_fingerprint,
            },
            digest_length=24,
        )
        for item in validated["operationFamilies"]
    }
    interface_by_id = {
        item["interfaceId"]: item
        for item in copied["interface_graph.json"].get("interfaces", [])
        if isinstance(item, Mapping)
    }

    candidate_rows: list[tuple[str, Mapping[str, Any], list[str]]] = []
    for row in validated["occurrenceRoles"]:
        candidate_rows.append(
            (
                "occurrence_role",
                row,
                [row["occurrenceId"]],
            )
        )
    for row in validated["functionalRelationships"]:
        candidate_rows.append(
            ("functional_relationship", row, list(row["occurrenceRefs"]))
        )
    for row in validated["jointArchetypes"]:
        interface = interface_by_id.get(row["interfaceId"], {})
        candidate_rows.append(
            (
                "joint_archetype",
                row,
                [row["interfaceId"], *interface.get("occurrenceRefs", [])],
            )
        )
    for row in validated["processBranches"]:
        candidate_rows.append(("process_branch", row, list(row["occurrenceRefs"])))
    for row in validated["intermediateResults"]:
        candidate_rows.append(
            (
                "intermediate_result",
                row,
                list(row["inputOccurrenceRefs"]),
            )
        )
    for row in validated["operationFamilies"]:
        candidate_rows.append(
            (
                "operation_family",
                row,
                [
                    item
                    for item in row["inputRefs"]
                    if item.startswith("occ-")
                ],
            )
        )

    model_evidence_by_identity: Dict[tuple[str, str], Dict[str, Any]] = {}
    for candidate_kind, row, subjects in candidate_rows:
        candidate_key = str(
            row.get("candidateKey")
            or row.get("occurrenceId")
            or row.get("interfaceId")
        )
        item = _model_evidence(
            candidate_kind=candidate_kind,
            candidate_key=candidate_key,
            subject_refs=subjects,
            request_fingerprint=request_fingerprint,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
        model_evidence_by_identity[(candidate_kind, candidate_key)] = item
        evidence_sources.append(item)
    evidence_sources.sort(key=lambda item: item["evidenceId"])
    evidence_fingerprint = canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": package["sourceRevision"],
            "sources": evidence_sources,
        }
    )
    copied["evidence_catalog.json"]["sources"] = evidence_sources
    copied["evidence_catalog.json"]["evidenceFingerprint"] = evidence_fingerprint

    def evidence_refs(
        kind: str,
        row: Mapping[str, Any],
    ) -> list[str]:
        key = str(
            row.get("candidateKey")
            or row.get("occurrenceId")
            or row.get("interfaceId")
        )
        model_ref = model_evidence_by_identity[(kind, key)]["evidenceId"]
        return sorted({model_ref, *row.get("evidenceRefs", [])})

    def assumption_refs(row: Mapping[str, Any]) -> list[str]:
        return [
            assumption_id_by_key[key]
            for key in row.get("assumptionRefs", [])
        ]

    functional_claims = [
        copy.deepcopy(item)
        for item in copied["functional_context.json"].get("claims", [])
        if not _is_model_generated_claim(item)
    ]
    retained_functional_claim_ids = {
        item.get("claimId")
        for item in functional_claims
        if isinstance(item.get("claimId"), str)
    }
    relationships = [
        copy.deepcopy(item)
        for item in copied["functional_context.json"].get("relationships", [])
        if isinstance(item, Mapping)
        and (
            not isinstance(item.get("claimId"), str)
            or item.get("claimId") in retained_functional_claim_ids
        )
    ]
    for row in validated["occurrenceRoles"]:
        functional_claims.append(
            _model_claim(
                subject_ref=row["occurrenceId"],
                predicate="occurrence_role",
                object_refs=[],
                value={"role": row["role"], "function": row["function"]},
                evidence_refs=evidence_refs("occurrence_role", row),
                assumption_ids=assumption_refs(row),
                evidence_fingerprint=evidence_fingerprint,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
            )
        )
    for row in validated["functionalRelationships"]:
        relationship_id = stable_id(
            "relationship",
            {
                "candidateKey": row["candidateKey"],
                "requestFingerprint": request_fingerprint,
            },
            digest_length=24,
        )
        claim = _model_claim(
            subject_ref=row["occurrenceRefs"][0],
            predicate="functional_relationship",
            object_refs=row["occurrenceRefs"][1:],
            value={
                "relationshipId": relationship_id,
                "relationshipType": row["relationshipType"],
                "description": row["description"],
            },
            evidence_refs=evidence_refs("functional_relationship", row),
            assumption_ids=assumption_refs(row),
            evidence_fingerprint=evidence_fingerprint,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
        relationships.append(
            {
                "relationshipId": relationship_id,
                "claimId": claim["claimId"],
                "relationshipType": row["relationshipType"],
                "description": row["description"],
                "occurrenceRefs": list(row["occurrenceRefs"]),
                "knowledgeStatus": "inferred",
                "authority": "supporting",
                "reviewStatus": "pending",
                "evidenceRefs": evidence_refs("functional_relationship", row),
                "assumptionIds": assumption_refs(row),
            }
        )
        functional_claims.append(claim)
    for row in validated["jointArchetypes"]:
        interface = interface_by_id[row["interfaceId"]]
        functional_claims.append(
            _model_claim(
                subject_ref=row["interfaceId"],
                predicate="joint_archetype",
                object_refs=interface.get("occurrenceRefs", []),
                value={
                    "archetype": row["archetype"],
                    "description": row["description"],
                },
                evidence_refs=evidence_refs("joint_archetype", row),
                assumption_ids=assumption_refs(row),
                evidence_fingerprint=evidence_fingerprint,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
            )
        )
    functional_claims.sort(key=lambda item: item["claimId"])
    copied["functional_context.json"].update(
        {
            "evidenceFingerprint": evidence_fingerprint,
            "claims": functional_claims,
            "relationships": sorted(
                relationships,
                key=lambda item: str(
                    item.get("relationshipId")
                    or item.get("interfaceId")
                    or item.get("claimId")
                    or ""
                ),
            ),
        }
    )

    branches = [
        {
            "branchId": branch_id_by_key[row["candidateKey"]],
            "label": row["label"],
            "description": row["description"],
            "occurrenceRefs": list(row["occurrenceRefs"]),
            "knowledgeStatus": "inferred",
            "authority": "supporting",
            "reviewStatus": "pending",
            "evidenceRefs": evidence_refs("process_branch", row),
            "assumptionIds": assumption_refs(row),
        }
        for row in validated["processBranches"]
    ]
    intermediate_results = [
        {
            "intermediateResultId": intermediate_id_by_key[row["candidateKey"]],
            "label": row["label"],
            "description": row["description"],
            "inputOccurrenceRefs": list(row["inputOccurrenceRefs"]),
            "branchId": (
                branch_id_by_key[row["branchKey"]]
                if row["branchKey"] is not None
                else None
            ),
            "knowledgeStatus": "inferred",
            "authority": "supporting",
            "reviewStatus": "pending",
            "evidenceRefs": evidence_refs("intermediate_result", row),
            "assumptionIds": assumption_refs(row),
        }
        for row in validated["intermediateResults"]
    ]
    operation_families = []
    process_claims = [
        copy.deepcopy(item)
        for item in copied["process_candidates.json"].get("claims", [])
        if not _is_model_generated_claim(item)
    ]
    for row, branch in zip(validated["processBranches"], branches):
        claim = _model_claim(
            subject_ref=branch["branchId"],
            predicate="candidate_process_branch",
            object_refs=branch["occurrenceRefs"],
            value={
                "label": branch["label"],
                "description": branch["description"],
            },
            evidence_refs=branch["evidenceRefs"],
            assumption_ids=branch["assumptionIds"],
            evidence_fingerprint=evidence_fingerprint,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
        branch["claimId"] = claim["claimId"]
        process_claims.append(claim)
    for row, intermediate in zip(
        validated["intermediateResults"], intermediate_results
    ):
        claim = _model_claim(
            subject_ref=intermediate["intermediateResultId"],
            predicate="candidate_intermediate_result",
            object_refs=intermediate["inputOccurrenceRefs"],
            value={
                "label": intermediate["label"],
                "description": intermediate["description"],
                "branchId": intermediate["branchId"],
            },
            evidence_refs=intermediate["evidenceRefs"],
            assumption_ids=intermediate["assumptionIds"],
            evidence_fingerprint=evidence_fingerprint,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
        intermediate["claimId"] = claim["claimId"]
        process_claims.append(claim)
    for row in validated["operationFamilies"]:
        operation_id = operation_id_by_key[row["candidateKey"]]

        def resolve_ref(ref: Optional[str]) -> Optional[str]:
            if ref is None:
                return None
            return intermediate_id_by_key.get(ref, ref)

        operation = {
            "operationId": operation_id,
            "label": row["label"],
            "family": row["family"],
            "description": row["description"],
            "inputRefs": [resolve_ref(ref) for ref in row["inputRefs"]],
            "outputRef": resolve_ref(row["outputRef"]),
            "branchId": (
                branch_id_by_key[row["branchKey"]]
                if row["branchKey"] is not None
                else None
            ),
            "predecessorOperationIds": [
                operation_id_by_key[key] for key in row["predecessorKeys"]
            ],
            "knowledgeStatus": "inferred",
            "authority": "supporting",
            "reviewStatus": "pending",
            "evidenceRefs": evidence_refs("operation_family", row),
            "assumptionIds": assumption_refs(row),
        }
        operation_families.append(operation)
        claim = _model_claim(
            subject_ref=operation_id,
            predicate="candidate_operation_family",
            object_refs=[
                ref for ref in operation["inputRefs"] if ref is not None
            ],
            value={
                "family": row["family"],
                "label": row["label"],
                "outputRef": operation["outputRef"],
            },
            evidence_refs=operation["evidenceRefs"],
            assumption_ids=operation["assumptionIds"],
            evidence_fingerprint=evidence_fingerprint,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
        operation["claimId"] = claim["claimId"]
        process_claims.append(claim)
    assumptions = [
        {
            "id": assumption_id_by_key[row["candidateKey"]],
            "text": row["text"],
            "status": "open",
            "subjectRefs": list(row["subjectRefs"]),
        }
        for row in validated["assumptions"]
    ]
    questions = [
        {
            "id": stable_id(
                "question",
                {
                    "candidateKey": row["candidateKey"],
                    "requestFingerprint": request_fingerprint,
                    "text": row["text"],
                },
                digest_length=24,
            ),
            "text": row["text"],
            "status": "open",
            "subjectRefs": list(row["subjectRefs"]),
        }
        for row in validated["unresolvedQuestions"]
    ]
    process_claims.sort(key=lambda item: item["claimId"])
    if task_mode == "semantic_pilot":
        copied["process_candidates.json"]["evidenceFingerprint"] = (
            evidence_fingerprint
        )
    else:
        copied["process_candidates.json"].update(
            {
            "evidenceFingerprint": evidence_fingerprint,
            "claims": process_claims,
            "branches": sorted(branches, key=lambda item: item["branchId"]),
            "intermediateResults": sorted(
                intermediate_results,
                key=lambda item: item["intermediateResultId"],
            ),
            "operationFamilies": sorted(
                operation_families, key=lambda item: item["operationId"]
            ),
            "assumptions": assumptions,
            "unresolvedQuestions": questions,
            }
        )

    unresolved = copied["unresolved.json"]
    root_id = copied["product_structure.json"]["rootOccurrenceId"]
    if task_mode == "semantic_pilot":
        finding_code = "semantic_candidates_require_review"
        finding_message = (
            "Model-generated semantic candidates are inferred and require "
            "human review before controlled retrieval."
        )
        unresolved["findings"] = [
            item
            for item in unresolved.get("findings", [])
            if not (
                item.get("code") == finding_code
                and isinstance(item.get("details"), Mapping)
                and item["details"].get("generatedBy")
                == "assembly-knowledge-enrichment"
            )
        ]
    else:
        finding_code = "manufacturing_sequence_inferred_only"
        finding_message = (
            "Manufacturing sequence candidates are inferred and require review; "
            "CAD evidence does not make them authoritative."
        )
        unresolved["findings"] = [
            item
            for item in unresolved.get("findings", [])
            if item.get("code")
            not in {
                "manufacturing_sequence_not_established",
                "manufacturing_sequence_inferred_only",
            }
        ]
    inferred_finding = {
        "findingId": finding_id(
            finding_code,
            subject_refs=[root_id],
            details={"requestFingerprint": request_fingerprint},
        ),
        "severity": "warning",
        "code": finding_code,
        "message": finding_message,
        "subjectRefs": [root_id],
        "details": {
            "requestFingerprint": request_fingerprint,
            "generatedBy": "assembly-knowledge-enrichment",
            "taskMode": task_mode,
        },
    }
    unresolved["findings"].append(inferred_finding)
    unresolved["findings"].sort(key=lambda item: item["findingId"])
    new_assumption_ids = {item["id"] for item in assumptions}
    new_question_ids = {item["id"] for item in questions}
    unresolved["assumptions"] = [
        item
        for item in unresolved.get("assumptions", [])
        if item.get("id") not in old_model_assumption_ids
        and item.get("id") not in new_assumption_ids
    ] + assumptions
    unresolved["questions"] = [
        item
        for item in unresolved.get("questions", [])
        if item.get("id") not in old_model_question_ids
        and item.get("id") not in new_question_ids
    ] + questions
    unresolved["assumptions"].sort(key=lambda item: item["id"])
    unresolved["questions"].sort(key=lambda item: item["id"])

    normalized_usage = {
        "inputTokens": int(usage.get("inputTokens", 0) or 0),
        "outputTokens": int(usage.get("outputTokens", 0) or 0),
        "totalTokens": int(usage.get("totalTokens", 0) or 0),
        "imageCount": int(usage.get("imageCount", 0) or 0),
        "providerAttempts": int(usage.get("providerAttempts", 0) or 0),
        "schemaCorrections": int(usage.get("schemaCorrections", 0) or 0),
    }
    package_updates = {
        "readiness": (
            package.get("readiness", "function_ready")
            if task_mode == "semantic_pilot"
            else "planning_ready"
        ),
        "productionEligible": False,
        "modelProvider": provider,
        "modelId": model,
        "promptVersion": prompt_version,
        "enrichmentReceipt": {
            "authorizationId": authorization["authorizationId"],
            "requestFingerprint": request_fingerprint,
            "cacheKey": budget_plan["cacheKey"],
            "evidenceFingerprint": evidence_fingerprint,
            "policyVersion": budget_plan["policyVersion"],
            "promptVersion": prompt_version,
            "provider": provider,
            "model": model,
            "imageHashes": sorted(
                item["assetHash"] for item in budget_plan.get("images", [])
            ),
            "usage": normalized_usage,
            "pricingConfidence": budget_plan["pricingConfidence"],
            "estimatedMaximumCostUsd": budget_plan[
                "estimatedMaximumCostUsd"
            ],
            "fromCache": bool(from_cache),
        },
    }
    refreshed = refresh_package_revision(
        copied,
        package_updates=package_updates,
    )
    errors = [
        item
        for item in validate_package_documents(refreshed)
        if item.get("severity") == "error"
    ]
    if errors:
        raise AssemblyKnowledgeSchemaError(errors)
    return refreshed


def execute_economy_enrichment(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    package_dir: str | Path,
    budget_plan: Mapping[str, Any],
    authorization: Mapping[str, Any],
    provider: MultimodalEnrichmentProvider,
    cache: Optional[AssemblyKnowledgeEnrichmentCache] = None,
) -> Dict[str, Any]:
    assert_authorization_matches_plan(budget_plan, authorization)
    if provider.provider_name != budget_plan.get("provider"):
        raise AssemblyEnrichmentError(
            "provider_mismatch",
            "Configured provider does not match the authorized plan.",
        )
    if provider.model != budget_plan.get("model"):
        raise AssemblyEnrichmentError(
            "model_mismatch",
            "Configured model does not match the authorized plan.",
        )
    task_mode = str(budget_plan.get("taskMode") or "process_planning")
    selected_occurrence_ids = budget_plan.get("selectedOccurrenceIds") or None

    cache_key = str(budget_plan["cacheKey"])
    cached = cache.read(cache_key) if cache is not None else None
    if cached is not None:
        output = validate_output_for_package(
            cached["response"],
            documents,
            task_mode=task_mode,
            selected_occurrence_ids=selected_occurrence_ids,
        )
        usage = {
            **cached.get("usage", {}),
            "imageCount": 0,
            "providerAttempts": 0,
            "schemaCorrections": 0,
        }
        enriched = compile_enrichment_output(
            documents,
            output,
            budget_plan=budget_plan,
            authorization=authorization,
            usage=usage,
            from_cache=True,
        )
        return {
            "documents": enriched,
            "output": output,
            "usage": usage,
            "fromCache": True,
            "warnings": [],
        }

    maximum_attempts = int(budget_plan.get("maximumProviderAttempts", 1))
    attempts = 0
    schema_corrections = 0
    aggregate_usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    request = build_enrichment_provider_request(
        documents,
        package_dir=package_dir,
        budget_plan=budget_plan,
    )
    last_error: Exception | None = None
    output: Dict[str, Any] | None = None
    while attempts < maximum_attempts:
        attempts += 1
        try:
            result = provider.invoke(request)
        except EnrichmentProviderError as exc:
            last_error = exc
            if not exc.retryable or attempts >= maximum_attempts:
                raise
            continue
        for field in aggregate_usage:
            aggregate_usage[field] += int(result.get("usage", {}).get(field, 0) or 0)
        try:
            output = validate_output_for_package(
                result.get("output"),
                documents,
                task_mode=task_mode,
                selected_occurrence_ids=selected_occurrence_ids,
            )
            break
        except EnrichmentOutputError as exc:
            last_error = exc
            if attempts >= maximum_attempts:
                raise
            schema_corrections += 1
            request = build_enrichment_provider_request(
                documents,
                package_dir=package_dir,
                budget_plan=budget_plan,
                correction={
                    "priorOutput": result.get("output"),
                    "validationFindings": exc.findings,
                },
            )
    if output is None:
        raise AssemblyEnrichmentError(
            "enrichment_failed",
            "Assembly enrichment produced no valid output.",
            details=str(last_error) if last_error else None,
        )
    usage = {
        **aggregate_usage,
        "imageCount": len(budget_plan.get("images", [])),
        "providerAttempts": attempts,
        "schemaCorrections": schema_corrections,
    }
    if cache is not None:
        cache.write(
            cache_key,
            request_fingerprint=str(budget_plan["requestFingerprint"]),
            response=output,
            usage=usage,
            provider=provider.provider_name,
            model=provider.model,
            occurrence_fingerprints=occurrence_dependency_fingerprints(documents),
        )
    enriched = compile_enrichment_output(
        documents,
        output,
        budget_plan=budget_plan,
        authorization=authorization,
        usage=usage,
        from_cache=False,
    )
    return {
        "documents": enriched,
        "output": output,
        "usage": usage,
        "fromCache": False,
        "warnings": [
            {
                "code": "semantic_candidates_require_review",
                "message": (
                    "Model-generated semantic candidates remain inferred and "
                    "supporting until reviewed."
                ),
            }
        ],
    }
