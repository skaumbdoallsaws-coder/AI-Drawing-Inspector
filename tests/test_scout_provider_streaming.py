"""Contract tests for provider-token streaming on Scout's search endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server


class _TextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        self.content = [_TextBlock(text)]
        self.usage = SimpleNamespace(
            input_tokens=11,
            output_tokens=7,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )


class _FakeStream:
    def __init__(self, chunks, response):
        self._chunks = list(chunks)
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        async def _iterate():
            for chunk in self._chunks:
                yield chunk
        return _iterate()

    async def get_final_message(self):
        return self._response


class _FakeMessages:
    def __init__(self, chunks, response):
        self._chunks = chunks
        self._response = response

    def stream(self, **_kwargs):
        return _FakeStream(self._chunks, self._response)

    async def create(self, **_kwargs):
        return self._response


class _FakeAsyncAnthropic:
    response = _Response("")
    chunks = []

    def __init__(self, *_args, **_kwargs):
        self.messages = _FakeMessages(self.chunks, self.response)


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _post(monkeypatch, chunks, final_text):
    import anthropic

    _FakeAsyncAnthropic.chunks = list(chunks)
    _FakeAsyncAnthropic.response = _Response(final_text)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    return TestClient(server.app).post("/api/agent/chat/stream", json={
        "message": "Find a compatible spacer.",
        "agent_type": "parts-finder",
        "history": [],
    })


def test_scout_streams_provider_deltas_then_commits_final_text(monkeypatch):
    response = _post(monkeypatch, ["Scout ", "found ", "a source."], "Scout found a source.")
    assert response.status_code == 200, response.text
    events = _events(response)
    deltas = "".join(event.get("text", "") for event in events if event["type"] == "text_delta")
    final = next(event for event in events if event["type"] == "response")
    assert events[0] == {"type": "status", "phase": "generating"}
    assert deltas.startswith("Scout")
    assert final["text"] == "Scout found a source."
    assert events[-1] == {"type": "done"}


def test_scout_never_commits_hidden_directive_text(monkeypatch):
    raw = "Visible answer.\n<TOOL_CALLS>{bad json}</TOOL_CALLS>"
    response = _post(monkeypatch, list(raw), raw)
    assert response.status_code == 200, response.text
    events = _events(response)
    displayed = "".join(event.get("text", "") for event in events if event["type"] == "text_delta")
    final = next(event for event in events if event["type"] == "response")
    assert "tool_calls" not in displayed.lower()
    assert "tool_calls" not in final["text"].lower()
    assert final["text"] == "Visible answer."


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q", "--basetemp", ".runtime/pytest-scout-stream"]))
