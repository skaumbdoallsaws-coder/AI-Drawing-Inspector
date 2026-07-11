"""Backend contract tests for the v2 chat stream."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server


class _Block:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        self.content = [_Block(text)]
        self.usage = SimpleNamespace(
            input_tokens=11,
            output_tokens=7,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )


def _events(response):
    parsed = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            parsed.append(json.loads(line[6:]))
    return parsed


def _payload():
    return {
        "message": "Explain the selected catalog part.",
        "history": [],
        "inspection_context": {"part_number": "SYNTH-P1", "part_name": "Bracket"},
        "agent_type": "parts-finder",
        "session_id": "synthetic-session",
    }


def test_accumulate_response_text_accepts_message_and_string():
    assert server._accumulate_response_text(_Response("hello")) == "hello"
    assert server._accumulate_response_text("already text") == "already text"


def test_streaming_disabled_fails_before_generation(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "0")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=_payload())
    assert response.status_code == 404


def test_legacy_and_stream_terminal_results_are_identical(monkeypatch):
    raw = "The bracket is the selected catalog part."

    async def fake_invoke(_client, **kwargs):
        sink = kwargs.get("stream_sink")
        if sink is not None:
            for chunk in (raw[:8], raw[8:19], raw[19:]):
                pending = sink(chunk)
                if asyncio.iscoroutine(pending):
                    await pending
        return _Response(raw)

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    client = TestClient(server.app)

    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "0")
    legacy = client.post("/api/agent/chat", json=_payload())
    assert legacy.status_code == 200, legacy.text

    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    streamed = client.post("/api/agent/chat/v2/stream", json=_payload())
    assert streamed.status_code == 200, streamed.text
    events = _events(streamed)
    terminal = [event for event in events if event["event"] == "response_completed"]
    assert len(terminal) == 1
    assert terminal[0]["final"] == legacy.json()
    assert "".join(
        event.get("text", "") for event in events if event["event"] == "text_delta"
    ) == raw
    assert all(events[index]["seq"] == index for index in range(len(events)))
    assert events[0]["event"] == "response_started"
    assert events[-1]["event"] == "response_completed"


def test_directive_payload_is_never_streamed(monkeypatch):
    raw = (
        "I found a matching catalog result.\n"
        "<tool_calls>[{\"name\":\"search_parts\",\"args\":{}}]</tool_calls>"
    )

    async def fake_invoke(_client, **kwargs):
        sink = kwargs.get("stream_sink")
        for char in raw:
            await sink(char)
        return _Response(raw)

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=_payload())
    assert response.status_code == 200, response.text
    events = _events(response)
    visible = "".join(event.get("text", "") for event in events)
    assert visible == "I found a matching catalog result.\n"
    assert "tool_calls" not in visible.lower()
    assert sum(event["event"] == "tool_block_started" for event in events) == 1
    assert sum(event["event"] == "response_completed" for event in events) == 1


def test_high_risk_mode_falls_back_until_separate_flag_is_enabled(monkeypatch):
    payload = _payload()
    payload["inspection_context"] = {
        "attachments": {"session": {"active_mode": "report_fai"}}
    }
    payload["agent_type"] = "deviation-analyst"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_HIGH_RISK_MODES", "0")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload)
    assert response.status_code == 409


def test_high_risk_stream_releases_only_cleaned_sentences(monkeypatch):
    raw = (
        "Scrap. The oversized bore will seize within minutes. "
        "Check the last 10 parts from the lot immediately."
    )

    async def fake_invoke(_client, **kwargs):
        meta = server._AGENT_CHAT_STREAM_META.get()
        meta["provider_started_perf"] = time.perf_counter()
        sink = kwargs.get("stream_sink")
        for chunk in (raw[:4], raw[4:21], raw[21:55], raw[55:]):
            if "first_token_perf" not in meta:
                meta["first_token_perf"] = time.perf_counter()
            await sink(chunk)
        meta["provider_completed_perf"] = time.perf_counter()
        return _Response(raw)

    payload = _payload()
    payload["message"] = "Assess the FAI result."
    payload["inspection_context"] = {
        "attachments": {"session": {"active_mode": "report_fai"}},
        "fai_characteristics": [{
            "char_number": 5,
            "description": "Pin bore",
            "nominal": 30.0,
            "measured": 33.0,
            "tol_plus": 0.05,
            "tol_minus": 0.05,
            "lower_limit": 29.95,
            "upper_limit": 30.05,
            "status": "FAIL",
        }],
    }
    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_HIGH_RISK_MODES", "1")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload)
    assert response.status_code == 200, response.text
    events = _events(response)
    visible = "".join(event.get("text", "") for event in events)
    assert "scrap" not in visible.lower()
    assert "seize" not in visible.lower()
    assert "last 10" not in visible.lower()
    terminal = next(event for event in events if event["event"] == "response_completed")
    assert terminal["timings"]["first_clean_sentence_ms"] is not None
    final_text = terminal["final"]["response"]
    assert "33.0 mm" in final_text
    assert "30.0 mm" in final_text
    assert "scrap" not in final_text.lower()
    assert "seize" not in final_text.lower()


def test_failed_stream_never_enters_workflow_commit(monkeypatch):
    commit_calls = []

    async def failing_chat(_payload):
        sink = server._AGENT_CHAT_STREAM_SINK.get()
        await sink("A partial response that must not commit.")
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(server, "agent_chat", failing_chat)
    monkeypatch.setattr(
        server,
        "_commit_stream_workflow_state",
        lambda *args, **kwargs: commit_calls.append((args, kwargs)),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=_payload())
    events = _events(response)
    assert sum(event["event"] == "response_error" for event in events) == 1
    assert not any(event["event"] == "response_completed" for event in events)
    assert commit_calls == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q", "--basetemp", ".runtime/pytest-chat-stream-backend"]))
