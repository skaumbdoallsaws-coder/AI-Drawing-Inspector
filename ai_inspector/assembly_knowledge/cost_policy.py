"""Deterministic cost planning and authorization for assembly enrichment.

This module never calls a model provider. It computes a bounded request plan
and issues an authorization receipt bound to that exact plan.
"""

from __future__ import annotations

import copy
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ai_inspector.telemetry.pricing import (
    CONFIDENCE_UNKNOWN,
    compute_cost,
    lookup_pricing,
)

from .manifest import canonical_json_sha256, stable_id


_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "contracts"
    / "assembly-knowledge-enrichment-budget-v1.json"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EnrichmentBudgetError(ValueError):
    """Raised when a proposed paid request violates the budget contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@lru_cache(maxsize=1)
def load_enrichment_budget_contract() -> Dict[str, Any]:
    import json

    contract = json.loads(_CONTRACT_PATH.read_text(encoding="ascii"))
    if contract.get("contractVersion") != 1:
        raise RuntimeError("unsupported assembly enrichment budget contract")
    constraints = contract.get("constraints")
    if not isinstance(constraints, dict):
        raise RuntimeError("assembly enrichment budget constraints are missing")
    if int(constraints.get("defaultCalls", 0)) != 1:
        raise RuntimeError("Economy enrichment must default to one call")
    if int(constraints.get("maximumCalls", 0)) > 2:
        raise RuntimeError("Economy enrichment cannot permit more than two calls")
    return contract


def reset_enrichment_budget_contract_for_tests() -> None:
    load_enrichment_budget_contract.cache_clear()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise EnrichmentBudgetError(
            f"invalid_{field}",
            f"{field} must be a lowercase SHA-256 digest.",
        )
    return value


def _image_catalog(
    documents: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    visual = documents.get("visual_manifest.json")
    package = documents.get("package.json")
    if not isinstance(visual, Mapping) or not isinstance(package, Mapping):
        raise EnrichmentBudgetError(
            "visual_manifest_missing",
            "A validated visual manifest and package index are required.",
        )
    asset_hashes = package.get("assetHashes")
    if not isinstance(asset_hashes, Mapping):
        raise EnrichmentBudgetError(
            "asset_hashes_missing",
            "Package asset hashes are required.",
        )

    candidates: list[Dict[str, Any]] = []
    for sheet in visual.get("contactSheets", []):
        if not isinstance(sheet, Mapping):
            continue
        candidates.append(
            {
                "assetPath": sheet.get("assetPath"),
                "assetHash": sheet.get("assetHash"),
                "width": sheet.get("width"),
                "height": sheet.get("height"),
                "kind": "contact_sheet",
                "viewId": sheet.get("contactSheetId"),
            }
        )
    for view in visual.get("views", []):
        if not isinstance(view, Mapping) or view.get("kind") != "presentation":
            continue
        candidates.append(
            {
                "assetPath": view.get("assetPath"),
                "assetHash": view.get("assetHash"),
                "width": view.get("width"),
                "height": view.get("height"),
                "kind": "presentation",
                "viewId": view.get("viewId"),
            }
        )

    images: list[Dict[str, Any]] = []
    seen_paths = set()
    for candidate in candidates:
        path = candidate.get("assetPath")
        digest = candidate.get("assetHash")
        width = candidate.get("width")
        height = candidate.get("height")
        if not isinstance(path, str) or path in seen_paths:
            continue
        if asset_hashes.get(path) != digest:
            raise EnrichmentBudgetError(
                "image_hash_mismatch",
                f"Visual manifest hash does not match package asset hash: {path}",
            )
        _require_sha256(digest, "image_hash")
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            raise EnrichmentBudgetError(
                "invalid_image_dimensions",
                f"Image dimensions are invalid: {path}",
            )
        item = dict(candidate)
        item["pixels"] = width * height
        images.append(item)
        seen_paths.add(path)
    return images


def _select_images(
    images: Sequence[Mapping[str, Any]],
    *,
    maximum_images: int,
    maximum_pixels: int,
) -> list[Dict[str, Any]]:
    selected: list[Dict[str, Any]] = []
    used_pixels = 0
    for image in images:
        pixels = int(image["pixels"])
        if len(selected) >= maximum_images:
            break
        if used_pixels + pixels > maximum_pixels:
            continue
        selected.append(copy.deepcopy(dict(image)))
        used_pixels += pixels
    if images and not selected:
        raise EnrichmentBudgetError(
            "image_pixel_budget_exceeded",
            "No visual evidence fits within the submitted-image pixel budget.",
        )
    return selected


def required_process_input_occurrence_ids(
    structure: Mapping[str, Any],
) -> list[str]:
    """Return active leaf occurrences that a complete process must consume."""

    occurrences = [
        item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("occurrenceId"), str)
    ]
    root_occurrence_id = structure.get("rootOccurrenceId")
    active_ids = {
        item["occurrenceId"]
        for item in occurrences
        if not (
            isinstance(item.get("state"), Mapping)
            and item["state"].get("suppressed") is True
        )
    }
    active_parent_ids = {
        item["parentOccurrenceId"]
        for item in occurrences
        if item["occurrenceId"] in active_ids
        and isinstance(item.get("parentOccurrenceId"), str)
    }
    return sorted(
        occurrence_id
        for occurrence_id in active_ids
        if occurrence_id != root_occurrence_id
        and occurrence_id not in active_parent_ids
    )


def enrichment_process_reference_map(
    structure: Mapping[str, Any],
) -> Dict[str, str]:
    """Map canonical occurrence IDs to compact, request-local model handles."""

    occurrence_ids = sorted(
        item["occurrenceId"]
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("occurrenceId"), str)
    )
    root_occurrence_id = structure.get("rootOccurrenceId")
    result: Dict[str, str] = {}
    part_index = 0
    for occurrence_id in occurrence_ids:
        if occurrence_id == root_occurrence_id:
            result[occurrence_id] = "occRef-root"
            continue
        part_index += 1
        result[occurrence_id] = f"occRef-{part_index:03d}"
    return result


def build_enrichment_semantic_input(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    task_mode: str = "process_planning",
    selected_occurrence_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return the exact structured facts used to estimate input size."""

    structure = documents.get("product_structure.json", {})
    interfaces = documents.get("interface_graph.json", {})
    geometry = documents.get("geometry_summary.json", {})
    evidence = documents.get("evidence_catalog.json", {})
    if task_mode not in {"process_planning", "semantic_pilot"}:
        raise EnrichmentBudgetError(
            "invalid_task_mode",
            f"Unsupported enrichment task mode: {task_mode}",
        )

    process_refs = enrichment_process_reference_map(structure)
    occurrence_by_id = {
        item["occurrenceId"]: item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("occurrenceId"), str)
    }
    scoped_occurrence_ids = set(occurrence_by_id)
    scoped_interfaces: Optional[list[Mapping[str, Any]]] = None
    selected = sorted(set(selected_occurrence_ids or []))
    if task_mode == "semantic_pilot":
        if not selected:
            raise EnrichmentBudgetError(
                "semantic_pilot_scope_required",
                "semantic_pilot requires at least one selected occurrence.",
            )
        unknown = sorted(set(selected) - set(occurrence_by_id))
        if unknown:
            raise EnrichmentBudgetError(
                "unknown_selected_occurrence",
                "Selected enrichment occurrences are not in the package: "
                + ", ".join(unknown[:8]),
            )

        scoped_occurrence_ids = set(selected)
        root_occurrence_id = structure.get("rootOccurrenceId")
        if isinstance(root_occurrence_id, str):
            scoped_occurrence_ids.add(root_occurrence_id)

        # Include directly connected occurrences so a role or joint is never
        # inferred from an isolated endpoint. More distant assembly content is
        # deliberately excluded from this bounded Economy request.
        scoped_interfaces = []
        for item in interfaces.get("interfaces", []):
            if not isinstance(item, Mapping):
                continue
            refs = {
                ref
                for ref in item.get("occurrenceRefs", [])
                if isinstance(ref, str)
            }
            if refs & set(selected):
                scoped_interfaces.append(item)
                scoped_occurrence_ids.update(refs)

        # Preserve enough hierarchy to identify every selected or adjacent
        # occurrence without pulling in sibling subtrees.
        pending = list(scoped_occurrence_ids)
        while pending:
            occurrence_id = pending.pop()
            item = occurrence_by_id.get(occurrence_id)
            parent_id = item.get("parentOccurrenceId") if item else None
            if isinstance(parent_id, str) and parent_id not in scoped_occurrence_ids:
                scoped_occurrence_ids.add(parent_id)
                pending.append(parent_id)

    occurrences = []
    for item in structure.get("occurrences", []):
        if not isinstance(item, Mapping):
            continue
        if item.get("occurrenceId") not in scoped_occurrence_ids:
            continue
        occurrences.append(
            {
                "occurrenceId": item.get("occurrenceId"),
                "processRef": process_refs.get(item.get("occurrenceId")),
                "parentOccurrenceId": item.get("parentOccurrenceId"),
                "itemId": item.get("itemId"),
                "name": item.get("name"),
                "kind": item.get("kind"),
                "quantity": item.get("quantity"),
                "properties": item.get("properties", {}),
            }
        )
    mate_by_id = {
        item.get("mateId"): item
        for item in interfaces.get("mates", [])
        if isinstance(item, Mapping) and isinstance(item.get("mateId"), str)
    }
    relationships = []
    interface_rows = (
        scoped_interfaces
        if scoped_interfaces is not None
        else interfaces.get("interfaces", [])
    )
    for item in interface_rows:
        if not isinstance(item, Mapping):
            continue
        mate_refs = item.get("mateRefs", [])
        relationships.append(
            {
                "interfaceId": item.get("interfaceId"),
                "occurrenceRefs": item.get("occurrenceRefs"),
                "mateRefs": mate_refs,
                "mateTypes": sorted(
                    {
                        str(mate_by_id[ref].get("type"))
                        for ref in mate_refs
                        if ref in mate_by_id and mate_by_id[ref].get("type")
                    }
                ),
                "status": item.get("status"),
            }
        )
    result = {
        "sourceRevision": structure.get("sourceRevision"),
        "rootOccurrenceId": structure.get("rootOccurrenceId"),
        "rootProcessRef": process_refs.get(structure.get("rootOccurrenceId")),
        "requiredProcessInputRefs": (
            []
            if task_mode == "semantic_pilot"
            else [
                process_refs[occurrence_id]
                for occurrence_id in required_process_input_occurrence_ids(
                    structure
                )
            ]
        ),
        "occurrences": sorted(
            occurrences, key=lambda item: str(item.get("occurrenceId") or "")
        ),
        "interfaces": sorted(
            relationships, key=lambda item: str(item.get("interfaceId") or "")
        ),
        "geometryOccurrenceCount": len(geometry.get("occurrences", [])),
        "evidenceFingerprint": evidence.get("evidenceFingerprint"),
    }
    if task_mode == "semantic_pilot":
        result.update(
            {
                "taskMode": task_mode,
                "selectedOccurrenceRefs": [process_refs[item] for item in selected],
                "scopedOccurrenceCount": len(scoped_occurrence_ids),
                "totalOccurrenceCount": len(occurrence_by_id),
            }
        )
    return result


def _estimate_input_tokens(value: Any, *, prompt_characters: int) -> int:
    import json

    serialized = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    # Four characters per token is intentionally conservative for mostly
    # ASCII JSON. Image token accounting is represented separately as pixels.
    return max(1, math.ceil((len(serialized) + max(0, prompt_characters)) / 4))


def build_enrichment_cache_key(
    *,
    source_revision: str,
    evidence_fingerprint: str,
    image_hashes: Iterable[str],
    enrichment_policy_version: str,
    prompt_version: str,
    provider: str,
    model: str,
    task_mode: str = "process_planning",
    selected_occurrence_ids: Sequence[str] = (),
) -> str:
    identity = {
            "enrichmentPolicyVersion": enrichment_policy_version,
            "evidenceFingerprint": _require_sha256(
                evidence_fingerprint, "evidence_fingerprint"
            ),
            "imageHashes": sorted(_require_sha256(item, "image_hash") for item in image_hashes),
            "model": model,
            "promptVersion": prompt_version,
            "provider": provider,
            "sourceRevision": _require_sha256(source_revision, "source_revision"),
        }
    if task_mode != "process_planning" or selected_occurrence_ids:
        identity["taskMode"] = task_mode
        identity["selectedOccurrenceIds"] = sorted(set(selected_occurrence_ids))
    return canonical_json_sha256(identity)


def plan_enrichment_request(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_characters: int = 5_000,
    maximum_output_tokens: int = 4_000,
    schema_correction_required: bool = False,
    cache_hit: bool = False,
    changed_occurrence_ids: Optional[Sequence[str]] = None,
    task_mode: str = "process_planning",
) -> Dict[str, Any]:
    contract = load_enrichment_budget_contract()
    limits = contract["constraints"]
    package = documents.get("package.json")
    evidence = documents.get("evidence_catalog.json")
    structure = documents.get("product_structure.json")
    if not all(isinstance(item, Mapping) for item in (package, evidence, structure)):
        raise EnrichmentBudgetError(
            "package_documents_missing",
            "Package, product structure, and evidence catalog are required.",
        )
    source_revision = _require_sha256(
        package.get("sourceRevision"), "source_revision"
    )
    evidence_fingerprint = _require_sha256(
        evidence.get("evidenceFingerprint"), "evidence_fingerprint"
    )
    if structure.get("sourceRevision") != source_revision:
        raise EnrichmentBudgetError(
            "source_revision_mismatch",
            "Package and product-structure revisions do not match.",
        )
    if not isinstance(provider, str) or not provider.strip():
        raise EnrichmentBudgetError("invalid_provider", "provider is required")
    if not isinstance(model, str) or not model.strip():
        raise EnrichmentBudgetError("invalid_model", "model is required")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise EnrichmentBudgetError(
            "invalid_prompt_version", "prompt_version is required"
        )

    images = _select_images(
        _image_catalog(documents),
        maximum_images=int(limits["maximumImagesPerCall"]),
        maximum_pixels=int(limits["maximumSubmittedImagePixels"]),
    )
    planned_calls = 2 if schema_correction_required else int(limits["defaultCalls"])
    if planned_calls > int(limits["maximumCalls"]):
        raise EnrichmentBudgetError(
            "call_budget_exceeded",
            "Planned calls exceed the Economy hard limit.",
        )
    occurrence_ids = sorted(
        str(item.get("occurrenceId"))
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and isinstance(item.get("occurrenceId"), str)
    )
    changed = (
        sorted(set(changed_occurrence_ids))
        if changed_occurrence_ids is not None
        else occurrence_ids
    )
    input_snapshot = build_enrichment_semantic_input(
        documents,
        task_mode=task_mode,
        selected_occurrence_ids=(
            changed if task_mode == "semantic_pilot" else None
        ),
    )
    input_tokens = _estimate_input_tokens(
        input_snapshot,
        prompt_characters=prompt_characters,
    )
    output_tokens = int(maximum_output_tokens)
    if input_tokens > int(limits["maximumInputTokensPerCall"]):
        raise EnrichmentBudgetError(
            "input_token_budget_exceeded",
            "Estimated input tokens exceed the per-call limit.",
        )
    if output_tokens <= 0 or output_tokens > int(limits["maximumOutputTokensPerCall"]):
        raise EnrichmentBudgetError(
            "output_token_budget_exceeded",
            "Requested output tokens exceed the per-call limit.",
        )

    entry = lookup_pricing(provider, model)
    maximum_provider_attempts = min(
        int(limits["maximumCalls"]),
        planned_calls + (1 if planned_calls == 1 else 0),
    )
    planned_cost, pricing_confidence = compute_cost(
        provider,
        model,
        inputTokens=input_tokens * planned_calls,
        outputTokens=output_tokens * planned_calls,
    )
    maximum_cost, _ = compute_cost(
        provider,
        model,
        inputTokens=input_tokens * maximum_provider_attempts,
        outputTokens=output_tokens * maximum_provider_attempts,
    )
    cost_available = entry is not None and pricing_confidence != CONFIDENCE_UNKNOWN
    if cost_available and maximum_cost > float(limits["maximumEstimatedCostUsd"]):
        raise EnrichmentBudgetError(
            "estimated_cost_budget_exceeded",
            "Estimated maximum cost exceeds the Economy limit.",
        )
    retry_cost = (
        max(0.0, maximum_cost - planned_cost) if cost_available else None
    )
    if (
        retry_cost is not None
        and retry_cost > float(limits["maximumRetryCostUsd"])
    ):
        raise EnrichmentBudgetError(
            "retry_cost_budget_exceeded",
            "Maximum retry cost exceeds the Economy limit.",
        )

    cache_key = build_enrichment_cache_key(
        source_revision=source_revision,
        evidence_fingerprint=evidence_fingerprint,
        image_hashes=(item["assetHash"] for item in images),
        enrichment_policy_version=str(package.get("enrichmentPolicyVersion")),
        prompt_version=prompt_version,
        provider=provider,
        model=model,
        task_mode=task_mode,
        selected_occurrence_ids=(
            changed if task_mode == "semantic_pilot" else ()
        ),
    )
    request_fingerprint = canonical_json_sha256(
        {
            "cacheKey": cache_key,
            "calls": planned_calls,
            "images": [
                {
                    "assetHash": item["assetHash"],
                    "assetPath": item["assetPath"],
                    "height": item["height"],
                    "width": item["width"],
                }
                for item in images
            ],
            "inputTokensPerCall": input_tokens,
            "outputTokensPerCall": output_tokens,
            "schemaCorrectionOnly": bool(schema_correction_required),
            "taskMode": task_mode,
            "selectedOccurrenceIds": (
                changed if task_mode == "semantic_pilot" else []
            ),
        }
    )
    return {
        "contractVersion": contract["contractVersion"],
        "policyVersion": contract["policyVersion"],
        "productId": package.get("productId"),
        "packageId": package.get("packageId"),
        "packageRevision": package.get("packageRevision"),
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "provider": provider,
        "model": model,
        "promptVersion": prompt_version,
        "requestFingerprint": request_fingerprint,
        "cacheKey": cache_key,
        "cacheHit": bool(cache_hit),
        "plannedCalls": 0 if cache_hit else planned_calls,
        "uncachedPlannedCalls": planned_calls,
        "maximumCalls": int(limits["maximumCalls"]),
        "maximumProviderAttempts": maximum_provider_attempts,
        "maximumRetries": maximum_provider_attempts - planned_calls,
        "perOccurrenceCalls": 0,
        "perInterfaceCalls": 0,
        "images": images,
        "imagesPerCall": len(images),
        "submittedImagePixelsPerCall": sum(item["pixels"] for item in images),
        "estimatedInputTokensPerCall": input_tokens,
        "maximumOutputTokensPerCall": output_tokens,
        "estimatedPlannedCostUsd": round(planned_cost, 8) if cost_available else None,
        "estimatedMaximumCostUsd": round(maximum_cost, 8) if cost_available else None,
        "maximumRetryCostUsd": round(retry_cost, 8) if retry_cost is not None else None,
        "pricingConfidence": pricing_confidence,
        "pricingKnown": cost_available,
        "taskMode": task_mode,
        "selectedOccurrenceIds": (
            changed if task_mode == "semantic_pilot" else []
        ),
        "changedOccurrenceIds": changed,
        "changedOccurrenceCount": len(changed),
        "occurrenceCount": len(occurrence_ids),
        "schemaCorrectionOnly": bool(schema_correction_required),
    }


def authorize_enrichment_plan(
    plan: Mapping[str, Any],
    *,
    explicit_approval: bool,
    user_id: str,
    session_id: str,
    idempotency_key: str,
    unknown_pricing_acknowledged: bool = False,
) -> Dict[str, Any]:
    contract = load_enrichment_budget_contract()
    limits = contract["constraints"]
    if limits.get("requireExplicitApproval") and explicit_approval is not True:
        return {"authorized": False, "reason": "explicit_approval_required"}
    maximum = int(limits.get("identityMaxLength", 128))
    for field, value in (("user_id", user_id), ("session_id", session_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            return {"authorized": False, "reason": f"invalid_{field}"}
    pattern = str(limits["idempotencyKeyPattern"])
    if not isinstance(idempotency_key, str) or re.fullmatch(pattern, idempotency_key) is None:
        return {"authorized": False, "reason": "invalid_idempotency_key"}
    if (
        not plan.get("pricingKnown")
        and limits.get("requireUnknownPricingAcknowledgement")
        and unknown_pricing_acknowledged is not True
    ):
        return {
            "authorized": False,
            "reason": "unknown_pricing_acknowledgement_required",
        }
    if int(plan.get("uncachedPlannedCalls", -1)) > int(limits["maximumCalls"]):
        return {"authorized": False, "reason": "call_budget_exceeded"}
    if int(plan.get("maximumProviderAttempts", -1)) > int(
        limits["maximumCalls"]
    ):
        return {"authorized": False, "reason": "provider_attempt_budget_exceeded"}
    if int(plan.get("imagesPerCall", -1)) > int(limits["maximumImagesPerCall"]):
        return {"authorized": False, "reason": "image_count_budget_exceeded"}
    if int(plan.get("submittedImagePixelsPerCall", -1)) > int(
        limits["maximumSubmittedImagePixels"]
    ):
        return {"authorized": False, "reason": "image_pixel_budget_exceeded"}
    if int(plan.get("estimatedInputTokensPerCall", -1)) > int(
        limits["maximumInputTokensPerCall"]
    ):
        return {"authorized": False, "reason": "input_token_budget_exceeded"}
    if int(plan.get("maximumOutputTokensPerCall", -1)) > int(
        limits["maximumOutputTokensPerCall"]
    ):
        return {"authorized": False, "reason": "output_token_budget_exceeded"}
    fingerprint = plan.get("requestFingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        return {"authorized": False, "reason": "invalid_request_fingerprint"}

    authorization_id = stable_id(
        "akpauth",
        {
            "idempotencyKey": idempotency_key,
            "requestFingerprint": fingerprint,
            "sessionId": session_id,
            "userId": user_id,
        },
        digest_length=24,
    )
    return {
        "authorized": True,
        "reason": "authorized",
        "authorizationId": authorization_id,
        "contractVersion": contract["contractVersion"],
        "policyVersion": contract["policyVersion"],
        "requestFingerprint": fingerprint,
        "cacheKey": plan.get("cacheKey"),
        "pricingKnown": bool(plan.get("pricingKnown")),
        "unknownPricingAcknowledged": bool(unknown_pricing_acknowledged),
        "limits": {
            "maximumCalls": int(plan.get("uncachedPlannedCalls", 0)),
            "maximumProviderAttempts": int(
                plan.get("maximumProviderAttempts", 0)
            ),
            "maximumImagesPerCall": int(plan.get("imagesPerCall", 0)),
            "maximumSubmittedImagePixelsPerCall": int(
                plan.get("submittedImagePixelsPerCall", 0)
            ),
            "maximumInputTokensPerCall": int(
                plan.get("estimatedInputTokensPerCall", 0)
            ),
            "maximumOutputTokensPerCall": int(
                plan.get("maximumOutputTokensPerCall", 0)
            ),
        },
        "actor": {
            "userId": user_id,
            "sessionId": session_id,
        },
        "idempotencyKey": idempotency_key,
    }


def assert_authorization_matches_plan(
    plan: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> None:
    if authorization.get("authorized") is not True:
        raise EnrichmentBudgetError(
            "authorization_required",
            "The enrichment plan is not authorized.",
        )
    if authorization.get("requestFingerprint") != plan.get("requestFingerprint"):
        raise EnrichmentBudgetError(
            "authorization_fingerprint_mismatch",
            "Authorization does not match the current enrichment request.",
        )
    if authorization.get("cacheKey") != plan.get("cacheKey"):
        raise EnrichmentBudgetError(
            "authorization_cache_key_mismatch",
            "Authorization does not match the current enrichment cache key.",
        )


def enrichment_budget_metadata() -> Dict[str, Any]:
    contract = load_enrichment_budget_contract()
    return {
        "contractVersion": contract["contractVersion"],
        "policyVersion": contract["policyVersion"],
        "constraints": copy.deepcopy(contract["constraints"]),
        "invariants": copy.deepcopy(contract["invariants"]),
    }
