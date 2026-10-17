"""Codex requires cancellable HTTP transport; inference is always stubbed here."""

import json

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.codex_runtime.policy import FLAG


def payload(agent="deviation-analyst", mode="facility_layout"):
    return {
        "message": "Walk me through the saved layout facts.",
        "agent_type": agent,
        "session_id": "transport-test-session",
        "client_turn_id": "transport-test-turn",
        "inspection_context": {"attachments": {"session": {"active_mode": mode}}},
    }


@pytest.mark.parametrize("streaming", ["0", "1"])
@pytest.mark.parametrize("context_shape", ["attachment", "flat", "contract", "legacy_context"])
def test_codex_batch_rejected_before_memory_or_inference(monkeypatch, streaming, context_shape):
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", streaming)

    async def forbidden(*args, **kwargs):
        pytest.fail("Batch HTTP must reject before entering the shared pipeline")

    monkeypatch.setattr(server, "_execute_agent_chat_with_memory", forbidden)
    request = payload()
    if context_shape == "flat":
        request["inspection_context"] = {"active_mode": "facility_layout"}
    elif context_shape == "contract":
        request["inspection_context"] = {"attachments": {
            "session": {"mode_contract": {"mode": "facility_layout"}},
        }}
    elif context_shape == "legacy_context":
        request["context"] = request.pop("inspection_context")
    response = TestClient(server.app).post("/api/agent/chat", json=request)
    assert response.status_code == 409, response.text
    error = response.json()["detail"]["error"]
    assert error["code"] == "codex_stream_required"
    assert error["retryable"] is False


@pytest.mark.parametrize("flag,agent,mode", [
    ("0", "deviation-analyst", "facility_layout"),
    ("1", "inspector", "facility_layout"),
    ("1", "deviation-analyst", "assembly"),
])
def test_other_batch_routes_still_use_the_shared_pipeline(monkeypatch, flag, agent, mode):
    monkeypatch.setenv(FLAG, flag)
    calls = []

    async def pipeline(request, http_request, *, streaming):
        calls.append((request.agent_type, streaming))
        return {"response": "legacy response", "tool_calls": []}

    monkeypatch.setattr(server, "_execute_agent_chat_with_memory", pipeline)
    response = TestClient(server.app).post("/api/agent/chat", json=payload(agent, mode))
    assert response.status_code == 200, response.text
    assert response.json()["response"] == "legacy response"
    assert calls == [(agent, False)]


@pytest.mark.parametrize("streaming,agents", [("1", "sage"), ("0", "sage"), ("0", "iris"), ("1", "")])
def test_codex_sse_still_reaches_internal_dispatch(monkeypatch, streaming, agents):
    from ai_inspector.codex_runtime import pilot

    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", streaming)
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", agents)
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    calls = []

    async def inspect(request, host, http_request, context, **kwargs):
        calls.append(request.client_turn_id)
        await kwargs["status_sink"]("codex_inspecting")
        return {"response": "saved facts", "tool_calls": []}

    monkeypatch.setattr(pilot, "inspect_facility", inspect)
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload())
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["event"] == "response_completed"
    assert events[-1]["final"]["response"] == "saved facts"
    assert calls == ["transport-test-turn"]


@pytest.mark.parametrize("flag,agent,mode", [
    ("0", "deviation-analyst", "facility_layout"),
    ("1", "inspector", "facility_layout"),
    ("1", "deviation-analyst", "assembly"),
])
def test_legacy_streaming_disabled_still_rejects_before_pipeline(monkeypatch, flag, agent, mode):
    monkeypatch.setenv(FLAG, flag)
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "0")

    async def forbidden(*args, **kwargs):
        pytest.fail("Codex transport override must not enable other streaming routes")

    monkeypatch.setattr(server, "_execute_agent_chat_with_memory", forbidden)
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload(agent, mode))
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("flag,expected", [("0", "legacy"), ("1", "codex")])
def test_status_marker_matches_backend_runtime_selection(monkeypatch, flag, expected):
    monkeypatch.setenv(FLAG, flag)
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "0")
    response = TestClient(server.app).get("/api/agent/chat/streaming-status")
    assert response.status_code == 200
    assert response.json()["facilityRuntime"] == expected
    assert response.json()["enabled"] is False
