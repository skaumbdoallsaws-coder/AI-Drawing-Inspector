from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

import server
from ai_inspector.memory import (
    MemoryPrincipal,
    SqliteMemoryRepository,
    TrustedTurnContext,
    TurnLifecycleService,
    build_request_identity_v1,
)


ROOT = Path(__file__).resolve().parents[1]


def _context() -> TrustedTurnContext:
    revision = {"processMapRevision": "a" * 64}
    return TrustedTurnContext(
        asset_scope={
            "kind": "process_map",
            "ids": {"productId": "pilot", "mapId": "default"},
            "expectedRevisionVector": revision,
        },
        scope_fingerprint="scope-v1:" + "1" * 64,
        revision_vector=revision,
        workflow_mode="process_map",
    )


def _identity(message: str) -> dict:
    context = _context()
    identity, _digest = build_request_identity_v1(
        message=message,
        agent_type="deviation-analyst",
        trusted_context=context,
        request_context={
            "asset_scope": context.asset_scope,
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
    return identity


def test_provider_switch_between_turns_survives_repository_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    repository = SqliteMemoryRepository(database)
    principal = MemoryPrincipal("pilot-tenant", "pilot-user")
    conversation = repository.create_conversation(
        principal, title="Provider switch"
    )
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="deviation-analyst",
        scope_fingerprint=_context().scope_fingerprint,
        revision_vector=_context().revision_vector,
    )
    service = TurnLifecycleService(repository, mode="enforce")

    async def execute_turn(index: int, provider: str, model: str):
        message = f"Provider switch turn {index}."

        async def execute():
            return {"response": f"Committed through {provider}."}

        return await service.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id=f"provider-switch-{index}",
            request_identity=_identity(message),
            user_message={"role": "user", "content": message},
            trusted_context=_context(),
            classification="read_only",
            execute=execute,
            resolve_current_context=_context,
            model_metadata={"provider": provider, "model": model},
        )

    asyncio.run(execute_turn(1, "anthropic", "claude-sonnet"))
    asyncio.run(execute_turn(2, "openai", "gpt-adaptive"))
    repository.close()

    reopened = SqliteMemoryRepository(database)
    turns = reopened.list_turns(
        principal, conversation.conversation_id, limit=10
    )
    assert [turn.model_metadata["provider"] for turn in turns] == [
        "anthropic",
        "openai",
    ]
    assert [turn.status for turn in turns] == ["committed", "committed"]
    assert all(turn.context_manifest_id for turn in turns)
    assert reopened.get_conversation(
        principal, conversation.conversation_id
    ).last_turn_sequence == 2
    reopened.close()


def test_off_mode_rollback_leaves_memory_and_engineering_assets_byte_exact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "memory.sqlite3"
    repository = SqliteMemoryRepository(database)
    principal = MemoryPrincipal("local", "local-user")
    repository.create_conversation(principal, title="Preserved rollback data")
    repository.close()
    database_before = database.read_bytes()

    engineering_assets = [
        ROOT / "generated" / "training" / "facility-layout"
        / "facility_layout.json",
        ROOT / "generated" / "training" / "racing-bike"
        / "racing_bike_process_map_working_draft.json",
    ]
    asset_hashes = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in engineering_assets
    }

    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_DB_PATH", str(database))
    server._reset_agent_memory_runtime_for_tests()

    async def legacy_answer(_payload, _http_request):
        return {"response": "Legacy rollback path."}

    monkeypatch.setattr(server, "agent_chat", legacy_answer)
    try:
        response = TestClient(server.app).post(
            "/api/agent/chat",
            json={
                "message": "Read the current context.",
                "history": [],
                "inspection_context": {},
                "agent_type": "deviation-analyst",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"response": "Legacy rollback path."}
        assert server._AGENT_MEMORY_RUNTIME is None
        assert database.read_bytes() == database_before
        assert {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in engineering_assets
        } == asset_hashes
    finally:
        server._reset_agent_memory_runtime_for_tests()
