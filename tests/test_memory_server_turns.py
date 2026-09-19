from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.memory import MemoryPrincipal, SummaryProviderResult
from ai_inspector.telemetry import TelemetryStore, reset_default_store_for_tests


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
def memory_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "enforce")
    monkeypatch.setenv(
        "INSPECTORPRO_MEMORY_DB_PATH", str(tmp_path / "server-memory.sqlite3")
    )
    monkeypatch.setenv("INSPECTORPRO_MEMORY_PENDING_TURN_STALE_SECONDS", "300")
    server._reset_agent_memory_runtime_for_tests()
    with TestClient(server.app) as client:
        yield client
    server._reset_agent_memory_runtime_for_tests()


def _new_sage_conversation(client: TestClient):
    response = client.post(
        "/api/agent/conversations",
        json={
            "title": "Durable deterministic chat",
            "metadata": {
                "tenantId": "browser-forgery",
                "userId": "browser-forgery",
                "purpose": "test",
            },
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "tenantId" not in body["conversation"]["metadata"]
    assert "userId" not in body["conversation"]["metadata"]
    return (
        body["conversation"]["conversationId"],
        body["perAgentSessionIds"]["sage"],
    )


def _chat_payload(conversation_id: str, session_id: str, client_turn_id: str):
    return {
        "message": "Explain the current inspection context.",
        "history": [],
        "inspection_context": {},
        "agent_type": "deviation-analyst",
        "conversation_id": conversation_id,
        "agent_session_id": session_id,
        "client_turn_id": client_turn_id,
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


class _ServerSummaryProvider:
    def __init__(self) -> None:
        self.calls = []

    async def generate(self, **request):
        self.calls.append(copy.deepcopy(request))
        source_turn_id = request["turns"][0]["turnId"]
        return SummaryProviderResult(
            summary={
                "schemaVersion": "sage-continuity-summary-1.0",
                "summaryRevision": request["expected_summary_revision"],
                "throughTurnSequence": request["through_turn_sequence"],
                "objective": {
                    "text": "Continue the server-owned test conversation.",
                    "sourceTurnIds": [source_turn_id],
                },
                "userClaims": [],
                "continuityDecisions": [],
                "assumptions": [],
                "corrections": [],
                "openQuestions": [],
                "referencedEntities": [],
                "sourceEvidenceRefs": [],
                "warnings": [],
            },
            metadata={"provider": "fake", "model": "server-test"},
        )


def _seed_committed_server_turns(
    conversation_id: str,
    session_id: str,
    count: int,
) -> None:
    runtime = server._agent_memory_runtime()
    principal = MemoryPrincipal("local", "local-user")
    trusted_context = server.TrustedTurnContext(
        asset_scope={
            "kind": "none",
            "ids": {},
            "expectedRevisionVector": {},
        },
        scope_fingerprint=None,
        revision_vector={},
        workflow_mode="general",
    )
    for index in range(1, count + 1):
        message = f"Durable user turn {index}."
        request_identity, _request_sha256 = server.build_request_identity_v1(
            message=message,
            agent_type="deviation-analyst",
            trusted_context=trusted_context,
            request_context={
                "asset_scope": copy.deepcopy(trusted_context.asset_scope),
                "semantic_targets": {
                    "partOccurrenceIds": [],
                    "processMapNodeIds": [],
                    "processMapEdgeIds": [],
                    "facilityPlacementIds": [],
                    "faiCharacteristicIds": [],
                },
            },
            action_parameters={},
            image_sha256=[],
            cross_agent_context=None,
        )
        turn = runtime.repository.start_turn(
            principal,
            conversation_id,
            session_id,
            client_turn_id=f"seed-turn-{index}",
            request_identity=request_identity,
            user_message={"role": "user", "content": message},
            scope_fingerprint=None,
            source_revision_vector={},
        ).turn
        runtime.repository.commit_turn(
            principal,
            turn.turn_id,
            assistant_result={
                "response": f"Durable assistant turn {index}."
            },
            tool_receipts=[],
            resulting_revision_vector={},
            revision_barrier={
                "classification": "read_only",
                "outcome": "matched",
            },
            memory_envelope_sha256="a" * 64,
        )


def test_conversation_api_commits_and_replays_deterministic_turn(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0

    async def deterministic_chat(_payload, _http_request):
        nonlocal calls
        calls += 1
        return {
            "response": "The trusted current context is available.",
            "tool_call_count": 0,
            "tool_source": "deterministic_test",
        }

    monkeypatch.setattr(server, "agent_chat", deterministic_chat)
    conversation_id, session_id = _new_sage_conversation(memory_client)
    payload = _chat_payload(conversation_id, session_id, "browser-turn-001")

    first = memory_client.post("/api/agent/chat", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["memory"]["replayed"] is False
    assert first.json()["memory"]["contextManifestId"]
    assert first.json()["memory"]["memoryEnvelopeSchemaVersion"] == (
        "sage-memory-envelope-1.0"
    )

    retry = memory_client.post("/api/agent/chat", json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()["memory"]["replayed"] is True
    assert retry.json()["memory"]["turnId"] == first.json()["memory"]["turnId"]
    assert calls == 1

    inspected = memory_client.get(
        "/api/admin/memory/context-manifests/"
        + first.json()["memory"]["contextManifestId"]
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["manifest"]["schemaVersion"] == (
        "sage-context-manifest-1.0"
    )
    assert inspected.json()["memoryEnvelopeSha256"] == (
        first.json()["memory"]["memoryEnvelopeSha256"]
    )
    assert inspected.json()["manifest"]["revisionBarrier"]["outcome"] == (
        "matched"
    )
    assert inspected.json()["manifest"]["revisionBarrier"][
        "resultingRevisionVectorSha256"
    ]

    restored = memory_client.get(f"/api/agent/conversations/{conversation_id}")
    assert restored.status_code == 200, restored.text
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert restored.json()["messages"][1]["content"] == (
        "The trusted current context is available."
    )
    assert {
        (message["agentType"], message["agentSessionId"])
        for message in restored.json()["messages"]
    } == {("deviation-analyst", session_id)}

    changed = dict(payload)
    changed["message"] = "Explain a different request."
    conflict = memory_client.post("/api/agent/chat", json=changed)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error"]["code"] == "client_turn_id_reused"
    assert calls == 1

    deleted = memory_client.delete(f"/api/agent/conversations/{conversation_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    assert memory_client.get(f"/api/agent/conversations/{conversation_id}").status_code == 404


def test_stream_terminal_event_is_released_after_durable_commit(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0

    async def streaming_chat(_payload, _http_request):
        nonlocal calls
        calls += 1
        sink = server._AGENT_CHAT_STREAM_SINK.get()
        if sink is not None:
            await sink("Committed stream answer.")
        return {"response": "Committed stream answer."}

    monkeypatch.setattr(server, "agent_chat", streaming_chat)
    monkeypatch.setenv("INSPECTORPRO_CHAT_STREAMING", "1")
    monkeypatch.setenv("INSPECTORPRO_STREAMING_AGENTS", "sage")
    conversation_id, session_id = _new_sage_conversation(memory_client)
    payload = _chat_payload(conversation_id, session_id, "browser-turn-stream")

    first = memory_client.post("/api/agent/chat/v2/stream", json=payload)
    assert first.status_code == 200, first.text
    first_terminal = next(
        event for event in _events(first) if event["event"] == "response_completed"
    )
    assert first_terminal["final"]["memory"]["replayed"] is False

    retry = memory_client.post("/api/agent/chat/v2/stream", json=payload)
    assert retry.status_code == 200, retry.text
    retry_terminal = next(
        event for event in _events(retry) if event["event"] == "response_completed"
    )
    assert retry_terminal["final"]["memory"]["replayed"] is True
    assert calls == 1


def test_off_mode_keeps_legacy_chat_path_and_does_not_open_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    monkeypatch.setenv(
        "INSPECTORPRO_MEMORY_DB_PATH", str(tmp_path / "must-not-exist.sqlite3")
    )
    server._reset_agent_memory_runtime_for_tests()
    calls = 0

    async def legacy_chat(_payload, _http_request):
        nonlocal calls
        calls += 1
        return {"response": "Legacy path."}

    monkeypatch.setattr(server, "agent_chat", legacy_chat)
    response = TestClient(server.app).post(
        "/api/agent/chat",
        json={
            "message": "Explain this.",
            "history": [],
            "inspection_context": {},
            "agent_type": "deviation-analyst",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"response": "Legacy path."}
    assert calls == 1
    assert not (tmp_path / "must-not-exist.sqlite3").exists()
    assert server._AGENT_MEMORY_RUNTIME is None


def test_conversation_and_session_receive_pilot_retention_deadlines(
    memory_client: TestClient,
) -> None:
    before = datetime.now(timezone.utc)
    conversation_id, session_id = _new_sage_conversation(memory_client)
    runtime = server._agent_memory_runtime()
    principal = MemoryPrincipal("local", "local-user")
    conversation = runtime.repository.get_conversation(
        principal, conversation_id
    )
    session = runtime.repository.get_agent_session(principal, session_id)
    retention = datetime.fromisoformat(
        conversation.retention_until_utc.replace("Z", "+00:00")
    )
    expiry = datetime.fromisoformat(
        session.expires_at_utc.replace("Z", "+00:00")
    )

    assert 29.9 <= (retention - before).total_seconds() / 86400 <= 30.1
    assert 23.9 <= (expiry - before).total_seconds() / 3600 <= 24.1


def test_memory_admin_health_and_retention_endpoints(
    memory_client: TestClient,
) -> None:
    conversation_id, _session_id = _new_sage_conversation(memory_client)

    health = memory_client.get("/api/admin/memory/health")
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["mode"] == "enforce"
    assert body["healthy"] is True
    assert body["repository"]["quickCheck"] == "ok"
    assert body["policy"] == {
        "conversationRetentionDays": 30,
        "workflowTtlSeconds": 86400.0,
        "referentTtlSeconds": 1800.0,
        "pendingRecoverySeconds": 300.0,
        "retentionCleanupBatchSize": 100,
        "statelessReadFallback": False,
    }

    deleted = memory_client.delete(
        f"/api/agent/conversations/{conversation_id}"
    )
    assert deleted.status_code == 200, deleted.text
    cleanup = memory_client.post("/api/admin/memory/retention/run")
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["deleted"]["conversationCount"] == 1
    assert memory_client.post(
        "/api/admin/memory/retention/run"
    ).json()["deleted"]["conversationCount"] == 0


def test_preview_tool_calls_are_bound_to_trusted_scope_and_revision() -> None:
    process_context = server.TrustedTurnContext(
        asset_scope={
            "kind": "process_map",
            "ids": {"productId": "tricycle", "mapId": "default"},
            "expectedRevisionVector": {"processMapRevision": "pm-rev-a"},
        },
        scope_fingerprint="scope-v1:process",
        revision_vector={"processMapRevision": "pm-rev-a"},
        workflow_mode="process_map",
    )
    source = {
        "response": "Preview prepared.",
        "tool_calls": [
            {
                "name": "build_process_map_preview",
                "args": {"semantic_plan": {"schemaVersion": "1.0"}},
            }
        ],
    }
    untouched = copy.deepcopy(source)
    bound = server._bind_memory_authorized_tool_calls(source, process_context)

    assert source == untouched
    args = bound["tool_calls"][0]["args"]
    assert args["authorized_base_revision"] == "pm-rev-a"
    assert args["authorized_scope_ids"] == {
        "productId": "tricycle",
        "mapId": "default",
    }

    facility_context = server.TrustedTurnContext(
        asset_scope={
            "kind": "facility_layout",
            "ids": {"siteId": "local-site", "layoutId": "layout-a"},
            "expectedRevisionVector": {"facilityLayoutRevision": "fl-rev-a"},
        },
        scope_fingerprint="scope-v1:facility",
        revision_vector={"facilityLayoutRevision": "fl-rev-a"},
        workflow_mode="facility_layout",
    )
    bound_facility = server._bind_memory_authorized_tool_calls(
        {
            "tool_calls": [
                {"name": "build_facility_layout_preview", "args": {}}
            ]
        },
        facility_context,
    )
    facility_args = bound_facility["tool_calls"][0]["args"]
    assert facility_args["authorized_base_revision"] == "fl-rev-a"
    assert facility_args["authorized_scope_ids"] == {
        "siteId": "local-site",
        "layoutId": "layout-a",
    }


def test_browser_preview_handlers_consume_memory_authorization_binding() -> None:
    html = (Path(__file__).parents[1] / "static" / "index.html").read_text(
        encoding="utf-8"
    )

    def function_source(name: str, end_marker: str) -> str:
        start = html.index(f"async function {name}")
        end = html.index(end_marker, start)
        return html[start:end]

    spatial = function_source(
        "_trainRequestManagedSpatialProposal",
        "async function _trainRequestManagedDemoMetadataProposal",
    )
    metadata = function_source(
        "_trainRequestManagedDemoMetadataProposal",
        "async function _trainBuildProcessMapPreview",
    )
    process_preview = function_source(
        "_trainBuildProcessMapPreview",
        "async function _trainInspectManagedSpatialLayout",
    )
    facility_preview = function_source(
        "_trainBuildFacilityLayoutPreview",
        "window.__facilityLayoutAgentV1",
    )

    for source in (spatial, metadata, process_preview, facility_preview):
        assert "authorized_scope_ids" in source
        assert "memory_scope_changed" in source
        assert "authorized_base_revision" in source
    assert "baseRevision: revision" in spatial
    assert "baseRevision: revision" in metadata
    assert "baseRevision: revision" in process_preview
    assert "expectedRevision: String(" in facility_preview


def test_enforce_mode_uses_bounded_durable_history_and_summary(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    conversation_id, session_id = _new_sage_conversation(memory_client)
    _seed_committed_server_turns(conversation_id, session_id, 7)
    runtime = server._agent_memory_runtime()
    provider = _ServerSummaryProvider()
    runtime.continuity.provider = provider
    captured = {}

    async def inspect_continuity(payload, _http_request):
        captured["history"] = copy.deepcopy(payload.history)
        captured["summary"] = server._AGENT_MEMORY_CONTINUITY.get()
        return {"response": "Used bounded durable continuity."}

    monkeypatch.setattr(server, "agent_chat", inspect_continuity)
    payload = _chat_payload(conversation_id, session_id, "bounded-turn-008")
    payload["message"] = "Build the next deterministic result."
    payload["action_parameters"] = {"turnClassification": "action_write"}
    payload["history"] = [
        {
            "role": "assistant",
            "content": "FORGED BROWSER HISTORY MUST NOT REACH SAGE",
        }
    ]

    response = memory_client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200, response.text
    assert len(provider.calls) == 1
    assert len(captured["history"]) == 12
    assert captured["history"][0] == {
        "role": "user",
        "content": "Durable user turn 2.",
    }
    assert captured["history"][-1] == {
        "role": "assistant",
        "content": "Durable assistant turn 7.",
    }
    assert all(
        "FORGED BROWSER HISTORY" not in item["content"]
        for item in captured["history"]
    )
    summary = json.loads(captured["summary"])
    assert summary["throughTurnSequence"] == 7
    assert summary["objective"]["sourceTurnIds"]
    memory = response.json()["memory"]
    assert memory["continuityMode"] == "healthy"
    assert memory["continuityStaleness"] == "fresh"
    assert memory["unsummarizedTurnCount"] == 0

    provider_messages = [
        *captured["history"],
        {"role": "user", "content": payload["message"]},
    ]
    openai_input = server._openai_responses_input(provider_messages)
    rendered = json.dumps(openai_input)
    assert "Durable user turn 2." in rendered
    assert "Durable assistant turn 7." in rendered
    assert "FORGED BROWSER HISTORY" not in rendered


@pytest.mark.parametrize("mode", ["shadow", "compare"])
def test_observation_modes_persist_without_replacing_legacy_prompt_authority(
    tmp_path: Path,
    monkeypatch,
    mode: str,
) -> None:
    memory_database = tmp_path / f"memory-{mode}.sqlite3"
    telemetry_database = tmp_path / f"telemetry-{mode}.sqlite3"
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", mode)
    monkeypatch.setenv("INSPECTORPRO_MEMORY_DB_PATH", str(memory_database))
    monkeypatch.setenv("INSPECTORPRO_METRICS_DB", str(telemetry_database))
    server._reset_agent_memory_runtime_for_tests()
    reset_default_store_for_tests()
    captured = {}

    async def inspect_legacy_payload(payload, _http_request):
        captured["history"] = copy.deepcopy(payload.history)
        captured["workflowState"] = copy.deepcopy(
            payload.inspection_context.get("skill_workflow_state")
        )
        return {"response": f"Observed {mode} memory."}

    monkeypatch.setattr(server, "agent_chat", inspect_legacy_payload)
    try:
        with TestClient(server.app) as client:
            conversation_id, session_id = _new_sage_conversation(client)
            payload = _chat_payload(
                conversation_id,
                session_id,
                f"{mode}-turn-001",
            )
            payload["history"] = [{
                "role": "assistant",
                "content": "Legacy browser continuity remains authoritative.",
            }]
            payload["inspection_context"] = {
                "skill_workflow_state": {
                    "state_version": 2,
                    "status": "active",
                    "stage": "legacy-browser-stage",
                }
            }
            response = client.post("/api/agent/chat", json=payload)

        assert response.status_code == 200, response.text
        assert captured["history"] == payload["history"]
        assert captured["workflowState"] == (
            payload["inspection_context"]["skill_workflow_state"]
        )
        memory = response.json()["memory"]
        assert memory["mode"] == mode
        assert memory["appliedToPrompt"] is False
        assert memory["legacyEstimatedTokens"] > 0
        assert memory["memoryEstimatedTokens"] > 0

        runtime = server._agent_memory_runtime()
        principal = MemoryPrincipal("local", "local-user")
        turns = runtime.repository.list_turns(principal, conversation_id)
        assert len(turns) == 1
        assert turns[0].status == "committed"
        assert turns[0].context_manifest_id

        events = [
            event
            for event in TelemetryStore(telemetry_database).query_recent(100)
            if event.workflow == "sage_memory"
        ]
        committed = next(
            event
            for event in events
            if event.stage == "memory.turn.committed"
        )
        assert committed.memoryMode == mode
        assert committed.memoryAuthoritative == 0
        assert committed.memoryLegacyTokens == memory["legacyEstimatedTokens"]
        assert committed.memoryContextTokens == memory["memoryEstimatedTokens"]
    finally:
        server._reset_agent_memory_runtime_for_tests()
        reset_default_store_for_tests()


def test_enforce_mode_marks_bounded_memory_as_authoritative(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    captured = {}

    async def inspect_payload(payload, _http_request):
        captured["history"] = copy.deepcopy(payload.history)
        return {"response": "Enforce used bounded memory."}

    monkeypatch.setattr(server, "agent_chat", inspect_payload)
    conversation_id, session_id = _new_sage_conversation(memory_client)
    payload = _chat_payload(conversation_id, session_id, "enforce-authority")
    payload["history"] = [{
        "role": "assistant",
        "content": "Browser history must not be authoritative.",
    }]
    response = memory_client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200, response.text
    assert captured["history"] == []
    assert response.json()["memory"]["appliedToPrompt"] is True


def test_cross_agent_projection_budget_fails_before_model_call(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    calls = 0

    async def should_not_run(_payload, _http_request):
        nonlocal calls
        calls += 1
        return {"response": "unexpected"}

    monkeypatch.setattr(server, "agent_chat", should_not_run)
    conversation_id, session_id = _new_sage_conversation(memory_client)
    payload = _chat_payload(conversation_id, session_id, "oversized-cross-agent")
    payload["cross_agent_context"] = "x" * 3000

    response = memory_client.post("/api/agent/chat", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"]["code"] == (
        "cross_agent_projection_budget_exceeded"
    )
    assert calls == 0


def test_context_manifest_is_persisted_before_answer_and_hides_payloads(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    conversation_id, session_id = _new_sage_conversation(memory_client)
    observed = {}

    async def inspect_envelope(_payload, _http_request):
        preparer = server._AGENT_MEMORY_ENVELOPE_PREPARER.get()
        assert preparer is not None
        observed["prompt"] = preparer({
            "providers": [
                {
                    "contextKey": "assembly.parts",
                    "origin": "browser",
                    "requestedBy": ["generate-process-map"],
                    "required": False,
                    "included": True,
                    "payload": {"selected_parts": ["browser-claim"]},
                },
                {
                    "contextKey": "process_map.state",
                    "origin": "server",
                    "requestedBy": ["generate-process-map"],
                    "required": True,
                    "included": True,
                    "payload": {"dirty": False, "selection": []},
                },
            ],
            "selectedSkills": ["generate-process-map"],
            "allowedTools": ["build_process_map_preview"],
            "restrictions": ["no_commit_without_approval"],
        })
        runtime = server._agent_memory_runtime()
        with sqlite3.connect(runtime.config.database_path) as connection:
            observed["manifestCountBeforeAnswer"] = connection.execute(
                "SELECT COUNT(*) FROM memory_context_manifests"
            ).fetchone()[0]
        return {"response": "Envelope inspected."}

    monkeypatch.setattr(server, "agent_chat", inspect_envelope)
    payload = _chat_payload(conversation_id, session_id, "envelope-turn-001")
    response = memory_client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200, response.text
    assert observed["manifestCountBeforeAnswer"] == 1
    assert "<trusted_current_state>" in observed["prompt"]
    assert "<untrusted_recent_turns>" in observed["prompt"]
    memory = response.json()["memory"]
    assert memory["contextProviderCount"] == 2
    assert memory["memoryEstimatedTokens"] > 0
    inspected = memory_client.get(
        "/api/admin/memory/context-manifests/"
        + memory["contextManifestId"]
    )
    assert inspected.status_code == 200, inspected.text
    manifest = inspected.json()["manifest"]
    providers = {row["contextKey"]: row for row in manifest["providers"]}
    assert providers["process_map.state"]["origin"] == "server"
    assert providers["assembly.parts"]["origin"] == "browser"
    assert providers["process_map.state"]["payloadSha256"]
    assert manifest["revisionBarrier"]["outcome"] == "matched"
    assert manifest["revisionBarrier"]["resultingRevisionVectorSha256"]
    assert "browser-claim" not in json.dumps(manifest)
    assert "selected_parts" not in json.dumps(manifest)


def test_revision_reconciliation_precedes_routing_and_is_audited(
    memory_client: TestClient,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    conversation_id, session_id = _new_sage_conversation(memory_client)
    runtime = server._agent_memory_runtime()
    principal = MemoryPrincipal("local", "local-user")
    scope_ids = {"productId": "tricycle", "mapId": "default"}
    scope_fingerprint = "scope-v1:" + server.memory_canonical_sha256(
        {"kind": "process_map", "ids": scope_ids}
    )
    revision_a = {
        "processMapRevision": "map-a",
        "productStructureRevision": "structure-a",
    }
    revision_b = {
        "processMapRevision": "map-b",
        "productStructureRevision": "structure-a",
    }
    session = runtime.repository.get_agent_session(principal, session_id)
    seeded_state = {
        "state_version": 2,
        "workflow_id": "process-map-generation",
        "version": "1.0.0",
        "status": "active",
        "stage": "build_complete_ghost_preview",
        "objective": "Build the approved Tricycle process-map proposal",
        "entities": {
            "process_map_id": "default",
            "process_node_ids": ["node-keep", "node-removed"],
        },
        "evidence_refs": ["process-map:default:node-removed"],
        "referents": {"last_process_node_ids": ["node-removed"]},
        "milestones": {
            "visualization_requested": True,
            "visualization_succeeded": True,
        },
        "last_execution_receipts": [{
            "receipt_id": "receipt:stale-preview",
            "tool_id": "build_process_map_preview",
            "status": "succeeded",
        }],
        "audit_receipts": [],
        "pending_clarification": None,
        "scope_fingerprint": scope_fingerprint,
        "revision_vector": revision_a,
        "revision_vector_sha256": server.revision_vector_sha256(revision_a),
        "invalidation_audit": [],
        "revision": 4,
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }
    runtime.repository.update_agent_session_state(
        principal,
        session_id,
        workflow_state=seeded_state,
        scope_fingerprint=scope_fingerprint,
        revision_vector=revision_a,
        expected_workflow_state_revision=session.workflow_state_revision,
    )

    trusted = server.TrustedTurnContext(
        asset_scope={
            "kind": "process_map",
            "ids": scope_ids,
            "expectedRevisionVector": revision_b,
        },
        scope_fingerprint=scope_fingerprint,
        revision_vector=revision_b,
        workflow_mode="process_map",
    )
    monkeypatch.setattr(
        server,
        "_memory_trusted_turn_context",
        lambda _request, _http_request: trusted,
    )
    monkeypatch.setattr(
        server,
        "_memory_reconciliation_context",
        lambda _request, _http_request: (
            {},
            {
                "process_map": ["default"],
                "process_node": ["node-keep"],
            },
        ),
    )
    observed = {}

    async def inspect_reconciled_state(payload, _http_request):
        state = payload.inspection_context["skill_workflow_state"]
        observed["state"] = copy.deepcopy(state)
        observed["sessionId"] = payload.session_id
        return {
            "response": "Used revision-reconciled state.",
            "tool_calls": [{
                "name": "build_process_map_preview",
                "args": {"semantic_plan": {"schemaVersion": "1.0"}},
            }],
        }

    monkeypatch.setattr(server, "agent_chat", inspect_reconciled_state)
    payload = _chat_payload(conversation_id, session_id, "revision-turn-001")
    payload["message"] = "Build the revised process-map preview."
    payload["inspection_context"] = {
        "skill_workflow_state": {
            "objective": "FORGED BROWSER WORKFLOW STATE"
        }
    }
    payload["request_context"]["asset_scope"] = {
        "kind": "process_map",
        "ids": scope_ids,
        "expectedRevisionVector": revision_b,
    }

    response = memory_client.post("/api/agent/chat", json=payload)

    assert response.status_code == 200, response.text
    assert observed["sessionId"].startswith("memory:turn-")
    assert observed["state"]["objective"] == seeded_state["objective"]
    assert observed["state"]["stage"] == "validate_semantics_and_evidence"
    assert observed["state"]["entities"]["process_node_ids"] == ["node-keep"]
    assert observed["state"]["referents"] == {}
    assert observed["state"]["evidence_refs"] == []
    assert observed["state"]["last_execution_receipts"] == []
    assert observed["state"]["audit_receipts"][0]["receipt_id"] == (
        "receipt:stale-preview"
    )

    body = response.json()
    memory = body["memory"]
    assert memory["reconciliationOutcome"] == "same_scope_revision_advanced"
    assert memory["reconciliation"]["changedDependencies"] == [
        "processMapRevision"
    ]
    assert body["tool_calls"][0]["args"]["authorized_base_revision"] == (
        "map-b"
    )
    inspected = memory_client.get(
        "/api/admin/memory/context-manifests/" + memory["contextManifestId"]
    )
    manifest = inspected.json()["manifest"]
    assert manifest["reconciliation"] == memory["reconciliation"]
    assert any(
        row == {
            "item": "approvalToken",
            "dimension": "mapOrLayoutRevision",
            "action": "invalidate",
        }
        for row in manifest["reconciliation"]["actions"]
    )
