"""Durable, trace-linked feedback storage for InspectorPro chat."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .memory.redaction import redact_for_persistence


FEEDBACK_DB_ENV = "INSPECTORPRO_CHAT_FEEDBACK_DB_PATH"
FEEDBACK_REASONS = frozenset({
    "incorrect_answer",
    "wrong_cad_feature",
    "wrong_drawing_interpretation",
    "wrong_revision",
    "missing_context",
    "incorrect_calculation",
    "bad_source",
    "bad_replacement_recommendation",
    "tool_failure",
    "unsafe_recommendation",
    "unclear_answer",
    "invalid_clearance",
    "blocked_aisle",
    "unsafe_placement",
    "wrong_orientation",
    "unrealistic_spacing",
    "bad_material_flow",
    "other",
})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class ChatFeedbackError(ValueError):
    """Raised when a feedback record violates the durable contract."""


@dataclass(frozen=True)
class ChatFeedbackRecord:
    feedback_id: str
    tenant_id: str
    user_id: str
    message_id: str
    rating: str
    reasons: tuple[str, ...]
    correction: str
    turn_id: str
    run_id: str
    created_at_utc: str
    updated_at_utc: str


def default_feedback_db_path(repository_root: Optional[Path] = None) -> Path:
    configured = str(os.getenv(FEEDBACK_DB_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    root = repository_root or Path(__file__).resolve().parents[1]
    return (root / "runtime_logs" / "inspectorpro-chat-feedback.sqlite3").resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(value: Any, field: str, *, required: bool = False) -> str:
    text = str(value if value is not None else "").strip()
    if not text and not required:
        return ""
    if not _IDENTIFIER.fullmatch(text):
        raise ChatFeedbackError(f"{field} is invalid")
    return text


def _bounded_text(value: Any, maximum: int) -> str:
    return str(value if value is not None else "").strip()[:maximum]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class ChatFeedbackStore:
    """SQLite repository with one current feedback record per user/message."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self._initialize_lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self._initialize_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
                if mode != "wal":
                    raise ChatFeedbackError("feedback database could not enable WAL mode")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS chat_feedback (
                        feedback_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL DEFAULT '',
                        agent_session_id TEXT NOT NULL DEFAULT '',
                        client_turn_id TEXT NOT NULL DEFAULT '',
                        turn_id TEXT NOT NULL DEFAULT '',
                        run_id TEXT NOT NULL DEFAULT '',
                        response_id TEXT NOT NULL DEFAULT '',
                        agent_type TEXT NOT NULL,
                        model TEXT NOT NULL DEFAULT '',
                        prompt_version TEXT NOT NULL DEFAULT '',
                        rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                        reasons_json TEXT NOT NULL,
                        correction_text TEXT NOT NULL DEFAULT '',
                        response_text TEXT NOT NULL,
                        response_sha256 TEXT NOT NULL,
                        trace_json TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL,
                        UNIQUE (tenant_id, user_id, message_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_chat_feedback_turn
                        ON chat_feedback (tenant_id, turn_id);
                    CREATE INDEX IF NOT EXISTS idx_chat_feedback_rating_updated
                        ON chat_feedback (tenant_id, rating, updated_at_utc DESC);
                    """
                )
            self._initialized = True

    def record(
        self,
        *,
        tenant_id: str,
        user_id: str,
        payload: Mapping[str, Any],
    ) -> ChatFeedbackRecord:
        self.initialize()
        tenant = _identifier(tenant_id, "tenant_id", required=True)
        user = _identifier(user_id, "user_id", required=True)
        message_id = _identifier(payload.get("messageId"), "messageId", required=True)
        rating = _bounded_text(payload.get("rating"), 12).lower()
        if rating not in {"up", "down"}:
            raise ChatFeedbackError("rating must be up or down")
        reasons = []
        for reason in list(payload.get("reasons") or [])[:8]:
            normalized = _bounded_text(reason, 80).lower()
            if normalized not in FEEDBACK_REASONS:
                raise ChatFeedbackError(f"unsupported feedback reason: {normalized}")
            if normalized not in reasons:
                reasons.append(normalized)
        if rating == "up":
            reasons = []
        raw_response = _bounded_text(payload.get("responseText"), 50_000)
        if not raw_response:
            raise ChatFeedbackError("responseText is required")
        response = str(redact_for_persistence(raw_response))
        correction = str(redact_for_persistence(
            _bounded_text(payload.get("correction"), 4_000)
        ))
        trace_value = payload.get("trace")
        trace = redact_for_persistence(
            dict(trace_value) if isinstance(trace_value, Mapping) else {}
        )
        trace_json = _canonical_json(trace)
        now = _utc_now()
        identifiers = {
            field: _identifier(payload.get(field), field)
            for field in (
                "conversationId",
                "agentSessionId",
                "clientTurnId",
                "turnId",
                "runId",
                "responseId",
            )
        }
        values = {
            "tenant_id": tenant,
            "user_id": user,
            "message_id": message_id,
            "conversation_id": identifiers["conversationId"],
            "agent_session_id": identifiers["agentSessionId"],
            "client_turn_id": identifiers["clientTurnId"],
            "turn_id": identifiers["turnId"],
            "run_id": identifiers["runId"],
            "response_id": identifiers["responseId"],
            "agent_type": _bounded_text(payload.get("agentType") or "unknown", 80),
            "model": _bounded_text(payload.get("model"), 160),
            "prompt_version": _bounded_text(payload.get("promptVersion"), 160),
            "rating": rating,
            "reasons_json": _canonical_json(reasons),
            "correction_text": correction,
            "response_text": response,
            "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
            "trace_json": trace_json,
            "updated_at_utc": now,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT feedback_id, created_at_utc
                FROM chat_feedback
                WHERE tenant_id = ? AND user_id = ? AND message_id = ?
                """,
                (tenant, user, message_id),
            ).fetchone()
            if existing:
                feedback_id = str(existing["feedback_id"])
                created_at = str(existing["created_at_utc"])
                assignments = ", ".join(
                    f"{key} = ?" for key in values
                    if key not in {"tenant_id", "user_id", "message_id"}
                )
                update_values = [
                    values[key] for key in values
                    if key not in {"tenant_id", "user_id", "message_id"}
                ]
                connection.execute(
                    f"UPDATE chat_feedback SET {assignments} WHERE feedback_id = ?",
                    (*update_values, feedback_id),
                )
            else:
                feedback_id = "feedback_" + secrets.token_hex(12)
                created_at = now
                columns = ["feedback_id", *values.keys(), "created_at_utc"]
                placeholders = ",".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO chat_feedback ({','.join(columns)}) VALUES ({placeholders})",
                    (feedback_id, *values.values(), created_at),
                )
            connection.commit()
        return ChatFeedbackRecord(
            feedback_id=feedback_id,
            tenant_id=tenant,
            user_id=user,
            message_id=message_id,
            rating=rating,
            reasons=tuple(reasons),
            correction=correction,
            turn_id=identifiers["turnId"],
            run_id=identifiers["runId"],
            created_at_utc=created_at,
            updated_at_utc=now,
        )

    def get(self, *, tenant_id: str, user_id: str, message_id: str) -> Optional[sqlite3.Row]:
        self.initialize()
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT * FROM chat_feedback
                WHERE tenant_id = ? AND user_id = ? AND message_id = ?
                """,
                (tenant_id, user_id, message_id),
            ).fetchone()


__all__ = [
    "ChatFeedbackError",
    "ChatFeedbackRecord",
    "ChatFeedbackStore",
    "FEEDBACK_DB_ENV",
    "FEEDBACK_REASONS",
    "default_feedback_db_path",
]
