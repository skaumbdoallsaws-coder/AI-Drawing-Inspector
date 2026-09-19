"""Storage-agnostic repository contract for Sage memory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

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
)


class MemoryRepositoryError(RuntimeError):
    """Base class for persistence failures safe to classify at service boundaries."""


class MemoryNotFoundError(MemoryRepositoryError):
    pass


class MemoryConflictError(MemoryRepositoryError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MemoryValidationError(MemoryRepositoryError):
    pass


class MemoryMigrationError(MemoryRepositoryError):
    pass


class MemoryRepository(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_conversation(
        self,
        principal: MemoryPrincipal,
        *,
        title: str,
        metadata: Optional[Mapping[str, Any]] = None,
        retention_until: Optional[datetime] = None,
    ) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def get_conversation(
        self, principal: MemoryPrincipal, conversation_id: str
    ) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def list_conversations(
        self,
        principal: MemoryPrincipal,
        *,
        status: Optional[str] = "active",
        limit: int = 100,
    ) -> Sequence[ConversationRecord]:
        raise NotImplementedError

    @abstractmethod
    def soft_delete_conversation(
        self, principal: MemoryPrincipal, conversation_id: str
    ) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
    def set_conversation_retention(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        retention_until: datetime,
    ) -> ConversationRecord:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def get_agent_session(
        self, principal: MemoryPrincipal, agent_session_id: str
    ) -> AgentSessionRecord:
        raise NotImplementedError

    @abstractmethod
    def list_agent_sessions(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        limit: int = 100,
    ) -> Sequence[AgentSessionRecord]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def set_agent_session_status(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        status: str,
    ) -> AgentSessionRecord:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def get_turn(self, principal: MemoryPrincipal, turn_id: str) -> TurnRecord:
        raise NotImplementedError

    @abstractmethod
    def list_turns(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> Sequence[TurnRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_agent_session_turns(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        committed_only: bool = True,
    ) -> Sequence[TurnRecord]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def fail_turn(
        self,
        principal: MemoryPrincipal,
        turn_id: str,
        *,
        error_code: str,
        revision_barrier: Optional[Mapping[str, Any]] = None,
    ) -> TurnRecord:
        raise NotImplementedError

    @abstractmethod
    def cancel_turn(
        self, principal: MemoryPrincipal, turn_id: str
    ) -> TurnRecord:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def get_current_summary(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> Optional[SummaryRecord]:
        raise NotImplementedError

    @abstractmethod
    def enqueue_summary_job(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        *,
        target_through_turn_sequence: int,
        source_turn_sha256: str,
    ) -> SummaryJobRecord:
        raise NotImplementedError

    @abstractmethod
    def get_pending_summary_job(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> Optional[SummaryJobRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_summary_job(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
    ) -> Optional[SummaryJobRecord]:
        raise NotImplementedError

    @abstractmethod
    def claim_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
        *,
        lease_seconds: float,
    ) -> SummaryJobRecord:
        raise NotImplementedError

    @abstractmethod
    def complete_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
    ) -> SummaryJobRecord:
        raise NotImplementedError

    @abstractmethod
    def fail_summary_job(
        self,
        principal: MemoryPrincipal,
        job_id: str,
        *,
        error_code: str,
    ) -> SummaryJobRecord:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def update_context_manifest(
        self,
        principal: MemoryPrincipal,
        context_manifest_id: str,
        *,
        manifest: Mapping[str, Any],
        expected_memory_envelope_sha256: str,
    ) -> ContextManifestRecord:
        raise NotImplementedError

    @abstractmethod
    def get_context_manifest(
        self,
        principal: MemoryPrincipal,
        context_manifest_id: str,
    ) -> ContextManifestRecord:
        raise NotImplementedError

    @abstractmethod
    def purge_expired(
        self, principal: MemoryPrincipal, *, before: datetime, limit: int = 100
    ) -> RetentionResult:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> RepositoryHealth:
        raise NotImplementedError
