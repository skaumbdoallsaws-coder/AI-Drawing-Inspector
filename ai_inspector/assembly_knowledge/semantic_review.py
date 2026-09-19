"""Review-by-exception queue for the bounded semantic pilot."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .review import build_review_queue


_MOTION_OR_HAZARD_RE = re.compile(
    r"\b(?:brake|motor|ram|cylinder|motion|rotat|dynamic|actuat|drive|caster)\w*\b",
    re.IGNORECASE,
)

_WORKFLOW_REUSE: dict[str, tuple[str, ...]] = {
    "occurrence_role": (
        "fai",
        "training",
        "drawing_release",
        "revision_compare",
        "process_map",
        "documentation",
    ),
    "functional_relationship": (
        "fai",
        "training",
        "drawing_release",
        "revision_compare",
        "process_map",
        "documentation",
    ),
    "joint_archetype": (
        "fai",
        "training",
        "drawing_release",
        "revision_compare",
        "process_map",
        "documentation",
    ),
}


def _interface_degree(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    degree: dict[str, int] = {}
    for interface in documents.get("interface_graph.json", {}).get("interfaces", []):
        if not isinstance(interface, Mapping):
            continue
        for ref in interface.get("occurrenceRefs", []):
            if isinstance(ref, str):
                degree[ref] = degree.get(ref, 0) + 1
    return degree


def build_semantic_pilot_review_queue(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    prompt_version: str,
    founder_review_minutes: int = 0,
) -> dict[str, Any]:
    """Return only claims created by the named pilot, with impact diagnostics."""

    all_queue = build_review_queue(documents)
    all_model_claims = {
        claim["claimId"]: claim
        for name in ("functional_context.json", "process_candidates.json")
        for claim in documents.get(name, {}).get("claims", [])
        if isinstance(claim, Mapping)
        and isinstance(claim.get("generatedBy"), Mapping)
        and claim["generatedBy"].get("kind") == "model"
        and claim["generatedBy"].get("version") == prompt_version
    }
    model_claims = {
        claim_id: claim
        for claim_id, claim in all_model_claims.items()
        if claim.get("reviewStatus") == "pending"
    }
    degree = _interface_degree(documents)
    conflict_refs = {
        str(ref)
        for finding in documents.get("unresolved.json", {}).get("findings", [])
        if isinstance(finding, Mapping)
        and "conflict" in str(finding.get("code") or "").lower()
        for ref in finding.get("subjectRefs", [])
    }
    items = []
    for item in all_queue["items"]:
        claim = model_claims.get(item["claimId"])
        if claim is None:
            continue
        refs = [
            str(item.get("subjectRef") or ""),
            *[str(ref) for ref in item.get("objectRefs", [])],
        ]
        rendered = json.dumps(item.get("value"), ensure_ascii=True, sort_keys=True)
        motion_or_hazard = _MOTION_OR_HAZARD_RE.search(rendered) is not None
        maximum_degree = max((degree.get(ref, 0) for ref in refs), default=0)
        workflows = list(_WORKFLOW_REUSE.get(item["predicate"], ()))
        conflict = any(ref in conflict_refs for ref in refs)
        high_impact_reasons = []
        if motion_or_hazard:
            high_impact_reasons.append("motion_or_hazard_related_interpretation")
        if len(workflows) >= 3 and item["predicate"] in {
            "functional_relationship",
            "joint_archetype",
        }:
            high_impact_reasons.append("interface_semantics_reused_by_three_or_more_workflows")
        if conflict:
            high_impact_reasons.append("bound_conflict")
        enriched = dict(item)
        enriched.update(
            {
                "highImpact": bool(high_impact_reasons),
                "highImpactReasons": high_impact_reasons,
                "interfaceCentrality": maximum_degree,
                "potentialWorkflowReuse": workflows,
                "conflictBound": conflict,
                "prototypeReviewOnly": True,
                "authorityPromotionAllowed": False,
            }
        )
        items.append(enriched)
    items.sort(
        key=lambda item: (
            0 if item["highImpact"] else 1,
            -item["interfaceCentrality"],
            item["priority"],
            item["claimId"],
        )
    )
    pending_high_impact = sum(item["highImpact"] for item in items)
    total_pending = int(all_queue["summary"]["pendingClaimCount"])
    reviewed_count = sum(
        claim.get("reviewStatus")
        in {"confirmed", "edited", "rejected", "unknown", "deferred"}
        for claim in all_model_claims.values()
    )
    return {
        **all_queue,
        "scope": {
            "kind": "model_prompt_version",
            "promptVersion": prompt_version,
            "explicitPrototypeMode": True,
            "outsideScopePolicy": (
                "Remain pending in the package; excluded from this bounded "
                "semantic-pilot review budget and never auto-confirmed."
            ),
        },
        "summary": {
            **all_queue["summary"],
            "totalRepositoryPendingClaimCount": total_pending,
            "pilotPendingClaimCount": len(items),
            "outsidePilotPendingClaimCount": total_pending - len(items),
            "pendingHighImpactClaimCount": pending_high_impact,
            "totalPilotClaimCount": len(all_model_claims),
            "reviewedPilotClaimCount": reviewed_count,
            "reviewCapClaimCount": 60,
            "reviewCapPassed": len(all_model_claims) <= 60,
            "founderReviewMinutesRecorded": int(founder_review_minutes),
            "founderReviewCapMinutes": 480,
            "humanAuthorityGranted": False,
        },
        "items": items,
    }


__all__ = ["build_semantic_pilot_review_queue"]
