"""Repository-backed workflow-state adapter for Phase 1 memory."""

from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from ai_inspector.agent_skills.workflow_state import (
    WorkflowStateResult,
    advance_workflow_state_v2,
    merge_audit_receipts,
    merge_execution_receipts,
    reconcile_workflow_state_v2,
    sanitize_workflow_state,
)

from .ids import is_memory_id
from .invalidation import reset_workflow_state_for_version
from .models import MemoryPrincipal
from .sqlite_repository import SqliteMemoryRepository


class RepositoryWorkflowStateStore:
    """Persist workflow state on a server-owned agent-session record."""

    def __init__(
        self,
        repository: SqliteMemoryRepository,
        principal: MemoryPrincipal,
        *,
        ttl_seconds: float = 86400.0,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("workflow-state TTL must be positive")
        self.repository = repository
        self.principal = principal
        self.ttl_seconds = float(ttl_seconds)
        self._wall_clock = wall_clock

    @staticmethod
    def valid_session_id(session_id: Any) -> str:
        token = str(session_id or "").strip()
        return token if is_memory_id(token, "agent_session") else ""

    def stats(self) -> dict[str, Any]:
        health = self.repository.health()
        return {
            "backend": "sqlite",
            "ttl_seconds": self.ttl_seconds,
            "healthy": health.healthy,
            "schema_version": health.schema_version,
            "journal_mode": health.journal_mode,
        }

    def reconcile(
        self,
        agent_session_id: str,
        *,
        scope_fingerprint: str,
        revision_vector: Mapping[str, Any],
        target_index: Mapping[str, Any] | None = None,
        client_state: Any = None,
        receipts: Sequence[Mapping[str, Any]] = (),
        workflow_version: Optional[str] = None,
        workflow_stages: Sequence[str] = (),
        invalidate_authorizations: bool = True,
    ) -> WorkflowStateResult:
        session = self.repository.get_agent_session(self.principal, agent_session_id)
        if session.status != "active":
            return WorkflowStateResult(None, "explicitly_abandoned")
        if _expired(session.expires_at_utc, self._wall_clock()):
            self.repository.update_agent_session_state(
                self.principal,
                agent_session_id,
                workflow_state=None,
                scope_fingerprint=scope_fingerprint,
                revision_vector=revision_vector,
                expected_workflow_state_revision=session.workflow_state_revision,
                expires_at=self._expires_at(),
            )
            return WorkflowStateResult(None, "memory_expired")

        state = session.workflow_state
        event = "empty"
        if state is None and client_state is not None:
            state = sanitize_workflow_state(
                client_state,
                expected_scope_fingerprint=scope_fingerprint,
                now_epoch=self._wall_clock(),
            )
            event = "restored_client_mirror" if state else "empty"
        if state is None:
            return WorkflowStateResult(None, event)

        if workflow_version and state.get("version") != workflow_version:
            next_state = reset_workflow_state_for_version(
                state,
                workflow_version=workflow_version,
                workflow_stages=workflow_stages,
                scope_fingerprint=scope_fingerprint,
                revision_vector=revision_vector,
                now_epoch=self._wall_clock(),
                ttl_seconds=self.ttl_seconds,
            )
            self.repository.update_agent_session_state(
                self.principal,
                agent_session_id,
                workflow_state=next_state,
                scope_fingerprint=scope_fingerprint,
                revision_vector=revision_vector,
                expected_workflow_state_revision=session.workflow_state_revision,
                expires_at=self._expires_at(),
            )
            return WorkflowStateResult(
                copy.deepcopy(next_state), "workflow_version_changed"
            )

        reconciled = reconcile_workflow_state_v2(
            state,
            current_scope_fingerprint=scope_fingerprint,
            current_revision_vector=revision_vector,
            target_index=target_index,
            now_epoch=self._wall_clock(),
            invalidate_authorizations=invalidate_authorizations,
        )
        if reconciled.state is None:
            self.repository.update_agent_session_state(
                self.principal,
                agent_session_id,
                workflow_state=None,
                scope_fingerprint=scope_fingerprint,
                revision_vector=revision_vector,
                expected_workflow_state_revision=session.workflow_state_revision,
                expires_at=self._expires_at(),
            )
            return reconciled

        next_state = copy.deepcopy(reconciled.state)
        invalidated = reconciled.event in {
            "authorization_stage_invalidated",
            "same_scope_revision_advanced",
            "same_scope_dependency_removed",
        }
        receipts_changed = (
            merge_audit_receipts(next_state, receipts)
            if invalidated
            else merge_execution_receipts(next_state, receipts)
        )
        self.repository.update_agent_session_state(
            self.principal,
            agent_session_id,
            workflow_state=next_state,
            scope_fingerprint=scope_fingerprint,
            revision_vector=revision_vector,
            expected_workflow_state_revision=session.workflow_state_revision,
            expires_at=self._expires_at(),
        )
        if receipts_changed and not invalidated:
            event = "receipts_reconciled"
        elif event == "restored_client_mirror":
            pass
        elif reconciled.event == "same_scope_same_revisions":
            event = "resumed"
        else:
            event = reconciled.event
        return WorkflowStateResult(copy.deepcopy(next_state), event)

    def advance(
        self,
        agent_session_id: str,
        *,
        scope_fingerprint: str,
        revision_vector: Mapping[str, Any],
        route: Mapping[str, Any],
        context_facts: Mapping[str, Any],
        workflow_version: str,
        workflow_stages: Sequence[str],
    ) -> WorkflowStateResult:
        session = self.repository.get_agent_session(self.principal, agent_session_id)
        if session.status != "active":
            return WorkflowStateResult(None, "explicitly_abandoned")
        prior = session.workflow_state
        restarting = bool(prior and route.get("continue_existing_workflow") is False)
        state = advance_workflow_state_v2(
            prior,
            route=route,
            context_facts=context_facts,
            scope_fingerprint=scope_fingerprint,
            revision_vector=revision_vector,
            workflow_version=workflow_version,
            workflow_stages=workflow_stages,
            now_epoch=self._wall_clock(),
            ttl_seconds=self.ttl_seconds,
        )
        if state is None:
            return WorkflowStateResult(copy.deepcopy(prior), "unchanged")
        self.repository.update_agent_session_state(
            self.principal,
            agent_session_id,
            workflow_state=state,
            scope_fingerprint=scope_fingerprint,
            revision_vector=revision_vector,
            expected_workflow_state_revision=session.workflow_state_revision,
            expires_at=self._expires_at(),
        )
        event = "restarted" if restarting else ("started" if prior is None else "continued")
        if prior and not restarting and prior.get("stage") != state.get("stage"):
            event = "advanced"
        if state.get("status") == "completed" and (
            not prior or prior.get("status") != "completed"
        ):
            event = "completed"
        return WorkflowStateResult(copy.deepcopy(state), event)

    def abandon(
        self, agent_session_id: str, *, reason: str = "user_requested"
    ) -> WorkflowStateResult:
        session = self.repository.get_agent_session(self.principal, agent_session_id)
        if session.status != "abandoned":
            self.repository.update_agent_session_state(
                self.principal,
                agent_session_id,
                workflow_state=None,
                scope_fingerprint=session.scope_fingerprint,
                revision_vector=session.revision_vector,
                expected_workflow_state_revision=session.workflow_state_revision,
                expires_at=self._expires_at(),
            )
        token = str(reason or "user_requested").strip().lower()[:40]
        return WorkflowStateResult(None, f"abandoned:{token}")

    def get(self, agent_session_id: str) -> Optional[dict[str, Any]]:
        session = self.repository.get_agent_session(self.principal, agent_session_id)
        if session.status != "active" or _expired(
            session.expires_at_utc, self._wall_clock()
        ):
            return None
        return copy.deepcopy(session.workflow_state)

    def _expires_at(self) -> datetime:
        return datetime.fromtimestamp(self._wall_clock(), tz=timezone.utc) + timedelta(
            seconds=self.ttl_seconds
        )


def _expired(expires_at_utc: Optional[str], now_epoch: float) -> bool:
    if not expires_at_utc:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at_utc.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expiry.timestamp() <= now_epoch
