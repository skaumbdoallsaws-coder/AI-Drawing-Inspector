"""SQLite implementation of the server-authoritative memory repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple

from .ids import is_memory_id, new_memory_id
from .models import (
    AgentSessionRecord,
    ContextManifestRecord,
    ConversationRecord,
    MemoryPrincipal,
    RepositoryHealth,
    RetentionResult,
    StartTurnResult,
    SummaryRecord,
    SummaryJobRecord,
    TurnRecord,
    canonical_json,
    canonical_sha256,
    utc_timestamp,
)
from .policy import request_identity_sha256_v1
from .redaction import redact_for_persistence, redact_text
from .repository import (
    MemoryConflictError,
    MemoryMigrationError,
    MemoryNotFoundError,
    MemoryRepository,
    MemoryRepositoryError,
    MemoryValidationError,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONVERSATION_STATUSES = frozenset({"active", "archived", "deleted"})
_SESSION_STATUSES = frozenset({"active", "completed", "abandoned"})
_TURN_STATUSES = frozenset({"pending", "committed", "failed", "cancelled"})


@dataclass(frozen=True)
class SqliteMigration:
    version: int
    statements: Tuple[str, ...]

    @property
    def sha256(self) -> str:
        payload = "\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL,
    sha256 TEXT NOT NULL
)
"""


MIGRATION_1 = SqliteMigration(
    version=1,
    statements=(
        """
        CREATE TABLE memory_conversations (
            conversation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'deleted')),
            schema_version INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            last_turn_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_turn_sequence >= 0),
            retention_until_utc TEXT,
            metadata_json TEXT NOT NULL,
            UNIQUE (conversation_id, tenant_id)
        )
        """,
        """
        CREATE INDEX memory_conversations_owner_updated_idx
        ON memory_conversations (tenant_id, user_id, updated_at_utc DESC)
        """,
        """
        CREATE INDEX memory_conversations_retention_idx
        ON memory_conversations (tenant_id, status, retention_until_utc)
        """,
        """
        CREATE TABLE memory_agent_sessions (
            agent_session_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'abandoned')),
            scope_fingerprint TEXT,
            revision_vector_json TEXT NOT NULL,
            workflow_state_json TEXT,
            workflow_state_revision INTEGER NOT NULL DEFAULT 0
                CHECK (workflow_state_revision >= 0),
            summary_revision INTEGER NOT NULL DEFAULT 0 CHECK (summary_revision >= 0),
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            expires_at_utc TEXT,
            UNIQUE (tenant_id, conversation_id, agent_type, agent_session_id),
            UNIQUE (agent_session_id, conversation_id, tenant_id),
            FOREIGN KEY (conversation_id, tenant_id)
                REFERENCES memory_conversations (conversation_id, tenant_id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX memory_agent_sessions_conversation_idx
        ON memory_agent_sessions (tenant_id, conversation_id, updated_at_utc DESC)
        """,
        """
        CREATE TABLE memory_turns (
            turn_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            agent_session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            client_turn_id TEXT NOT NULL,
            request_hash_version INTEGER NOT NULL,
            request_identity_json TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'committed', 'failed', 'cancelled')),
            user_message_json TEXT NOT NULL,
            assistant_result_json TEXT,
            tool_receipts_json TEXT NOT NULL,
            route_metadata_json TEXT NOT NULL,
            model_metadata_json TEXT NOT NULL,
            scope_fingerprint TEXT,
            source_revision_vector_json TEXT NOT NULL,
            resulting_revision_vector_json TEXT,
            revision_barrier_json TEXT NOT NULL,
            memory_envelope_sha256 TEXT,
            context_manifest_id TEXT,
            error_code TEXT,
            created_at_utc TEXT NOT NULL,
            committed_at_utc TEXT,
            UNIQUE (tenant_id, conversation_id, agent_session_id, client_turn_id),
            UNIQUE (tenant_id, conversation_id, sequence),
            UNIQUE (turn_id, agent_session_id, conversation_id, tenant_id),
            FOREIGN KEY (conversation_id, tenant_id)
                REFERENCES memory_conversations (conversation_id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (agent_session_id, conversation_id, tenant_id)
                REFERENCES memory_agent_sessions (
                    agent_session_id,
                    conversation_id,
                    tenant_id
                ) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX memory_turns_session_sequence_idx
        ON memory_turns (tenant_id, agent_session_id, sequence)
        """,
        """
        CREATE TABLE memory_summaries (
            summary_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            agent_session_id TEXT NOT NULL,
            summary_revision INTEGER NOT NULL CHECK (summary_revision > 0),
            through_turn_sequence INTEGER NOT NULL CHECK (through_turn_sequence >= 0),
            source_turn_sha256 TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            summary_sha256 TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('current', 'superseded', 'failed')),
            model_metadata_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            UNIQUE (tenant_id, agent_session_id, summary_revision),
            FOREIGN KEY (agent_session_id, conversation_id, tenant_id)
                REFERENCES memory_agent_sessions (
                    agent_session_id,
                    conversation_id,
                    tenant_id
                ) ON DELETE CASCADE
        )
        """,
        """
        CREATE UNIQUE INDEX memory_summaries_current_idx
        ON memory_summaries (tenant_id, agent_session_id)
        WHERE status = 'current'
        """,
        """
        CREATE TABLE memory_context_manifests (
            context_manifest_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            agent_session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            scope_fingerprint TEXT,
            revision_vector_sha256 TEXT NOT NULL,
            memory_envelope_sha256 TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            UNIQUE (context_manifest_id, tenant_id),
            FOREIGN KEY (turn_id, agent_session_id, conversation_id, tenant_id)
                REFERENCES memory_turns (
                    turn_id,
                    agent_session_id,
                    conversation_id,
                    tenant_id
                ) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX memory_context_manifests_turn_idx
        ON memory_context_manifests (tenant_id, turn_id, created_at_utc DESC)
        """,
    ),
)


MIGRATION_2 = SqliteMigration(
    version=2,
    statements=(
        """
        CREATE TABLE memory_summary_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            agent_session_id TEXT NOT NULL,
            target_through_turn_sequence INTEGER NOT NULL
                CHECK (target_through_turn_sequence > 0),
            source_turn_sha256 TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            lease_until_utc TEXT,
            last_error_code TEXT,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            UNIQUE (
                tenant_id,
                agent_session_id,
                target_through_turn_sequence,
                source_turn_sha256
            ),
            FOREIGN KEY (agent_session_id, conversation_id, tenant_id)
                REFERENCES memory_agent_sessions (
                    agent_session_id,
                    conversation_id,
                    tenant_id
                ) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX memory_summary_jobs_pending_idx
        ON memory_summary_jobs (
            tenant_id,
            agent_session_id,
            status,
            target_through_turn_sequence
        )
        """,
    ),
)


DEFAULT_MIGRATIONS = (MIGRATION_1, MIGRATION_2)


def default_memory_db_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    values = os.environ if environ is None else environ
    override = str(values.get("INSPECTORPRO_MEMORY_DB_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    local_app_data = str(values.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        raise MemoryValidationError(
            "LOCALAPPDATA is required when INSPECTORPRO_MEMORY_DB_PATH is unset"
        )
    return Path(local_app_data) / "InspectorPro" / "memory" / "inspectorpro-memory.sqlite3"


class SqliteMemoryRepository(MemoryRepository):
    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = 5000,
        migrations: Sequence[SqliteMigration] = DEFAULT_MIGRATIONS,
        now_factory: Optional[Callable[[], datetime]] = None,
        initialize: bool = True,
    ) -> None:
        self.database_path = Path(database_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self._migrations = tuple(migrations)
        self._validate_migrations()
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._initialize_lock = threading.RLock()
        self._initialized = False
        if initialize:
            self.initialize()

    @property
    def latest_schema_version(self) -> int:
        return self._migrations[-1].version if self._migrations else 0

    def initialize(self) -> None:
        with self._initialize_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._connection() as connection:
                    journal_mode = str(
                        connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    ).lower()
                    if journal_mode != "wal":
                        raise MemoryMigrationError("SQLite WAL mode could not be enabled")
                    connection.execute("PRAGMA synchronous=NORMAL")
                    connection.execute(_MIGRATION_TABLE_SQL)
                self._apply_migrations()
            except MemoryRepositoryError:
                raise
            except (OSError, sqlite3.DatabaseError) as exc:
                raise MemoryMigrationError(f"memory database initialization failed: {exc}") from exc
            self._initialized = True

    def close(self) -> None:
        with self._initialize_lock:
            if not self.database_path.exists():
                self._initialized = False
                return
            try:
                with self._connection() as connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self._initialized = False

    def create_conversation(
        self,
        principal: MemoryPrincipal,
        *,
        title: str,
        metadata: Optional[Mapping[str, Any]] = None,
        retention_until: Optional[datetime] = None,
    ) -> ConversationRecord:
        normalized_title = redact_text(
            _required_text("title", title, maximum=200)
        )
        metadata_value = _json_object(
            redact_for_persistence(metadata or {}), "metadata"
        )
        conversation_id = new_memory_id("conversation")
        now = self._now()
        retention = _optional_timestamp(retention_until)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO memory_conversations (
                    conversation_id, tenant_id, user_id, title, status,
                    schema_version, created_at_utc, updated_at_utc,
                    last_turn_sequence, retention_until_utc, metadata_json
                ) VALUES (?, ?, ?, ?, 'active', 1, ?, ?, 0, ?, ?)
                """,
                (
                    conversation_id,
                    principal.tenant_id,
                    principal.user_id,
                    normalized_title,
                    now,
                    now,
                    retention,
                    canonical_json(metadata_value),
                ),
            )
            row = self._conversation_row(connection, principal, conversation_id)
        return _conversation_record(row)

    def get_conversation(
        self, principal: MemoryPrincipal, conversation_id: str
    ) -> ConversationRecord:
        with self._read_connection() as connection:
            row = self._conversation_row(connection, principal, conversation_id)
        return _conversation_record(row)

    def list_conversations(
        self,
        principal: MemoryPrincipal,
        *,
        status: Optional[str] = "active",
        limit: int = 100,
    ) -> Sequence[ConversationRecord]:
        limit_value = _limit(limit)
        parameters: list[Any] = [principal.tenant_id, principal.user_id]
        status_clause = ""
        if status is not None:
            if status not in _CONVERSATION_STATUSES:
                raise MemoryValidationError("invalid conversation status")
            status_clause = " AND status = ?"
            parameters.append(status)
        parameters.append(limit_value)
        with self._read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memory_conversations
                WHERE tenant_id = ? AND user_id = ?{status_clause}
                ORDER BY updated_at_utc DESC, conversation_id ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return tuple(_conversation_record(row) for row in rows)

    def update_conversation(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        title: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        status: Optional[str] = None,
        retention_until: Optional[datetime] = None,
    ) -> ConversationRecord:
        if status is not None and status not in _CONVERSATION_STATUSES:
            raise MemoryValidationError("invalid conversation status")
        with self._transaction() as connection:
            current = self._conversation_row(connection, principal, conversation_id)
            next_title = (
                redact_text(_required_text("title", title, maximum=200))
                if title is not None
                else current["title"]
            )
            next_metadata = (
                canonical_json(_json_object(
                    redact_for_persistence(metadata), "metadata"
                ))
                if metadata is not None
                else current["metadata_json"]
            )
            next_retention = (
                _optional_timestamp(retention_until)
                if retention_until is not None
                else current["retention_until_utc"]
            )
            connection.execute(
                """
                UPDATE memory_conversations
                SET title = ?, metadata_json = ?, status = ?,
                    retention_until_utc = ?, updated_at_utc = ?
                WHERE conversation_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (
                    next_title,
                    next_metadata,
                    status or current["status"],
                    next_retention,
                    self._now(),
                    conversation_id,
                    principal.tenant_id,
                    principal.user_id,
                ),
            )
            row = self._conversation_row(connection, principal, conversation_id)
        return _conversation_record(row)

    def soft_delete_conversation(
        self, principal: MemoryPrincipal, conversation_id: str
    ) -> ConversationRecord:
        now = self._now()
        with self._transaction() as connection:
            self._conversation_row(connection, principal, conversation_id)
            connection.execute(
                """
                UPDATE memory_conversations
                SET status = 'deleted', retention_until_utc = ?, updated_at_utc = ?
                WHERE conversation_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (
                    now,
                    now,
                    conversation_id,
                    principal.tenant_id,
                    principal.user_id,
                ),
            )
            row = self._conversation_row(connection, principal, conversation_id)
        return _conversation_record(row)

    def set_conversation_retention(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        retention_until: datetime,
    ) -> ConversationRecord:
        retention = _optional_timestamp(retention_until)
        if retention is None:
            raise MemoryValidationError("retention deadline is required")
        with self._transaction() as connection:
            self._conversation_row(connection, principal, conversation_id)
            connection.execute(
                """
                UPDATE memory_conversations
                SET retention_until_utc = ?
                WHERE conversation_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (
                    retention,
                    conversation_id,
                    principal.tenant_id,
                    principal.user_id,
                ),
            )
            row = self._conversation_row(connection, principal, conversation_id)
        return _conversation_record(row)

    def create_agent_session(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        agent_type: str,
        scope_fingerprint: Optional[str] = None,
        revision_vector: Optional[Mapping[str, Any]] = None,
        workflow_state: Optional[Mapping[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> AgentSessionRecord:
        normalized_agent = _required_text("agent_type", agent_type, maximum=80).lower()
        revision_value = _json_object(revision_vector or {}, "revision_vector")
        workflow_value = (
            _json_object(
                redact_for_persistence(workflow_state), "workflow_state"
            )
            if workflow_state is not None
            else None
        )
        agent_session_id = new_memory_id("agent_session")
        now = self._now()
        with self._transaction() as connection:
            conversation = self._conversation_row(connection, principal, conversation_id)
            if conversation["status"] != "active":
                raise MemoryConflictError(
                    "conversation_not_active", "conversation is not active"
                )
            connection.execute(
                """
                INSERT INTO memory_agent_sessions (
                    agent_session_id, conversation_id, tenant_id, agent_type,
                    status, scope_fingerprint, revision_vector_json,
                    workflow_state_json, workflow_state_revision,
                    summary_revision, created_at_utc, updated_at_utc,
                    expires_at_utc
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    agent_session_id,
                    conversation_id,
                    principal.tenant_id,
                    normalized_agent,
                    _optional_text("scope_fingerprint", scope_fingerprint),
                    canonical_json(revision_value),
                    canonical_json(workflow_value) if workflow_value is not None else None,
                    now,
                    now,
                    _optional_timestamp(expires_at),
                ),
            )
            row = self._agent_session_row(connection, principal, agent_session_id)
        return _agent_session_record(row)

    def get_agent_session(
        self, principal: MemoryPrincipal, agent_session_id: str
    ) -> AgentSessionRecord:
        with self._read_connection() as connection:
            row = self._agent_session_row(connection, principal, agent_session_id)
        return _agent_session_record(row)

    def list_agent_sessions(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        limit: int = 100,
    ) -> Sequence[AgentSessionRecord]:
        with self._read_connection() as connection:
            self._conversation_row(connection, principal, conversation_id)
            rows = connection.execute(
                """
                SELECT s.*
                FROM memory_agent_sessions s
                JOIN memory_conversations c
                  ON c.conversation_id = s.conversation_id
                 AND c.tenant_id = s.tenant_id
                WHERE s.tenant_id = ? AND s.conversation_id = ? AND c.user_id = ?
                ORDER BY s.updated_at_utc DESC, s.agent_session_id ASC
                LIMIT ?
                """,
                (principal.tenant_id, conversation_id, principal.user_id, _limit(limit)),
            ).fetchall()
        return tuple(_agent_session_record(row) for row in rows)

    def update_agent_session_state(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        *,
        workflow_state: Optional[Mapping[str, Any]],
        scope_fingerprint: Optional[str],
        revision_vector: Mapping[str, Any],
        expected_workflow_state_revision: Optional[int] = None,
        expires_at: Optional[datetime] = None,
    ) -> AgentSessionRecord:
        workflow_value = (
            _json_object(
                redact_for_persistence(workflow_state), "workflow_state"
            )
            if workflow_state is not None
            else None
        )
        revision_value = _json_object(revision_vector, "revision_vector")
        with self._transaction() as connection:
            current = self._agent_session_row(connection, principal, agent_session_id)
            current_revision = int(current["workflow_state_revision"])
            if (
                expected_workflow_state_revision is not None
                and current_revision != int(expected_workflow_state_revision)
            ):
                raise MemoryConflictError(
                    "workflow_state_revision_conflict",
                    "workflow state revision conflict",
                )
            connection.execute(
                """
                UPDATE memory_agent_sessions
                SET workflow_state_json = ?, scope_fingerprint = ?,
                    revision_vector_json = ?, workflow_state_revision = ?,
                    updated_at_utc = ?, expires_at_utc = ?
                WHERE agent_session_id = ? AND tenant_id = ?
                """,
                (
                    canonical_json(workflow_value) if workflow_value is not None else None,
                    _optional_text("scope_fingerprint", scope_fingerprint),
                    canonical_json(revision_value),
                    current_revision + 1,
                    self._now(),
                    _optional_timestamp(expires_at),
                    agent_session_id,
                    principal.tenant_id,
                ),
            )
            row = self._agent_session_row(connection, principal, agent_session_id)
        return _agent_session_record(row)

    def set_agent_session_status(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        status: str,
    ) -> AgentSessionRecord:
        if status not in _SESSION_STATUSES:
            raise MemoryValidationError("invalid agent session status")
        with self._transaction() as connection:
            self._agent_session_row(connection, principal, agent_session_id)
            connection.execute(
                """
                UPDATE memory_agent_sessions
                SET status = ?, updated_at_utc = ?
                WHERE agent_session_id = ? AND tenant_id = ?
                """,
                (status, self._now(), agent_session_id, principal.tenant_id),
            )
            row = self._agent_session_row(connection, principal, agent_session_id)
        return _agent_session_record(row)

    def start_turn(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        *,
        client_turn_id: str,
        request_identity: Mapping[str, Any],
        user_message: Mapping[str, Any],
        scope_fingerprint: Optional[str] = None,
        source_revision_vector: Optional[Mapping[str, Any]] = None,
        route_metadata: Optional[Mapping[str, Any]] = None,
        model_metadata: Optional[Mapping[str, Any]] = None,
    ) -> StartTurnResult:
        client_id = _required_text("client_turn_id", client_turn_id, maximum=200)
        try:
            identity, request_sha256 = request_identity_sha256_v1(request_identity)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError(f"invalid request identity: {exc}") from exc
        identity = _json_object(
            redact_for_persistence(identity), "request_identity"
        )
        user_value = _json_object(
            redact_for_persistence(user_message), "user_message"
        )
        route_value = _json_object(
            redact_for_persistence(route_metadata or {}), "route_metadata"
        )
        model_value = _json_object(
            redact_for_persistence(model_metadata or {}), "model_metadata"
        )
        source_value = _json_object(
            source_revision_vector
            if source_revision_vector is not None
            else identity["assetScope"]["expectedRevisionVector"],
            "source_revision_vector",
        )
        identity_json = canonical_json(identity)
        now = self._now()

        with self._transaction() as connection:
            conversation = self._conversation_row(connection, principal, conversation_id)
            if conversation["status"] != "active":
                raise MemoryConflictError(
                    "conversation_not_active", "conversation is not active"
                )
            session = self._agent_session_row(connection, principal, agent_session_id)
            if session["conversation_id"] != conversation_id:
                raise MemoryNotFoundError("agent session not found")
            if session["status"] != "active":
                raise MemoryConflictError(
                    "agent_session_not_active", "agent session is not active"
                )

            existing = connection.execute(
                """
                SELECT * FROM memory_turns
                WHERE tenant_id = ? AND conversation_id = ?
                  AND agent_session_id = ? AND client_turn_id = ?
                """,
                (
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    client_id,
                ),
            ).fetchone()
            if existing is not None:
                if (
                    existing["request_sha256"] != request_sha256
                    or existing["request_identity_json"] != identity_json
                ):
                    raise MemoryConflictError(
                        "client_turn_id_reused",
                        "client turn ID was reused with a different request",
                    )
                return StartTurnResult(
                    disposition=f"existing_{existing['status']}",
                    turn=_turn_record(existing),
                )

            sequence = int(conversation["last_turn_sequence"]) + 1
            turn_id = new_memory_id("turn")
            connection.execute(
                """
                UPDATE memory_conversations
                SET last_turn_sequence = ?, updated_at_utc = ?
                WHERE conversation_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (
                    sequence,
                    now,
                    conversation_id,
                    principal.tenant_id,
                    principal.user_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO memory_turns (
                    turn_id, tenant_id, conversation_id, agent_session_id,
                    sequence, client_turn_id, request_hash_version,
                    request_identity_json, request_sha256, status,
                    user_message_json, assistant_result_json, tool_receipts_json,
                    route_metadata_json, model_metadata_json, scope_fingerprint,
                    source_revision_vector_json, resulting_revision_vector_json,
                    revision_barrier_json, memory_envelope_sha256,
                    context_manifest_id, error_code, created_at_utc, committed_at_utc
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 1, ?, ?, 'pending', ?, NULL, '[]',
                    ?, ?, ?, ?, NULL, '{}', NULL, NULL, NULL, ?, NULL
                )
                """,
                (
                    turn_id,
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    sequence,
                    client_id,
                    identity_json,
                    request_sha256,
                    canonical_json(user_value),
                    canonical_json(route_value),
                    canonical_json(model_value),
                    _optional_text("scope_fingerprint", scope_fingerprint),
                    canonical_json(source_value),
                    now,
                ),
            )
            row = self._turn_row(connection, principal, turn_id)
        return StartTurnResult(disposition="created", turn=_turn_record(row))

    def get_turn(self, principal: MemoryPrincipal, turn_id: str) -> TurnRecord:
        with self._read_connection() as connection:
            row = self._turn_row(connection, principal, turn_id)
        return _turn_record(row)

    def list_turns(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> Sequence[TurnRecord]:
        with self._read_connection() as connection:
            self._conversation_row(connection, principal, conversation_id)
            rows = connection.execute(
                """
                SELECT t.*
                FROM memory_turns t
                JOIN memory_conversations c
                  ON c.conversation_id = t.conversation_id
                 AND c.tenant_id = t.tenant_id
                WHERE t.tenant_id = ? AND t.conversation_id = ?
                  AND c.user_id = ? AND t.sequence > ?
                ORDER BY t.sequence ASC
                LIMIT ?
                """,
                (
                    principal.tenant_id,
                    conversation_id,
                    principal.user_id,
                    max(0, int(after_sequence)),
                    _limit(limit),
                ),
            ).fetchall()
        return tuple(_turn_record(row) for row in rows)

    def list_agent_session_turns(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        committed_only: bool = True,
    ) -> Sequence[TurnRecord]:
        with self._read_connection() as connection:
            self._agent_session_row(connection, principal, agent_session_id)
            status_clause = "AND t.status = 'committed'" if committed_only else ""
            rows = connection.execute(
                f"""
                SELECT t.*
                FROM memory_turns t
                JOIN memory_conversations c
                  ON c.conversation_id = t.conversation_id
                 AND c.tenant_id = t.tenant_id
                WHERE t.tenant_id = ? AND t.agent_session_id = ?
                  AND c.user_id = ? AND t.sequence > ?
                  {status_clause}
                ORDER BY t.sequence ASC
                LIMIT ?
                """,
                (
                    principal.tenant_id,
                    agent_session_id,
                    principal.user_id,
                    max(0, int(after_sequence)),
                    _limit(limit),
                ),
            ).fetchall()
        return tuple(_turn_record(row) for row in rows)

    def commit_turn(
        self,
        principal: MemoryPrincipal,
        turn_id: str,
        *,
        assistant_result: Mapping[str, Any],
        tool_receipts: Sequence[Any],
        resulting_revision_vector: Mapping[str, Any],
        revision_barrier: Mapping[str, Any],
        memory_envelope_sha256: str,
        context_manifest_id: Optional[str] = None,
        route_metadata: Optional[Mapping[str, Any]] = None,
        model_metadata: Optional[Mapping[str, Any]] = None,
    ) -> TurnRecord:
        assistant_value = _json_object(
            redact_for_persistence(assistant_result), "assistant_result"
        )
        receipts_value = _json_array(
            redact_for_persistence(list(tool_receipts)), "tool_receipts"
        )
        resulting_value = _json_object(
            resulting_revision_vector, "resulting_revision_vector"
        )
        barrier_value = _json_object(revision_barrier, "revision_barrier")
        envelope_hash = _sha256("memory_envelope_sha256", memory_envelope_sha256)
        route_value = (
            _json_object(
                redact_for_persistence(route_metadata), "route_metadata"
            )
            if route_metadata is not None
            else None
        )
        model_value = (
            _json_object(
                redact_for_persistence(model_metadata), "model_metadata"
            )
            if model_metadata is not None
            else None
        )
        with self._transaction() as connection:
            current = self._turn_row(connection, principal, turn_id)
            if current["status"] == "committed":
                return _turn_record(current)
            if current["status"] != "pending":
                raise MemoryConflictError("turn_not_pending", "turn is not pending")
            if context_manifest_id is not None:
                manifest = connection.execute(
                    """
                    SELECT context_manifest_id FROM memory_context_manifests
                    WHERE context_manifest_id = ? AND tenant_id = ? AND turn_id = ?
                    """,
                    (context_manifest_id, principal.tenant_id, turn_id),
                ).fetchone()
                if manifest is None:
                    raise MemoryNotFoundError("context manifest not found")
            committed_at = self._now()
            connection.execute(
                """
                UPDATE memory_turns
                SET status = 'committed', assistant_result_json = ?,
                    tool_receipts_json = ?, route_metadata_json = ?,
                    model_metadata_json = ?, resulting_revision_vector_json = ?,
                    revision_barrier_json = ?, memory_envelope_sha256 = ?,
                    context_manifest_id = ?, error_code = NULL,
                    committed_at_utc = ?
                WHERE turn_id = ? AND tenant_id = ?
                """,
                (
                    canonical_json(assistant_value),
                    canonical_json(receipts_value),
                    canonical_json(route_value)
                    if route_value is not None
                    else current["route_metadata_json"],
                    canonical_json(model_value)
                    if model_value is not None
                    else current["model_metadata_json"],
                    canonical_json(resulting_value),
                    canonical_json(barrier_value),
                    envelope_hash,
                    context_manifest_id,
                    committed_at,
                    turn_id,
                    principal.tenant_id,
                ),
            )
            connection.execute(
                """
                UPDATE memory_conversations
                SET updated_at_utc = ?
                WHERE conversation_id = ? AND tenant_id = ?
                """,
                (committed_at, current["conversation_id"], principal.tenant_id),
            )
            row = self._turn_row(connection, principal, turn_id)
        return _turn_record(row)

    def fail_turn(
        self,
        principal: MemoryPrincipal,
        turn_id: str,
        *,
        error_code: str,
        revision_barrier: Optional[Mapping[str, Any]] = None,
    ) -> TurnRecord:
        return self._finish_noncommitted_turn(
            principal,
            turn_id,
            status="failed",
            error_code=_required_text("error_code", error_code, maximum=160),
            revision_barrier=revision_barrier,
        )

    def cancel_turn(
        self, principal: MemoryPrincipal, turn_id: str
    ) -> TurnRecord:
        return self._finish_noncommitted_turn(
            principal,
            turn_id,
            status="cancelled",
            error_code="cancelled",
            revision_barrier=None,
        )

    def create_summary(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        *,
        through_turn_sequence: int,
        source_turn_sha256: str,
        summary: Mapping[str, Any],
        model_metadata: Optional[Mapping[str, Any]] = None,
        expected_summary_revision: Optional[int] = None,
    ) -> SummaryRecord:
        through = int(through_turn_sequence)
        if through < 0:
            raise MemoryValidationError("through_turn_sequence must not be negative")
        source_hash = _sha256("source_turn_sha256", source_turn_sha256)
        summary_value = _json_object(
            redact_for_persistence(summary), "summary"
        )
        model_value = _json_object(
            redact_for_persistence(model_metadata or {}), "model_metadata"
        )
        summary_hash = canonical_sha256(summary_value)
        summary_id = new_memory_id("summary")
        with self._transaction() as connection:
            conversation = self._conversation_row(connection, principal, conversation_id)
            session = self._agent_session_row(connection, principal, agent_session_id)
            if session["conversation_id"] != conversation_id:
                raise MemoryNotFoundError("agent session not found")
            target_turn = connection.execute(
                """
                SELECT turn_id FROM memory_turns
                WHERE tenant_id = ? AND conversation_id = ?
                  AND agent_session_id = ? AND sequence = ?
                  AND status = 'committed'
                """,
                (
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    through,
                ),
            ).fetchone()
            if through > 0 and target_turn is None:
                raise MemoryValidationError(
                    "summary must end on a committed turn in the agent session"
                )
            current_revision = int(session["summary_revision"])
            if (
                expected_summary_revision is not None
                and current_revision != int(expected_summary_revision)
            ):
                raise MemoryConflictError(
                    "summary_revision_conflict",
                    "summary revision changed before commit",
                )
            current_summary = connection.execute(
                """
                SELECT through_turn_sequence FROM memory_summaries
                WHERE tenant_id = ? AND agent_session_id = ? AND status = 'current'
                """,
                (principal.tenant_id, agent_session_id),
            ).fetchone()
            if (
                current_summary is not None
                and through < int(current_summary["through_turn_sequence"])
            ):
                raise MemoryConflictError(
                    "summary_range_regressed",
                    "summary cannot replace a newer covered turn range",
                )
            revision = current_revision + 1
            declared_revision = summary_value.get("summaryRevision")
            if declared_revision is not None and int(declared_revision) != revision:
                raise MemoryValidationError(
                    "summaryRevision does not match the repository revision"
                )
            declared_through = summary_value.get("throughTurnSequence")
            if declared_through is not None and int(declared_through) != through:
                raise MemoryValidationError(
                    "throughTurnSequence does not match the persisted range"
                )
            connection.execute(
                """
                UPDATE memory_summaries
                SET status = 'superseded'
                WHERE tenant_id = ? AND agent_session_id = ? AND status = 'current'
                """,
                (principal.tenant_id, agent_session_id),
            )
            created_at = self._now()
            connection.execute(
                """
                INSERT INTO memory_summaries (
                    summary_id, tenant_id, conversation_id, agent_session_id,
                    summary_revision, through_turn_sequence, source_turn_sha256,
                    summary_json, summary_sha256, status, model_metadata_json,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?)
                """,
                (
                    summary_id,
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    revision,
                    through,
                    source_hash,
                    canonical_json(summary_value),
                    summary_hash,
                    canonical_json(model_value),
                    created_at,
                ),
            )
            connection.execute(
                """
                UPDATE memory_agent_sessions
                SET summary_revision = ?, updated_at_utc = ?
                WHERE agent_session_id = ? AND tenant_id = ?
                """,
                (revision, created_at, agent_session_id, principal.tenant_id),
            )
            row = connection.execute(
                """
                SELECT * FROM memory_summaries
                WHERE summary_id = ? AND tenant_id = ?
                """,
                (summary_id, principal.tenant_id),
            ).fetchone()
        return _summary_record(row)

    def get_current_summary(
        self, principal: MemoryPrincipal, agent_session_id: str
    ) -> Optional[SummaryRecord]:
        with self._read_connection() as connection:
            self._agent_session_row(connection, principal, agent_session_id)
            row = connection.execute(
                """
                SELECT * FROM memory_summaries
                WHERE tenant_id = ? AND agent_session_id = ? AND status = 'current'
                """,
                (principal.tenant_id, agent_session_id),
            ).fetchone()
        return _summary_record(row) if row is not None else None

    def enqueue_summary_job(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        *,
        target_through_turn_sequence: int,
        source_turn_sha256: str,
    ) -> SummaryJobRecord:
        target = int(target_through_turn_sequence)
        if target < 1:
            raise MemoryValidationError(
                "target_through_turn_sequence must be positive"
            )
        source_hash = _sha256("source_turn_sha256", source_turn_sha256)
        with self._transaction() as connection:
            self._conversation_row(connection, principal, conversation_id)
            session = self._agent_session_row(
                connection, principal, agent_session_id
            )
            if session["conversation_id"] != conversation_id:
                raise MemoryNotFoundError("agent session not found")
            target_turn = connection.execute(
                """
                SELECT turn_id FROM memory_turns
                WHERE tenant_id = ? AND conversation_id = ?
                  AND agent_session_id = ? AND sequence = ?
                  AND status = 'committed'
                """,
                (
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    target,
                ),
            ).fetchone()
            if target_turn is None:
                raise MemoryValidationError(
                    "summary job must target a committed agent-session turn"
                )
            row = connection.execute(
                """
                SELECT * FROM memory_summary_jobs
                WHERE tenant_id = ? AND agent_session_id = ?
                  AND target_through_turn_sequence = ?
                  AND source_turn_sha256 = ?
                """,
                (
                    principal.tenant_id,
                    agent_session_id,
                    target,
                    source_hash,
                ),
            ).fetchone()
            now = self._now()
            if row is None:
                job_id = new_memory_id("summary_job")
                connection.execute(
                    """
                    INSERT INTO memory_summary_jobs (
                        job_id, tenant_id, conversation_id, agent_session_id,
                        target_through_turn_sequence, source_turn_sha256,
                        status, attempt_count, lease_until_utc,
                        last_error_code, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, ?, ?)
                    """,
                    (
                        job_id,
                        principal.tenant_id,
                        conversation_id,
                        agent_session_id,
                        target,
                        source_hash,
                        now,
                        now,
                    ),
                )
                row = self._summary_job_row(connection, principal, job_id)
            elif row["status"] == "failed":
                connection.execute(
                    """
                    UPDATE memory_summary_jobs
                    SET status = 'pending', lease_until_utc = NULL,
                        last_error_code = NULL, updated_at_utc = ?
                    WHERE job_id = ? AND tenant_id = ?
                    """,
                    (now, row["job_id"], principal.tenant_id),
                )
                row = self._summary_job_row(
                    connection, principal, row["job_id"]
                )
        return _summary_job_record(row)

    def get_pending_summary_job(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> Optional[SummaryJobRecord]:
        with self._read_connection() as connection:
            self._agent_session_row(connection, principal, agent_session_id)
            row = connection.execute(
                """
                SELECT j.* FROM memory_summary_jobs j
                JOIN memory_conversations c
                  ON c.conversation_id = j.conversation_id
                 AND c.tenant_id = j.tenant_id
                WHERE j.tenant_id = ? AND j.agent_session_id = ?
                  AND j.status IN ('pending', 'running') AND c.user_id = ?
                ORDER BY j.target_through_turn_sequence DESC, j.created_at_utc ASC
                LIMIT 1
                """,
                (principal.tenant_id, agent_session_id, principal.user_id),
            ).fetchone()
        return _summary_job_record(row) if row is not None else None

    def get_latest_summary_job(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> Optional[SummaryJobRecord]:
        with self._read_connection() as connection:
            self._agent_session_row(connection, principal, agent_session_id)
            row = connection.execute(
                """
                SELECT j.* FROM memory_summary_jobs j
                JOIN memory_conversations c
                  ON c.conversation_id = j.conversation_id
                 AND c.tenant_id = j.tenant_id
                WHERE j.tenant_id = ? AND j.agent_session_id = ?
                  AND c.user_id = ?
                ORDER BY j.target_through_turn_sequence DESC,
                         j.updated_at_utc DESC
                LIMIT 1
                """,
                (principal.tenant_id, agent_session_id, principal.user_id),
            ).fetchone()
        return _summary_job_record(row) if row is not None else None

    def claim_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
        *,
        lease_seconds: float,
    ) -> SummaryJobRecord:
        seconds = float(lease_seconds)
        if not 1.0 <= seconds <= 3600.0:
            raise MemoryValidationError("summary job lease must be 1-3600 seconds")
        with self._transaction() as connection:
            row = self._summary_job_row(connection, principal, job_id)
            now_dt = self._now_factory().astimezone(timezone.utc)
            now = utc_timestamp(now_dt)
            lease = row["lease_until_utc"]
            lease_active = (
                row["status"] == "running"
                and isinstance(lease, str)
                and lease > now
            )
            if lease_active:
                raise MemoryConflictError(
                    "summary_job_leased",
                    "summary job is already running",
                )
            if row["status"] not in {"pending", "running"}:
                raise MemoryConflictError(
                    "summary_job_not_pending",
                    "summary job is not available to claim",
                )
            lease_until = utc_timestamp(now_dt + timedelta(seconds=seconds))
            connection.execute(
                """
                UPDATE memory_summary_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    lease_until_utc = ?, last_error_code = NULL,
                    updated_at_utc = ?
                WHERE job_id = ? AND tenant_id = ?
                """,
                (lease_until, now, job_id, principal.tenant_id),
            )
            row = self._summary_job_row(connection, principal, job_id)
        return _summary_job_record(row)

    def complete_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
    ) -> SummaryJobRecord:
        return self._finish_summary_job(
            principal, job_id, status="succeeded", error_code=None
        )

    def fail_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
        *,
        error_code: str,
    ) -> SummaryJobRecord:
        return self._finish_summary_job(
            principal,
            job_id,
            status="failed",
            error_code=_required_text("error_code", error_code, maximum=160),
        )

    def create_context_manifest(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        turn_id: str,
        *,
        schema_version: int,
        scope_fingerprint: Optional[str],
        revision_vector_sha256: str,
        memory_envelope_sha256: str,
        manifest: Mapping[str, Any],
        context_manifest_id: Optional[str] = None,
    ) -> ContextManifestRecord:
        schema = int(schema_version)
        if schema < 1:
            raise MemoryValidationError("schema_version must be positive")
        revision_hash = _sha256("revision_vector_sha256", revision_vector_sha256)
        envelope_hash = _sha256("memory_envelope_sha256", memory_envelope_sha256)
        manifest_value = _json_object(manifest, "manifest")
        manifest_id = (
            str(context_manifest_id).strip()
            if context_manifest_id is not None
            else new_memory_id("context_manifest")
        )
        if not is_memory_id(manifest_id, "context_manifest"):
            raise MemoryValidationError("invalid context_manifest_id")
        with self._transaction() as connection:
            conversation = self._conversation_row(connection, principal, conversation_id)
            session = self._agent_session_row(connection, principal, agent_session_id)
            turn = self._turn_row(connection, principal, turn_id)
            if (
                session["conversation_id"] != conversation_id
                or turn["conversation_id"] != conversation_id
                or turn["agent_session_id"] != agent_session_id
            ):
                raise MemoryNotFoundError("turn scope not found")
            created_at = self._now()
            connection.execute(
                """
                INSERT INTO memory_context_manifests (
                    context_manifest_id, tenant_id, conversation_id,
                    agent_session_id, turn_id, schema_version,
                    scope_fingerprint, revision_vector_sha256,
                    memory_envelope_sha256, manifest_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest_id,
                    principal.tenant_id,
                    conversation_id,
                    agent_session_id,
                    turn_id,
                    schema,
                    _optional_text("scope_fingerprint", scope_fingerprint),
                    revision_hash,
                    envelope_hash,
                    canonical_json(manifest_value),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM memory_context_manifests
                WHERE context_manifest_id = ? AND tenant_id = ?
                """,
                (manifest_id, principal.tenant_id),
            ).fetchone()
        return _context_manifest_record(row)

    def update_context_manifest(
        self,
        principal: MemoryPrincipal,
        context_manifest_id: str,
        *,
        manifest: Mapping[str, Any],
        expected_memory_envelope_sha256: str,
    ) -> ContextManifestRecord:
        manifest_id = str(context_manifest_id or "").strip()
        if not is_memory_id(manifest_id, "context_manifest"):
            raise MemoryValidationError("invalid context_manifest_id")
        envelope_hash = _sha256(
            "expected_memory_envelope_sha256",
            expected_memory_envelope_sha256,
        )
        manifest_value = _json_object(manifest, "manifest")
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT m.*
                FROM memory_context_manifests m
                JOIN memory_conversations c
                  ON c.conversation_id = m.conversation_id
                 AND c.tenant_id = m.tenant_id
                WHERE m.context_manifest_id = ? AND m.tenant_id = ?
                  AND c.user_id = ?
                """,
                (manifest_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("context manifest not found")
            if row["memory_envelope_sha256"] != envelope_hash:
                raise MemoryConflictError(
                    "context_manifest_envelope_conflict",
                    "context manifest belongs to a different memory envelope",
                )
            connection.execute(
                """
                UPDATE memory_context_manifests
                SET manifest_json = ?
                WHERE context_manifest_id = ? AND tenant_id = ?
                """,
                (
                    canonical_json(manifest_value),
                    manifest_id,
                    principal.tenant_id,
                ),
            )
            updated = connection.execute(
                """
                SELECT * FROM memory_context_manifests
                WHERE context_manifest_id = ? AND tenant_id = ?
                """,
                (manifest_id, principal.tenant_id),
            ).fetchone()
        return _context_manifest_record(updated)

    def get_context_manifest(
        self, principal: MemoryPrincipal, context_manifest_id: str
    ) -> ContextManifestRecord:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT m.*
                FROM memory_context_manifests m
                JOIN memory_conversations c
                  ON c.conversation_id = m.conversation_id
                 AND c.tenant_id = m.tenant_id
                WHERE m.context_manifest_id = ? AND m.tenant_id = ?
                  AND c.user_id = ?
                """,
                (context_manifest_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("context manifest not found")
        return _context_manifest_record(row)

    def retention_candidates(
        self, principal: MemoryPrincipal, *, before: datetime, limit: int = 100
    ) -> Sequence[str]:
        before_value = _timestamp(before)
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT conversation_id
                FROM memory_conversations
                WHERE tenant_id = ? AND user_id = ?
                  AND (
                    status = 'deleted'
                    OR (retention_until_utc IS NOT NULL AND retention_until_utc <= ?)
                  )
                ORDER BY updated_at_utc ASC, conversation_id ASC
                LIMIT ?
                """,
                (
                    principal.tenant_id,
                    principal.user_id,
                    before_value,
                    _limit(limit),
                ),
            ).fetchall()
        return tuple(row["conversation_id"] for row in rows)

    def purge_expired(
        self, principal: MemoryPrincipal, *, before: datetime, limit: int = 100
    ) -> RetentionResult:
        before_value = _timestamp(before)
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT conversation_id
                FROM memory_conversations
                WHERE tenant_id = ? AND user_id = ?
                  AND (
                    status = 'deleted'
                    OR (retention_until_utc IS NOT NULL AND retention_until_utc <= ?)
                  )
                ORDER BY updated_at_utc ASC, conversation_id ASC
                LIMIT ?
                """,
                (
                    principal.tenant_id,
                    principal.user_id,
                    before_value,
                    _limit(limit),
                ),
            ).fetchall()
            conversation_ids = [row["conversation_id"] for row in rows]
            if not conversation_ids:
                return RetentionResult(0, 0, 0, 0, 0)
            placeholders = ",".join("?" for _ in conversation_ids)
            scoped_parameters = [principal.tenant_id, *conversation_ids]
            counts = {
                "agent_session_count": self._count_for_conversations(
                    connection,
                    "memory_agent_sessions",
                    placeholders,
                    scoped_parameters,
                ),
                "turn_count": self._count_for_conversations(
                    connection, "memory_turns", placeholders, scoped_parameters
                ),
                "summary_count": self._count_for_conversations(
                    connection, "memory_summaries", placeholders, scoped_parameters
                ),
                "context_manifest_count": self._count_for_conversations(
                    connection,
                    "memory_context_manifests",
                    placeholders,
                    scoped_parameters,
                ),
            }
            connection.execute(
                f"""
                DELETE FROM memory_conversations
                WHERE tenant_id = ? AND conversation_id IN ({placeholders})
                """,
                scoped_parameters,
            )
        return RetentionResult(
            conversation_count=len(conversation_ids),
            **counts,
        )

    def health(self) -> RepositoryHealth:
        self._ensure_initialized()
        with self._read_connection() as connection:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            foreign_keys = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            busy_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM memory_schema_migrations"
            ).fetchone()
            schema_version = int(row[0])
        return RepositoryHealth(
            healthy=(
                quick_check == "ok"
                and journal_mode.lower() == "wal"
                and foreign_keys
                and schema_version == self.latest_schema_version
            ),
            schema_version=schema_version,
            latest_schema_version=self.latest_schema_version,
            journal_mode=journal_mode,
            foreign_keys=foreign_keys,
            busy_timeout_ms=busy_timeout,
            quick_check=quick_check,
            database_path=str(self.database_path),
        )

    def _finish_noncommitted_turn(
        self,
        principal: MemoryPrincipal,
        turn_id: str,
        *,
        status: str,
        error_code: str,
        revision_barrier: Optional[Mapping[str, Any]],
    ) -> TurnRecord:
        if status not in {"failed", "cancelled"}:
            raise ValueError("invalid noncommitted terminal status")
        barrier_value = (
            _json_object(revision_barrier, "revision_barrier")
            if revision_barrier is not None
            else None
        )
        with self._transaction() as connection:
            current = self._turn_row(connection, principal, turn_id)
            if current["status"] == status:
                return _turn_record(current)
            if current["status"] != "pending":
                raise MemoryConflictError("turn_not_pending", "turn is not pending")
            connection.execute(
                """
                UPDATE memory_turns
                SET status = ?, error_code = ?, revision_barrier_json = ?
                WHERE turn_id = ? AND tenant_id = ?
                """,
                (
                    status,
                    error_code,
                    canonical_json(barrier_value)
                    if barrier_value is not None
                    else current["revision_barrier_json"],
                    turn_id,
                    principal.tenant_id,
                ),
            )
            row = self._turn_row(connection, principal, turn_id)
        return _turn_record(row)

    def _apply_migrations(self) -> None:
        with self._connection() as connection:
            applied_rows = connection.execute(
                "SELECT version, sha256 FROM memory_schema_migrations ORDER BY version"
            ).fetchall()
        applied = {int(row["version"]): row["sha256"] for row in applied_rows}
        known = {migration.version: migration for migration in self._migrations}
        unknown_versions = set(applied) - set(known)
        if unknown_versions:
            raise MemoryMigrationError(
                f"database has unknown memory migrations: {sorted(unknown_versions)}"
            )
        for version, stored_hash in applied.items():
            if stored_hash != known[version].sha256:
                raise MemoryMigrationError(
                    f"memory migration {version} hash does not match the binary"
                )
        for migration in self._migrations:
            if migration.version in applied:
                continue
            try:
                with self._transaction(initialize=False) as connection:
                    for statement in migration.statements:
                        connection.execute(statement)
                    connection.execute(
                        """
                        INSERT INTO memory_schema_migrations
                            (version, applied_at_utc, sha256)
                        VALUES (?, ?, ?)
                        """,
                        (migration.version, self._now(), migration.sha256),
                    )
            except (sqlite3.DatabaseError, MemoryRepositoryError) as exc:
                raise MemoryMigrationError(
                    f"memory migration {migration.version} failed: {exc}"
                ) from exc

    def _validate_migrations(self) -> None:
        versions = [migration.version for migration in self._migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError("memory migrations must be contiguous and start at version 1")
        if any(not migration.statements for migration in self._migrations):
            raise ValueError("memory migrations must contain statements")
        for migration in self._migrations:
            try:
                "\n".join(migration.statements).encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("memory migrations must be ASCII") from exc

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=self.busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        self._ensure_initialized()
        with self._connection() as connection:
            yield connection

    @contextmanager
    def _transaction(
        self, *, initialize: bool = True
    ) -> Iterator[sqlite3.Connection]:
        if initialize:
            self._ensure_initialized()
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _conversation_row(
        self,
        connection: sqlite3.Connection,
        principal: MemoryPrincipal,
        conversation_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM memory_conversations
            WHERE conversation_id = ? AND tenant_id = ? AND user_id = ?
            """,
            (conversation_id, principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError("conversation not found")
        return row

    def _agent_session_row(
        self,
        connection: sqlite3.Connection,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT s.*
            FROM memory_agent_sessions s
            JOIN memory_conversations c
              ON c.conversation_id = s.conversation_id
             AND c.tenant_id = s.tenant_id
            WHERE s.agent_session_id = ? AND s.tenant_id = ? AND c.user_id = ?
            """,
            (agent_session_id, principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError("agent session not found")
        return row

    def _turn_row(
        self,
        connection: sqlite3.Connection,
        principal: MemoryPrincipal,
        turn_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT t.*
            FROM memory_turns t
            JOIN memory_conversations c
              ON c.conversation_id = t.conversation_id
             AND c.tenant_id = t.tenant_id
            WHERE t.turn_id = ? AND t.tenant_id = ? AND c.user_id = ?
            """,
            (turn_id, principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError("turn not found")
        return row

    def _summary_job_row(
        self,
        connection: sqlite3.Connection,
        principal: MemoryPrincipal,
        job_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT j.*
            FROM memory_summary_jobs j
            JOIN memory_conversations c
              ON c.conversation_id = j.conversation_id
             AND c.tenant_id = j.tenant_id
            WHERE j.job_id = ? AND j.tenant_id = ? AND c.user_id = ?
            """,
            (job_id, principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError("summary job not found")
        return row

    def _finish_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
        *,
        status: str,
        error_code: Optional[str],
    ) -> SummaryJobRecord:
        if status not in {"succeeded", "failed"}:
            raise ValueError("invalid terminal summary job status")
        with self._transaction() as connection:
            row = self._summary_job_row(connection, principal, job_id)
            if row["status"] == status:
                return _summary_job_record(row)
            if row["status"] not in {"pending", "running"}:
                raise MemoryConflictError(
                    "summary_job_already_terminal",
                    "summary job is already terminal",
                )
            now = self._now()
            connection.execute(
                """
                UPDATE memory_summary_jobs
                SET status = ?, lease_until_utc = NULL,
                    last_error_code = ?, updated_at_utc = ?
                WHERE job_id = ? AND tenant_id = ?
                """,
                (status, error_code, now, job_id, principal.tenant_id),
            )
            row = self._summary_job_row(connection, principal, job_id)
        return _summary_job_record(row)

    @staticmethod
    def _count_for_conversations(
        connection: sqlite3.Connection,
        table: str,
        placeholders: str,
        parameters: Sequence[Any],
    ) -> int:
        allowed = {
            "memory_agent_sessions",
            "memory_turns",
            "memory_summaries",
            "memory_context_manifests",
        }
        if table not in allowed:
            raise ValueError("unsupported retention table")
        row = connection.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE tenant_id = ? AND conversation_id IN ({placeholders})
            """,
            parameters,
        ).fetchone()
        return int(row[0])

    def _now(self) -> str:
        return utc_timestamp(self._now_factory())


def _conversation_record(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=row["conversation_id"],
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        title=row["title"],
        status=row["status"],
        schema_version=int(row["schema_version"]),
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
        last_turn_sequence=int(row["last_turn_sequence"]),
        retention_until_utc=row["retention_until_utc"],
        metadata=_load_object(row["metadata_json"], "metadata_json"),
    )


def _agent_session_record(row: sqlite3.Row) -> AgentSessionRecord:
    workflow = (
        _load_object(row["workflow_state_json"], "workflow_state_json")
        if row["workflow_state_json"] is not None
        else None
    )
    return AgentSessionRecord(
        agent_session_id=row["agent_session_id"],
        conversation_id=row["conversation_id"],
        tenant_id=row["tenant_id"],
        agent_type=row["agent_type"],
        status=row["status"],
        scope_fingerprint=row["scope_fingerprint"],
        revision_vector=_load_object(
            row["revision_vector_json"], "revision_vector_json"
        ),
        workflow_state=workflow,
        workflow_state_revision=int(row["workflow_state_revision"]),
        summary_revision=int(row["summary_revision"]),
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
        expires_at_utc=row["expires_at_utc"],
    )


def _turn_record(row: sqlite3.Row) -> TurnRecord:
    return TurnRecord(
        turn_id=row["turn_id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        agent_session_id=row["agent_session_id"],
        sequence=int(row["sequence"]),
        client_turn_id=row["client_turn_id"],
        request_hash_version=int(row["request_hash_version"]),
        request_identity=_load_object(
            row["request_identity_json"], "request_identity_json"
        ),
        request_sha256=row["request_sha256"],
        status=row["status"],
        user_message=_load_object(row["user_message_json"], "user_message_json"),
        assistant_result=(
            _load_object(row["assistant_result_json"], "assistant_result_json")
            if row["assistant_result_json"] is not None
            else None
        ),
        tool_receipts=_load_array(row["tool_receipts_json"], "tool_receipts_json"),
        route_metadata=_load_object(row["route_metadata_json"], "route_metadata_json"),
        model_metadata=_load_object(row["model_metadata_json"], "model_metadata_json"),
        scope_fingerprint=row["scope_fingerprint"],
        source_revision_vector=_load_object(
            row["source_revision_vector_json"], "source_revision_vector_json"
        ),
        resulting_revision_vector=(
            _load_object(
                row["resulting_revision_vector_json"],
                "resulting_revision_vector_json",
            )
            if row["resulting_revision_vector_json"] is not None
            else None
        ),
        revision_barrier=_load_object(
            row["revision_barrier_json"], "revision_barrier_json"
        ),
        memory_envelope_sha256=row["memory_envelope_sha256"],
        context_manifest_id=row["context_manifest_id"],
        error_code=row["error_code"],
        created_at_utc=row["created_at_utc"],
        committed_at_utc=row["committed_at_utc"],
    )


def _summary_record(row: sqlite3.Row) -> SummaryRecord:
    return SummaryRecord(
        summary_id=row["summary_id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        agent_session_id=row["agent_session_id"],
        summary_revision=int(row["summary_revision"]),
        through_turn_sequence=int(row["through_turn_sequence"]),
        source_turn_sha256=row["source_turn_sha256"],
        summary=_load_object(row["summary_json"], "summary_json"),
        summary_sha256=row["summary_sha256"],
        status=row["status"],
        model_metadata=_load_object(
            row["model_metadata_json"], "model_metadata_json"
        ),
        created_at_utc=row["created_at_utc"],
    )


def _summary_job_record(row: sqlite3.Row) -> SummaryJobRecord:
    return SummaryJobRecord(
        job_id=row["job_id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        agent_session_id=row["agent_session_id"],
        target_through_turn_sequence=int(row["target_through_turn_sequence"]),
        source_turn_sha256=row["source_turn_sha256"],
        status=row["status"],
        attempt_count=int(row["attempt_count"]),
        lease_until_utc=row["lease_until_utc"],
        last_error_code=row["last_error_code"],
        created_at_utc=row["created_at_utc"],
        updated_at_utc=row["updated_at_utc"],
    )


def _context_manifest_record(row: sqlite3.Row) -> ContextManifestRecord:
    return ContextManifestRecord(
        context_manifest_id=row["context_manifest_id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        agent_session_id=row["agent_session_id"],
        turn_id=row["turn_id"],
        schema_version=int(row["schema_version"]),
        scope_fingerprint=row["scope_fingerprint"],
        revision_vector_sha256=row["revision_vector_sha256"],
        memory_envelope_sha256=row["memory_envelope_sha256"],
        manifest=_load_object(row["manifest_json"], "manifest_json"),
        created_at_utc=row["created_at_utc"],
    )


def _json_object(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MemoryValidationError(f"{name} must be an object")
    cloned = dict(value)
    try:
        canonical_json(cloned)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(f"{name} is not finite JSON: {exc}") from exc
    return json.loads(canonical_json(cloned))


def _json_array(value: Any, name: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MemoryValidationError(f"{name} must be an array")
    cloned = list(value)
    try:
        encoded = canonical_json(cloned)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(f"{name} is not finite JSON: {exc}") from exc
    return json.loads(encoded)


def _load_object(value: str, name: str) -> Dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise MemoryRepositoryError(f"stored {name} is not an object")
    return parsed


def _load_array(value: str, name: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise MemoryRepositoryError(f"stored {name} is not an array")
    return parsed


def _required_text(name: str, value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{name} must be a non-empty string")
    if len(value) > maximum or any(ord(character) < 32 for character in value):
        raise MemoryValidationError(f"{name} is invalid")
    return value.strip()


def _optional_text(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _required_text(name, value, maximum=300)


def _sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MemoryValidationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: datetime) -> str:
    try:
        return utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(f"invalid timestamp: {exc}") from exc


def _optional_timestamp(value: Optional[datetime]) -> Optional[str]:
    return _timestamp(value) if value is not None else None


def _limit(value: int) -> int:
    normalized = int(value)
    if normalized < 1 or normalized > 1000:
        raise MemoryValidationError("limit must be between 1 and 1000")
    return normalized
