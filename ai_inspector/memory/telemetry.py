"""Privacy-bounded telemetry helpers for the Sage-memory rollout."""

from __future__ import annotations

from typing import Optional

from ai_inspector.telemetry import TelemetryEvent, TelemetryStore
from ai_inspector.telemetry import record_workflow_stage


MEMORY_TELEMETRY_EVENTS = frozenset({
    "memory.turn.started",
    "memory.turn.committed",
    "memory.turn.idempotent_replay",
    "memory.turn.failed",
    "memory.turn.revision_barrier_checked",
    "memory.turn.revision_advanced_during_turn",
    "memory.turn.post_effect_revision_drift",
    "memory.summary.started",
    "memory.summary.committed",
    "memory.summary.invalid",
    "memory.summary.soft_stale",
    "memory.summary.hard_stale",
    "memory.summary.action_blocked",
    "memory.workflow.resumed",
    "memory.workflow.reconciled_revision",
    "memory.workflow.scope_changed",
    "memory.context.budget_used",
    "memory.context.optional_omitted",
    "memory.context.required_over_budget",
    "memory.context.envelope_build_ms",
    "memory.repository.operation_ms",
    "memory.retention.deleted",
})
MEMORY_MODES = frozenset({"off", "shadow", "compare", "enforce"})
MEMORY_CLASSIFICATIONS = frozenset({"read_only", "preview", "action_write"})


def record_memory_event(
    event: str,
    *,
    mode: str,
    latency_ms: float = 0.0,
    status: str = "success",
    error_code: Optional[str] = None,
    classification: Optional[str] = None,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    applied_to_prompt: Optional[bool] = None,
    context_tokens: Optional[int] = None,
    legacy_tokens: Optional[int] = None,
    omission_count: Optional[int] = None,
    replayed: Optional[bool] = None,
    revision_outcome: Optional[str] = None,
    retention_deleted_count: Optional[int] = None,
    summary_revision: Optional[int] = None,
    workflow_state_revision: Optional[int] = None,
    context_manifest_id: Optional[str] = None,
    envelope_sha256: Optional[str] = None,
    source_revision_sha256: Optional[str] = None,
    result_revision_sha256: Optional[str] = None,
    fallback_mode: Optional[str] = None,
    store: Optional[TelemetryStore] = None,
) -> Optional[TelemetryEvent]:
    """Record one closed, content-free memory event."""

    if event not in MEMORY_TELEMETRY_EVENTS:
        raise ValueError("unsupported Sage-memory telemetry event")
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in MEMORY_MODES:
        raise ValueError("unsupported Sage-memory telemetry mode")
    normalized_classification = None
    if classification is not None:
        normalized_classification = str(classification).strip().lower()
        if normalized_classification not in MEMORY_CLASSIFICATIONS:
            raise ValueError("unsupported Sage-memory turn classification")

    return record_workflow_stage(
        workflow="sage_memory",
        stage=event,
        latency_ms=max(0.0, float(latency_ms)),
        status=str(status or "success"),
        errorType=_bounded_identifier(error_code),
        store=store,
        route="/api/agent/memory",
        agentType=_bounded_identifier(agent_type),
        sessionId=_bounded_identifier(session_id),
        requestId=_bounded_identifier(turn_id),
        memoryMode=normalized_mode,
        memoryClassification=normalized_classification,
        memoryAuthoritative=_optional_bool(applied_to_prompt),
        memoryContextTokens=_nonnegative(context_tokens),
        memoryLegacyTokens=_nonnegative(legacy_tokens),
        memoryOmissionCount=_nonnegative(omission_count),
        memoryReplayed=_optional_bool(replayed),
        memoryRevisionOutcome=_bounded_identifier(revision_outcome),
        memoryRetentionDeletedCount=_nonnegative(
            retention_deleted_count
        ),
        memorySummaryRevision=_nonnegative(summary_revision),
        memoryWorkflowStateRevision=_nonnegative(workflow_state_revision),
        memoryContextManifestId=_bounded_identifier(context_manifest_id),
        memoryEnvelopeSha256=_sha256(envelope_sha256),
        memorySourceRevisionSha256=_sha256(source_revision_sha256),
        memoryResultRevisionSha256=_sha256(result_revision_sha256),
        memoryFallbackMode=_bounded_identifier(fallback_mode),
    )


def _bounded_identifier(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > 200 or any(ord(char) < 32 for char in normalized):
        raise ValueError("memory telemetry identifiers must be bounded")
    return normalized


def _sha256(value: Optional[str]) -> Optional[str]:
    normalized = _bounded_identifier(value)
    if normalized is None:
        return None
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError("memory telemetry hashes must be lowercase SHA-256")
    return normalized


def _nonnegative(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    normalized = int(value)
    if normalized < 0:
        raise ValueError("memory telemetry counts must be nonnegative")
    return normalized


def _optional_bool(value: Optional[bool]) -> Optional[bool]:
    return None if value is None else bool(value)


__all__ = ["MEMORY_TELEMETRY_EVENTS", "record_memory_event"]
