"""Existing Sage streaming boundary for packaging; no paid inference."""
import asyncio
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from ai_inspector.codex_runtime import packaging_pilot
from ai_inspector.codex_runtime.packaging_tools import packaging_scope
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.admission import PackagingAdmission
from ai_inspector.packaging_shipping.service import PackagingService


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_READONLY_PILOT", "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_PACKAGING", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    monkeypatch.setenv("INSPECTORPRO_CODEX_AUTH_MODE", "api_key")
    principal = FacilityPrincipal("engineer", "tenant", ("site",), ("editor",))
    service = PackagingService(tmp_path / "packages")
    registry = PackagingAdmission(service)
    doc = service.create(packaging_scope(principal))
    editor = registry.publish(principal, {"document_id": doc["id"], "revision": 0,
        "session_id": "session-1", "conversation_id": "conversation-1", "active_mode": "packaging_shipping",
        "dirty": False, "conflict": False, "pending_operations": 0})
    monkeypatch.setattr(server, "_PACKAGING_SERVICE", service)
    monkeypatch.setattr(server, "_PACKAGING_ADMISSION", registry)
    monkeypatch.setattr(server._FACILITY_LAYOUT_HOST, "resolve_principal", lambda _: principal)
    request = server.AgentChatRequest(message="Inspect the package", agent_type="deviation-analyst",
        session_id="session-1", agent_session_id="session-1", conversation_id="conversation-1", client_turn_id="turn-1",
        inspection_context={"attachments": {"session": {"active_mode": "packaging_shipping"},
            "packaging": {"admission_id": editor["admission_id"]}}})
    return request, service, registry, doc


def test_admitted_packaging_precedes_legacy_and_receives_sinks(route, monkeypatch):
    request, service, registry, _ = route
    async def run(req, saved, admitted, **kw):
        assert req is request and saved is service and admitted is registry
        assert kw["normalized"]["packaging_admission_id"]
        assert kw["text_sink"] is sink
        return {"response": "Checked", "tool_source": "codex_packaging"}
    def forbidden(*args, **kwargs):
        pytest.fail("No legacy provider fallback")
    async def sink(_):
        pass
    monkeypatch.setattr(packaging_pilot, "inspect_packaging", run)
    monkeypatch.setattr(server, "_agent_chat_impl", forbidden)
    monkeypatch.setattr(server, "load_gateway_config", forbidden)
    token = server._AGENT_CHAT_STREAM_SINK.set(sink)
    try:
        assert asyncio.run(server.agent_chat(request, None))["tool_source"] == "codex_packaging"
    finally:
        server._AGENT_CHAT_STREAM_SINK.reset(token)


def test_host_gives_sage_its_quote_desk_only_for_the_same_service(route, monkeypatch):
    from ai_inspector.packaging_shipping.quoting import QuoteDesk
    request, service, _, _ = route
    seen = []

    async def run(req, saved, admitted, **kw):
        seen.append(kw.get("quotes"))
        return {"response": "Checked", "tool_source": "codex_packaging"}
    monkeypatch.setattr(packaging_pilot, "inspect_packaging", run)
    desk = QuoteDesk(service)
    monkeypatch.setattr(server, "_PACKAGING_QUOTES", desk, raising=False)
    asyncio.run(server.agent_chat(request, None))
    monkeypatch.setattr(server, "_PACKAGING_QUOTES", QuoteDesk(PackagingService(service.root.parent / "other")), raising=False)
    asyncio.run(server.agent_chat(request, None))
    monkeypatch.delattr(server, "_PACKAGING_QUOTES", raising=False)
    asyncio.run(server.agent_chat(request, None))
    assert seen[0] is desk and seen[1:] == [None, None]


def test_disabled_packaging_never_falls_back(route, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_PACKAGING", "0")
    monkeypatch.setattr(server, "_agent_chat_impl", lambda *_: pytest.fail("No legacy fallback"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(server.agent_chat(route[0], None))
    assert caught.value.detail["error"]["code"] == "codex_packaging_unavailable"


def test_subscription_accepts_only_enabled_packaging_route(route, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_AUTH_MODE", "chatgpt_plan")
    server._require_subscription_chat_route(route[0])
    monkeypatch.setenv("INSPECTORPRO_CODEX_PACKAGING", "0")
    with pytest.raises(HTTPException):
        server._require_subscription_chat_route(route[0])


def test_sync_endpoint_refuses_packaging(route):
    response = TestClient(server.app).post("/api/agent/chat", json=route[0].model_dump())
    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "codex_stream_required"


def test_packaging_stream_carries_receipts(route, monkeypatch):
    async def run(*args, **kw):
        await kw["status_sink"]("codex_packaging")
        await kw["text_sink"]("Arranged six.")
        return {"response": "Arranged six.", "tool_calls": [], "tool_source": "codex_packaging",
                "codex_packaging": {"documentId": route[3]["id"], "revision": 1, "mutationOutcome": "committed"}}
    monkeypatch.setattr(packaging_pilot, "inspect_packaging", run)
    response = TestClient(server.app).post("/api/agent/chat/v2/stream", json=route[0].model_dump())
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert any(e.get("phase") == "codex_packaging" for e in events)
    assert events[-1]["final"]["codex_packaging"]["mutationOutcome"] == "committed"


def test_partial_error_metadata_survives_sse_normalization(route, monkeypatch):
    async def fail(*args, **kw):
        error = PilotError("codex_packaging_failed", "Interrupted; saved edits remain.")
        error.packaging_result = {"documentId": route[3]["id"], "revision": 1, "mutationOutcome": "committed"}
        raise error
    monkeypatch.setattr(packaging_pilot, "inspect_packaging", fail)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(server.agent_chat(route[0], None))
    error = server._stream_provider_error_payload(caught.value)
    assert error["codex_packaging"]["mutationOutcome"] == "committed"
    assert error["retryable"] is False


def test_memory_uses_admitted_document_not_renderer_fields(route):
    request, _, _, doc = route
    context = server._memory_trusted_turn_context(request, None)
    assert context.asset_scope["kind"] == "packaging_shipping"
    assert context.asset_scope["ids"] == {"documentId": doc["id"]}
    assert context.revision_vector == {"packagingRevision": "0"}
    data = server._memory_fallback_provider_inputs(request, None, context)
    assert len(data) == 1 and "admission_id" not in json.dumps(data)
    assert "geometry" in data[0]["payload"]


def test_normalization_discards_forged_permissions_and_references(route):
    raw = route[0].inspection_context.copy()
    raw.update(packaging_admission_id="forged", packaging_revision=99,
               packaging_design={"name": "forged"}, _packaging_write_grant=True)
    flat = server.normalize_agent_context(raw)["flat"]
    assert flat["packaging_admission_id"] != "forged"
    assert "packaging_revision" not in flat and "packaging_design" not in flat
    assert "_packaging_write_grant" not in flat
    raw["attachments"] = {"packaging": {"admission_id": "a" * 32, "direct_edit": True}}
    assert "packaging_admission_id" not in server.normalize_agent_context(raw)["flat"]


def test_packaging_stream_status_and_model_metadata(route, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_MODEL", "gpt-5.5")
    assert server.agent_chat_streaming_status()["packagingRuntime"] == "codex"
    assert server._memory_model_metadata(route[0], streaming=True)["runtime"] == "codex_app_server"
