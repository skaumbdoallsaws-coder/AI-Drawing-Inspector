"""Offline host acceptance with real memory, admission, MCP, and packaging writes.

Only AppServer's model transport is scripted. No application/provider process is
started; the real MCP bridge listens briefly on literal loopback. All databases
and runtime files live in pytest's temporary directory.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import platform
import socket
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import server
from ai_inspector.codex_runtime.app_server import AppServer
from ai_inspector.codex_runtime.packaging_tools import PackagingGateway, packaging_scope
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.memory.invalidation import revision_vector_sha256
from ai_inspector.memory.models import MemoryPrincipal
from ai_inspector.memory.repository import MemoryNotFoundError
from ai_inspector.memory.sqlite_repository import SqliteMemoryRepository
from ai_inspector.memory.turn_lifecycle import active_memory_turn
from ai_inspector.packaging_shipping.admission import PackagingAdmission
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService


PROTOCOL = "2025-11-25"
PRIVATE_HISTORY = "OTHER_CONVERSATION_PRIVATE_HISTORY"
FORGED_HISTORY = "UNTRUSTED_RENDERER_HISTORY"
SYNTHETIC_KEY = "offline-acceptance-not-a-provider-credential"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Do not allow ambient credentials to turn this acceptance into a live test."""
    if sys.platform == "win32":
        monkeypatch.setattr(platform, "system", lambda: "Windows")
    original_resolve = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_async_send = httpx.AsyncClient.send
    original_sync_send = httpx.Client.send

    def require_loopback(host):
        assert host in {"127.0.0.1", "::1"}, "Offline acceptance forbids external network access"

    def resolve(host, *args, **kwargs):
        require_loopback(host)
        return original_resolve(host, *args, **kwargs)

    def connect(sock, address):
        require_loopback(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        require_loopback(address[0])
        return original_connect_ex(sock, address)

    async def async_send(client, request, *args, **kwargs):
        require_loopback(request.url.host)
        assert request.url.scheme == "http"
        return await original_async_send(client, request, *args, **kwargs)

    def sync_send(client, request, *args, **kwargs):
        require_loopback(request.url.host)
        assert request.url.scheme == "http"
        return original_sync_send(client, request, *args, **kwargs)

    def no_process(*args, **kwargs):
        pytest.fail("Offline acceptance must not launch any subprocess")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(httpx.AsyncClient, "send", async_send)
    monkeypatch.setattr(httpx.Client, "send", sync_send)
    monkeypatch.setattr(subprocess, "Popen", no_process)


def _design(name):
    return Design.model_validate({
        "name": name, "quantity": 1,
        "product": {"name": "Measured block", "dimensions_m": [0.1, 0.06, 0.04],
                    "mass_kg": 2, "mass_basis": "user_measured", "mass_evidence": "Test scale"},
        "constraints": {"contents": "ordinary_nonhazardous", "allowed_orientations": [0]},
        "packages": [{"id": "box_1", "carton": {
            "name": "Test carton", "inner_m": [0.4, 0.3, 0.25], "outer_m": [0.41, 0.31, 0.26],
            "tare_kg": 0.3, "tare_evidence": "Test scale"},
            "placements": [{"id": "item_1", "position_m": [0.02, 0.02, 0.02], "orientation": 0}],
            "allowance_kg": 0, "allowance_evidence": "No additional packing"}],
    })


def _scope(document_id, revision=0):
    return {"kind": "packaging_shipping", "ids": {"documentId": document_id},
            "expectedRevisionVector": {"packagingRevision": str(revision)}}


def _seed_private_history(repository, principal, conversation, session):
    identity = {
        "message": PRIVATE_HISTORY, "agentType": "deviation-analyst", "workflowMode": "general",
        "assetScope": {"kind": "none", "ids": {}, "expectedRevisionVector": {}},
        "semanticTargets": {}, "imageSha256": [], "actionParameters": {},
        "crossAgentProjectionSha256": None, "memorySchemaVersion": "1.0", "requestHashVersion": 1,
    }
    turn = repository.start_turn(principal, conversation.conversation_id, session.agent_session_id,
        client_turn_id="private-seed", request_identity=identity,
        user_message={"role": "user", "content": PRIVATE_HISTORY},
        scope_fingerprint=None, source_revision_vector={}).turn
    repository.commit_turn(principal, turn.turn_id, assistant_result={"response": PRIVATE_HISTORY},
        tool_receipts=[], resulting_revision_vector={},
        revision_barrier={"classification": "read_only", "outcome": "matched"},
        memory_envelope_sha256="a" * 64)


@pytest.fixture
def host(tmp_path, monkeypatch):
    settings = {
        "INSPECTORPRO_MEMORY_V1_MODE": "enforce",
        "INSPECTORPRO_MEMORY_DB_PATH": str(tmp_path / "memory.sqlite3"),
        "INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TURNS": "100",
        "INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TURNS": "200",
        "INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TOKENS": "100000",
        "INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TOKENS": "200000",
        "INSPECTORPRO_CODEX_READONLY_PILOT": "1",
        "INSPECTORPRO_CODEX_PACKAGING": "1",
        "INSPECTORPRO_CODEX_EDIT_PREVIEWS": "1",
        "INSPECTORPRO_CODEX_AUTH_MODE": "api_key",
        # Real credential preparation reads only this synthetic fixture value.
        "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE": "1",
        "INSPECTORPRO_CODEX_API_KEY": SYNTHETIC_KEY,
        "INSPECTORPRO_CODEX_BINARY": sys.executable,
        "INSPECTORPRO_CODEX_PILOT_ROOT": str(tmp_path / "model-transport"),
        "INSPECTORPRO_CODEX_MODEL": "gpt-5.5",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    server._reset_agent_memory_runtime_for_tests()
    service = PackagingService(tmp_path / "packaging")
    registry = PackagingAdmission(service, ttl_seconds=120)
    principal = FacilityPrincipal("memory-engineer", "memory-tenant", ("site-a",), ("editor",))
    memory_principal = MemoryPrincipal(principal.tenant_id, principal.principal_id, principal.roles)
    state = SimpleNamespace(principal=principal, memory_principal=memory_principal,
        service=service, registry=registry, scope=packaging_scope(principal),
        observed=[], transports=[], tool_results=[], attempt_scope_override=False)
    monkeypatch.setattr(server, "_PACKAGING_SERVICE", service)
    monkeypatch.setattr(server, "_PACKAGING_ADMISSION", registry)
    monkeypatch.setattr(server._FACILITY_LAYOUT_HOST, "resolve_principal", lambda _: state.principal)
    runtime = server._agent_memory_runtime()
    assert runtime.mode == "enforce" and isinstance(runtime.repository, SqliteMemoryRepository)
    state.repository = runtime.repository
    conversation = state.repository.create_conversation(memory_principal, title="Packaging acceptance")
    session = state.repository.create_agent_session(memory_principal, conversation.conversation_id,
        agent_type="deviation-analyst")
    state.conversation_id, state.session_id = conversation.conversation_id, session.agent_session_id
    private = state.repository.create_conversation(memory_principal, title="Other private conversation")
    private_session = state.repository.create_agent_session(memory_principal, private.conversation_id,
        agent_type="deviation-analyst")
    _seed_private_history(state.repository, memory_principal, private, private_session)
    state.other_conversation_id, state.other_session_id = private.conversation_id, private_session.agent_session_id
    state.saved = service.create(state.scope, _design("Selected packaging document"))
    state.other = service.create(state.scope, _design("UNSELECTED_DOCUMENT_PRIVATE_GEOMETRY"))
    state.editor_state = {"document_id": state.saved["id"], "revision": 0,
        "session_id": state.session_id, "conversation_id": state.conversation_id,
        "active_mode": "packaging_shipping", "dirty": False, "conflict": False, "pending_operations": 0}
    state.admission = registry.publish(principal, state.editor_state)
    state.http_request = Request({"type": "http", "method": "POST", "scheme": "http",
        "path": "/api/agent/chat/v2/stream", "headers": [],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "query_string": b""})

    async def enter(transport):
        state.transports.append(transport)
        transport.acceptance_closed = False
        return transport

    async def leave(transport, *_exc):
        transport.acceptance_closed = True

    async def inspect(transport, *, message, on_thread, check, **_kwargs):
        gateway = check.__self__
        assert isinstance(gateway, PackagingGateway)
        state.gateway = gateway
        state.turn = gateway.current_context.__self__
        bound = gateway.current_context()
        assert bound.session_id == state.session_id
        assert bound.conversation_id == state.conversation_id
        assert bound.document_id == state.saved["id"] and bound.revision == 0
        assert bound.direct_edit_authorized is True
        state.prompt = json.loads(message)
        assert state.prompt["boundDocument"] == {"document_id": state.saved["id"], "revision": 0}
        assert state.prompt["conversationContext"]
        on_thread("offline-packaging-thread")
        mcp = transport.config["mcp_servers"]["inspectorpro"]
        headers = {"Authorization": "Bearer " + transport.environment[mcp["bearer_token_env_var"]],
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        async with httpx.AsyncClient(headers=headers, trust_env=False, timeout=10) as client:
            sequence = 0

            async def rpc(method, params):
                nonlocal sequence
                sequence += 1
                response = await client.post(mcp["url"], json={"jsonrpc": "2.0", "id": sequence,
                                                               "method": method, "params": params})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["id"] == sequence and "error" not in body, body
                return body["result"]

            async def call(name, arguments, *, error=None):
                result = await rpc("tools/call", {"name": name, "arguments": arguments})
                assert result["isError"] is (error is not None), result
                structured = result["structuredContent"]
                assert structured["ok"] is (error is None), structured
                if error:
                    assert structured["error"]["code"] == error
                state.tool_results.append((name, deepcopy(structured)))
                return structured.get("data")

            initialized = await rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "offline-memory-host-acceptance", "version": "1"}})
            assert initialized["protocolVersion"] == PROTOCOL
            notification = await client.post(mcp["url"], json={"jsonrpc": "2.0",
                "method": "notifications/initialized", "params": {}})
            assert notification.status_code == 202
            listing = await rpc("tools/list", {})
            assert {tool["name"] for tool in listing["tools"]} == {
                "inspect_packaging", "validate_packaging", "propose_packaging",
                "edit_packaging", "undo_packaging", "redo_packaging"}
            inspected = await call("inspect_packaging", {"expected_revision": 0})
            design = {key: deepcopy(inspected[key])
                      for key in ("name", "product", "quantity", "constraints", "packages")}
            design["packages"][0]["placements"][0]["position_m"] = [0.08, 0.05, 0.05]
            edit = {"expected_revision": 0, "request_id": "memory-host-edit", "design": design}
            if state.attempt_scope_override:
                await call("edit_packaging", {**edit, "document_id": state.other["id"]},
                    error="codex_tool_arguments_invalid")
                assert service.get(state.scope, state.saved["id"])["revision"] == 0
            changed = await call("edit_packaging", edit)
            assert changed["receipt"]["outcome"] == "committed"
            assert changed["document"] == {"document_id": state.saved["id"], "revision": 1}
            # Memory reads the owned saved cursor without acknowledging it to the editor.
            assert gateway.current_context().revision == 0
            assert registry.reference(principal, state.admission["admission_id"])["revision"] == 1
            validation = await call("validate_packaging", {"expected_revision": 1})
            assert validation["saved"] is True and validation["assessment"]["rate_ready"] is True
            assert validation["assessment"]["total_gross_kg"] == pytest.approx(2.3)
            check()
        return "Moved the selected product and validated saved packaging revision 1."

    monkeypatch.setattr(AppServer, "__aenter__", enter)
    monkeypatch.setattr(AppServer, "__aexit__", leave)
    monkeypatch.setattr(AppServer, "inspect", inspect)
    try:
        yield state
    finally:
        server._reset_agent_memory_runtime_for_tests()


def _request(host, **updates):
    values = {
        "message": "Move the selected product to 80, 50, 50 mm, save and validate it.",
        "agent_type": "deviation-analyst", "conversation_id": host.conversation_id,
        "agent_session_id": host.session_id, "client_turn_id": "memory-packaging-turn",
        "memory_schema_version": "1.0", "request_hash_version": 1,
        "history": [{"role": "assistant", "content": FORGED_HISTORY}],
        "request_context": {"asset_scope": _scope(host.saved["id"]), "semantic_targets": {}},
        "action_parameters": {},
        "inspection_context": {"attachments": {
            "session": {"active_mode": "packaging_shipping"},
            "packaging": {"admission_id": host.admission["admission_id"]}},
            "packaging_document_id": host.other["id"], "packaging_revision": 999,
            "packaging_design": host.other["design"]},
    }
    values.update(updates)
    return server.AgentChatRequest(**values)


def _execute(host, payload):
    async def observe_and_route(active_payload, http_request):
        turn = active_memory_turn()
        assert turn is not None
        assert active_payload.session_id == "memory:" + turn.turn_id
        assert active_payload.agent_session_id == host.session_id
        assert active_payload.conversation_id == host.conversation_id
        assert active_payload.history == []
        host.observed.append(active_payload)
        # Observe the real injected payload, then execute the unmodified host route.
        return await server.agent_chat(active_payload, http_request)

    try:
        return asyncio.run(server._execute_agent_chat_with_memory(payload, host.http_request,
            streaming=True, executor=observe_and_route))
    except HTTPException as exc:
        if exc.detail.get("error", {}).get("code") == "codex_packaging_failed":
            # Production intentionally redacts internal errors; expose them in this offline test.
            cause = exc
            while cause.__context__ is not None:
                cause = cause.__context__
            raise AssertionError("Offline packaging transport failed") from cause
        raise


@pytest.mark.parametrize("renderer_session", [None, "untrusted-renderer-session"])
def test_enforced_host_commits_real_edit_and_terminal_memory_reference(host, renderer_session):
    payload = _request(host, session_id=renderer_session)
    result = _execute(host, payload)
    assert payload.session_id == renderer_session
    assert result["tool_source"] == "codex_packaging"
    assert result["codex_packaging"]["revision"] == 1
    assert result["codex_packaging"]["checkedPackaging"] is True
    assert [name for name, _ in host.tool_results] == [
        "inspect_packaging", "edit_packaging", "validate_packaging"]
    saved = host.service.get(host.scope, host.saved["id"])
    assert saved["revision"] == 1 and saved["can_undo"] is True
    assert saved["design"]["packages"][0]["placements"][0]["position_m"] == [0.08, 0.05, 0.05]
    assert host.service.get(host.scope, host.other["id"]) == host.other
    assert len(result["tool_receipts"]) == 1
    receipt = result["tool_receipts"][0]
    assert receipt["casOutcome"] == "applied"
    assert receipt["resultingRevisionVector"] == {"packagingRevision": "1"}
    assert receipt["before_revision"] == 0 and receipt["after_revision"] == 1

    memory = result["memory"]
    assert memory["appliedToPrompt"] is True and memory["replayed"] is False
    turn = host.repository.get_turn(host.memory_principal, memory["turnId"])
    assert turn.status == "committed"
    assert turn.agent_session_id == host.session_id and turn.conversation_id == host.conversation_id
    assert turn.request_identity["assetScope"] == _scope(host.saved["id"])
    assert turn.source_revision_vector == {"packagingRevision": "0"}
    assert turn.resulting_revision_vector == {"packagingRevision": "1"}
    assert turn.tool_receipts == result["tool_receipts"]
    barrier = turn.revision_barrier
    assert barrier["classification"] == "action_write"
    assert barrier["terminalStatus"] == "committed" and barrier["errorCode"] is None
    assert barrier["effectCount"] == 1 and barrier["casOutcome"] == "applied"
    assert barrier["preEffectRevisionVector"] == {"packagingRevision": "0"}
    assert barrier["currentRevisionVector"] == {"packagingRevision": "1"}
    assert barrier["revisionAdvancedDuringTurn"] is True
    assert barrier["postEffectRevisionDrift"] is False
    manifest = host.repository.get_context_manifest(host.memory_principal, memory["contextManifestId"])
    assert manifest.agent_session_id == host.session_id and manifest.turn_id == turn.turn_id
    assert manifest.memory_envelope_sha256 == memory["memoryEnvelopeSha256"]
    assert manifest.manifest["revisionBarrier"]["postEffectRevisionDrift"] is False
    assert manifest.manifest["revisionBarrier"]["outcome"] == "effect_committed"
    assert manifest.manifest["revisionBarrier"]["resultingRevisionVectorSha256"] == revision_vector_sha256({"packagingRevision": "1"})
    session = host.repository.get_agent_session(host.memory_principal, host.session_id)
    assert session.revision_vector == {"packagingRevision": "1"}
    assert session.scope_fingerprint == turn.scope_fingerprint == manifest.scope_fingerprint

    reference = host.registry.reference(host.principal, host.admission["admission_id"])
    assert reference == {"document_id": host.saved["id"], "revision": 1,
        "session_id": host.session_id, "conversation_id": host.conversation_id,
        "selection_id": host.admission["selection_id"]}
    assert host.gateway.closed and not host.turn.cancel_event.is_set()
    assert len(host.transports) == 1 and host.transports[0].acceptance_closed
    with pytest.raises(PackagingError):
        host.turn.current_context()
    with pytest.raises(PackagingError):
        host.registry.begin(host.principal, host.admission["admission_id"],
            session_id=host.session_id, conversation_id=host.conversation_id,
            turn_id="cannot-reopen-terminal", principal_resolver=lambda: host.principal)

    disclosed = json.dumps({"prompt": host.prompt, "result": result,
                            "manifest": manifest.manifest, "tools": host.tool_results})
    for forbidden in (host.admission["admission_id"], SYNTHETIC_KEY, PRIVATE_HISTORY,
                      FORGED_HISTORY, host.other["id"], host.other["design"]["name"]):
        assert forbidden not in disclosed
    with pytest.raises(MemoryNotFoundError):
        host.repository.get_turn(MemoryPrincipal("other-tenant", "other-user"), turn.turn_id)


def test_model_cannot_redirect_edit_to_unselected_document(host):
    host.attempt_scope_override = True
    result = _execute(host, _request(host))
    assert host.tool_results[1][1]["error"]["code"] == "codex_tool_arguments_invalid"
    assert len(result["tool_receipts"]) == 1
    assert host.service.get(host.scope, host.other["id"]) == host.other
    assert host.service.get(host.scope, host.saved["id"])["revision"] == 1
    turn = host.repository.get_turn(host.memory_principal, result["memory"]["turnId"])
    assert turn.status == "committed" and turn.revision_barrier["postEffectRevisionDrift"] is False


@pytest.mark.parametrize("forgery", ["document", "revision", "session", "conversation", "principal"])
def test_untrusted_scope_or_identity_is_rejected_before_model_or_mutation(host, forgery):
    payload = _request(host)
    if forgery == "document":
        payload.request_context["asset_scope"] = _scope(host.other["id"])
    elif forgery == "revision":
        payload.request_context["asset_scope"] = _scope(host.saved["id"], 99)
    elif forgery == "session":
        payload.agent_session_id = host.other_session_id
    elif forgery == "conversation":
        payload.conversation_id = host.other_conversation_id
    else:
        host.principal = FacilityPrincipal("intruder", "other-tenant", ("site-a",), ("editor",))
    with pytest.raises(HTTPException) as error:
        _execute(host, payload)
    assert error.value.status_code in {403, 404, 409}
    assert not host.transports and not host.observed and not host.tool_results
    assert host.service.get(host.scope, host.saved["id"]) == host.saved
    assert host.service.get(host.scope, host.other["id"]) == host.other
    assert not host.repository.list_turns(host.memory_principal, host.conversation_id)
