"""Tests for ai_inspector.telemetry Phase 1.

Covers (per the user direction at Phase 1 kick-off):
  - telemetry event serialization
  - SQLite insert/query round trip
  - pricing lookup
  - cost calculation
  - telemetry write failure does not raise into caller
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pytest

from ai_inspector.telemetry import (
    CONFIDENCE_ESTIMATED,
    CONFIDENCE_UNKNOWN,
    PRICING_TABLE,
    PricingEntry,
    TelemetryEvent,
    TelemetryStore,
    compute_cost,
    lookup_pricing,
    record_event,
    record_provider_call,
    reset_default_store_for_tests,
    time_block,
)


# ─── Event serialization ────────────────────────────────────────────

def test_event_default_factory_populates_id_and_timestamp():
    e = TelemetryEvent()
    assert isinstance(e.eventId, str) and len(e.eventId) >= 32
    assert e.timestampUtc and "T" in e.timestampUtc  # ISO-8601 with date+time
    assert e.environment == "dev"
    assert e.provider == "unknown"
    assert e.status == "success"
    assert e.inputTokens == 0
    assert e.estimatedCostUsd == 0.0
    assert e.pricingConfidence == "unknown"


def test_event_to_dict_roundtrip_via_from_dict():
    original = TelemetryEvent(
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        inputTokens=1000,
        outputTokens=500,
        latencyMs=1234.5,
        route="/api/agent/chat",
        workflow="agent_chat",
        agentType="sage",
        partNumber="1020001",
        documentKind="drawing",
    )
    d = original.to_dict()
    # All declared fields show up in the dict.
    assert "eventId" in d and "timestampUtc" in d
    assert d["provider"] == "anthropic"
    assert d["partNumber"] == "1020001"

    # Round-trip via from_dict produces an equivalent dataclass.
    restored = TelemetryEvent.from_dict(d)
    assert restored.eventId == original.eventId
    assert restored.provider == original.provider
    assert restored.model == original.model
    assert restored.inputTokens == 1000
    assert restored.partNumber == "1020001"


def test_event_from_dict_tolerates_unknown_columns():
    """An older or extra column in a sqlite row must not crash the loader.
    Future schema additions stay non-breaking under this rule."""
    d = TelemetryEvent().to_dict()
    d["mysteryFutureColumn"] = "ignore-me"
    e = TelemetryEvent.from_dict(d)
    assert isinstance(e, TelemetryEvent)
    assert not hasattr(e, "mysteryFutureColumn")


# ─── Pricing lookup ──────────────────────────────────────────────────

def test_pricing_table_contains_known_models():
    """Anchor the inventory we surveyed at Phase 1 kick-off. If a model
    leaves the pricing table the dashboard would silently show $0 for it
    — better to catch that in a test."""
    expected = {
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("anthropic", "claude-sonnet-4-20250514"),
        ("openai", "gpt-4o"),
        ("openai", "gpt-4o-mini"),
        ("openai", "whisper-1"),
    }
    for key in expected:
        assert key in PRICING_TABLE, f"missing pricing entry: {key}"


def test_lookup_pricing_known_model_returns_entry():
    entry = lookup_pricing("anthropic", "claude-sonnet-4-5-20250929")
    assert isinstance(entry, PricingEntry)
    assert entry.provider == "anthropic"
    assert entry.confidence == CONFIDENCE_ESTIMATED


def test_lookup_pricing_unknown_model_returns_none():
    assert lookup_pricing("anthropic", "claude-fictional-9000") is None
    assert lookup_pricing("openai", "gpt-99o") is None
    assert lookup_pricing("", "") is None
    assert lookup_pricing("anthropic", "") is None
    assert lookup_pricing(None, "x") is None  # type: ignore[arg-type]


# ─── Cost calculation ────────────────────────────────────────────────

def test_compute_cost_known_model_returns_estimated():
    """1M input + 1M output tokens against Sonnet 4.5 estimated rates."""
    cost, confidence = compute_cost(
        "anthropic", "claude-sonnet-4-5-20250929",
        inputTokens=1_000_000,
        outputTokens=1_000_000,
    )
    entry = PRICING_TABLE[("anthropic", "claude-sonnet-4-5-20250929")]
    expected = entry.inputCostPerMillionTokens + entry.outputCostPerMillionTokens
    assert cost == pytest.approx(expected)
    assert confidence == CONFIDENCE_ESTIMATED


def test_compute_cost_unknown_model_returns_zero_unknown():
    """Per user direction: don't silently guess for unknown models."""
    cost, confidence = compute_cost(
        "fictional-provider", "fictional-model",
        inputTokens=999_999, outputTokens=999_999,
    )
    assert cost == 0.0
    assert confidence == CONFIDENCE_UNKNOWN


def test_compute_cost_whisper_returns_zero_unknown():
    """Whisper is in the table but its `confidence` is 'unknown' because
    the per-token cost model doesn't apply to it (per-audio-minute pricing)."""
    cost, confidence = compute_cost("openai", "whisper-1", inputTokens=10_000)
    assert cost == 0.0
    assert confidence == CONFIDENCE_UNKNOWN


def test_compute_cost_includes_cache_tokens():
    cost, _ = compute_cost(
        "anthropic", "claude-sonnet-4-5-20250929",
        inputTokens=0, outputTokens=0,
        cacheReadTokens=1_000_000, cacheWriteTokens=0,
    )
    entry = PRICING_TABLE[("anthropic", "claude-sonnet-4-5-20250929")]
    assert cost == pytest.approx(entry.cacheReadCostPerMillionTokens)


def test_compute_cost_clamps_negative_token_counts():
    """Defensive: a caller miscounting tokens as -1 must not flip the cost sign."""
    cost, _ = compute_cost(
        "anthropic", "claude-sonnet-4-5-20250929",
        inputTokens=-100, outputTokens=-50,
    )
    assert cost == 0.0


def test_compute_cost_handles_none_tokens():
    """Anthropic's cache fields can be absent in some response shapes."""
    cost, _ = compute_cost(
        "anthropic", "claude-sonnet-4-5-20250929",
        inputTokens=100, outputTokens=None,  # type: ignore[arg-type]
    )
    entry = PRICING_TABLE[("anthropic", "claude-sonnet-4-5-20250929")]
    # 100 input tokens, 0 output (coerced from None).
    expected = 100 * entry.inputCostPerMillionTokens / 1_000_000.0
    assert cost == pytest.approx(expected)


# ─── SQLite store round-trip ────────────────────────────────────────

def test_store_insert_and_query_roundtrip(tmp_path: Path):
    db = tmp_path / "metrics.sqlite"
    store = TelemetryStore(db_path=db)
    assert store.count() == 0

    e = TelemetryEvent(
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        inputTokens=100, outputTokens=50, totalTokens=150,
        latencyMs=1234.5,
        route="/api/agent/chat", workflow="agent_chat", agentType="sage",
        partNumber="1020001", documentKind="drawing",
        estimatedCostUsd=0.001, pricingConfidence=CONFIDENCE_ESTIMATED,
    )
    store.write(e)
    assert store.count() == 1

    rows = store.query_recent(limit=10)
    assert len(rows) == 1
    got = rows[0]
    assert got.eventId == e.eventId
    assert got.provider == "anthropic"
    assert got.model == "claude-sonnet-4-5-20250929"
    assert got.inputTokens == 100
    assert got.outputTokens == 50
    assert got.totalTokens == 150
    assert got.latencyMs == pytest.approx(1234.5)
    assert got.partNumber == "1020001"
    assert got.estimatedCostUsd == pytest.approx(0.001)
    assert got.pricingConfidence == CONFIDENCE_ESTIMATED


def test_store_insert_or_ignore_dedupes_by_event_id(tmp_path: Path):
    """Duplicate eventId writes must not double-count. Belt-and-suspenders
    against a caller retrying the same event."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = TelemetryEvent(provider="anthropic", model="x")
    store.write(e)
    store.write(e)  # same eventId — should be ignored
    assert store.count() == 1


def test_store_schema_version_persisted(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    store.write(TelemetryEvent())  # triggers init
    # v2: Phase 3 added httpStatus + stage columns.
    assert store.schema_version() == 3


def test_store_creates_parent_directory(tmp_path: Path):
    """The default path is `runtime_metrics/inspectorpro_metrics.sqlite` —
    the parent dir may not exist on a fresh checkout. Store must mkdir."""
    nested = tmp_path / "deep" / "nested" / "runtime_metrics"
    store = TelemetryStore(db_path=nested / "m.sqlite")
    store.write(TelemetryEvent())
    assert nested.exists() and nested.is_dir()
    assert (nested / "m.sqlite").exists()


# ─── record_event soft-fail guarantee ────────────────────────────────

class _FailingStore:
    """Minimal store stub whose write() always raises. Stands in for
    sqlite3.OperationalError ('database is locked'), disk-full, or any
    other transient failure mode the real store could throw."""

    def write(self, event):
        raise sqlite3.OperationalError("simulated write failure")


def test_record_event_swallows_store_failure(caplog):
    """The whole point of the soft-fail wrapper: a telemetry write
    failure must NEVER raise into the calling product workflow."""
    failing = _FailingStore()
    e = TelemetryEvent(provider="anthropic", model="claude-sonnet-4-5-20250929")

    # Capture warning log so we can assert the failure was reported
    # (logged, not silenced — silenced failures are how operators end
    # up confused about why metrics aren't recording).
    with caplog.at_level(logging.WARNING, logger="inspectorpro.telemetry"):
        record_event(e, store=failing)  # MUST NOT raise

    matching = [r for r in caplog.records
                if "telemetry write failed" in r.getMessage()]
    assert matching, "expected a WARNING log on telemetry write failure"
    # Privacy: log line should NOT contain raw prompt-like content.
    # The event has none, but assert the eventId is present (it's
    # the only identifier we expose).
    assert e.eventId in matching[0].getMessage()


def test_record_provider_call_writes_event_with_computed_cost(tmp_path: Path):
    """End-to-end: helper builds event + computes cost + persists."""
    reset_default_store_for_tests()
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_provider_call(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        inputTokens=200,
        outputTokens=100,
        latencyMs=42.5,
        route="/api/agent/chat",
        workflow="agent_chat",
        agentType="sage",
        store=store,
    )
    assert e.totalTokens == 300
    assert e.pricingConfidence == CONFIDENCE_ESTIMATED
    # Haiku 4.5 estimated rate: input 0.80, output 4.00 per million.
    expected_cost = (200 * 0.80 + 100 * 4.00) / 1_000_000.0
    assert e.estimatedCostUsd == pytest.approx(expected_cost)
    assert store.count() == 1


def test_record_provider_call_with_unknown_model_records_zero_cost(tmp_path: Path):
    """Per user direction: unknown models record cost=0 and confidence=unknown
    rather than silently guessing. Caller still gets an event back so the
    request is observable even though the cost is not."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_provider_call(
        provider="anthropic",
        model="claude-fictional-9000",
        inputTokens=100,
        outputTokens=50,
        store=store,
    )
    assert e.estimatedCostUsd == 0.0
    assert e.pricingConfidence == CONFIDENCE_UNKNOWN
    assert store.count() == 1


# ─── Timing helper ──────────────────────────────────────────────────

def test_time_block_returns_elapsed_ms():
    import time as _t
    with time_block() as elapsed:
        _t.sleep(0.01)  # 10 ms
        mid = elapsed()
    end = elapsed()
    # 10 ms +/- jitter. Just confirm monotonicity + sane magnitude.
    assert mid >= 0.0
    assert end >= mid
    assert end < 1000.0  # would be a serious problem if 10ms slept >1s


# ─── Phase 2: provider-call helpers ──────────────────────────────────

from ai_inspector.telemetry import (
    classify_exception_status,
    record_anthropic_call,
    record_openai_call,
    record_openai_transcription,
)


class _FakeAnthropicUsage:
    """Mimics anthropic.types.Usage shape."""
    def __init__(self, input_tokens=0, output_tokens=0,
                 cache_read_input_tokens=0, cache_creation_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeAnthropicResponse:
    def __init__(self, **usage_kwargs):
        self.usage = _FakeAnthropicUsage(**usage_kwargs)


class _FakeOpenAIUsage:
    """Mimics openai.types.completion_usage.CompletionUsage shape."""
    def __init__(self, prompt_tokens=0, completion_tokens=0, total_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class _FakeOpenAIResponse:
    def __init__(self, **usage_kwargs):
        self.usage = _FakeOpenAIUsage(**usage_kwargs)


# ─── classify_exception_status ──────────────────────────────────────

def test_classify_exception_status_rate_limit():
    class RateLimitError(Exception): pass
    s, e = classify_exception_status(RateLimitError("..."))
    assert s == "rate_limited"
    assert e == "RateLimitError"


def test_classify_exception_status_timeout():
    class APITimeoutError(Exception): pass
    s, e = classify_exception_status(APITimeoutError("..."))
    assert s == "timeout"
    assert e == "APITimeoutError"


def test_classify_exception_status_other():
    class WeirdError(Exception): pass
    s, e = classify_exception_status(WeirdError("..."))
    assert s == "error"
    assert e == "WeirdError"


# ─── record_anthropic_call ──────────────────────────────────────────

def test_record_anthropic_call_extracts_all_token_fields(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    resp = _FakeAnthropicResponse(
        input_tokens=1000, output_tokens=500,
        cache_read_input_tokens=200, cache_creation_input_tokens=100,
    )
    event = record_anthropic_call(
        model="claude-sonnet-4-5-20250929",
        response=resp, latency_ms=42.5,
        route="/api/agent/chat", workflow="agent_chat", agentType="sage",
        store=store,
    )
    assert event is not None
    assert event.provider == "anthropic"
    assert event.model == "claude-sonnet-4-5-20250929"
    assert event.status == "success"
    assert event.inputTokens == 1000
    assert event.outputTokens == 500
    assert event.cacheReadTokens == 200
    assert event.cacheWriteTokens == 100
    assert event.totalTokens == 1800
    assert event.latencyMs == 42.5
    assert event.route == "/api/agent/chat"
    assert event.workflow == "agent_chat"
    assert event.agentType == "sage"
    # Cost from estimated rates; just confirm > 0 and confidence label.
    assert event.estimatedCostUsd > 0.0
    assert event.pricingConfidence == "estimated"
    assert store.count() == 1


def test_record_anthropic_call_error_path_records_zero_tokens(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    event = record_anthropic_call(
        model="claude-sonnet-4-5-20250929",
        response=None, latency_ms=12.0,
        status="rate_limited", errorType="RateLimitError",
        route="/api/agent/chat", workflow="agent_chat", agentType="sage",
        store=store,
    )
    assert event is not None
    assert event.status == "rate_limited"
    assert event.errorType == "RateLimitError"
    assert event.inputTokens == 0
    assert event.outputTokens == 0
    assert event.totalTokens == 0
    assert event.estimatedCostUsd == 0.0
    assert store.count() == 1


def test_record_anthropic_call_tolerates_response_without_usage(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    class Bare: pass
    event = record_anthropic_call(
        model="claude-sonnet-4-5-20250929",
        response=Bare(), latency_ms=5.0,
        route="/api/agent/chat", workflow="agent_chat", agentType="sage",
        store=store,
    )
    # No usage attr → tokens default to 0, status still success.
    assert event is not None
    assert event.inputTokens == 0
    assert event.outputTokens == 0
    assert store.count() == 1


def test_record_anthropic_call_swallows_internal_failure(caplog):
    """Helper itself must never raise — bad tag name would normally
    TypeError out of TelemetryEvent(**extra); helper catches and logs."""
    with caplog.at_level(logging.WARNING, logger="inspectorpro.telemetry"):
        result = record_anthropic_call(
            model="claude-sonnet-4-5-20250929",
            response=_FakeAnthropicResponse(input_tokens=10, output_tokens=5),
            latency_ms=1.0,
            unknownFieldThatDoesNotExist="bad-tag",
        )
    assert result is None
    # Helper logs at warning when its internal call fails.
    matching = [r for r in caplog.records
                if "record_anthropic_call failed" in r.getMessage()]
    assert matching, "expected warning when helper itself fails"


# ─── record_openai_call ─────────────────────────────────────────────

def test_record_openai_call_extracts_prompt_completion_tokens(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    resp = _FakeOpenAIResponse(prompt_tokens=400, completion_tokens=200, total_tokens=600)
    event = record_openai_call(
        model="gpt-4o-mini",
        response=resp, latency_ms=33.3,
        route="/api/inspect", workflow="inspection", agentType="iris",
        partNumber="1020001",
        store=store,
    )
    assert event is not None
    assert event.provider == "openai"
    assert event.model == "gpt-4o-mini"
    assert event.inputTokens == 400
    assert event.outputTokens == 200
    assert event.totalTokens == 600
    assert event.partNumber == "1020001"
    assert event.estimatedCostUsd > 0.0
    assert event.pricingConfidence == "estimated"


def test_record_openai_call_error_path(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    event = record_openai_call(
        model="gpt-4o-mini",
        response=None, latency_ms=7.0,
        status="timeout", errorType="APITimeoutError",
        route="/api/inspect", workflow="inspection", agentType="iris",
        store=store,
    )
    assert event.status == "timeout"
    assert event.errorType == "APITimeoutError"
    assert event.totalTokens == 0


# ─── record_openai_transcription ────────────────────────────────────

def test_record_openai_transcription_records_zero_cost_whisper(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    event = record_openai_transcription(
        model="whisper-1", latency_ms=123.4,
        route="/api/voice/transcribe", workflow="voice_transcribe", agentType="none",
        store=store,
    )
    assert event is not None
    assert event.provider == "openai"
    assert event.model == "whisper-1"
    assert event.totalTokens == 0
    # whisper-1 confidence is "unknown" by design — cost MUST be 0.0.
    assert event.estimatedCostUsd == 0.0
    assert event.pricingConfidence == "unknown"
    assert event.latencyMs == 123.4


# ─── End-to-end with mocked SDK client ──────────────────────────────

def test_mocked_anthropic_call_emits_event_with_full_field_set(tmp_path):
    """Demonstrates the call-site pattern used in engine.py / qc_report.py
    / server.py: time_block + try/except + record_anthropic_call. Uses a
    mock client so no live API hit. Verifies every field the acceptance
    criteria require (tokens, model, provider, workflow, latency,
    estimatedCostUsd)."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    mock_response = _FakeAnthropicResponse(input_tokens=1500, output_tokens=300)
    fake_client_calls = []

    def fake_messages_create(**kwargs):
        fake_client_calls.append(kwargs)
        return mock_response

    # Mimic the engine.py pattern verbatim.
    model = "claude-sonnet-4-5-20250929"
    with time_block() as elapsed:
        response = fake_messages_create(model=model, max_tokens=4096)
    record_anthropic_call(
        model=model, response=response, latency_ms=elapsed(),
        route="engine/inspection", workflow="inspection", agentType="iris",
        store=store,
    )

    assert fake_client_calls == [{"model": model, "max_tokens": 4096}]
    rows = store.query_recent(10)
    assert len(rows) == 1
    e = rows[0]
    assert e.provider == "anthropic"
    assert e.model == model
    assert e.workflow == "inspection"
    assert e.inputTokens == 1500
    assert e.outputTokens == 300
    assert e.totalTokens == 1800
    assert e.latencyMs >= 0.0
    assert e.estimatedCostUsd > 0.0


def test_mocked_openai_call_emits_event_with_full_field_set(tmp_path):
    """Same shape for the OpenAI path."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    mock_response = _FakeOpenAIResponse(
        prompt_tokens=800, completion_tokens=200, total_tokens=1000,
    )

    def fake_chat_create(**kwargs):
        return mock_response

    model = "gpt-4o"
    with time_block() as elapsed:
        response = fake_chat_create(model=model)
    record_openai_call(
        model=model, response=response, latency_ms=elapsed(),
        route="engine/report", workflow="report", agentType="none",
        partNumber="1020001",
        store=store,
    )

    rows = store.query_recent(10)
    assert len(rows) == 1
    e = rows[0]
    assert e.provider == "openai"
    assert e.model == model
    assert e.workflow == "report"
    assert e.inputTokens == 800
    assert e.outputTokens == 200
    assert e.totalTokens == 1000
    assert e.partNumber == "1020001"
    assert e.estimatedCostUsd > 0.0


def test_helpers_never_propagate_into_caller_on_store_failure(caplog):
    """Provider-call helpers must respect the soft-fail boundary even
    when the underlying store crashes (e.g. disk-full)."""
    class FailingStore:
        def write(self, event):
            raise sqlite3.OperationalError("simulated")

    failing = FailingStore()
    with caplog.at_level(logging.WARNING, logger="inspectorpro.telemetry"):
        # All three helpers must not raise.
        record_anthropic_call(
            model="x", response=_FakeAnthropicResponse(input_tokens=1),
            latency_ms=1.0, store=failing,
        )
        record_openai_call(
            model="y", response=_FakeOpenAIResponse(prompt_tokens=1),
            latency_ms=1.0, store=failing,
        )
        record_openai_transcription(
            model="whisper-1", latency_ms=1.0, store=failing,
        )
    # Each call should have logged a warning via record_event's wrapper.
    assert any("telemetry write failed" in r.getMessage() for r in caplog.records)


def test_no_raw_prompt_or_response_field_on_telemetry_event():
    """Privacy invariant: the TelemetryEvent dataclass MUST NOT carry
    any field that could hold raw user content."""
    from dataclasses import fields as dc_fields
    forbidden_substrings = ("prompt", "response", "message", "content",
                            "drawing_bytes", "cad", "api_key", "payload")
    field_names = {f.name.lower() for f in dc_fields(TelemetryEvent)}
    for forbidden in forbidden_substrings:
        leaks = [n for n in field_names if forbidden in n]
        assert not leaks, f"forbidden field substring '{forbidden}' found in {leaks}"


# ─── Phase 3: endpoint + workflow stage events ───────────────────────

from ai_inspector.telemetry import (
    record_endpoint_event,
    record_workflow_stage,
)


# Schema additions

def test_event_has_phase3_fields_default_to_none():
    e = TelemetryEvent()
    assert e.httpStatus is None
    assert e.stage is None


def test_event_phase3_fields_roundtrip_via_dict():
    e = TelemetryEvent(httpStatus=404, stage="inspect")
    d = e.to_dict()
    assert d["httpStatus"] == 404
    assert d["stage"] == "inspect"
    restored = TelemetryEvent.from_dict(d)
    assert restored.httpStatus == 404
    assert restored.stage == "inspect"


def test_event_streaming_fields_roundtrip_via_dict():
    e = TelemetryEvent(
        firstTokenLatencyMs=120.5,
        firstCleanSentenceMs=340.0,
        streamDurationMs=1450.25,
        pipelineLatencyMs=18.75,
        finalizeDeltaChars=12,
    )
    restored = TelemetryEvent.from_dict(e.to_dict())
    assert restored.firstTokenLatencyMs == 120.5
    assert restored.firstCleanSentenceMs == 340.0
    assert restored.streamDurationMs == 1450.25
    assert restored.pipelineLatencyMs == 18.75
    assert restored.finalizeDeltaChars == 12


def test_store_persists_streaming_columns(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "stream.sqlite")
    try:
        store.write(TelemetryEvent(
            workflow="agent_chat_stream_v2",
            firstTokenLatencyMs=100.0,
            firstCleanSentenceMs=250.0,
            streamDurationMs=900.0,
            pipelineLatencyMs=20.0,
            finalizeDeltaChars=4,
        ))
        row = store.query_recent(1)[0]
        assert row.firstTokenLatencyMs == 100.0
        assert row.firstCleanSentenceMs == 250.0
        assert row.streamDurationMs == 900.0
        assert row.pipelineLatencyMs == 20.0
        assert row.finalizeDeltaChars == 4
        assert store.schema_version() == 3
    finally:
        store.close()


def test_store_persists_phase3_columns(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = TelemetryEvent(
        provider="none", route="GET /api/profiles",
        httpStatus=200, latencyMs=12.3,
    )
    store.write(e)
    rows = store.query_recent(10)
    assert len(rows) == 1
    assert rows[0].httpStatus == 200
    assert rows[0].route == "GET /api/profiles"


def test_store_migrates_v1_database_to_v2(tmp_path: Path):
    """Open a sqlite file that was created with the Phase 1/2 schema
    (no httpStatus, no stage columns) and confirm Store._apply_migrations
    adds the missing columns on first init."""
    db = tmp_path / "legacy.sqlite"
    # Hand-craft a Phase 1/2 schema (no httpStatus, no stage). Must include
    # all columns the Phase 1/2 indexes referenced, otherwise SCHEMA_SQL's
    # CREATE INDEX IF NOT EXISTS will fail against the table that already
    # exists without those columns.
    import sqlite3 as _s
    conn = _s.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE telemetry_events (
                eventId TEXT PRIMARY KEY,
                timestampUtc TEXT NOT NULL,
                environment TEXT,
                sessionId TEXT,
                requestId TEXT,
                route TEXT,
                workflow TEXT,
                agentType TEXT,
                provider TEXT,
                model TEXT,
                status TEXT,
                errorType TEXT,
                inputTokens INTEGER NOT NULL DEFAULT 0,
                outputTokens INTEGER NOT NULL DEFAULT 0,
                cacheReadTokens INTEGER NOT NULL DEFAULT 0,
                cacheWriteTokens INTEGER NOT NULL DEFAULT 0,
                totalTokens INTEGER NOT NULL DEFAULT 0,
                estimatedCostUsd REAL NOT NULL DEFAULT 0.0,
                pricingConfidence TEXT,
                latencyMs REAL NOT NULL DEFAULT 0.0,
                retryCount INTEGER NOT NULL DEFAULT 0,
                toolCallCount INTEGER NOT NULL DEFAULT 0,
                partNumber TEXT,
                documentKind TEXT
            );
            CREATE INDEX idx_telemetry_timestamp ON telemetry_events (timestampUtc);
            CREATE INDEX idx_telemetry_workflow  ON telemetry_events (workflow);
            CREATE INDEX idx_telemetry_model     ON telemetry_events (model);
            CREATE INDEX idx_telemetry_route     ON telemetry_events (route);
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1');
        """)
        conn.commit()
    finally:
        conn.close()

    store = TelemetryStore(db_path=db)
    try:
        # Trigger init by writing — should run the v1→v2 migration in-flight.
        store.write(TelemetryEvent(httpStatus=200, stage="total"))

        # Confirm migrated columns now accept writes.
        rows = store.query_recent(10)
        assert len(rows) == 1
        assert rows[0].httpStatus == 200
        assert rows[0].stage == "total"
        assert store.schema_version() == 3
    finally:
        store.close()  # truncate WAL so tmp_path cleanup can rmtree on Windows


# record_endpoint_event

def test_record_endpoint_event_2xx_status_is_success(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_endpoint_event(
        route="/api/profiles", method="GET",
        httpStatus=200, latency_ms=12.0, store=store,
    )
    assert e is not None
    assert e.status == "success"
    assert e.errorType is None
    assert e.provider == "none"
    assert e.model is None
    assert e.route == "GET /api/profiles"
    assert e.httpStatus == 200
    assert e.latencyMs == 12.0


def test_record_endpoint_event_4xx_5xx_status_is_error(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e1 = record_endpoint_event(route="/api/x", method="POST",
                               httpStatus=404, latency_ms=1.0, store=store)
    e2 = record_endpoint_event(route="/api/y", method="GET",
                               httpStatus=503, latency_ms=2.0, store=store)
    assert e1.status == "error"
    assert e1.errorType == "HTTP_404"
    assert e2.status == "error"
    assert e2.errorType == "HTTP_503"


def test_record_endpoint_event_accepts_workflow_tag(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_endpoint_event(
        route="/api/inspect", method="POST",
        httpStatus=200, latency_ms=12345.0,
        workflow="inspection", partNumber="1020001",
        store=store,
    )
    assert e.workflow == "inspection"
    assert e.partNumber == "1020001"


def test_record_endpoint_event_errorType_in_tags_does_not_collide(tmp_path: Path):
    """Regression: the FastAPI endpoint-timing middleware passes
    errorType as a kwarg on every call (None on success, exception
    class name on non-HTTPException failures). errorType is NOT a
    named parameter of record_endpoint_event, so it lands in **tags.
    Forwarding to record_provider_call used to pass errorType BOTH
    explicitly AND via **tags spread, triggering:
        TypeError: got multiple values for keyword argument 'errorType'
    Soft-fail caught the TypeError so user-facing responses kept
    working, but every endpoint event was silently dropped — the
    dashboard telemetry foundation was effectively broken.

    Three call shapes must all succeed and round-trip correctly:
      1. caller passes errorType=None on success → errorType stays None
      2. caller passes errorType="MyError" on failure → caller wins
      3. caller passes errorType=None on a 4xx/5xx → helper's
         "HTTP_<code>" fallback is used"""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    try:
        # Case 1: success path, caller's errorType=None tag
        e1 = record_endpoint_event(
            route="/api/bridge/status", method="GET",
            httpStatus=200, latency_ms=5.0, store=store,
            errorType=None,
        )
        assert e1 is not None, "soft-fail swallowed the call — collision regressed"
        assert e1.status == "success"
        assert e1.errorType is None
        assert e1.httpStatus == 200

        # Case 2: caller-provided errorType beats helper-derived HTTP_x
        e2 = record_endpoint_event(
            route="/api/x", method="POST",
            httpStatus=500, latency_ms=10.0, store=store,
            errorType="ZeroDivisionError",
        )
        assert e2 is not None
        assert e2.status == "error"
        assert e2.errorType == "ZeroDivisionError"
        assert e2.httpStatus == 500

        # Case 3: caller-provided None + error status → fall back to HTTP_x
        e3 = record_endpoint_event(
            route="/api/y", method="GET",
            httpStatus=404, latency_ms=2.0, store=store,
            errorType=None,
        )
        assert e3 is not None
        assert e3.status == "error"
        assert e3.errorType == "HTTP_404"
    finally:
        store.close()


# record_workflow_stage

def test_record_workflow_stage_basic(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_workflow_stage(
        workflow="inspection", stage="inspect",
        latency_ms=12345.0,
        route="/api/inspect", partNumber="1020001",
        store=store,
    )
    assert e is not None
    assert e.workflow == "inspection"
    assert e.stage == "inspect"
    assert e.latencyMs == 12345.0
    assert e.partNumber == "1020001"
    assert e.provider == "none"
    assert e.estimatedCostUsd == 0.0  # workflow events have no token cost


def test_record_workflow_stage_error_path(tmp_path: Path):
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    e = record_workflow_stage(
        workflow="bridge_extract", stage="total",
        latency_ms=42.0, status="error", errorType="HTTP_500",
        route="/api/request-part-extraction",
        store=store,
    )
    assert e.status == "error"
    assert e.errorType == "HTTP_500"
    assert e.stage == "total"


def test_record_workflow_stage_swallows_internal_failure(caplog):
    """Unknown tag → TypeError on TelemetryEvent construction → helper
    catches and logs. No raise into caller."""
    with caplog.at_level(logging.WARNING, logger="inspectorpro.telemetry"):
        result = record_workflow_stage(
            workflow="x", stage="y", latency_ms=1.0,
            unknownTag="will_typeerror",
        )
    assert result is None
    assert any("record_workflow_stage failed" in r.getMessage() for r in caplog.records)


# Bridge approval-wait split via on_state_change callback

def test_bridge_on_state_change_fires_on_transitions():
    """Phase 3 bridge change: wait_for_terminal accepts on_state_change.
    Verifies the callback fires for each state transition and can be
    used to mark the approval-wait → extract-wait boundary."""
    import asyncio
    from ai_inspector.bridge.client import BridgeClient
    from ai_inspector.bridge import JobSnapshot

    # Mock the BridgeClient.get_job to return a scripted sequence of
    # state transitions: awaiting-approval → approved → running → done.
    scripted_states = ["awaiting-approval", "approved", "running", "done"]
    state_iter = iter(scripted_states)

    class _FakeClient(BridgeClient):
        async def get_job(self, job_id):
            state = next(state_iter)
            return JobSnapshot(
                job_id=job_id, state=state,
                package_id=("sha-x" if state == "done" else None),
            )

    transitions = []
    def cb(old, new):
        transitions.append((old, new))

    fc = _FakeClient()
    snap = asyncio.run(fc.wait_for_terminal(
        "job-1", poll_interval_s=0.001, timeout_s=5.0,
        on_state_change=cb,
    ))
    assert snap.state == "done"
    # Four states observed → four transitions (None→awaiting-approval,
    # awaiting-approval→approved, approved→running, running→done).
    assert transitions == [
        (None,                "awaiting-approval"),
        ("awaiting-approval", "approved"),
        ("approved",          "running"),
        ("running",           "done"),
    ]


def test_bridge_on_state_change_callback_failure_is_swallowed():
    """If the callback itself raises, the poll loop must continue —
    a telemetry-side bug should not break the bridge extraction."""
    import asyncio
    from ai_inspector.bridge.client import BridgeClient
    from ai_inspector.bridge import JobSnapshot

    scripted_states = iter(["awaiting-approval", "done"])

    class _FakeClient(BridgeClient):
        async def get_job(self, job_id):
            return JobSnapshot(
                job_id=job_id, state=next(scripted_states),
                package_id="sha-y",
            )

    def bad_cb(old, new):
        raise RuntimeError("simulated callback bug")

    fc = _FakeClient()
    # Must not raise:
    snap = asyncio.run(fc.wait_for_terminal(
        "job-2", poll_interval_s=0.001, timeout_s=5.0,
        on_state_change=bad_cb,
    ))
    assert snap.state == "done"


# Privacy + safety regressions

def test_phase3_helpers_no_raw_content_leakage(tmp_path: Path):
    """Phase 3 events MUST NOT carry request bodies, response bodies,
    file contents, or prompts. The schema already enforces this; this
    test pins that neither new helper provides a sneaky way to inject
    free-text content into the schema."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    # Try to pass an unknown tag with content-like name — should not be
    # silently accepted (would hide secrets). The helper soft-fails.
    result = record_workflow_stage(
        workflow="x", stage="y", latency_ms=1.0,
        rawPrompt="SECRET PROMPT TEXT", store=store,
    )
    assert result is None  # soft-fail (unknown tag)
    assert store.count() == 0


def test_endpoint_event_includes_provider_none_for_dashboard_filtering(tmp_path: Path):
    """Endpoint events must be distinguishable from provider-call events
    so the dashboard can chart endpoint latency separately from model
    latency. The agreed marker is provider='none' + httpStatus set."""
    store = TelemetryStore(db_path=tmp_path / "m.sqlite")
    try:
        e = record_endpoint_event(
            route="/api/x", method="GET",
            httpStatus=200, latency_ms=1.0, store=store,
        )
        assert e.provider == "none"
        assert e.httpStatus == 200
    finally:
        store.close()


# ─── FastAPI middleware end-to-end ──────────────────────────────────

def test_middleware_records_api_request_via_test_client(tmp_path: Path, monkeypatch):
    """Server-level integration test: hit a tiny FastAPI app that mirrors
    the middleware wiring in server.py, then verify an endpoint event
    was recorded with the right route, method, status, and latency.
    Uses the env-var override so we never touch the real default store."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from ai_inspector.telemetry import (
        get_default_store, reset_default_store_for_tests,
        ENV_VAR, record_endpoint_event,
    )

    # Point the default store at a tmp file so the middleware writes
    # there, not into the project's runtime_metrics/.
    db = tmp_path / "middleware.sqlite"
    monkeypatch.setenv(ENV_VAR, str(db))
    reset_default_store_for_tests()

    app = FastAPI()

    @app.middleware("http")
    async def _timing(request, call_next):
        # Mirror server.py's middleware shape — skip non-/api/ and
        # record one event per /api/* request.
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        import time as _t
        _s = _t.perf_counter()
        response = None
        raised = None
        try:
            response = await call_next(request)
            return response
        except BaseException as ex:
            raised = ex
            raise
        finally:
            try:
                elapsed = (_t.perf_counter() - _s) * 1000.0
                if response is not None:
                    code = int(response.status_code)
                elif isinstance(raised, HTTPException):
                    code = int(getattr(raised, "status_code", 500))
                else:
                    code = 500
                record_endpoint_event(
                    route=path, method=request.method,
                    httpStatus=code, latency_ms=elapsed,
                )
            except Exception:
                pass

    @app.get("/api/ok")
    def _ok():
        return {"ok": True}

    @app.get("/api/notfound")
    def _nf():
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/")
    def _root():
        return {"hello": "world"}

    client = TestClient(app)
    r1 = client.get("/api/ok")
    assert r1.status_code == 200
    r2 = client.get("/api/notfound")
    assert r2.status_code == 404
    r3 = client.get("/")  # not /api/* — must NOT generate a telemetry event
    assert r3.status_code == 200

    store = get_default_store()
    try:
        # /api/ok + /api/notfound → 2 events; / → 0.
        # (record_endpoint_event uses the default store because we did
        # not pass `store=...` to the middleware mirror above.)
        assert store.count() == 2
        rows = store.query_recent(10)
        by_route = {r.route: r for r in rows}
        assert "GET /api/ok" in by_route
        assert by_route["GET /api/ok"].httpStatus == 200
        assert by_route["GET /api/ok"].status == "success"
        assert by_route["GET /api/ok"].provider == "none"
        assert "GET /api/notfound" in by_route
        assert by_route["GET /api/notfound"].httpStatus == 404
        assert by_route["GET /api/notfound"].status == "error"
        assert by_route["GET /api/notfound"].errorType == "HTTP_404"
    finally:
        store.close()
        reset_default_store_for_tests()


def test_middleware_skips_non_api_routes(tmp_path: Path, monkeypatch):
    """Sanity: middleware in server.py filters by /api/ prefix so we
    don't bury the dashboard in static-asset telemetry. Verify that
    a request to / produces no telemetry event."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.telemetry import (
        get_default_store, reset_default_store_for_tests,
        ENV_VAR, record_endpoint_event,
    )

    db = tmp_path / "skip.sqlite"
    monkeypatch.setenv(ENV_VAR, str(db))
    reset_default_store_for_tests()

    app = FastAPI()

    @app.middleware("http")
    async def _timing(request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        record_endpoint_event(
            route=request.url.path, method=request.method,
            httpStatus=200, latency_ms=1.0,
        )
        return await call_next(request)

    @app.get("/")
    def _root():
        return {"hello": "world"}

    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200

    store = get_default_store()
    try:
        assert store.count() == 0
    finally:
        store.close()
        reset_default_store_for_tests()
