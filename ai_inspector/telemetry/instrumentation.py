"""Telemetry instrumentation helpers.

Phase 1 ships these building blocks; Phase 2 wires them into actual
provider call sites in server.py / ai_inspector/spatial/engine.py /
ai_inspector/report/qc_report.py. Per the user direction at Phase 1
kick-off, this module is NOT used by any existing code yet.

Hard guarantee (per docs/usage-cost-dashboard-plan.md §7):
`record_event()` MUST NOT propagate exceptions into the calling product
workflow. If the SQLite store fails, log a warning and continue. The
store's own `write()` raises on failure so unit tests can verify the
failure path; the soft-fail wrapper lives here.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

from .models import TelemetryEvent
from .pricing import compute_cost
from .store import TelemetryStore

logger = logging.getLogger("inspectorpro.telemetry")

# Process-wide default store. Lazily constructed so importing this
# module never touches the filesystem.
_default_store: Optional[TelemetryStore] = None


def get_default_store() -> TelemetryStore:
    """Return the process-wide default store, creating it on first call."""
    global _default_store
    if _default_store is None:
        _default_store = TelemetryStore()
    return _default_store


def reset_default_store_for_tests() -> None:
    """Test helper: clear the singleton so a test can install a fresh store
    pointed at a tmpdir without inheriting leftover state."""
    global _default_store
    _default_store = None


def new_event_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return str(uuid.uuid4())


def record_event(event: TelemetryEvent, store: Optional[TelemetryStore] = None) -> None:
    """Write a telemetry event with hard-soft-fail semantics.

    If the underlying store raises, we log at WARNING and swallow.
    Telemetry must never break a product workflow — that's the §7
    plan-level invariant this function enforces.
    """
    target = store if store is not None else get_default_store()
    try:
        target.write(event)
    except Exception as ex:  # noqa: BLE001 — intentional broad catch; this is the soft-fail boundary
        # event.eventId is always set by the dataclass factory; safe to log.
        logger.warning("telemetry write failed (eventId=%s): %s", event.eventId, ex)


@contextmanager
def time_block() -> Iterator[callable]:
    """Context manager yielding a callable that returns elapsed milliseconds.

        with time_block() as elapsed_ms:
            do_provider_call()
        latency = elapsed_ms()   # ms since enter

    Using a callable (rather than mutating an attribute) keeps the elapsed
    value live: the caller can read it AFTER the block exits and still get
    the correct duration up to the exit moment.
    """
    start = time.perf_counter()

    def get_ms() -> float:
        return (time.perf_counter() - start) * 1000.0

    yield get_ms


def record_provider_call(
    *,
    provider:         str,
    model:            str,
    status:           str = "success",
    inputTokens:      int = 0,
    outputTokens:     int = 0,
    cacheReadTokens:  int = 0,
    cacheWriteTokens: int = 0,
    latencyMs:        float = 0.0,
    store:            Optional[TelemetryStore] = None,
    **extra,
) -> TelemetryEvent:
    """Convenience helper that composes a TelemetryEvent from the common
    fields, computes cost from the pricing table, writes it via the
    soft-fail wrapper, and returns the event for the caller to inspect
    (useful in tests and in callers that want to log the eventId).

    `**extra` accepts any TelemetryEvent field name — environment,
    sessionId, requestId, route, workflow, agentType, errorType,
    retryCount, toolCallCount, partNumber, documentKind. Unknown
    keys raise TypeError at construction time (intentional — typos
    in field names would otherwise silently drop data).
    """
    cost_usd, confidence = compute_cost(
        provider,
        model,
        inputTokens=inputTokens,
        outputTokens=outputTokens,
        cacheReadTokens=cacheReadTokens,
        cacheWriteTokens=cacheWriteTokens,
    )
    total = max(0, int(inputTokens or 0)) + max(0, int(outputTokens or 0)) \
          + max(0, int(cacheReadTokens or 0)) + max(0, int(cacheWriteTokens or 0))
    event = TelemetryEvent(
        provider=provider,
        model=model,
        status=status,
        inputTokens=inputTokens,
        outputTokens=outputTokens,
        cacheReadTokens=cacheReadTokens,
        cacheWriteTokens=cacheWriteTokens,
        totalTokens=total,
        estimatedCostUsd=cost_usd,
        pricingConfidence=confidence,
        latencyMs=latencyMs,
        **extra,
    )
    record_event(event, store=store)
    return event


# ─── Phase 2: provider-call wrappers ────────────────────────────────
#
# These thin helpers extract token counts from Anthropic / OpenAI
# response objects and forward to record_provider_call(). Each one is
# double-wrapped so a telemetry bug (token-extraction crash, missing
# field, typo in a tag name) NEVER propagates into the calling product
# workflow — the soft-fail boundary lives here too, not just in
# record_event().


def classify_exception_status(exc: BaseException) -> tuple:
    """Map an exception class to (status, errorType) for the telemetry event.

    Status is one of: "error" | "timeout" | "rate_limited". Classification
    is by class-name substring match (not isinstance) so this module does
    not need to import the Anthropic / OpenAI SDKs. errorType is the
    unqualified class name.
    """
    name = type(exc).__name__
    lower = name.lower()
    if "ratelimit" in lower or "rate_limit" in lower:
        return ("rate_limited", name)
    if "timeout" in lower:
        return ("timeout", name)
    return ("error", name)


def record_anthropic_call(
    *,
    model:      str,
    response:   Optional[object],
    latency_ms: float,
    status:     str = "success",
    errorType:  Optional[str] = None,
    store:      Optional[TelemetryStore] = None,
    **tags,
) -> Optional[TelemetryEvent]:
    """Record one Anthropic Messages API call.

    `response` is the SDK response object (or None on failure). Token
    counts are pulled from `response.usage.{input_tokens, output_tokens,
    cache_read_input_tokens, cache_creation_input_tokens}` defensively —
    missing attrs default to 0.

    `tags` accepts any TelemetryEvent field (route, workflow, agentType,
    sessionId, partNumber, documentKind, ...). See record_provider_call().

    Soft-fail: any internal exception (bad response shape, store failure,
    typo in tags) is caught and logged at WARNING. Returns None in that
    case; otherwise returns the TelemetryEvent for caller inspection.
    """
    try:
        it = ot = crt = cwt = 0
        if response is not None:
            usage = getattr(response, "usage", None)
            if usage is not None:
                it  = int(getattr(usage, "input_tokens",                0) or 0)
                ot  = int(getattr(usage, "output_tokens",               0) or 0)
                crt = int(getattr(usage, "cache_read_input_tokens",     0) or 0)
                cwt = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        return record_provider_call(
            provider="anthropic",
            model=model,
            status=status,
            inputTokens=it,
            outputTokens=ot,
            cacheReadTokens=crt,
            cacheWriteTokens=cwt,
            latencyMs=latency_ms,
            errorType=errorType,
            store=store,
            **tags,
        )
    except Exception as ex:  # noqa: BLE001 — soft-fail boundary
        logger.warning("record_anthropic_call failed (model=%s): %s", model, ex)
        return None


def record_openai_call(
    *,
    model:      str,
    response:   Optional[object],
    latency_ms: float,
    status:     str = "success",
    errorType:  Optional[str] = None,
    store:      Optional[TelemetryStore] = None,
    **tags,
) -> Optional[TelemetryEvent]:
    """Record one OpenAI Chat Completions or Responses API call.

    Token counts are read from Chat Completions (`prompt_tokens`,
    `completion_tokens`) or Responses (`input_tokens`, `output_tokens`)
    defensively. OpenAI's cache-cost model is not tracked in MVP, so cache
    fields remain zero in the event.
    """
    try:
        it = ot = 0
        if response is not None:
            usage = getattr(response, "usage", None)
            if usage is not None:
                it = int(
                    getattr(usage, "prompt_tokens", None)
                    or getattr(usage, "input_tokens", 0)
                    or 0
                )
                ot = int(
                    getattr(usage, "completion_tokens", None)
                    or getattr(usage, "output_tokens", 0)
                    or 0
                )
        return record_provider_call(
            provider="openai",
            model=model,
            status=status,
            inputTokens=it,
            outputTokens=ot,
            latencyMs=latency_ms,
            errorType=errorType,
            store=store,
            **tags,
        )
    except Exception as ex:  # noqa: BLE001
        logger.warning("record_openai_call failed (model=%s): %s", model, ex)
        return None


def record_openai_transcription(
    *,
    model:      str,
    latency_ms: float,
    status:     str = "success",
    errorType:  Optional[str] = None,
    store:      Optional[TelemetryStore] = None,
    **tags,
) -> Optional[TelemetryEvent]:
    """Record one OpenAI Whisper transcription call.

    Whisper has no per-token usage field — pricing is per audio MINUTE,
    not per token. The pricing table marks `whisper-1` confidence as
    "unknown" so cost computation always returns 0 for this provider/
    model pair. The event still captures latency + status + tags so the
    dashboard can show call volume and reliability even without cost.
    Audio-minute pricing is a Phase 2+ enhancement (see pricing.py
    notes on whisper-1).
    """
    try:
        return record_provider_call(
            provider="openai",
            model=model,
            status=status,
            inputTokens=0,
            outputTokens=0,
            latencyMs=latency_ms,
            errorType=errorType,
            store=store,
            **tags,
        )
    except Exception as ex:  # noqa: BLE001
        logger.warning("record_openai_transcription failed (model=%s): %s", model, ex)
        return None


# ─── Phase 3: endpoint + workflow stage timing ──────────────────────
#
# Two new event flavors, both reusing TelemetryEvent:
#
#   - Endpoint events come from the FastAPI middleware. provider="none",
#     route=request path, httpStatus=response status, latencyMs=request
#     duration. workflow may or may not be known at middleware time.
#
#   - Workflow stage events come from explicit instrumentation inside
#     long-running handlers. workflow="inspection"|"bridge_extract"|...,
#     stage="precheck"|"inspect"|"approval_wait"|... — lets the dashboard
#     compute p50/p95 per stage.
#
# Both helpers go through record_provider_call → record_event so the
# soft-fail guarantee from Phase 1 + the per-helper try/except from
# Phase 2 still apply.


def record_endpoint_event(
    *,
    route:      str,
    method:     str = "GET",
    httpStatus: int,
    latency_ms: float,
    workflow:   Optional[str] = None,
    store:      Optional[TelemetryStore] = None,
    **tags,
) -> Optional[TelemetryEvent]:
    """Record one FastAPI endpoint request.

    Used by the per-request middleware in server.py. Provider is
    explicitly "none" (this event measures HTTP-layer latency, not a
    provider call). 2xx/3xx httpStatus → status="success"; 4xx/5xx →
    status="error". errorType carries the bare status-code string
    (e.g. "HTTP_404") so dashboard error breakdowns work without
    needing a separate exception-class field.
    """
    try:
        status = "success" if 200 <= int(httpStatus) < 400 else "error"
        error_type = None
        if status == "error":
            error_type = f"HTTP_{int(httpStatus)}"
        # method goes into a route-style suffix so the (route, method)
        # pair stays queryable from one column. e.g. "GET /api/profiles".
        route_label = f"{method} {route}" if method else route
        # errorType is not a named parameter on this helper, so a caller
        # that passes errorType=... ends up with it inside **tags. The
        # forwarding call to record_provider_call would then pass errorType
        # both explicitly AND via **tags spread — Python rejects that with
        # "got multiple values for keyword argument 'errorType'". Pull it
        # out of tags first and prefer the caller's value when truthy,
        # else fall back to the http-derived default.
        caller_error_type = tags.pop("errorType", None)
        return record_provider_call(
            provider="none",
            model=None,
            status=status,
            errorType=(caller_error_type or error_type),
            latencyMs=latency_ms,
            route=route_label,
            workflow=workflow,
            httpStatus=int(httpStatus),
            store=store,
            **tags,
        )
    except Exception as ex:  # noqa: BLE001 — soft-fail boundary
        logger.warning("record_endpoint_event failed (route=%s): %s", route, ex)
        return None


def record_workflow_stage(
    *,
    workflow:   str,
    stage:      str,
    latency_ms: float,
    status:     str = "success",
    errorType:  Optional[str] = None,
    store:      Optional[TelemetryStore] = None,
    **tags,
) -> Optional[TelemetryEvent]:
    """Record one workflow stage timing.

    Workflow stages decompose long-running endpoint handlers into named
    phases (e.g. workflow="bridge_extract" with stages "precheck",
    "job_create", "approval_wait", "extract_wait", "download",
    "validate", "unzip", "import"). The separation matters most for
    bridge: approval_wait is the user clicking Approve in SOLIDWORKS
    and should not be conflated with software latency.

    `tags` accepts any TelemetryEvent field (route, agentType,
    partNumber, documentKind, etc.).
    """
    try:
        return record_provider_call(
            provider="none",
            model=None,
            status=status,
            errorType=errorType,
            latencyMs=latency_ms,
            workflow=workflow,
            stage=stage,
            store=store,
            **tags,
        )
    except Exception as ex:  # noqa: BLE001
        logger.warning("record_workflow_stage failed (workflow=%s stage=%s): %s",
                       workflow, stage, ex)
        return None
