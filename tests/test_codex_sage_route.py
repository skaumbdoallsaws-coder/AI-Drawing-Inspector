"""Existing Sage endpoint integration. All inference is stubbed, never paid."""
import asyncio

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.codex_runtime import pilot
from ai_inspector.codex_runtime.policy import FLAG, PilotError


def payload(agent="deviation-analyst", mode="facility_layout"):
    return server.AgentChatRequest(message="Inspect the layout", agent_type=agent,
        session_id="test-session", client_turn_id="test-turn",
        inspection_context={"active_mode": mode})


@pytest.mark.parametrize("flag,agent,mode", [("0", "deviation-analyst", "facility_layout"),
    ("1", "parts-finder", "facility_layout"), ("1", "deviation-analyst", "assembly")])
def test_pilot_does_not_replace_other_routes(monkeypatch, flag, agent, mode):
    monkeypatch.setenv(FLAG, flag)
    async def legacy(*_):
        return {"response": "legacy", "tool_calls": []}
    async def forbidden(*_, **__):
        pytest.fail("Pilot called for another workflow or disabled flag")
    monkeypatch.setattr(server, "_agent_chat_impl", legacy)
    monkeypatch.setattr(server, "load_gateway_config", lambda: None)
    monkeypatch.setattr(pilot, "inspect_facility", forbidden)
    assert asyncio.run(server.agent_chat(payload(agent, mode), None))["response"] == "legacy"


def test_pilot_precedes_model_gateway_and_uses_existing_sinks(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    def forbidden(*_, **__):
        pytest.fail("Legacy provider or gateway must not execute")
    async def inspect(request, host, http_request, context, **kwargs):
        assert host is server._FACILITY_LAYOUT_HOST
        assert kwargs["text_sink"] is sink
        return {"response": "inspected", "tool_calls": []}
    async def sink(_):
        pass
    monkeypatch.setattr(server, "load_gateway_config", forbidden)
    monkeypatch.setattr(server, "_agent_chat_impl", forbidden)
    monkeypatch.setattr(pilot, "inspect_facility", inspect)
    token = server._AGENT_CHAT_STREAM_SINK.set(sink)
    try:
        assert asyncio.run(server.agent_chat(payload(), None))["response"] == "inspected"
    finally:
        server._AGENT_CHAT_STREAM_SINK.reset(token)


def test_runtime_error_is_terminal_and_never_falls_back(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    async def failed(*_, **__):
        raise PilotError("codex_time_budget_exhausted", "Inspection timed out.")
    monkeypatch.setattr(pilot, "inspect_facility", failed)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(server.agent_chat(payload(), None))
    assert server._stream_provider_error_payload(caught.value) == {
        "code": "codex_time_budget_exhausted", "message": "Inspection timed out.", "retryable": False}


def test_memory_is_prepared_before_codex_execution(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    events = []
    def prepare(inputs):
        assert inputs == {}
        events.append("prepared")
        return "server-owned-memory"
    async def inspect(*_, **kwargs):
        assert events == ["prepared"]
        assert kwargs["memory_context"] == "server-owned-memory"
        events.append("executed")
        return {"response": "inspected", "tool_calls": []}
    monkeypatch.setattr(pilot, "inspect_facility", inspect)
    token = server._AGENT_MEMORY_ENVELOPE_PREPARER.set(prepare)
    try:
        asyncio.run(server.agent_chat(payload(), None))
    finally:
        server._AGENT_MEMORY_ENVELOPE_PREPARER.reset(token)
    assert events == ["prepared", "executed"]


def test_memory_preparation_failure_prevents_codex(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    def prepare(_):
        raise ValueError("context unavailable")
    async def forbidden(*_, **__):
        pytest.fail("Inference must not start without the required memory context")
    monkeypatch.setattr(pilot, "inspect_facility", forbidden)
    token = server._AGENT_MEMORY_ENVELOPE_PREPARER.set(prepare)
    try:
        with pytest.raises(ValueError, match="context unavailable"):
            asyncio.run(server.agent_chat(payload(), None))
    finally:
        server._AGENT_MEMORY_ENVELOPE_PREPARER.reset(token)


def test_memory_metadata_identifies_codex_not_legacy_gateway(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_MODEL", "gpt-5.5")
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *_args, **_kw: pytest.fail("Legacy model must not be attributed"))
    metadata = server._memory_model_metadata(payload(), streaming=True)
    assert metadata["model"] == "gpt-5.5"
    assert metadata["provider"] == "openai"
    assert metadata["runtime"] == "codex_app_server"


def test_codex_memory_carries_trusted_binding_not_full_geometry(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    trusted = server.TrustedTurnContext(
        asset_scope={"kind": "facility_layout", "ids": {"siteId": "site-local", "layoutId": "saved-layout"}},
        scope_fingerprint="scope-v1:test", revision_vector={"facilityLayoutRevision": "saved-revision"},
        workflow_mode="facility_layout")
    monkeypatch.setattr(server, "_resolve_trusted_facility_layout_context",
        lambda *_: pytest.fail("Do not duplicate geometry already available through MCP"))
    rows = server._memory_fallback_provider_inputs(payload(), None, trusted)
    assert len(rows) == 1 and rows[0]["origin"] == "server" and rows[0]["required"]
    assert rows[0]["payload"]["scope"] == trusted.asset_scope
    assert rows[0]["payload"]["revisionVector"] == trusted.revision_vector
    assert server.estimate_json_tokens(rows) < 600


def test_legacy_memory_keeps_existing_context_resolution(monkeypatch):
    monkeypatch.setenv(FLAG, "0")
    trusted = server.TrustedTurnContext(asset_scope={"kind": "facility_layout", "ids": {}},
        scope_fingerprint=None, revision_vector={}, workflow_mode="facility_layout")
    calls = []
    monkeypatch.setattr(server, "_resolve_trusted_facility_layout_context", lambda *_: calls.append("resolved"))
    server._memory_fallback_provider_inputs(payload(), None, trusted)
    assert calls == ["resolved"]


def test_sage_stream_transports_pilot_progress_and_response(monkeypatch):
    import json
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    async def inspect(*_, **kwargs):
        await kwargs["status_sink"]("codex_connecting")
        await kwargs["status_sink"]("codex_inspecting")
        await kwargs["status_sink"]("codex_researching")
        await kwargs["text_sink"]("Inspection complete.")
        return {"response": "Inspection complete.", "tool_calls": [], "tool_source": "codex_readonly_pilot",
            "content_blocks": [{"type": "sources", "title": "Research sources (unreviewed)", "sources": [
                {"url": "https://www.access-board.gov/ada/", "title": "Accessibility standards", "inferIdentity": False}]}]}
    monkeypatch.setattr(pilot, "inspect_facility", inspect)
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload().model_dump())
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["phase"] for e in events if e.get("phase", "").startswith("codex_")] == ["codex_connecting", "codex_inspecting", "codex_researching"]
    assert events[-1]["event"] == "response_completed"
    assert events[-1]["final"]["content_blocks"][0]["sources"][0]["url"] == "https://www.access-board.gov/ada/"
