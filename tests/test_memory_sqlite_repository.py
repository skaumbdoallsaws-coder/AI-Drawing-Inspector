from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_inspector.memory import (
    MemoryConflictError,
    MemoryPrincipal,
    SqliteMemoryRepository,
    backup_sqlite_database,
    canonical_json,
    canonical_sha256,
    restore_sqlite_database,
    run_retention_cleanup,
    sqlite_quick_check,
)
from ai_inspector.memory.sqlite_repository import (
    DEFAULT_MIGRATIONS,
    SqliteMigration,
)
from ai_inspector.memory.repository import MemoryMigrationError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "memory"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _request_raw() -> dict:
    fixture = json.loads(
        (FIXTURES / "request-hash-v1-cases.json").read_text(encoding="ascii")
    )
    return fixture["baseRaw"]


def _seed(repository: SqliteMemoryRepository, principal: MemoryPrincipal):
    conversation = repository.create_conversation(
        principal,
        title="Tricycle process map",
        metadata={"workflow": "process_map"},
    )
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="sage",
        scope_fingerprint="scope-v1:test",
        revision_vector={"processMapRevision": "map-rev-a"},
    )
    return conversation, session


def _start(
    repository: SqliteMemoryRepository,
    principal: MemoryPrincipal,
    conversation_id: str,
    session_id: str,
    client_turn_id: str,
    request: dict | None = None,
):
    return repository.start_turn(
        principal,
        conversation_id,
        session_id,
        client_turn_id=client_turn_id,
        request_identity=request or _request_raw(),
        user_message={"role": "user", "content": "Build the map"},
        scope_fingerprint="scope-v1:test",
        source_revision_vector={"processMapRevision": "map-rev-a"},
    )


def test_repository_enables_required_sqlite_safety_settings(tmp_path: Path) -> None:
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3", busy_timeout_ms=4321)
    health = repository.health()
    assert health.healthy is True
    assert health.schema_version == health.latest_schema_version == 2
    assert health.journal_mode.lower() == "wal"
    assert health.foreign_keys is True
    assert health.busy_timeout_ms == 4321
    assert health.quick_check == "ok"
    repository.close()


def test_committed_records_survive_restart_and_round_trip_canonical_json(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a", ("operator",))
    repository = SqliteMemoryRepository(database)
    conversation, session = _seed(repository, principal)
    started = _start(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        "client-1",
    )
    assert started.disposition == "created"
    assert started.turn.sequence == 1

    manifest = repository.create_context_manifest(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        started.turn.turn_id,
        schema_version=1,
        scope_fingerprint="scope-v1:test",
        revision_vector_sha256=SHA_A,
        memory_envelope_sha256=SHA_B,
        manifest={"providers": [], "schemaVersion": "sage-context-manifest-1.0"},
    )
    manifest = repository.update_context_manifest(
        principal,
        manifest.context_manifest_id,
        manifest={
            "providers": [],
            "schemaVersion": "sage-context-manifest-1.0",
            "revisionBarrier": {"outcome": "matched"},
        },
        expected_memory_envelope_sha256=SHA_B,
    )
    assert manifest.manifest["revisionBarrier"]["outcome"] == "matched"
    committed = repository.commit_turn(
        principal,
        started.turn.turn_id,
        assistant_result={"content": "Preview ready", "kind": "answer"},
        tool_receipts=[{"tool": "build_process_map_preview", "ok": True}],
        resulting_revision_vector={"processMapRevision": "map-rev-a"},
        revision_barrier={"classification": "preview", "outcome": "matched"},
        memory_envelope_sha256=SHA_B,
        context_manifest_id=manifest.context_manifest_id,
    )
    summary = repository.create_summary(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        through_turn_sequence=1,
        source_turn_sha256=canonical_sha256([committed.request_sha256]),
        summary={"schemaVersion": "sage-continuity-summary-1.0", "warnings": []},
    )
    assert summary.summary_revision == 1
    repository.close()

    reopened = SqliteMemoryRepository(database)
    restored = reopened.get_turn(principal, started.turn.turn_id)
    assert restored.status == "committed"
    assert restored.assistant_result == {"content": "Preview ready", "kind": "answer"}
    assert restored.context_manifest_id == manifest.context_manifest_id
    assert reopened.get_current_summary(principal, session.agent_session_id) == summary
    assert reopened.get_context_manifest(principal, manifest.context_manifest_id) == manifest
    assert reopened.get_conversation(principal, conversation.conversation_id).last_turn_sequence == 1

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT assistant_result_json FROM memory_turns WHERE turn_id = ?",
            (started.turn.turn_id,),
        ).fetchone()[0]
    assert stored == '{"content":"Preview ready","kind":"answer"}'
    reopened.close()


def test_duplicate_client_turn_ids_are_deterministic(tmp_path: Path) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    conversation, session = _seed(repository, principal)
    first = _start(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        "client-stable",
    )
    retry = _start(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        "client-stable",
    )
    assert retry.disposition == "existing_pending"
    assert retry.turn.turn_id == first.turn.turn_id
    assert repository.get_conversation(
        principal, conversation.conversation_id
    ).last_turn_sequence == 1

    changed = copy.deepcopy(_request_raw())
    changed["message"] = "A different request"
    with pytest.raises(MemoryConflictError) as error:
        _start(
            repository,
            principal,
            conversation.conversation_id,
            session.agent_session_id,
            "client-stable",
            changed,
        )
    assert error.value.code == "client_turn_id_reused"

    committed = repository.commit_turn(
        principal,
        first.turn.turn_id,
        assistant_result={"content": "done"},
        tool_receipts=[],
        resulting_revision_vector={},
        revision_barrier={"classification": "read_only", "outcome": "matched"},
        memory_envelope_sha256=SHA_A,
    )
    committed_retry = _start(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        "client-stable",
    )
    assert committed_retry.disposition == "existing_committed"
    assert committed_retry.turn == committed


def test_concurrent_turns_allocate_unique_monotonic_sequences(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(database, busy_timeout_ms=10000)
    conversation, session = _seed(repository, principal)

    def create(index: int) -> tuple[int, str]:
        worker = SqliteMemoryRepository(database, busy_timeout_ms=10000)
        try:
            result = _start(
                worker,
                principal,
                conversation.conversation_id,
                session.agent_session_id,
                f"client-{index}",
            )
            return result.turn.sequence, result.turn.turn_id
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(create, range(12)))

    sequences = sorted(sequence for sequence, _ in results)
    assert sequences == list(range(1, 13))
    assert len({turn_id for _, turn_id in results}) == 12
    assert [turn.sequence for turn in repository.list_turns(
        principal, conversation.conversation_id
    )] == list(range(1, 13))
    repository.close()


def test_workflow_state_update_uses_compare_and_set(tmp_path: Path) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    _, session = _seed(repository, principal)
    updated = repository.update_agent_session_state(
        principal,
        session.agent_session_id,
        workflow_state={"state_version": 2, "stage": "planning"},
        scope_fingerprint="scope-v1:test",
        revision_vector={"processMapRevision": "map-rev-b"},
        expected_workflow_state_revision=0,
    )
    assert updated.workflow_state_revision == 1
    assert updated.workflow_state == {"stage": "planning", "state_version": 2}
    with pytest.raises(MemoryConflictError) as error:
        repository.update_agent_session_state(
            principal,
            session.agent_session_id,
            workflow_state={"state_version": 2, "stage": "preview"},
            scope_fingerprint="scope-v1:test",
            revision_vector={"processMapRevision": "map-rev-c"},
            expected_workflow_state_revision=0,
        )
    assert error.value.code == "workflow_state_revision_conflict"


def test_retention_cleanup_is_repeatable_and_cascades(tmp_path: Path) -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(
        tmp_path / "memory.sqlite3", now_factory=lambda: now
    )
    conversation = repository.create_conversation(
        principal,
        title="Expired",
        retention_until=now - timedelta(seconds=1),
    )
    session = repository.create_agent_session(
        principal, conversation.conversation_id, agent_type="sage"
    )
    turn = _start(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        "client-expired",
    ).turn
    repository.create_context_manifest(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        turn.turn_id,
        schema_version=1,
        scope_fingerprint=None,
        revision_vector_sha256=SHA_A,
        memory_envelope_sha256=SHA_B,
        manifest={},
    )
    repository.commit_turn(
        principal,
        turn.turn_id,
        assistant_result={"response": "Committed before summarization."},
        tool_receipts=[],
        resulting_revision_vector={},
        revision_barrier={"classification": "read_only", "outcome": "matched"},
        memory_envelope_sha256=SHA_A,
    )
    repository.create_summary(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        through_turn_sequence=1,
        source_turn_sha256=SHA_A,
        summary={},
    )
    result = repository.purge_expired(principal, before=now)
    assert result.conversation_count == 1
    assert result.agent_session_count == 1
    assert result.turn_count == 1
    assert result.summary_count == 1
    assert result.context_manifest_count == 1
    assert repository.purge_expired(principal, before=now).conversation_count == 0


def test_bounded_retention_cleanup_processes_all_batches_and_stays_tenant_scoped(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    repository = SqliteMemoryRepository(
        tmp_path / "memory.sqlite3", now_factory=lambda: now
    )
    principal = MemoryPrincipal("tenant-a", "user-a")
    other = MemoryPrincipal("tenant-b", "user-b")
    for index in range(5):
        repository.create_conversation(
            principal,
            title=f"Expired {index}",
            retention_until=now - timedelta(seconds=1),
        )
    retained = repository.create_conversation(
        other,
        title="Other tenant",
        retention_until=now - timedelta(seconds=1),
    )

    result = run_retention_cleanup(
        repository,
        principal,
        before=now,
        batch_size=2,
        maximum_batches=10,
    )

    assert result["batches"] == 3
    assert result["deleted"]["conversationCount"] == 5
    assert result["maximumBatchesReached"] is False
    assert run_retention_cleanup(
        repository,
        principal,
        before=now,
        batch_size=2,
    )["deleted"]["conversationCount"] == 0
    assert repository.get_conversation(other, retained.conversation_id).title == (
        "Other tenant"
    )


def test_online_backup_is_integrity_checked_and_does_not_modify_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "memory.sqlite3"
    destination = tmp_path / "backups" / "memory-backup.sqlite3"
    repository = SqliteMemoryRepository(source)
    principal = MemoryPrincipal("tenant-a", "user-a")
    conversation, _session = _seed(repository, principal)
    source_before = source.read_bytes()

    receipt = backup_sqlite_database(source, destination)

    assert receipt["destination"] == str(destination.resolve())
    assert receipt["quickCheck"] == "ok"
    assert receipt["bytes"] == destination.stat().st_size
    assert len(receipt["sha256"]) == 64
    assert sqlite_quick_check(destination) == "ok"
    assert source.read_bytes() == source_before
    restored = SqliteMemoryRepository(destination)
    assert restored.get_conversation(principal, conversation.conversation_id).title == (
        conversation.title
    )
    restored.close()

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(Exception, match="integrity check failed"):
        sqlite_quick_check(corrupt)


def test_restore_is_integrity_checked_and_preserves_pre_restore_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    backup = tmp_path / "memory-backup.sqlite3"
    rollback = tmp_path / "memory-pre-restore.sqlite3"
    repository = SqliteMemoryRepository(database)
    principal = MemoryPrincipal("tenant-a", "user-a")
    conversation, _session = _seed(repository, principal)
    backup_sqlite_database(database, backup)
    repository.update_conversation(
        principal,
        conversation.conversation_id,
        title="Changed after backup",
    )
    repository.close()

    receipt = restore_sqlite_database(
        backup,
        database,
        pre_restore_backup=rollback,
    )

    assert receipt["quickCheck"] == "ok"
    assert receipt["preRestoreBackup"] == str(rollback.resolve())
    restored = SqliteMemoryRepository(database)
    assert restored.get_conversation(
        principal, conversation.conversation_id
    ).title == conversation.title
    restored.close()
    prior = SqliteMemoryRepository(rollback)
    assert prior.get_conversation(
        principal, conversation.conversation_id
    ).title == "Changed after backup"
    prior.close()


def test_restore_removes_stale_destination_wal_and_shm_sidecars(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    backup = tmp_path / "memory-backup.sqlite3"
    repository = SqliteMemoryRepository(database)
    principal = MemoryPrincipal("tenant-a", "user-a")
    conversation, _session = _seed(repository, principal)
    backup_sqlite_database(database, backup)
    repository.close()

    wal = Path(str(database) + "-wal")
    shm = Path(str(database) + "-shm")
    wal.write_bytes(b"stale-wal-frames")
    shm.write_bytes(b"stale-shared-memory")

    restore_sqlite_database(backup, database)

    assert not wal.exists()
    assert not shm.exists()
    restored = SqliteMemoryRepository(database)
    assert restored.get_conversation(
        principal, conversation.conversation_id
    ).title == conversation.title
    restored.close()


def test_persisted_turns_redact_secrets_without_collapsing_request_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    repository = SqliteMemoryRepository(database)
    principal = MemoryPrincipal("tenant-a", "user-a")
    conversation, session = _seed(repository, principal)
    secret_a = "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_b = "sk-ant-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    request = _request_raw()
    request["message"] = f"Use api_key={secret_a} for this request."
    request["actionParameters"] = {
        "authorization": f"Bearer {secret_a}",
    }

    first = repository.start_turn(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        client_turn_id="secret-turn",
        request_identity=request,
        user_message={
            "role": "user",
            "content": f"Authorization: Bearer {secret_a}",
        },
    )
    retry = repository.start_turn(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        client_turn_id="secret-turn",
        request_identity=request,
        user_message={
            "role": "user",
            "content": f"Authorization: Bearer {secret_a}",
        },
    )
    assert retry.disposition == "existing_pending"
    assert retry.turn.turn_id == first.turn.turn_id
    assert secret_a not in canonical_json(first.turn.request_identity)
    assert secret_a not in canonical_json(first.turn.user_message)

    changed = copy.deepcopy(request)
    changed["message"] = f"Use api_key={secret_b} for this request."
    changed["actionParameters"] = {
        "authorization": f"Bearer {secret_b}",
    }
    with pytest.raises(MemoryConflictError) as error:
        repository.start_turn(
            principal,
            conversation.conversation_id,
            session.agent_session_id,
            client_turn_id="secret-turn",
            request_identity=changed,
            user_message={"role": "user", "content": secret_b},
        )
    assert error.value.code == "client_turn_id_reused"

    committed = repository.commit_turn(
        principal,
        first.turn.turn_id,
        assistant_result={
            "response": f"Authorization: Bearer {secret_a}",
        },
        tool_receipts=[{"apiKey": secret_a, "status": "not_executed"}],
        resulting_revision_vector={},
        revision_barrier={"classification": "read_only", "outcome": "matched"},
        memory_envelope_sha256=SHA_A,
    )
    summary = repository.create_summary(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        through_turn_sequence=1,
        source_turn_sha256=SHA_A,
        summary={
            "objective": {"text": f"password={secret_a}"},
            "warnings": [],
        },
    )
    assert secret_a not in canonical_json(committed.assistant_result)
    assert secret_a not in canonical_json(committed.tool_receipts)
    assert secret_a not in canonical_json(summary.summary)
    repository.close()

    persisted = database.read_bytes()
    wal = database.with_name(database.name + "-wal")
    if wal.exists():
        persisted += wal.read_bytes()
    assert secret_a.encode("ascii") not in persisted
    assert secret_b.encode("ascii") not in persisted


def test_failed_migration_rolls_back_and_prior_schema_reopens(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite3"
    repository = SqliteMemoryRepository(database)
    repository.close()
    failing = SqliteMigration(
        version=3,
        statements=(
            "CREATE TABLE migration_should_rollback (id INTEGER PRIMARY KEY)",
            "THIS IS NOT VALID SQL",
        ),
    )
    with pytest.raises(MemoryMigrationError):
        SqliteMemoryRepository(database, migrations=(*DEFAULT_MIGRATIONS, failing))

    reopened = SqliteMemoryRepository(database)
    assert reopened.health().schema_version == 2
    with sqlite3.connect(database) as connection:
        marker = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'migration_should_rollback'
            """
        ).fetchone()
    assert marker is None
    reopened.close()
