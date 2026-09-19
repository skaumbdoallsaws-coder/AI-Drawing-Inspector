"""Deterministic Sage Memory Envelope and context-manifest construction."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .continuity import ContinuityProjection
from .invalidation import (
    RECONCILIATION_OUTCOMES,
    RECONCILIATION_SCHEMA_VERSION,
    normalize_revision_vector,
    revision_vector_sha256,
)
from .models import canonical_json, canonical_sha256


MEMORY_ENVELOPE_SCHEMA_VERSION = "sage-memory-envelope-1.0"
CONTEXT_MANIFEST_SCHEMA_VERSION = "sage-context-manifest-1.0"
DEFAULT_ENVELOPE_ALLOCATIONS = {
    "trustedContext": 6000,
    "workflowAndReceipts": 800,
    "continuitySummary": 1200,
    "recentTurns": 2400,
    "crossAgentProjection": 600,
    "metadata": 600,
    "currentUserRequest": 2000,
}
DEFAULT_ENVELOPE_MAX_TOKENS = sum(DEFAULT_ENVELOPE_ALLOCATIONS.values())

_FORBIDDEN_KEY = re.compile(
    r"(?:api[_-]?key|authorization|password|secret|access[_-]?token|cookie)",
    re.IGNORECASE,
)
_RAW_IMAGE_PREFIXES = ("data:image/", "data:application/pdf")


class MemoryEnvelopeError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code)
        self.details = copy.deepcopy(dict(details or {}))


@dataclass(frozen=True)
class MemoryEnvelopeBuildResult:
    envelope: dict[str, Any]
    manifest: dict[str, Any]
    memory_envelope_sha256: str
    prompt_sections: str


def estimate_json_tokens(value: Any) -> int:
    return int(math.ceil(len(canonical_json(value)) / 4.0))


def build_memory_envelope(
    *,
    context_manifest_id: str,
    identity: Mapping[str, Any],
    scope: Mapping[str, Any],
    workflow_state: Optional[Mapping[str, Any]],
    providers: Sequence[Mapping[str, Any]],
    approved_source_decisions: Sequence[Mapping[str, Any]],
    continuity: ContinuityProjection,
    receipts: Sequence[Mapping[str, Any]],
    selected_skills: Sequence[str],
    allowed_tools: Sequence[str],
    restrictions: Sequence[str],
    classification: str,
    current_user_request: str,
    cross_agent_projection: Optional[str] = None,
    reconciliation: Optional[Mapping[str, Any]] = None,
    allocations: Optional[Mapping[str, Any]] = None,
    maximum_tokens: int = DEFAULT_ENVELOPE_MAX_TOKENS,
    warnings: Sequence[str] = (),
) -> MemoryEnvelopeBuildResult:
    """Build one canonical envelope and its non-secret audit manifest."""

    manifest_id = _required_text(context_manifest_id, "context_manifest_id")
    normalized_identity = _identity(identity)
    normalized_scope = _scope(scope)
    normalized_workflow = _workflow(workflow_state)
    normalized_reconciliation = _reconciliation(
        reconciliation,
        normalized_scope,
    )
    normalized_allocations = _allocations(allocations)
    normalized_warnings = _unique_strings(warnings)
    provider_rows, trusted_context, source_hashes, omissions = _providers(
        providers
    )
    decisions = _approved_decisions(approved_source_decisions)
    normalized_receipts, receipt_warnings = _receipts(receipts)
    normalized_warnings = _unique_strings(
        [*normalized_warnings, *receipt_warnings]
    )
    capability_block = {
        "selectedSkills": _unique_strings(selected_skills),
        "allowedTools": _unique_strings(allowed_tools),
        "restrictions": _unique_strings(restrictions),
    }
    summary_value = (
        copy.deepcopy(continuity.summary)
        if continuity.summary is not None and continuity.status != "stateless"
        else None
    )
    continuity_block = {
        "status": continuity.status,
        "summary": summary_value,
        "recentTurns": [copy.deepcopy(item) for item in continuity.recent_history],
        "throughTurnSequence": continuity.through_turn_sequence,
        "unsummarizedTurnCount": continuity.unsummarized_turn_count,
        "oldestUnsummarizedTurnSequence": (
            continuity.oldest_unsummarized_turn_sequence
        ),
        "authority": "untrusted_continuity",
    }
    _reject_unsafe_payload(trusted_context, path="observations.trustedContext")
    _reject_unsafe_payload(decisions, path="approvedSourceDecisions")
    _reject_unsafe_payload(normalized_receipts, path="receipts")

    section_tokens = {
        "trustedContext": sum(row["estimatedTokens"] for row in provider_rows),
        "workflowAndReceipts": estimate_json_tokens(
            {
                "workflow": normalized_workflow,
                "receipts": normalized_receipts,
                "reconciliation": normalized_reconciliation,
            }
        ),
        "continuitySummary": estimate_json_tokens(summary_value),
        "recentTurns": estimate_json_tokens(continuity_block["recentTurns"]),
        "crossAgentProjection": estimate_json_tokens(
            cross_agent_projection or ""
        ),
        "metadata": estimate_json_tokens(
            {
                "identity": normalized_identity,
                "scope": normalized_scope,
                "capabilities": capability_block,
                "decisions": decisions,
            }
        ),
        "currentUserRequest": estimate_json_tokens(current_user_request),
    }
    _enforce_allocations(
        section_tokens,
        normalized_allocations,
        providers=provider_rows,
        maximum_tokens=int(maximum_tokens),
    )
    estimated_total = sum(section_tokens.values())
    envelope = {
        "schemaVersion": MEMORY_ENVELOPE_SCHEMA_VERSION,
        "identity": normalized_identity,
        "scope": normalized_scope,
        "workflow": normalized_workflow,
        "reconciliation": normalized_reconciliation,
        "observations": {
            "trustedContext": trusted_context,
            "liveStateOverridesMemory": True,
        },
        "approvedSourceDecisions": decisions,
        "continuity": continuity_block,
        "receipts": normalized_receipts,
        "capabilities": capability_block,
        "budget": {
            "allocations": normalized_allocations,
            "estimatedTokens": estimated_total,
            "omissions": omissions,
        },
        "provenance": {
            "contextManifestId": manifest_id,
            "sourceHashes": source_hashes,
            "warnings": normalized_warnings,
        },
    }
    envelope_hash = canonical_sha256(envelope)
    source_revision_hash = revision_vector_sha256(
        normalized_scope["revisionVector"]
    )
    manifest = {
        "schemaVersion": CONTEXT_MANIFEST_SCHEMA_VERSION,
        "turnId": normalized_identity["turnId"],
        "memoryEnvelopeSha256": envelope_hash,
        "providers": provider_rows,
        "continuity": {
            "status": continuity.status,
            "summaryRevision": continuity.summary_revision,
            "throughTurnSequence": continuity.through_turn_sequence,
            "recentTurnIds": list(continuity.recent_turn_ids),
            "omittedTurnCount": continuity.omitted_turn_count,
            "unsummarizedTurnCount": continuity.unsummarized_turn_count,
            "oldestUnsummarizedTurnSequence": (
                continuity.oldest_unsummarized_turn_sequence
            ),
            "allUnsummarizedTurnsIncluded": (
                continuity.all_unsummarized_turns_included
            ),
        },
        "reconciliation": normalized_reconciliation,
        "revisionBarrier": {
            "classification": _classification(classification),
            "sourceRevisionVectorSha256": source_revision_hash,
            "preEffectRevisionVectorSha256": source_revision_hash,
            "outcome": "matched",
            "resultingRevisionVectorSha256": None,
            "postEffectRevisionDrift": False,
        },
        "budget": {
            "maximum": int(maximum_tokens),
            "estimated": estimated_total,
            "exceeded": False,
        },
        "warnings": normalized_warnings,
    }
    _reject_unsafe_payload(manifest, path="contextManifest")
    return MemoryEnvelopeBuildResult(
        envelope=copy.deepcopy(envelope),
        manifest=copy.deepcopy(manifest),
        memory_envelope_sha256=envelope_hash,
        prompt_sections=render_memory_envelope_prompt(envelope),
    )


def finalize_context_manifest(
    manifest: Mapping[str, Any],
    revision_barrier: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the terminal revision barrier without changing envelope identity."""

    finalized = copy.deepcopy(dict(manifest))
    barrier = dict(revision_barrier or {})
    outcome = str(barrier.get("outcome") or "").strip()
    if not outcome:
        if barrier.get("errorCode") == "revision_advanced_during_turn":
            outcome = "revision_advanced_during_turn"
        elif barrier.get("errorCode") == "cas_conflict" or str(
            barrier.get("casOutcome") or ""
        ).lower() == "conflict":
            outcome = "cas_conflict"
        elif int(barrier.get("effectCount", 0) or 0) > 0:
            outcome = "effect_committed"
        else:
            outcome = "matched"
    if outcome not in {
        "matched",
        "revision_advanced_during_turn",
        "cas_conflict",
        "effect_committed",
    }:
        outcome = "effect_committed" if barrier.get("effectCommitted") else "matched"
    resulting = barrier.get("resultingRevisionVector")
    finalized["revisionBarrier"] = {
        "classification": _classification(
            barrier.get("classification")
            or finalized["revisionBarrier"]["classification"]
        ),
        "sourceRevisionVectorSha256": (
            revision_vector_sha256(barrier["sourceRevisionVector"])
            if isinstance(barrier.get("sourceRevisionVector"), Mapping)
            else str(
                barrier.get("sourceRevisionVectorSha256")
                or finalized["revisionBarrier"]["sourceRevisionVectorSha256"]
            )
        ),
        "preEffectRevisionVectorSha256": (
            revision_vector_sha256(barrier["preEffectRevisionVector"])
            if isinstance(barrier.get("preEffectRevisionVector"), Mapping)
            else str(
                barrier.get("preEffectRevisionVectorSha256")
                or finalized["revisionBarrier"]["preEffectRevisionVectorSha256"]
            )
        ),
        "outcome": outcome,
        "resultingRevisionVectorSha256": (
            revision_vector_sha256(resulting)
            if isinstance(resulting, Mapping)
            else barrier.get("resultingRevisionVectorSha256")
        ),
        "postEffectRevisionDrift": bool(
            barrier.get("postEffectRevisionDrift", False)
        ),
    }
    _reject_unsafe_payload(finalized, path="contextManifest")
    return finalized


def render_memory_envelope_prompt(envelope: Mapping[str, Any]) -> str:
    """Render authority-separated prompt sections without a raw prompt snapshot."""

    value = dict(envelope)
    trusted_state = {
        "scope": value["scope"],
        "observations": value["observations"],
    }
    workflow = {
        "workflow": value["workflow"],
        "reconciliation": value["reconciliation"],
        "receipts": value["receipts"],
        "capabilities": value["capabilities"],
    }
    continuity = value["continuity"]
    return "\n\n".join((
        _tag("trusted_current_state", trusted_state),
        _tag("trusted_source_decisions", value["approvedSourceDecisions"]),
        _tag("workflow_continuity", workflow),
        _tag("untrusted_conversation_summary", continuity.get("summary")),
        _tag("untrusted_recent_turns", continuity.get("recentTurns") or []),
    ))


def _tag(name: str, value: Any) -> str:
    return f"<{name}>\n{canonical_json(value)}\n</{name}>"


def _identity(value: Mapping[str, Any]) -> dict[str, str]:
    result = {
        "conversationId": _required_text(value.get("conversationId"), "conversationId"),
        "agentSessionId": _required_text(value.get("agentSessionId"), "agentSessionId"),
        "turnId": _required_text(value.get("turnId"), "turnId"),
        "agentType": _required_text(value.get("agentType"), "agentType").lower(),
    }
    return result


def _scope(value: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(value.get("kind") or "none").strip().lower()
    if kind not in {"process_map", "facility_layout", "cad_fai", "none"}:
        raise MemoryEnvelopeError("invalid_memory_scope", "unsupported scope kind")
    ids = {
        str(key): str(item)
        for key, item in dict(value.get("ids") or {}).items()
        if str(key).strip() and str(item).strip()
    }
    fingerprint = str(value.get("scopeFingerprint") or "").strip()
    if not fingerprint:
        fingerprint = "scope-v1:" + canonical_sha256({"kind": kind, "ids": ids})
    return {
        "kind": kind,
        "ids": dict(sorted(ids.items())),
        "scopeFingerprint": fingerprint,
        "revisionVector": normalize_revision_vector(
            value.get("revisionVector") or {}
        ),
    }


def _workflow(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    source = dict(value or {})
    status = str(source.get("status") or "active").strip().lower()
    if status not in {"active", "completed"}:
        status = "active"
    return {
        "workflowId": _nonempty(
            source.get("workflowId") or source.get("workflow_id"), "general"
        ),
        "workflowVersion": _nonempty(
            source.get("workflowVersion") or source.get("version"), "1.0.0"
        ),
        "status": status,
        "stage": _nonempty(source.get("stage"), "idle"),
        "objective": _nonempty(
            source.get("objective"), "Handle the current request"
        ),
        "entities": copy.deepcopy(dict(source.get("entities") or {})),
        "referents": copy.deepcopy(dict(source.get("referents") or {})),
        "pendingClarification": (
            str(
                source.get("pendingClarification")
                or source.get("pending_clarification")
                or ""
            ).strip()
            or None
        ),
    }


def _reconciliation(
    value: Optional[Mapping[str, Any]],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    revision_hash = revision_vector_sha256(scope.get("revisionVector") or {})
    default = {
        "schemaVersion": RECONCILIATION_SCHEMA_VERSION,
        "outcome": "same_scope_same_revisions",
        "workflowStateEvent": "empty",
        "previousScopeFingerprint": str(scope.get("scopeFingerprint") or ""),
        "currentScopeFingerprint": str(scope.get("scopeFingerprint") or ""),
        "previousRevisionVectorSha256": revision_hash,
        "currentRevisionVectorSha256": revision_hash,
        "changedDependencies": [],
        "dimensions": [],
        "actions": [],
        "removedEntityFieldCount": 0,
        "removedReferentFieldCount": 0,
        "removedEvidenceRefCount": 0,
        "continuityAction": "preserve",
        "staleContinuityEvidenceRefs": [],
        "warnings": [],
    }
    source = {**default, **copy.deepcopy(dict(value or {}))}
    if source["schemaVersion"] != RECONCILIATION_SCHEMA_VERSION:
        raise MemoryEnvelopeError(
            "invalid_memory_reconciliation",
            "unsupported reconciliation schema version",
        )
    if source["outcome"] not in RECONCILIATION_OUTCOMES:
        raise MemoryEnvelopeError(
            "invalid_memory_reconciliation",
            "unsupported reconciliation outcome",
        )
    source["workflowStateEvent"] = _nonempty(
        source.get("workflowStateEvent"), "empty"
    )
    for key in (
        "previousScopeFingerprint",
        "currentScopeFingerprint",
    ):
        source[key] = str(source.get(key) or "")
    for key in (
        "previousRevisionVectorSha256",
        "currentRevisionVectorSha256",
    ):
        source[key] = _sha256_text(source.get(key), key)
    for key in (
        "changedDependencies",
        "dimensions",
        "staleContinuityEvidenceRefs",
        "warnings",
    ):
        source[key] = _unique_strings(source.get(key) or [])
    normalized_actions = []
    for raw in source.get("actions") or []:
        if not isinstance(raw, Mapping):
            raise MemoryEnvelopeError(
                "invalid_memory_reconciliation",
                "reconciliation actions must be objects",
            )
        normalized_actions.append(
            {
                "item": _required_text(raw.get("item"), "action.item"),
                "dimension": _required_text(
                    raw.get("dimension"), "action.dimension"
                ),
                "action": _required_text(raw.get("action"), "action.action"),
            }
        )
    source["actions"] = sorted(
        normalized_actions,
        key=lambda row: (row["item"], row["dimension"], row["action"]),
    )
    for key in (
        "removedEntityFieldCount",
        "removedReferentFieldCount",
        "removedEvidenceRefCount",
    ):
        try:
            source[key] = max(0, int(source.get(key) or 0))
        except (TypeError, ValueError) as exc:
            raise MemoryEnvelopeError(
                "invalid_memory_reconciliation",
                f"{key} must be an integer",
            ) from exc
    source["continuityAction"] = _nonempty(
        source.get("continuityAction"), "preserve"
    )
    return source


def _providers(
    values: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str], list[str]]:
    rows: list[dict[str, Any]] = []
    trusted: dict[str, Any] = {}
    source_hashes: dict[str, str] = {}
    omissions: list[str] = []
    seen: set[str] = set()
    for raw in sorted(values, key=lambda item: str(item.get("contextKey") or "")):
        key = _required_text(raw.get("contextKey"), "contextKey")
        if key in seen:
            raise MemoryEnvelopeError(
                "duplicate_context_provider", f"duplicate context provider: {key}"
            )
        seen.add(key)
        origin = str(raw.get("origin") or "browser").strip().lower()
        if origin not in {"server", "browser"}:
            raise MemoryEnvelopeError(
                "invalid_context_origin", f"unsupported origin for {key}"
            )
        included = bool(raw.get("included", raw.get("payload") is not None))
        payload = copy.deepcopy(raw.get("payload")) if included else None
        if included:
            _reject_unsafe_payload(payload, path=f"providers.{key}")
            payload_hash = canonical_sha256(payload)
            tokens = estimate_json_tokens(payload)
            if origin == "server":
                trusted[key] = payload
            source_hashes[key] = payload_hash
            omission_reason = None
        else:
            payload_hash = None
            tokens = 0
            omission_reason = _nonempty(
                raw.get("omissionReason"), "context_unavailable"
            )
            omissions.append(f"{key}:{omission_reason}")
        requested_by = _unique_strings(raw.get("requestedBy") or ["runtime"])
        if not requested_by:
            requested_by = ["runtime"]
        rows.append({
            "contextKey": key,
            "origin": origin,
            "requestedBy": requested_by,
            "required": bool(raw.get("required", False)),
            "sourceIds": _unique_strings(raw.get("sourceIds") or []),
            "sourceRevisions": _unique_strings(
                raw.get("sourceRevisions") or []
            ),
            "included": included,
            "estimatedTokens": tokens,
            "payloadSha256": payload_hash,
            "omissionReason": omission_reason,
        })
    return rows, trusted, dict(sorted(source_hashes.items())), omissions


def _approved_decisions(values: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in values:
        row = {
            "decisionId": _required_text(raw.get("decisionId"), "decisionId"),
            "sourceType": _required_text(raw.get("sourceType"), "sourceType"),
            "sourceId": _required_text(raw.get("sourceId"), "sourceId"),
            "sourceRevision": _required_text(
                raw.get("sourceRevision"), "sourceRevision"
            ),
            "decisionType": _required_text(
                raw.get("decisionType"), "decisionType"
            ),
            "payloadSha256": _sha256_text(
                raw.get("payloadSha256"), "payloadSha256"
            ),
        }
        rows.append(row)
    rows.sort(key=lambda item: item["decisionId"])
    if len({row["decisionId"] for row in rows}) != len(rows):
        raise MemoryEnvelopeError(
            "duplicate_approved_decision", "approved decision IDs must be unique"
        )
    return rows


def _receipts(
    values: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    required = {
        "receiptId",
        "toolId",
        "status",
        "idempotencyKey",
        "authorizedRevisionVector",
        "resultingRevisionVector",
        "warnings",
        "createdIds",
    }
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for raw in values:
        if set(raw) != required:
            warnings.append("unsupported_receipt_shape_omitted")
            continue
        status = str(raw.get("status") or "").strip().lower()
        if status not in {"succeeded", "failed", "rejected"}:
            warnings.append("unsupported_receipt_status_omitted")
            continue
        rows.append({
            "receiptId": _required_text(raw.get("receiptId"), "receiptId"),
            "toolId": _required_text(raw.get("toolId"), "toolId"),
            "status": status,
            "idempotencyKey": _required_text(
                raw.get("idempotencyKey"), "idempotencyKey"
            ),
            "authorizedRevisionVector": normalize_revision_vector(
                raw.get("authorizedRevisionVector") or {}
            ),
            "resultingRevisionVector": normalize_revision_vector(
                raw.get("resultingRevisionVector") or {}
            ),
            "warnings": _unique_strings(raw.get("warnings") or []),
            "createdIds": _unique_strings(raw.get("createdIds") or []),
        })
    return rows[-8:], warnings


def _allocations(values: Optional[Mapping[str, Any]]) -> dict[str, int]:
    result = dict(DEFAULT_ENVELOPE_ALLOCATIONS)
    for key, raw in dict(values or {}).items():
        if key not in result or isinstance(raw, bool):
            raise MemoryEnvelopeError(
                "invalid_memory_budget", f"unsupported allocation: {key}"
            )
        value = int(raw)
        if value < 0:
            raise MemoryEnvelopeError(
                "invalid_memory_budget", f"allocation must be non-negative: {key}"
            )
        result[key] = value
    return result


def _enforce_allocations(
    measured: Mapping[str, int],
    allocations: Mapping[str, int],
    *,
    providers: Sequence[Mapping[str, Any]],
    maximum_tokens: int,
) -> None:
    if maximum_tokens < 1:
        raise MemoryEnvelopeError(
            "invalid_memory_budget", "maximum envelope tokens must be positive"
        )
    for section, tokens in measured.items():
        allowed = int(allocations[section])
        if tokens <= allowed:
            continue
        details: dict[str, Any] = {
            "section": section,
            "estimatedTokens": tokens,
            "maximumTokens": allowed,
        }
        if section == "trustedContext":
            details["providers"] = [
                row["contextKey"]
                for row in providers
                if row["included"] and row["required"]
            ]
        raise MemoryEnvelopeError(
            "required_context_budget_exceeded",
            f"required memory section exceeds its allocation: {section}",
            details=details,
        )
    total = sum(measured.values())
    if total > maximum_tokens:
        raise MemoryEnvelopeError(
            "required_context_budget_exceeded",
            "memory envelope exceeds its total allocation",
            details={
                "section": "total",
                "estimatedTokens": total,
                "maximumTokens": maximum_tokens,
            },
        )


def _reject_unsafe_payload(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            token = str(key)
            if _FORBIDDEN_KEY.search(token):
                raise MemoryEnvelopeError(
                    "unsafe_memory_payload",
                    f"secret-like field is not allowed in memory: {path}.{token}",
                )
            _reject_unsafe_payload(item, path=f"{path}.{token}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_unsafe_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and value.strip().lower().startswith(
        _RAW_IMAGE_PREFIXES
    ):
        raise MemoryEnvelopeError(
            "unsafe_memory_payload",
            f"raw image or document payload is not allowed in memory: {path}",
        )


def _classification(value: Any) -> str:
    token = str(value or "read_only").strip().lower()
    if token not in {"read_only", "preview", "action_write"}:
        raise MemoryEnvelopeError(
            "invalid_turn_classification", "unsupported turn classification"
        )
    return token


def _required_text(value: Any, field: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise MemoryEnvelopeError(
            "invalid_memory_envelope", f"{field} must be non-empty"
        )
    return token


def _nonempty(value: Any, fallback: str) -> str:
    return str(value or "").strip() or fallback


def _unique_strings(values: Sequence[Any]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _sha256_text(value: Any, field: str) -> str:
    token = _required_text(value, field).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise MemoryEnvelopeError(
            "invalid_memory_envelope", f"{field} must be a SHA-256 value"
        )
    return token


__all__ = [
    "CONTEXT_MANIFEST_SCHEMA_VERSION",
    "DEFAULT_ENVELOPE_ALLOCATIONS",
    "DEFAULT_ENVELOPE_MAX_TOKENS",
    "MEMORY_ENVELOPE_SCHEMA_VERSION",
    "MemoryEnvelopeBuildResult",
    "MemoryEnvelopeError",
    "build_memory_envelope",
    "estimate_json_tokens",
    "finalize_context_manifest",
    "render_memory_envelope_prompt",
]
