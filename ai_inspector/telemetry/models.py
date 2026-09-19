"""Telemetry event dataclass.

Schema per docs/usage-cost-dashboard-plan.md §3. Every provider call emits
one TelemetryEvent. Field names match the spec exactly (camelCase) so the
SQLite columns + JSON exports + future dashboard chart series all refer to
the same identifiers.

Privacy rule (§3): do NOT add raw prompts, raw model responses, API keys,
customer drawings, or CAD payloads to this schema. The only free-text
fields are short identifiers (errorType, route, workflow tags, part number,
etc.) — none of them should be used for content capture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TelemetryEvent:
    """One provider call's worth of metrics."""

    # ── Identity + temporal ───────────────────────────────────────────
    eventId:      str = field(default_factory=_new_event_id)
    timestampUtc: str = field(default_factory=_now_iso)

    # ── Context ───────────────────────────────────────────────────────
    environment:  str            = "dev"          # dev | pilot | production
    sessionId:    Optional[str]  = None
    requestId:    Optional[str]  = None
    route:        Optional[str]  = None           # e.g. "/api/agent/chat"
    workflow:     Optional[str]  = None           # e.g. inspection, agent_chat, summary, report, voice_transcribe
    agentType:    Optional[str]  = None           # iris | sage | scout | none

    # ── Provider call ────────────────────────────────────────────────
    provider:     str            = "unknown"      # anthropic | openai | local | unknown
    model:        Optional[str]  = None
    status:       str            = "success"      # success | error | timeout | rate_limited
    errorType:    Optional[str]  = None

    # ── Token accounting ──────────────────────────────────────────────
    inputTokens:        int = 0
    outputTokens:       int = 0
    cacheReadTokens:    int = 0
    cacheWriteTokens:   int = 0
    totalTokens:        int = 0

    # ── Cost (computed at write time per §5 — historical events stay
    # correct even if pricing.PRICING_TABLE is later updated). ────────
    estimatedCostUsd:   float = 0.0
    pricingConfidence:  str   = "unknown"          # verified | estimated | unknown

    # ── Latency + retry ──────────────────────────────────────────────
    latencyMs:    float = 0.0
    # Streaming-specific timings remain nullable for legacy and batch calls.
    firstTokenLatencyMs:   Optional[float] = None
    firstCleanSentenceMs:  Optional[float] = None
    streamDurationMs:      Optional[float] = None
    pipelineLatencyMs:     Optional[float] = None
    finalizeDeltaChars:    Optional[int] = None
    retryCount:   int   = 0
    toolCallCount: int  = 0

    # ── Workflow context (optional, helps slice the dashboard) ──────
    partNumber:    Optional[str] = None
    documentKind:  Optional[str] = None             # drawing | part | assembly | other

    # ── Phase 3: endpoint + workflow-stage fields (additive) ────────
    # httpStatus is populated on events emitted by the FastAPI endpoint-
    # timing middleware; provider-call events leave it None.
    # stage is populated on workflow-stage events (e.g. workflow="inspection"
    # with stage="inspect"), letting the dashboard chart latency per stage.
    httpStatus:    Optional[int] = None
    stage:         Optional[str] = None

    # Process-map spatial rollout telemetry. These fields intentionally carry
    # only stable IDs, bounded enums, counts, timings, and aggregate metrics.
    # Labels, notes, coordinates, routes, and customer geometry are forbidden
    # by the endpoint schema that populates them.
    processMapProductId:              Optional[str] = None
    processMapId:                     Optional[str] = None
    processMapRevision:               Optional[str] = None
    processMapOperation:              Optional[str] = None
    processMapOutcome:                Optional[str] = None
    processMapScope:                  Optional[str] = None
    processMapSpatialEngineVersion:   Optional[int] = None
    processMapPolicyVersion:          Optional[int] = None
    processMapNodeCount:              Optional[int] = None
    processMapEdgeCount:              Optional[int] = None
    processMapScopedNodeCount:        Optional[int] = None
    processMapScopedEdgeCount:        Optional[int] = None
    processMapCandidatesEvaluated:    Optional[int] = None
    processMapMovedNodeCount:         Optional[int] = None
    processMapRejectionCountsJson:    Optional[str] = None
    processMapMetricsBeforeJson:      Optional[str] = None
    processMapMetricsAfterJson:       Optional[str] = None
    processMapFallbackReason:         Optional[str] = None

    # Sage-memory rollout telemetry. Only bounded enums, counts, IDs, and
    # hashes are allowed here; conversation content is never recorded.
    memoryMode:                       Optional[str] = None
    memoryClassification:             Optional[str] = None
    memoryAuthoritative:               Optional[bool] = None
    memoryContextTokens:               Optional[int] = None
    memoryLegacyTokens:                Optional[int] = None
    memoryOmissionCount:               Optional[int] = None
    memoryReplayed:                    Optional[bool] = None
    memoryRevisionOutcome:             Optional[str] = None
    memoryRetentionDeletedCount:       Optional[int] = None
    memorySummaryRevision:             Optional[int] = None
    memoryWorkflowStateRevision:       Optional[int] = None
    memoryContextManifestId:           Optional[str] = None
    memoryEnvelopeSha256:              Optional[str] = None
    memorySourceRevisionSha256:        Optional[str] = None
    memoryResultRevisionSha256:        Optional[str] = None
    memoryFallbackMode:                Optional[str] = None

    # Feedback telemetry carries only bounded aggregate metadata. Raw
    # response and correction text remain in the feedback repository.
    feedbackRating:                    Optional[str] = None
    feedbackReasonCount:               Optional[int] = None
    feedbackHasCorrection:             Optional[bool] = None
    feedbackLinkedTurn:                Optional[bool] = None
    feedbackLinkedRun:                 Optional[bool] = None

    # ── Conversions ──────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelemetryEvent":
        """Tolerant of unknown keys (e.g. older sqlite rows that have
        extra columns we deprecated) — only known fields are passed
        to the constructor."""
        known_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known_names}
        for name in (
            "memoryAuthoritative",
            "memoryReplayed",
            "feedbackHasCorrection",
            "feedbackLinkedTurn",
            "feedbackLinkedRun",
        ):
            if filtered.get(name) is not None:
                filtered[name] = bool(filtered[name])
        return cls(**filtered)
