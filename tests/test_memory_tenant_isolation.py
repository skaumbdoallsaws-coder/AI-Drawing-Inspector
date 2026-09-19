from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_inspector.memory import (
    MemoryNotFoundError,
    MemoryPrincipal,
    SqliteMemoryRepository,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "memory" / "request-hash-v1-cases.json"
SHA = "a" * 64


def _request() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))["baseRaw"]


def _create_owned_graph(
    repository: SqliteMemoryRepository,
    principal: MemoryPrincipal,
    title: str,
):
    conversation = repository.create_conversation(principal, title=title)
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="sage",
        revision_vector={},
    )
    turn = repository.start_turn(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        client_turn_id="same-client-label",
        request_identity=_request(),
        user_message={"role": "user", "content": "same content"},
    ).turn
    manifest = repository.create_context_manifest(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        turn.turn_id,
        schema_version=1,
        scope_fingerprint=None,
        revision_vector_sha256=SHA,
        memory_envelope_sha256=SHA,
        manifest={},
    )
    return conversation, session, turn, manifest


def test_ids_do_not_authorize_cross_tenant_or_cross_user_reads(tmp_path: Path) -> None:
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    owner = MemoryPrincipal("tenant-a", "user-a")
    other_tenant = MemoryPrincipal("tenant-b", "user-a")
    other_user = MemoryPrincipal("tenant-a", "user-b")
    conversation, session, turn, manifest = _create_owned_graph(
        repository, owner, "Same visible title"
    )

    for intruder in (other_tenant, other_user):
        with pytest.raises(MemoryNotFoundError):
            repository.get_conversation(intruder, conversation.conversation_id)
        with pytest.raises(MemoryNotFoundError):
            repository.get_agent_session(intruder, session.agent_session_id)
        with pytest.raises(MemoryNotFoundError):
            repository.get_turn(intruder, turn.turn_id)
        with pytest.raises(MemoryNotFoundError):
            repository.get_context_manifest(intruder, manifest.context_manifest_id)
        assert repository.list_conversations(intruder) == ()


def test_same_labels_and_client_ids_are_isolated_by_tenant(tmp_path: Path) -> None:
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    tenant_a = MemoryPrincipal("tenant-a", "same-user")
    tenant_b = MemoryPrincipal("tenant-b", "same-user")
    graph_a = _create_owned_graph(repository, tenant_a, "Shared label")
    graph_b = _create_owned_graph(repository, tenant_b, "Shared label")

    assert graph_a[0].conversation_id != graph_b[0].conversation_id
    assert repository.list_conversations(tenant_a)[0].title == "Shared label"
    assert repository.list_conversations(tenant_b)[0].title == "Shared label"

    repository.soft_delete_conversation(tenant_a, graph_a[0].conversation_id)
    cleanup = repository.purge_expired(
        tenant_a, before=datetime(2026, 8, 6, 23, 59, tzinfo=timezone.utc)
    )
    assert cleanup.conversation_count == 1
    assert repository.get_conversation(tenant_b, graph_b[0].conversation_id).status == "active"

