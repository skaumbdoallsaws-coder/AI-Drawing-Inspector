"""Terminal delivery and teardown when the SSE producer times out or is cancelled."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server


def _payload():
    return server.AgentChatRequest(message="Inspect the saved layout", agent_type="deviation-analyst",
        inspection_context={"attachments": {"session": {"active_mode": "facility_layout"}}})


def _event(chunk):
    return json.loads(chunk.removeprefix("data: ").strip())


@pytest.mark.parametrize("after_status", [False, True])
def test_cancelled_producer_finishes_connected_stream(monkeypatch, after_status):
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")

    async def exercise():
        workers = []

        async def pipeline(*args, **kwargs):
            workers.append(asyncio.current_task())
            if after_status:
                await server._AGENT_CHAT_STATUS_SINK.get()("codex_inspecting")
            raise asyncio.CancelledError

        async def connected():
            return False

        monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
        response = await server.agent_chat_v2_stream(_payload(), SimpleNamespace(is_disconnected=connected))
        events = []
        try:
            async with asyncio.timeout(1):
                async for chunk in response.body_iterator:
                    events.append(_event(chunk))
        except TimeoutError:
            pytest.fail("SSE kept polling an empty queue after its producer was already cancelled")
        assert workers[0].done() and workers[0].cancelled()
        terminals = [event for event in events if event["event"] in {
            "response_completed", "response_error", "response_cancelled",
        }]
        assert len(terminals) == 1
        assert terminals[0]["event"] == "response_cancelled"

    asyncio.run(exercise())


def test_timeout_delivers_one_error_after_joined_cleanup(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")

    async def exercise():
        cleaned = asyncio.Event()
        workers = []

        async def pipeline(*args, **kwargs):
            workers.append(asyncio.current_task())
            await server._AGENT_CHAT_STATUS_SINK.get()("codex_inspecting")
            try:
                async with asyncio.timeout(0.01):
                    try:
                        await asyncio.Event().wait()
                    finally:
                        await asyncio.sleep(0.02)
                        cleaned.set()
            except TimeoutError:
                raise HTTPException(status_code=503, detail={"error": {
                    "code": "codex_time_budget_exhausted", "message": "Inspection timed out.",
                    "retryable": False,
                }}) from None

        async def connected():
            return False

        monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
        response = await server.agent_chat_v2_stream(_payload(), SimpleNamespace(is_disconnected=connected))
        events = []
        async with asyncio.timeout(1):
            async for chunk in response.body_iterator:
                events.append(_event(chunk))
                if events[-1]["event"] == "response_error":
                    assert cleaned.is_set()
        assert workers[0].done()
        assert [event["event"] for event in events].count("response_error") == 1
        assert events[-1]["code"] == "codex_time_budget_exhausted"
        assert events[-1]["retryable"] is False
        assert not any(event["event"] == "response_completed" for event in events)

    asyncio.run(exercise())


def test_timeout_survives_cancelled_error_publication(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")

    async def exercise():
        workers = []

        async def pipeline(*args, **kwargs):
            workers.append(asyncio.current_task())
            # Fill the real producer queue so publishing the error must await capacity.
            for _ in range(64):
                await server._AGENT_CHAT_STATUS_SINK.get()("codex_inspecting")
            raise HTTPException(status_code=503, detail={"error": {
                "code": "codex_time_budget_exhausted", "message": "Inspection timed out.",
                "retryable": False,
            }})

        async def connected():
            return False

        monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
        response = await server.agent_chat_v2_stream(_payload(), SimpleNamespace(is_disconnected=connected))
        iterator = response.body_iterator
        events = [_event(await anext(iterator)), _event(await anext(iterator))]
        await asyncio.sleep(0)
        assert len(workers) == 1 and not workers[0].done()
        workers[0].cancel()
        async with asyncio.timeout(1):
            async for chunk in iterator:
                events.append(_event(chunk))
        assert workers[0].done() and workers[0].cancelled()
        assert events[-1]["event"] == "response_error"
        assert events[-1]["code"] == "codex_time_budget_exhausted"
        assert events[-1]["retryable"] is False
        assert not any(event["event"] in {"response_completed", "response_cancelled"} for event in events)
        assert sum(event["event"] == "response_error" for event in events) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("disconnect", [False, True])
def test_cleanup_cancellation_preserves_known_timeout_and_joins_worker(monkeypatch, disconnect):
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")

    async def exercise():
        cleaning = asyncio.Event()
        cleaned = asyncio.Event()
        workers = []
        disconnected = False

        async def pipeline(*args, **kwargs):
            workers.append(asyncio.current_task())
            try:
                raise HTTPException(status_code=503, detail={"error": {
                    "code": "codex_time_budget_exhausted", "message": "Inspection timed out.",
                    "retryable": False,
                }})
            finally:
                cleaning.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0.02)
                    cleaned.set()

        async def is_disconnected():
            return disconnected

        monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
        response = await server.agent_chat_v2_stream(_payload(), SimpleNamespace(is_disconnected=is_disconnected))
        iterator = response.body_iterator
        events = [_event(await anext(iterator)), _event(await anext(iterator))]
        await cleaning.wait()
        disconnected = disconnect
        if not disconnect:
            workers[0].cancel()
        async with asyncio.timeout(1):
            async for chunk in iterator:
                events.append(_event(chunk))
        assert cleaned.is_set() and workers[0].done()
        assert workers[0].cancelling() == 1
        if disconnect:
            assert not any(event["event"] in {"response_completed", "response_error", "response_cancelled"} for event in events)
        else:
            assert events[-1]["event"] == "response_error"
            assert events[-1]["code"] == "codex_time_budget_exhausted"
            assert events[-1]["retryable"] is False
            assert not any(event["event"] in {"response_completed", "response_cancelled"} for event in events)

    asyncio.run(exercise())
