"""Shared semantic claim, authority, and retrieval contracts.

The Assembly Knowledge Package remains the storage contract. This module adds
the policy that its intentionally open claim predicates cannot express alone:
typed predicate behavior, guarded authority promotion, prototype eligibility,
and bounded prompt retrieval.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


SEMANTIC_CONTRACT_VERSION = "semantic-contract-v1"
DEFAULT_MAX_RETRIEVED_CLAIMS = 12
DEFAULT_MAX_RENDERED_CHARACTERS = 6000


PREDICATE_REGISTRY: dict[str, dict[str, Any]] = {
    "functional_catalog_metadata": {
        "subjectKind": "assembly",
        "valueKind": "object",
        "cardinality": "one",
        "searchable": False,
    },
    "component_type_definition": {
        "subjectKind": "assembly",
        "valueKind": "component_type",
        "cardinality": "many",
        "searchable": True,
    },
    "component_instance_definition": {
        "subjectKind": "occurrence",
        "valueKind": "component_instance",
        "cardinality": "one",
        "searchable": True,
    },
    "external_entity_definition": {
        "subjectKind": "assembly",
        "valueKind": "external_entity",
        "cardinality": "many",
        "searchable": True,
    },
    "functional_interface_definition": {
        "subjectKind": "interface",
        "valueKind": "functional_interface",
        "cardinality": "one",
        "searchable": True,
    },
    "functional_coverage_snapshot": {
        "subjectKind": "assembly",
        "valueKind": "coverage",
        "cardinality": "one",
        "searchable": False,
        "computedDiagnostic": True,
    },
    "cad_interface_relationship": {
        "subjectKind": "interface",
        "valueKind": "relationship",
        "cardinality": "one",
        "searchable": True,
    },
    "occurrence_role": {
        "subjectKind": "occurrence",
        "valueKind": "role",
        "cardinality": "many",
        "searchable": True,
    },
    "functional_relationship": {
        "subjectKind": "occurrence_or_interface",
        "valueKind": "relationship",
        "cardinality": "many",
        "searchable": True,
    },
    "joint_archetype": {
        "subjectKind": "interface",
        "valueKind": "joint_archetype",
        "cardinality": "one",
        "searchable": True,
    },
    "candidate_operation_family": {
        "subjectKind": "operation",
        "valueKind": "process_candidate",
        "cardinality": "one",
        "searchable": True,
    },
}


LEGACY_AUTHORITY_TRANSLATION: dict[str, tuple[str, str]] = {
    "cad_structure": ("derived", "supporting"),
    "cad_constraint": ("derived", "supporting"),
    "curated_profile": ("authored", "supporting"),
    "validated_motion": ("derived", "supporting"),
    "reviewed_inference": ("inferred", "supporting"),
}


class SemanticContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def translate_legacy_authority(value: str) -> tuple[str, str]:
    """Translate product-evidence authority without adapting continuity memory."""

    normalized = str(value or "").strip()
    if normalized == "untrusted_continuity":
        raise SemanticContractError(
            "continuity_authority_not_adapted",
            "Continuity-memory authority is not product evidence.",
        )
    try:
        return LEGACY_AUTHORITY_TRANSLATION[normalized]
    except KeyError as exc:
        raise SemanticContractError(
            "unknown_legacy_authority",
            f"Legacy authority is not mapped: {normalized or '<empty>'}",
        ) from exc


def is_synthetic_claim(
    claim: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    generated = claim.get("generatedBy")
    generator_id = ""
    if isinstance(generated, Mapping):
        generator_id = str(generated.get("generatorId") or "").lower()
    if "synthetic" in generator_id or "fixture" in generator_id:
        return True
    value = claim.get("value")
    if isinstance(value, Mapping) and str(value.get("evidenceClass") or "").upper().startswith(
        "SYNTHETIC"
    ):
        return True
    for evidence_id in claim.get("evidenceRefs") or []:
        evidence = evidence_by_id.get(str(evidence_id), {})
        details = evidence.get("details") if isinstance(evidence, Mapping) else {}
        if isinstance(details, Mapping) and str(
            details.get("evidenceClass") or ""
        ).upper().startswith("SYNTHETIC"):
            return True
    return False


def enforce_claim_write_policy(
    claim: Mapping[str, Any],
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    review_events: Sequence[Mapping[str, Any]] = (),
    authenticated_actor: bool = False,
) -> dict[str, Any]:
    """Return a policy-safe claim or reject an authority escalation.

    This function is intended for writers and adapters. It does not reinterpret
    historical documents during reads.
    """

    result = copy.deepcopy(dict(claim))
    generated = result.get("generatedBy")
    generated_kind = str(generated.get("kind") or "") if isinstance(generated, Mapping) else ""

    if generated_kind == "model":
        result["knowledgeStatus"] = "inferred"
        result["authority"] = "supporting"
        result["reviewStatus"] = "pending"

    if is_synthetic_claim(result, evidence_by_id):
        result["authority"] = "illustrative"
        matching_review = any(
            str(event.get("claimId") or "") == str(result.get("claimId") or "")
            and event.get("action") in {"confirm", "edit"}
            for event in review_events
            if isinstance(event, Mapping)
        )
        if not (authenticated_actor and matching_review):
            result["reviewStatus"] = "pending"

    authority = str(result.get("authority") or "")
    if authority not in {"approved", "authored"}:
        return result

    if generated_kind != "user" or not authenticated_actor:
        raise SemanticContractError(
            "authority_promotion_requires_authenticated_user",
            f"authority {authority} requires an authenticated user writer.",
        )
    matching_events = [
        event
        for event in review_events
        if isinstance(event, Mapping)
        and str(event.get("claimId") or "") == str(result.get("claimId") or "")
        and event.get("action") in {"confirm", "edit"}
        and str(event.get("actor") or "").strip()
    ]
    if not matching_events:
        raise SemanticContractError(
            "authority_promotion_requires_review_event",
            f"authority {authority} requires a revision-bound review event.",
        )
    evidence_authorities = {
        str(evidence_by_id.get(str(ref), {}).get("authority") or "")
        for ref in result.get("evidenceRefs") or []
    }
    required = {"approved"} if authority == "approved" else {"approved", "authored"}
    if not (evidence_authorities & required):
        raise SemanticContractError(
            "authority_promotion_lacks_evidence",
            f"authority {authority} lacks evidence with sufficient authority.",
        )
    return result


@dataclass(frozen=True)
class RetrievalDecision:
    eligible: bool
    code: str
    message: str


def package_retrieval_decision(
    package: Mapping[str, Any],
    *,
    prototype_mode: bool,
    controlled_use: bool = False,
    source_current: bool = True,
) -> RetrievalDecision:
    if not source_current:
        return RetrievalDecision(False, "stale_or_unbound_source", "Package source is not current.")
    if controlled_use:
        if package.get("readiness") != "production_ready" or package.get(
            "productionEligible"
        ) is not True:
            return RetrievalDecision(
                False,
                "controlled_package_not_eligible",
                "Controlled retrieval requires a production-ready eligible package.",
            )
        return RetrievalDecision(True, "eligible", "Controlled package is eligible.")
    if package.get("productionEligible") is True:
        return RetrievalDecision(True, "eligible", "Production-eligible package is eligible.")
    if not prototype_mode:
        return RetrievalDecision(
            False,
            "prototype_mode_required",
            "Non-production package retrieval requires explicit prototype mode.",
        )
    return RetrievalDecision(True, "prototype_eligible", "Prototype package is explicitly enabled.")


def _claim_priority(claim: Mapping[str, Any]) -> tuple[int, str]:
    predicate = str(claim.get("predicate") or "")
    status = str(claim.get("knowledgeStatus") or "")
    review = str(claim.get("reviewStatus") or "")
    if "conflict" in predicate or status == "unknown":
        rank = 0
    elif review in {"pending", "unknown", "deferred"}:
        rank = 1
    elif claim.get("authority") == "illustrative":
        rank = 2
    else:
        rank = 3
    return rank, str(claim.get("claimId") or "")


def bounded_retrieval_claims(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    prototype_mode: bool,
    controlled_use: bool = False,
    source_current: bool = True,
    predicates: Iterable[str] | None = None,
    subject_refs: Iterable[str] | None = None,
    max_claims: int = DEFAULT_MAX_RETRIEVED_CLAIMS,
    max_rendered_characters: int = DEFAULT_MAX_RENDERED_CHARACTERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    package = documents.get("package.json", {})
    decision = package_retrieval_decision(
        package,
        prototype_mode=prototype_mode,
        controlled_use=controlled_use,
        source_current=source_current,
    )
    diagnostics = {
        "contractVersion": SEMANTIC_CONTRACT_VERSION,
        "eligible": decision.eligible,
        "code": decision.code,
        "message": decision.message,
        "prototypeMode": bool(prototype_mode),
        "controlledUse": bool(controlled_use),
        "packageRevision": package.get("packageRevision"),
        "readiness": package.get("readiness"),
        "productionEligible": package.get("productionEligible"),
        "maxClaims": int(max_claims),
        "maxRenderedCharacters": int(max_rendered_characters),
    }
    if not decision.eligible:
        diagnostics.update({"candidateCount": 0, "returnedCount": 0, "truncated": False})
        return [], diagnostics

    allowed_predicates = {str(item) for item in predicates or []}
    allowed_subjects = {str(item) for item in subject_refs or []}
    candidates: list[dict[str, Any]] = []
    for name in ("functional_context.json", "process_candidates.json"):
        for raw in documents.get(name, {}).get("claims", []):
            if not isinstance(raw, Mapping):
                continue
            claim = dict(raw)
            if claim.get("reviewStatus") in {"rejected"}:
                continue
            if claim.get("authority") in {"untrusted"}:
                continue
            if not prototype_mode and claim.get("authority") == "illustrative":
                continue
            if allowed_predicates and str(claim.get("predicate")) not in allowed_predicates:
                continue
            if allowed_subjects and str(claim.get("subjectRef")) not in allowed_subjects:
                continue
            candidates.append(copy.deepcopy(claim))
    candidates.sort(key=_claim_priority)

    selected: list[dict[str, Any]] = []
    rendered_characters = 0
    for claim in candidates:
        rendered = json.dumps(
            claim,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(selected) >= max(0, int(max_claims)):
            break
        if selected and rendered_characters + len(rendered) > max_rendered_characters:
            break
        if not selected and len(rendered) > max_rendered_characters:
            continue
        selected.append(claim)
        rendered_characters += len(rendered)
    diagnostics.update(
        {
            "candidateCount": len(candidates),
            "returnedCount": len(selected),
            "renderedCharacters": rendered_characters,
            "truncated": len(selected) < len(candidates),
        }
    )
    return selected, diagnostics
