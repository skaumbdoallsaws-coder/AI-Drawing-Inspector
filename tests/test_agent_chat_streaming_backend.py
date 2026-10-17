"""Backend contract tests for the v2 chat stream."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
import time
from types import SimpleNamespace
import pytest
import anyio

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


@pytest.mark.parametrize('disconnect_mode', ['task', 'scope', 'poll'])
def test_stream_disconnect_cancels_once_and_joins_cleanup(monkeypatch, disconnect_mode):
    monkeypatch.setenv('INSPECTORPRO_CHAT_STREAMING', '1')
    monkeypatch.setenv('INSPECTORPRO_STREAMING_AGENTS', 'scout')

    async def exercise():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        workers = []

        async def pipeline(*_args, **_kwargs):
            workers.append(asyncio.current_task())
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.03)
                cleaned.set()

        async def disconnected():
            return entered.is_set() and disconnect_mode == 'poll'

        monkeypatch.setattr(server, '_execute_agent_chat_with_memory', pipeline)

        async def consume():
            response = await server.agent_chat_v2_stream(server.AgentChatRequest(**_payload()),
                SimpleNamespace(is_disconnected=disconnected))
            async for _ in response.body_iterator:
                pass

        if disconnect_mode == 'scope':
            async with anyio.create_task_group() as group:
                group.start_soon(consume)
                await entered.wait()
                group.cancel_scope.cancel()
        else:
            consumer = asyncio.create_task(consume())
            await entered.wait()
            if disconnect_mode == 'task':
                consumer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await consumer
            else:
                await consumer
        assert cleaned.is_set(), 'Stream returned before runtime cleanup finished'
        assert workers[0].done()
        assert workers[0].cancelling() == 1

    asyncio.run(exercise())


def test_accumulate_response_text_accepts_message_and_string():
    assert server._accumulate_response_text(_Response("hello")) == "hello"
    assert server._accumulate_response_text("already text") == "already text"


def test_stream_transports_tool_status_without_turning_it_into_answer_text(monkeypatch):
    async def pipeline(*args, **kwargs):
        sink = server._AGENT_CHAT_STATUS_SINK.get()
        await sink("generation_search")
        await sink("generation_geometry")
        return {"response": "An isolated preview is ready.", "tool_calls": []}

    monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=_payload())
    events = _events(response)
    assert [item["phase"] for item in events if item.get("phase", "").startswith("generation_")] == [
        "generation_search", "generation_geometry"]
    assert not any(item["event"] == "text_delta" for item in events)
    assert events[-1]["event"] == "response_completed"
    assert server._AGENT_CHAT_STATUS_SINK.get() is None


def test_main_stream_retries_transient_failure_before_visible_text(monkeypatch):
    class FakeStream:
        def __init__(self, chunks=None, error=None):
            self._chunks = chunks or []
            self._error = error
            self.text_stream = self._iterate()

        async def _iterate(self):
            if self._error is not None:
                raise self._error
            for chunk in self._chunks:
                yield chunk

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get_final_message(self):
            return _Response("Recovered answer.")

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def stream(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeStream(error=RuntimeError("overloaded_error: Overloaded"))
            return FakeStream(chunks=["Recovered ", "answer."])

    messages = FakeMessages()
    received = []

    async def run():
        return await server._invoke_agent_model(
            SimpleNamespace(messages=messages),
            model="synthetic-model",
            max_tokens=32,
            system="system",
            messages=[{"role": "user", "content": "question"}],
            stream_sink=lambda text: received.append(text),
        )

    monkeypatch.setenv("INSPECTORPRO_AGENT_STREAM_ATTEMPTS", "2")
    monkeypatch.setenv("INSPECTORPRO_AGENT_STREAM_RETRY_BASE_MS", "0")
    response = asyncio.run(run())
    assert messages.calls == 2
    assert "".join(received) == "Recovered answer."
    assert server._accumulate_response_text(response) == "Recovered answer."


def test_main_stream_does_not_retry_after_visible_text(monkeypatch):
    class PartialStream:
        def __init__(self):
            self.text_stream = self._iterate()

        async def _iterate(self):
            yield "Partial answer"
            raise RuntimeError("overloaded_error: Overloaded")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def stream(self, **_kwargs):
            self.calls += 1
            return PartialStream()

    messages = FakeMessages()
    received = []

    async def run():
        await server._invoke_agent_model(
            SimpleNamespace(messages=messages),
            model="synthetic-model",
            max_tokens=32,
            system="system",
            messages=[{"role": "user", "content": "question"}],
            stream_sink=lambda text: received.append(text),
        )

    monkeypatch.setenv("INSPECTORPRO_AGENT_STREAM_ATTEMPTS", "3")
    monkeypatch.setenv("INSPECTORPRO_AGENT_STREAM_RETRY_BASE_MS", "0")
    try:
        asyncio.run(run())
    except RuntimeError as exc:
        assert "overloaded" in str(exc).lower()
    else:
        raise AssertionError("Expected the partial stream failure to propagate")
    assert messages.calls == 1
    assert received == ["Partial answer"]


def test_anthropic_adapter_forces_an_explicit_presentation_tool():
    captured = {}

    class FakeMessages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _Response("Structured result.")

    asyncio.run(server._invoke_agent_model(
        SimpleNamespace(messages=FakeMessages()),
        model="synthetic-model",
        max_tokens=64,
        system="system",
        messages=[{"role": "user", "content": "show a table"}],
        tools=[{
            "name": server.CHAT_TABLE_TOOL,
            "description": "Present a table.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }],
        required_tool_name=server.CHAT_TABLE_TOOL,
    ))

    assert captured["tool_choice"] == {
        "type": "tool",
        "name": server.CHAT_TABLE_TOOL,
        "disable_parallel_tool_use": True,
    }


def test_executor_only_fallback_is_limited_to_pure_authorized_actions():
    error = RuntimeError("overloaded_error: Overloaded")
    plan = SimpleNamespace(executor_id="show-resolved-motion-group")
    assert server._can_use_executor_only_provider_fallback(
        "Show the affected components in motion.", plan, error, {}
    )
    assert not server._can_use_executor_only_provider_fallback(
        "Explain the impact and show the affected components in motion.",
        plan,
        error,
        {},
    )
    assert not server._can_use_executor_only_provider_fallback(
        "What motion is affected?", plan, error, {}
    )
    assert not server._can_use_executor_only_provider_fallback(
        "Show the affected components in motion.",
        plan,
        error,
        {"first_token_perf": time.perf_counter()},
    )
    assert not server._can_use_executor_only_provider_fallback(
        "Show the affected components in motion.",
        plan,
        RuntimeError("invalid request"),
        {},
    )


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


def test_stream_terminal_serializes_immutable_facility_tool_policy(monkeypatch):
    async def facility_chat(_payload, _http_request):
        return {
            "response": "The Facility Layout draft is ready for review.",
            "skill_runtime": {
                "facility_orchestration": {
                    "allowedToolNames": frozenset({
                        "inspect_facility_semantics",
                        "generate_facility_departments_draft",
                    }),
                },
            },
        }

    monkeypatch.setattr(server, "agent_chat", facility_chat)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")

    response = TestClient(server.app).post(
        "/api/agent/chat/v2/stream", json=_payload()
    )

    assert response.status_code == 200, response.text
    events = _events(response)
    terminal = next(
        event for event in events if event["event"] == "response_completed"
    )
    assert terminal["final"]["skill_runtime"]["facility_orchestration"][
        "allowedToolNames"
    ] == [
        "generate_facility_departments_draft",
        "inspect_facility_semantics",
    ]
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

    async def failing_chat(_payload, _http_request):
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


def test_stream_surfaces_provider_credit_failure_without_generic_detail(monkeypatch):
    class ProviderCreditError(Exception):
        status_code = 400
        message = (
            "Error code: 400 - {'type': 'error', 'error': "
            "{'type': 'invalid_request_error', 'message': 'Your credit balance "
            "is too low to access the Anthropic API.'}}"
        )

    async def failing_chat(_payload, _http_request):
        raise ProviderCreditError()

    monkeypatch.setattr(server, "agent_chat", failing_chat)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "scout")

    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=_payload())
    events = _events(response)
    failure = next(event for event in events if event["event"] == "response_error")
    assert failure["code"] == "provider_credit_unavailable"
    assert failure["retryable"] is False
    assert "does not have enough credit" in failure["message"]
    assert "Error code:" not in failure["message"]
    assert not any(event["event"] == "response_completed" for event in events)


def test_required_context_budget_error_payload_is_actionable():
    failure = server._stream_provider_error_payload(
        server.ContextBudgetError(
            ["process_map.graph", "process_map.state"],
            estimated_tokens=17218,
            maximum_tokens=14000,
        )
    )

    assert failure == {
        "code": "required_context_budget_exceeded",
        "message": (
            "Sage could not assemble the required trusted context for this "
            "request. Narrow the requested scope and retry."
        ),
        "retryable": False,
    }


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q", "--basetemp", ".runtime/pytest-chat-stream-backend"]))
