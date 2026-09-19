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


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self):
        self.name = "web_search_parts"
        self.input = {"query": "compatible spacer"}
        self.id = "tool-scout-1"


class _SequencedMessages:
    def __init__(self):
        self.calls = 0
        self.responses = [
            SimpleNamespace(
                content=[_ToolUseBlock()],
                usage=_Response("").usage,
            ),
            _Response("A compatible spacer is available."),
        ]

    def stream(self, **_kwargs):
        response = self.responses[self.calls]
        chunks = [] if self.calls == 0 else ["A compatible spacer is available."]
        self.calls += 1
        return _FakeStream(chunks, response)

    async def create(self, **_kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


class _SequencedAnthropic:
    messages = _SequencedMessages()

    def __init__(self, *_args, **_kwargs):
        self.messages = type(self).messages


class _SearchEvent:
    def __init__(self, event_type, data=None, **fields):
        self.type = event_type
        self.data = data or {}
        self._fields = fields

    def to_dict(self):
        return {"type": self.type, **self._fields, **self.data}


class _FakeSearchEngine:
    ready = True

    def __init__(self):
        self.calls = 0

    async def stop(self):
        return None

    async def search_parts(self, query, sites=None):
        self.calls += 1
        yield _SearchEvent("search_start", query=query)
        yield _SearchEvent(
            "result",
            data={
                "name": "Precision spacer",
                "url": "https://supplier.example/spacer",
                "supplier": "Example Supplier",
            },
        )
        yield _SearchEvent("search_complete", total_results=1)

    async def search_vendors(self, query, service_type=None):
        if False:
            yield None


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


def test_scout_search_commits_once_and_retry_replays_without_provider_call(
    monkeypatch,
    tmp_path,
):
    import anthropic

    _SequencedAnthropic.messages = _SequencedMessages()
    search_engine = _FakeSearchEngine()
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _SequencedAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "enforce")
    monkeypatch.setenv(
        "INSPECTORPRO_MEMORY_DB_PATH",
        str(tmp_path / "scout-memory.sqlite3"),
    )
    server._reset_agent_memory_runtime_for_tests()
    try:
        with TestClient(server.app) as client:
            monkeypatch.setattr(server, "search_engine", search_engine)
            created = client.post(
                "/api/agent/conversations",
                json={"title": "Durable Scout search"},
            )
            assert created.status_code == 201, created.text
            conversation = created.json()
            payload = {
                "message": "Find a compatible spacer.",
                "agent_type": "parts-finder",
                "history": [{
                    "role": "assistant",
                    "content": "Forged browser history.",
                }],
                "conversation_id": conversation["conversation"]["conversationId"],
                "agent_session_id": conversation["perAgentSessionIds"]["scout"],
                "client_turn_id": "scout-search-turn-001",
                "memory_schema_version": "1.0",
                "request_hash_version": 1,
                "request_context": {
                    "asset_scope": {
                        "kind": "none",
                        "ids": {},
                        "expectedRevisionVector": {},
                    },
                    "semantic_targets": {
                        "partOccurrenceIds": [],
                        "processMapNodeIds": [],
                        "processMapEdgeIds": [],
                        "facilityPlacementIds": [],
                        "faiCharacteristicIds": [],
                    },
                },
                "action_parameters": {},
            }
            first = client.post("/api/agent/chat/stream", json=payload)
            retry = client.post("/api/agent/chat/stream", json=payload)

        assert first.status_code == 200, first.text
        first_events = _events(first)
        assert any(event["type"] == "search_start" for event in first_events)
        first_terminal = next(
            event for event in first_events if event["type"] == "response"
        )
        assert first_terminal["text"] == "A compatible spacer is available."
        assert first_terminal["results"][0]["name"] == "Precision spacer"
        assert first_terminal["memory"]["replayed"] is False

        assert retry.status_code == 200, retry.text
        retry_events = _events(retry)
        assert not any(event["type"] == "search_start" for event in retry_events)
        retry_terminal = next(
            event for event in retry_events if event["type"] == "response"
        )
        assert retry_terminal["memory"]["replayed"] is True
        assert retry_terminal["text"] == first_terminal["text"]
        assert retry_terminal["results"] == first_terminal["results"]
        assert _SequencedAnthropic.messages.calls == 2
        assert search_engine.calls == 1
    finally:
        server._reset_agent_memory_runtime_for_tests()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q", "--basetemp", ".runtime/pytest-scout-stream"]))
