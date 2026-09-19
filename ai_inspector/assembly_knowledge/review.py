"""Revision-bound review queue and auditable claim actions."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .manifest import refresh_package_revision, stable_id
from .schema import AssemblyKnowledgeSchemaError, validate_package_documents
from .validation import validate_assembly_knowledge_package, validation_summary


_ACTIONS = {"confirm", "edit", "reject", "mark_unknown", "defer"}
_ACTION_STATUS = {
    "confirm": "confirmed",
    "edit": "edited",
    "reject": "rejected",
    "mark_unknown": "unknown",
    "defer": "deferred",
}
_PREDICATE_PRIORITY = {
    "candidate_process_branch": 10,
    "candidate_operation_family": 12,
    "candidate_intermediate_result": 14,
    "joint_archetype": 20,
    "functional_relationship": 24,
    "occurrence_role": 30,
}


class AssemblyKnowledgeReviewError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _all_claims(
    documents: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    rows = []
    for name in ("functional_context.json", "process_candidates.json"):
        for claim in documents.get(name, {}).get("claims", []):
            if isinstance(claim, Mapping):
                rows.append(dict(claim))
    return rows


def _visual_context(
    documents: Mapping[str, Mapping[str, Any]],
    refs: Iterable[str],
) -> Dict[str, Any]:
    ref_set = set(refs)
    interface_rows = {
        str(item.get("interfaceId")): item
        for item in documents["interface_graph.json"].get("interfaces", [])
        if isinstance(item, Mapping)
    }
    mate_rows = {
        str(item.get("mateId")): item
        for item in documents["interface_graph.json"].get("mates", [])
        if isinstance(item, Mapping)
    }
    occurrence_ids = {
        str(ref) for ref in ref_set if str(ref).startswith("occ-")
    }
    for ref in ref_set:
        relationship = interface_rows.get(str(ref)) or mate_rows.get(str(ref))
        if not relationship:
            continue
        occurrence_ids.update(
            str(value)
            for value in relationship.get("occurrenceRefs", [])
            if isinstance(value, str)
        )
    occurrence_names = {
        str(item.get("occurrenceId")): item.get("name")
        for item in documents["product_structure.json"].get("occurrences", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("occurrenceId"), str)
    }
    views = []
    for view in documents.get("visual_manifest.json", {}).get("views", []):
        if not isinstance(view, Mapping):
            continue
        visible = set(view.get("visibleOccurrenceIds", []))
        overlap = sorted(occurrence_ids & visible)
        if overlap:
            views.append(
                {
                    "viewId": view.get("viewId"),
                    "assetPath": view.get("assetPath"),
                    "matchingOccurrenceIds": overlap,
                }
            )
    return {
        "occurrenceIds": sorted(occurrence_ids),
        "occurrences": [
            {
                "occurrenceId": occurrence_id,
                "name": occurrence_names.get(occurrence_id),
            }
            for occurrence_id in sorted(occurrence_ids)
        ],
        "interfaceIds": sorted(
            ref for ref in ref_set if str(ref).startswith("interface-")
        ),
        "mateIds": sorted(
            ref for ref in ref_set if str(ref).startswith("mate-")
        ),
        "views": views[:4],
    }


def _entity_context(
    documents: Mapping[str, Mapping[str, Any]],
    refs: Iterable[str],
) -> list[Dict[str, Any]]:
    entities: Dict[str, Dict[str, Any]] = {}
    for occurrence in documents["product_structure.json"].get("occurrences", []):
        if not isinstance(occurrence, Mapping):
            continue
        occurrence_id = occurrence.get("occurrenceId")
        if not isinstance(occurrence_id, str):
            continue
        entities[occurrence_id] = {
            "ref": occurrence_id,
            "kind": "occurrence",
            "name": occurrence.get("name"),
            "itemId": occurrence.get("itemId"),
            "parentOccurrenceId": occurrence.get("parentOccurrenceId"),
        }
    for kind, field, identifier in (
        ("interface", "interfaces", "interfaceId"),
        ("mate", "mates", "mateId"),
    ):
        for item in documents["interface_graph.json"].get(field, []):
            if not isinstance(item, Mapping):
                continue
            ref = item.get(identifier)
            if not isinstance(ref, str):
                continue
            entities[ref] = {
                "ref": ref,
                "kind": kind,
                "name": item.get("name") or item.get("interfaceType") or ref,
                "relationshipType": item.get("relationshipType")
                or item.get("mateType")
                or item.get("interfaceType"),
                "occurrenceRefs": list(item.get("occurrenceRefs", [])),
            }
    return [
        copy.deepcopy(entities[ref])
        for ref in refs
        if ref in entities
    ]


def build_review_queue(
    documents: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    findings = validate_assembly_knowledge_package(documents)
    pending_findings = [
        item
        for item in findings
        if item.get("severity") in {"error", "warning"}
        and item.get("code") != "inferred_claim_pending_review"
    ]
    evidence_by_id = {
        item["evidenceId"]: item
        for item in documents["evidence_catalog.json"].get("sources", [])
        if isinstance(item, Mapping) and isinstance(item.get("evidenceId"), str)
    }
    items = []
    for claim in _all_claims(documents):
        if claim.get("reviewStatus") != "pending":
            continue
        claim_id = claim["claimId"]
        refs = [
            claim.get("subjectRef"),
            *claim.get("objectRefs", []),
        ]
        evidence_rows = [
            copy.deepcopy(evidence_by_id[ref])
            for ref in claim.get("evidenceRefs", [])
            if ref in evidence_by_id
        ]
        predicate = str(claim.get("predicate"))
        items.append(
            {
                "queueItemId": stable_id(
                    "review",
                    {
                        "claimId": claim_id,
                        "packageRevision": documents["package.json"][
                            "packageRevision"
                        ],
                    },
                    digest_length=20,
                ),
                "kind": "claim",
                "priority": _PREDICATE_PRIORITY.get(predicate, 35),
                "claimId": claim_id,
                "predicate": predicate,
                "subjectRef": claim.get("subjectRef"),
                "objectRefs": list(claim.get("objectRefs", [])),
                "value": copy.deepcopy(claim.get("value")),
                "knowledgeStatus": claim.get("knowledgeStatus"),
                "authority": claim.get("authority"),
                "reviewStatus": claim.get("reviewStatus"),
                "evidence": evidence_rows,
                "visualContext": _visual_context(documents, refs),
                "entities": _entity_context(documents, refs),
                "whyItMatters": {
                    "candidate_process_branch": "Affects process scope and branch organization.",
                    "candidate_operation_family": "Affects the work represented in the process map.",
                    "candidate_intermediate_result": "Affects process stage boundaries.",
                    "joint_archetype": "Affects how connected parts may be assembled.",
                    "functional_relationship": "Affects which parts belong in the same process branch.",
                    "occurrence_role": "Affects how the component is interpreted.",
                }.get(predicate, "Affects process-planning context."),
                "actions": [
                    "confirm",
                    "edit",
                    "reject",
                    "mark_unknown",
                    "defer",
                ],
            }
        )
    items.sort(key=lambda item: (item["priority"], item["claimId"]))
    package = documents["package.json"]
    asset_hashes = package.get("assetHashes", {})
    assembly_asset = next(
        (
            path
            for path in sorted(asset_hashes)
            if path.lower().endswith((".glb", ".gltf"))
        ),
        None,
    )
    return {
        "schemaVersion": 1,
        "identity": {
            "productId": package["productId"],
            "packageId": package["packageId"],
            "packageRevision": package["packageRevision"],
            "sourceRevision": package["sourceRevision"],
            "readiness": package["readiness"],
            "productionEligible": package["productionEligible"],
        },
        "summary": {
            **validation_summary(findings),
            "pendingClaimCount": len(items),
            "reviewEventCount": len(
                documents["review_receipt.json"].get("events", [])
            ),
        },
        "assets": {
            "assemblyModel": assembly_asset,
            "presentationViews": [
                {
                    "viewId": view.get("viewId"),
                    "assetPath": view.get("assetPath"),
                    "width": view.get("width"),
                    "height": view.get("height"),
                }
                for view in documents["visual_manifest.json"].get("views", [])
                if isinstance(view, Mapping)
                and isinstance(view.get("assetPath"), str)
            ],
        },
        "items": items,
        "findings": pending_findings,
    }


def _sync_structured_review_state(
    value: Any,
    *,
    claim_id: str,
    review_status: str,
    knowledge_status: str,
    authority: str,
    edited_value: Any = None,
) -> None:
    if isinstance(value, dict):
        if value.get("claimId") == claim_id:
            value["reviewStatus"] = review_status
            value["knowledgeStatus"] = knowledge_status
            value["authority"] = authority
            if isinstance(edited_value, Mapping) and "generatedBy" not in value:
                if isinstance(edited_value.get("description"), str):
                    value["description"] = edited_value["description"]
                if isinstance(edited_value.get("label"), str):
                    value["label"] = edited_value["label"]
        for child in value.values():
            _sync_structured_review_state(
                child,
                claim_id=claim_id,
                review_status=review_status,
                knowledge_status=knowledge_status,
                authority=authority,
                edited_value=edited_value,
            )
    elif isinstance(value, list):
        for child in value:
            _sync_structured_review_state(
                child,
                claim_id=claim_id,
                review_status=review_status,
                knowledge_status=knowledge_status,
                authority=authority,
                edited_value=edited_value,
            )


def apply_review_action(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    base_revision: str,
    source_revision: str,
    claim_id: str,
    action: str,
    actor: str,
    edited_value: Any = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    package = documents["package.json"]
    if package.get("packageRevision") != base_revision:
        raise AssemblyKnowledgeReviewError(
            "stale_package_revision",
            "Review action targets a stale package revision.",
        )
    if package.get("sourceRevision") != source_revision:
        raise AssemblyKnowledgeReviewError(
            "stale_source_revision",
            "Review action targets a stale source revision.",
        )
    if action not in _ACTIONS:
        raise AssemblyKnowledgeReviewError(
            "invalid_review_action",
            "Unsupported review action.",
        )
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 160:
        raise AssemblyKnowledgeReviewError("invalid_actor", "actor is required.")
    copied = {
        str(name): copy.deepcopy(dict(document))
        for name, document in documents.items()
    }
    target = None
    for name in ("functional_context.json", "process_candidates.json"):
        for claim in copied[name].get("claims", []):
            if claim.get("claimId") == claim_id:
                target = claim
                break
        if target is not None:
            break
    if target is None:
        raise AssemblyKnowledgeReviewError(
            "claim_not_found",
            "Review claim was not found.",
        )
    if target.get("reviewStatus") not in {"pending", "deferred"}:
        raise AssemblyKnowledgeReviewError(
            "claim_already_reviewed",
            "Claim is no longer pending review.",
        )
    if action == "edit" and edited_value is None:
        raise AssemblyKnowledgeReviewError(
            "edited_value_required",
            "Edit requires a replacement value.",
        )
    before = copy.deepcopy(target)
    target["reviewStatus"] = _ACTION_STATUS[action]
    if action == "edit":
        target["value"] = copy.deepcopy(edited_value)
    elif action == "mark_unknown":
        target["knowledgeStatus"] = "unknown"
        target["value"] = None
    # Confirmation records human review but deliberately does not promote a
    # model candidate to authored/approved authority.
    target["authority"] = before["authority"]
    if action != "mark_unknown":
        target["knowledgeStatus"] = before["knowledgeStatus"]
    _sync_structured_review_state(
        copied,
        claim_id=claim_id,
        review_status=target["reviewStatus"],
        knowledge_status=target["knowledgeStatus"],
        authority=target["authority"],
        edited_value=edited_value if action == "edit" else None,
    )
    after = copy.deepcopy(target)
    event_timestamp = timestamp or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    event = {
        "eventId": stable_id(
            "review-event",
            {
                "action": action,
                "actor": actor,
                "baseRevision": base_revision,
                "claimId": claim_id,
                "timestamp": event_timestamp,
            },
            digest_length=24,
        ),
        "claimId": claim_id,
        "action": action,
        "actor": actor.strip(),
        "timestamp": event_timestamp,
        "before": before,
        "after": after,
    }
    copied["review_receipt.json"]["events"].append(event)
    copied["review_receipt.json"]["events"].sort(
        key=lambda item: (item["timestamp"], item["eventId"])
    )
    refreshed = refresh_package_revision(copied)
    errors = [
        item
        for item in validate_package_documents(refreshed)
        if item.get("severity") == "error"
    ]
    if errors:
        raise AssemblyKnowledgeSchemaError(errors)
    return refreshed
