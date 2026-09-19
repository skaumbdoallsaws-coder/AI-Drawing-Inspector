"""Targeted, cost-bounded semantic enrichment for the MMLE pilot."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cache import AssemblyKnowledgeEnrichmentCache
from .cost_policy import authorize_enrichment_plan, plan_enrichment_request
from .enrichment import execute_economy_enrichment
from .provider import OpenAIMultimodalProvider
from .repository import AssemblyKnowledgeRepository
from .schema import validate_package_documents
from .semantic_rollout import MMLE_PACKAGE_ID, MMLE_PRODUCT_ID


SEMANTIC_PILOT_VERSION = "mmle-semantic-pilot-v1"
SEMANTIC_PILOT_MODEL = "gpt-4o-mini"
SEMANTIC_PILOT_PROVIDER = "openai"


_PILOT_CATEGORIES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("lift_mechanism", ("inner scissor-1",), "subassembly"),
    ("scissor_arm", ("scissor arm-1", "scissor arm-2"), "part"),
    ("platform", ("_top-1",), "subassembly"),
    ("hydraulic_cylinder", ("_cylinder-1",), "subassembly"),
    ("cylinder_barrel", ("cylinder barrel",), "part"),
    ("hydraulic_ram", ("_ram-1",), "part"),
    ("hydraulic_power_module", ("pump and motor assem",), "subassembly"),
    ("hydraulic_pump", ("_pump-1",), "part"),
    ("electric_motor", ("/user library-mmle-50d_motor-1",), "part"),
    ("hydraulic_reservoir", ("_tank-1",), "part"),
    ("control_valve", ("sv08",), "part"),
    ("solenoid_coil", ("_coil-1",), "part"),
    ("swivel_caster", ("swivel caster lh-1",), "subassembly"),
    ("parking_brake", ("brake lever",), "part"),
    ("battery_module", ("battery box-2",), "subassembly"),
    ("battery_switch", ("battery switch",), "part"),
    ("charger", ("/user library-mmle-50d_charger-1",), "part"),
    ("operator_handle", ("_handle-3",), "part"),
)

_FORBIDDEN_TEXT_RE = re.compile(
    r"\b(?:torque|tolerance|pressure|voltage|amperage|material|disposition|"
    r"approved|certified|safety procedure|load rating|load-bearing|force)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|in|ft|n|nm|n-m|psi|bar|v|a)\b",
    re.IGNORECASE,
)


class SemanticPilotError(RuntimeError):
    pass


def _interface_degree(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for interface in documents.get("interface_graph.json", {}).get("interfaces", []):
        if not isinstance(interface, Mapping):
            continue
        for occurrence_id in interface.get("occurrenceRefs", []):
            if isinstance(occurrence_id, str):
                result[occurrence_id] = result.get(occurrence_id, 0) + 1
    return result


def select_mmle_pilot_occurrences(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    maximum_entities: int = 18,
) -> list[dict[str, Any]]:
    """Select one central occurrence for each high-value pilot category."""

    if maximum_entities < 12 or maximum_entities > 20:
        raise SemanticPilotError("Pilot entity count must remain between 12 and 20.")
    occurrences = [
        item
        for item in documents.get("product_structure.json", {}).get("occurrences", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("occurrenceId"), str)
    ]
    degree = _interface_degree(documents)
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for category, patterns, preferred_kind in _PILOT_CATEGORIES:
        candidates = []
        for occurrence in occurrences:
            occurrence_id = str(occurrence["occurrenceId"])
            if occurrence_id in used:
                continue
            name = str(occurrence.get("name") or "").lower()
            if not any(pattern in name for pattern in patterns):
                continue
            kind_match = occurrence.get("kind") == preferred_kind
            candidates.append(
                (
                    0 if kind_match else 1,
                    -degree.get(occurrence_id, 0),
                    len(name),
                    occurrence_id,
                    occurrence,
                )
            )
        if not candidates:
            continue
        _, negative_degree, _, occurrence_id, occurrence = sorted(candidates)[0]
        selected.append(
            {
                "category": category,
                "occurrenceId": occurrence_id,
                "itemId": occurrence.get("itemId"),
                "name": occurrence.get("name"),
                "kind": occurrence.get("kind"),
                "interfaceDegree": -negative_degree,
                "selectionBasis": "keyword_category_then_interface_centrality",
            }
        )
        used.add(occurrence_id)
        if len(selected) >= maximum_entities:
            break
    if len(selected) < 12:
        raise SemanticPilotError(
            f"Only {len(selected)} representative MMLE entities were resolved."
        )
    return selected


def _model_claims(documents: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(claim)
        for name in ("functional_context.json", "process_candidates.json")
        for claim in documents.get(name, {}).get("claims", [])
        if isinstance(claim, Mapping)
        and isinstance(claim.get("generatedBy"), Mapping)
        and claim["generatedBy"].get("kind") == "model"
    ]


def semantic_pilot_gate(
    documents: Mapping[str, Mapping[str, Any]],
    output: Mapping[str, Any],
) -> dict[str, Any]:
    claims = _model_claims(documents)
    text_fields: list[dict[str, str]] = []
    for collection in (
        "occurrenceRoles",
        "functionalRelationships",
        "jointArchetypes",
        "assumptions",
        "unresolvedQuestions",
    ):
        for index, row in enumerate(output.get(collection, [])):
            if not isinstance(row, Mapping):
                continue
            for field in ("role", "function", "relationshipType", "description", "archetype", "text"):
                value = row.get(field)
                if isinstance(value, str) and _FORBIDDEN_TEXT_RE.search(value):
                    text_fields.append(
                        {
                            "path": f"$.{collection}[{index}].{field}",
                            "text": value,
                        }
                    )
    validation_errors = [
        item
        for item in validate_package_documents(documents)
        if item.get("severity") == "error"
    ]
    status_counts: dict[str, int] = {}
    for claim in claims:
        key = "/".join(
            str(claim.get(field) or "")
            for field in ("knowledgeStatus", "authority", "reviewStatus")
        )
        status_counts[key] = status_counts.get(key, 0) + 1
    checks = {
        "modelClaimCountAtMost60": len(claims) <= 60,
        "allModelClaimsInferredSupportingPending": bool(claims)
        and all(
            claim.get("knowledgeStatus") == "inferred"
            and claim.get("authority") == "supporting"
            and claim.get("reviewStatus") == "pending"
            for claim in claims
        ),
        "noForbiddenEngineeringText": not text_fields,
        "packageRemainsPrototype": documents.get("package.json", {}).get(
            "productionEligible"
        )
        is False,
        "schemaValid": not validation_errors,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "modelClaimCount": len(claims),
        "statusCounts": dict(sorted(status_counts.items())),
        "forbiddenTextFindings": text_fields,
        "validationErrors": validation_errors,
    }


def build_mmle_semantic_pilot_plan(
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    selected = select_mmle_pilot_occurrences(documents)
    selected_ids = [item["occurrenceId"] for item in selected]
    plan = plan_enrichment_request(
        documents,
        provider=SEMANTIC_PILOT_PROVIDER,
        model=SEMANTIC_PILOT_MODEL,
        prompt_version=SEMANTIC_PILOT_VERSION,
        maximum_output_tokens=4_000,
        changed_occurrence_ids=selected_ids,
        task_mode="semantic_pilot",
    )
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="founder-prototype",
        session_id="semantic-rollout-20260825",
        idempotency_key="semantic-mmle-economy-v1-20260825",
        unknown_pricing_acknowledged=True,
    )
    if authorization.get("authorized") is not True:
        raise SemanticPilotError(
            f"Economy authorization failed: {authorization.get('reason')}"
        )
    return selected, plan, authorization


def execute_mmle_semantic_pilot(
    repo_root: str | Path,
    *,
    api_key: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    repository = AssemblyKnowledgeRepository(root / "generated" / "training")
    documents = repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    selected, plan, authorization = build_mmle_semantic_pilot_plan(documents)
    cache = AssemblyKnowledgeEnrichmentCache(
        root / ".runtime" / "semantic-knowledge-rollout" / "enrichment-cache"
    )
    provider = OpenAIMultimodalProvider(
        api_key=api_key,
        model=SEMANTIC_PILOT_MODEL,
    )
    package_dir = repository.package_dir(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)
    result = execute_economy_enrichment(
        documents,
        package_dir=package_dir,
        budget_plan=plan,
        authorization=authorization,
        provider=provider,
        cache=cache,
    )
    gate = semantic_pilot_gate(result["documents"], result["output"])
    if not gate["passed"]:
        raise SemanticPilotError(
            "Semantic pilot failed its pre-publication gate: "
            + json.dumps(gate, ensure_ascii=True, sort_keys=True)
        )
    replay = execute_economy_enrichment(
        documents,
        package_dir=package_dir,
        budget_plan=plan,
        authorization=authorization,
        provider=provider,
        cache=cache,
    )
    cache_replay_passed = (
        replay["fromCache"] is True
        and replay["documents"]["package.json"]["packageRevision"]
        == result["documents"]["package.json"]["packageRevision"]
    )
    if not cache_replay_passed:
        raise SemanticPilotError("Identical semantic input did not replay from cache.")
    repository.write(
        result["documents"],
        base_revision=documents["package.json"]["packageRevision"],
    )
    return {
        "success": True,
        "selectedEntities": selected,
        "plan": dict(plan),
        "authorization": dict(authorization),
        "usage": dict(result["usage"]),
        "fromCache": bool(result["fromCache"]),
        "cacheReplayPassed": cache_replay_passed,
        "gate": gate,
        "outputSummary": {
            field: len(result["output"].get(field, []))
            for field in (
                "occurrenceRoles",
                "functionalRelationships",
                "jointArchetypes",
                "assumptions",
                "unresolvedQuestions",
            )
        },
        "basePackageRevision": documents["package.json"]["packageRevision"],
        "packageRevision": result["documents"]["package.json"]["packageRevision"],
        "productionEligible": result["documents"]["package.json"][
            "productionEligible"
        ],
    }


__all__ = [
    "SEMANTIC_PILOT_MODEL",
    "SEMANTIC_PILOT_PROVIDER",
    "SEMANTIC_PILOT_VERSION",
    "SemanticPilotError",
    "build_mmle_semantic_pilot_plan",
    "execute_mmle_semantic_pilot",
    "select_mmle_pilot_occurrences",
    "semantic_pilot_gate",
]
