"""Immutable records and canonical serialization for Sage memory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


JsonObject = Dict[str, Any]
JsonArray = List[Any]


def canonical_json(value: Any) -> str:
    """Return the single persisted and hashed JSON representation."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def utc_timestamp(value: Optional[datetime] = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("memory timestamps must be timezone-aware")
    normalized = current.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class MemoryPrincipal:
    tenant_id: str
    user_id: str
    roles: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier("tenant_id", self.tenant_id)
        _require_identifier("user_id", self.user_id)
        if any(not isinstance(role, str) or not role.strip() for role in self.roles):
            raise ValueError("roles must contain non-empty strings")


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    tenant_id: str
    user_id: str
    title: str
    status: str
    schema_version: int
    created_at_utc: str
    updated_at_utc: str
    last_turn_sequence: int
    retention_until_utc: Optional[str]
    metadata: JsonObject


@dataclass(frozen=True)
class AgentSessionRecord:
    agent_session_id: str
    conversation_id: str
    tenant_id: str
    agent_type: str
    status: str
    scope_fingerprint: Optional[str]
    revision_vector: JsonObject
    workflow_state: Optional[JsonObject]
    workflow_state_revision: int
    summary_revision: int
    created_at_utc: str
    updated_at_utc: str
    expires_at_utc: Optional[str]


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    tenant_id: str
    conversation_id: str
    agent_session_id: str
    sequence: int
    client_turn_id: str
    request_hash_version: int
    request_identity: JsonObject
    request_sha256: str
    status: str
    user_message: JsonObject
    assistant_result: Optional[JsonObject]
    tool_receipts: JsonArray
    route_metadata: JsonObject
    model_metadata: JsonObject
    scope_fingerprint: Optional[str]
    source_revision_vector: JsonObject
    resulting_revision_vector: Optional[JsonObject]
    revision_barrier: JsonObject
    memory_envelope_sha256: Optional[str]
    context_manifest_id: Optional[str]
    error_code: Optional[str]
    created_at_utc: str
    committed_at_utc: Optional[str]


@dataclass(frozen=True)
class SummaryRecord:
    summary_id: str
    tenant_id: str
    conversation_id: str
    agent_session_id: str
    summary_revision: int
    through_turn_sequence: int
    source_turn_sha256: str
    summary: JsonObject
    summary_sha256: str
    status: str
    model_metadata: JsonObject
    created_at_utc: str


@dataclass(frozen=True)
class SummaryJobRecord:
    job_id: str
    tenant_id: str
    conversation_id: str
    agent_session_id: str
    target_through_turn_sequence: int
    source_turn_sha256: str
    status: str
    attempt_count: int
    lease_until_utc: Optional[str]
    last_error_code: Optional[str]
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class ContextManifestRecord:
    context_manifest_id: str
    tenant_id: str
    conversation_id: str
    agent_session_id: str
    turn_id: str
    schema_version: int
    scope_fingerprint: Optional[str]
    revision_vector_sha256: str
    memory_envelope_sha256: str
    manifest: JsonObject
    created_at_utc: str


@dataclass(frozen=True)
class StartTurnResult:
    disposition: str
    turn: TurnRecord


@dataclass(frozen=True)
class RetentionResult:
    conversation_count: int
    agent_session_count: int
    turn_count: int
    summary_count: int
    context_manifest_count: int


@dataclass(frozen=True)
class RepositoryHealth:
    healthy: bool
    schema_version: int
    latest_schema_version: int
    journal_mode: str
    foreign_keys: bool
    busy_timeout_ms: int
    quick_check: str
    database_path: str


def _require_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} is invalid")
    return value
