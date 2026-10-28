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


def test_sage_stream_carries_plain_language_steps_before_the_answer(monkeypatch):
    import json
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    async def inspect(*_, **kwargs):
        await kwargs["step_sink"]({"id": 1, "kind": "tool", "state": "running", "label": "Reading the layout overview"})
        await kwargs["step_sink"]({"id": 1, "kind": "tool", "state": "done", "label": "Read the layout overview"})
        await kwargs["text_sink"]("Two zones.")
        return {"response": "Two zones.", "tool_calls": [], "tool_source": "codex_readonly_pilot"}
    monkeypatch.setattr(pilot, "inspect_facility", inspect)
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=payload().model_dump())
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    kinds = [e["event"] for e in events]
    assert [(e["step"]["state"], e["step"]["label"]) for e in events if e["event"] == "agent_step"] == [
        ("running", "Reading the layout overview"), ("done", "Read the layout overview")]
    assert kinds.index("agent_step") < kinds.index("text_delta") < kinds.index("response_completed")


# Sage on Codex in Workflows > Documentation (codex_runtime/documentation_pilot.py).
def documentation_payload(agent="deviation-analyst", mode="documentation"):
    return server.AgentChatRequest(message="Which documents can you make?", agent_type=agent,
        session_id="test-session", client_turn_id="test-turn",
        inspection_context={"active_mode": mode, "attachments": {"assembly": {"assembly_number": "tricycle"}}})


@pytest.mark.parametrize("pilot_flag,documentation_flag,plan,agent,mode,codex", [
    ("1", "1", False, "deviation-analyst", "documentation", True),
    ("1", "", True, "deviation-analyst", "documentation", True),
    ("1", "", False, "deviation-analyst", "documentation", False),
    ("1", "0", True, "deviation-analyst", "documentation", False),
    ("0", "1", False, "deviation-analyst", "documentation", False),
    ("1", "1", False, "parts-finder", "documentation", False),
    # The Assembly tab's Sage: its assembly and appearance tools (docs/assembly-appearance-plan.md).
    ("1", "1", False, "deviation-analyst", "assembly", True),
    ("1", "", True, "deviation-analyst", "assembly", True),
    ("1", "1", False, "deviation-analyst", "report", False),
])
def test_documentation_turns_go_to_codex_only_when_enabled(monkeypatch, pilot_flag, documentation_flag, plan, agent,
                                                           mode, codex):
    from ai_inspector.codex_runtime import chatgpt_accounts, documentation_pilot
    monkeypatch.setenv(FLAG, pilot_flag)
    monkeypatch.setenv("INSPECTORPRO_CODEX_DOCUMENTATION", documentation_flag)
    monkeypatch.setattr(chatgpt_accounts, "subscription_mode", lambda: plan)
    async def legacy(*_):
        return {"response": "legacy", "tool_calls": []}
    async def documentation(request, host, http_request, context, **kwargs):
        assert host is server._DOCUMENTATION_AGENT_HOST and context["assembly_number"] == "tricycle"
        calls, warnings = kwargs["guard_tool_calls"]([{"name": name, "args": {}} for name in (
            "generate_parts_manual_draft", "publish_specification_sheet", "edit_parts_manual_composition",
            "write_file")])
        assert [call["name"] for call in calls] == [
            "generate_parts_manual_draft", "publish_specification_sheet", "edit_parts_manual_composition"]
        assert kwargs["workspace"] == ("assembly" if mode == "assembly" else "documentation")
        return {"response": "documented", "tool_calls": calls}
    monkeypatch.setattr(server, "_agent_chat_impl", legacy)
    monkeypatch.setattr(server, "load_gateway_config", lambda: None)
    monkeypatch.setattr(documentation_pilot, "inspect_documentation", documentation)
    monkeypatch.setattr(pilot, "inspect_facility", lambda *_, **__: pytest.fail("Facility pilot called"))
    request = documentation_payload(agent, mode)
    if plan and not codex:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(server.agent_chat(request, None))
        assert caught.value.detail["error"]["code"] == "codex_subscription_workflow_unavailable"
        return
    assert asyncio.run(server.agent_chat(request, None))["response"] == ("documented" if codex else "legacy")
    if codex:
        assert server._memory_model_metadata(request, streaming=True)["runtime"] == "codex_app_server"


def test_documentation_on_codex_requires_the_stream_and_reports_its_runtime(monkeypatch):
    import json
    from ai_inspector.codex_runtime import documentation_pilot
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_DOCUMENTATION", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    monkeypatch.delenv("INSPECTORPRO_CHAT_STREAMING", raising=False)
    async def documentation(*_, **kwargs):
        await kwargs["status_sink"]("codex_connecting")
        await kwargs["status_sink"]("codex_documentation")
        await kwargs["text_sink"]("Building the parts manual now.")
        return {"response": "Building the parts manual now.", "tool_source": "codex_documentation",
                "tool_calls": [{"name": "generate_parts_manual_draft", "args": {}}], "tool_call_count": 1,
                "codex_documentation": {"assemblyNumber": "tricycle", "checkedDocumentation": True}}
    monkeypatch.setattr(documentation_pilot, "inspect_documentation", documentation)
    client = TestClient(server.app)
    status = client.get("/api/agent/chat/streaming-status").json()
    assert status["documentationRuntime"] == "codex"
    legacy = client.post("/api/agent/chat", json=documentation_payload().model_dump())
    assert legacy.status_code == 409 and "codex_stream_required" in legacy.text
    response = client.post("/api/agent/chat/v2/stream", json=documentation_payload().model_dump())
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["phase"] for e in events if e.get("phase", "").startswith("codex_")] == [
        "codex_connecting", "codex_documentation"]
    final = events[-1]["final"]
    assert events[-1]["event"] == "response_completed"
    assert final["tool_calls"] == [{"name": "generate_parts_manual_draft", "args": {}}]
    assert final["codex_documentation"]["assemblyNumber"] == "tricycle"
    monkeypatch.setenv("INSPECTORPRO_CODEX_DOCUMENTATION", "0")
    assert client.get("/api/agent/chat/streaming-status").json()["documentationRuntime"] == "legacy"


def test_the_documentation_host_mirrors_the_browsers_auto_approval_rule():
    trusted = server._DocumentationAgentHost._trusted_for_publish
    ready = {"status": "ready", "source": "cad_hierarchy", "confidence": 0.9}
    assert trusted([ready, {**ready, "source": "process_map"}, {"status": "approved", "source": "names"}], {}) == {
        "ok": True}
    assert "library_manual_profile" in trusted([{**ready, "source": "library_manual_profile"}], {})["reason"]
    assert "0.80 confidence" in trusted([{**ready, "confidence": 0.79}], {})["reason"]
    assert "no reason" in trusted([ready], {"exclusions": [{"reason": " "}]})["reason"]
    assert trusted([], {}) == {"ok": False}


def test_the_documentation_host_names_which_assembly_the_evidence_is_for(monkeypatch):
    from fastapi.responses import JSONResponse
    monkeypatch.setattr(server, "operations_manual_get", lambda _: JSONResponse(status_code=409, content={
        "success": False, "error": "operations_manual_validation",
        "message": "publication nomenclature is bound to a different assembly"}))
    monkeypatch.setattr(server._DocumentationAgentHost, "_evidence_assembly", staticmethod(lambda: "MMLE-50D"))
    state = server._DOCUMENTATION_AGENT_HOST.state("tricycle", "operations_and_maintenance_manual")
    assert state == {"ok": False, "code": "operations_manual_validation", "message":
        "the registered operations-manual evidence (docs/operations-manual) is for MMLE-50D; tricycle has no "
        "registered evidence"}
