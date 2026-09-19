from __future__ import annotations

from pathlib import Path

import server

from ai_inspector.memory import MemoryPrincipal, SqliteMemoryRepository
from ai_inspector.memory.workflow_state_store import RepositoryWorkflowStateStore


SCOPE = "scope-v1:durable-workflow"
OTHER_SCOPE = "scope-v1:other-asset"
REVISIONS = {
    "partRevision": "part-a",
    "drawingRevision": "drawing-a",
    "faiRevision": "fai-a",
    "assemblyKnowledgeRevision": "assembly-a",
}
STAGES = (
    "identify_characteristic",
    "evaluate_result",
    "explain_part_function",
    "trace_assembly_impact",
    "visualize_affected_context",
    "recommend_disposition",
)
TARGET_INDEX = {
    "part": ["P-1"],
    "assembly": ["A-1"],
    "fai_characteristic": ["5"],
}


def _route(*, effect: bool = False):
    return {
        "route_version": 1,
        "speech_act": "command" if effect else "question",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": True,
        "workflow_confidence": 0.95,
        "intents": [{
            "kind": "visualize_affected_context" if effect else "explain_assembly_impact",
            "targets": [{"kind": "fai_characteristic", "id": "5", "label": "Bore"}],
            "requested_effects": ["highlight"] if effect else [],
            "confidence": 0.95,
        }],
        "requested_side_effects": {
            "viewport_write": effect,
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
        "clarification_question": None,
    }


def _facts():
    return {
        "part": {"part_number": "P-1", "part_name": "Test part"},
        "assembly_number": "A-1",
        "target_index": TARGET_INDEX,
        "fai": {
            "rows": [{"id": "5", "status": "fail", "description": "Bore"}],
        },
    }


def _seed(repository: SqliteMemoryRepository, principal: MemoryPrincipal):
    conversation = repository.create_conversation(principal, title="Durable workflow")
    return repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="sage",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
    )


def test_server_restart_resumes_without_a_browser_mirror(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(database)
    session = _seed(repository, principal)
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    started = store.advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert started.state is not None
    revision = started.state["revision"]
    repository.close()

    reopened = SqliteMemoryRepository(database)
    restored = RepositoryWorkflowStateStore(
        reopened, principal, ttl_seconds=600.0, wall_clock=lambda: 1010.0
    ).reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
    )
    assert restored.event == "resumed"
    assert restored.state["revision"] == revision
    assert restored.state["entities"]["part_number"] == "P-1"
    reopened.close()


def test_expired_state_is_not_restored(tmp_path: Path) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    session = _seed(repository, principal)
    RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=10.0, wall_clock=lambda: 1000.0
    ).advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    result = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=10.0, wall_clock=lambda: 1011.0
    ).reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
    )
    assert result.event == "memory_expired"
    assert result.state is None
    expired_session = repository.get_agent_session(principal, session.agent_session_id)
    assert expired_session.status == "active"
    assert expired_session.workflow_state is None
    repository.close()


def test_scope_change_drops_state_referents_and_pending_effects(tmp_path: Path) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    session = _seed(repository, principal)
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    started = store.advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(effect=True),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert started.state["referents"]["last_requested_effects"] == ["highlight"]
    changed = store.reconcile(
        session.agent_session_id,
        scope_fingerprint=OTHER_SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
    )
    assert changed.event == "scope_changed"
    assert changed.state is None
    persisted = repository.get_agent_session(principal, session.agent_session_id)
    assert persisted.workflow_state is None
    assert persisted.scope_fingerprint == OTHER_SCOPE
    repository.close()


def test_abandon_is_durable_and_never_replays_a_side_effect(tmp_path: Path) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(database)
    session = _seed(repository, principal)
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    store.advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(effect=True),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert store.abandon(session.agent_session_id).event == "abandoned:user_requested"
    repository.close()

    reopened = SqliteMemoryRepository(database)
    result = RepositoryWorkflowStateStore(
        reopened, principal, ttl_seconds=600.0, wall_clock=lambda: 1010.0
    ).reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
    )
    assert result.event == "empty"
    assert result.state is None
    assert reopened.get_agent_session(
        principal, session.agent_session_id
    ).status == "active"
    reopened.close()


def test_restart_regresses_authorization_stage_and_audits_receipts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(database)
    session = _seed(repository, principal)
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    started = store.advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(effect=True),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert started.state["stage"] == "visualize_affected_context"
    with_receipt = store.reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
        receipts=[{
            "receipt_id": "receipt:preview",
            "tool_id": "set_part_highlight",
            "status": "succeeded",
        }],
    )
    assert with_receipt.state["stage"] == "trace_assembly_impact"
    assert with_receipt.event == "authorization_stage_invalidated"
    assert with_receipt.state["last_execution_receipts"] == []
    assert with_receipt.state["audit_receipts"] == [{
        "receipt_id": "receipt:preview",
        "tool_id": "set_part_highlight",
        "status": "succeeded",
    }]
    repository.close()

    reopened = SqliteMemoryRepository(database)
    restored = RepositoryWorkflowStateStore(
        reopened, principal, ttl_seconds=600.0, wall_clock=lambda: 1010.0
    ).reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
    )
    assert restored.event == "resumed"
    assert restored.state["stage"] == "trace_assembly_impact"
    assert restored.state["last_execution_receipts"] == []
    reopened.close()


def test_server_reconciliation_resumes_sqlite_state_without_browser_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "memory.sqlite3"
    principal = MemoryPrincipal("tenant-a", "user-a")
    ctx = {
        "part_number": "P-1",
        "assembly_number": "A-1",
        "revision": "A",
        "asset_identity": {"part_revision": "A"},
    }
    scope, revisions = server._workflow_scope_and_revision(ctx)
    repository = SqliteMemoryRepository(database)
    conversation = repository.create_conversation(
        principal, title="Server restart workflow"
    )
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="sage",
        scope_fingerprint=scope,
        revision_vector=revisions,
    )
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    store.advance(
        session.agent_session_id,
        scope_fingerprint=scope,
        revision_vector=revisions,
        route=_route(),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert store.stats()["healthy"] is True
    repository.close()

    reopened = SqliteMemoryRepository(database)
    restarted_store = RepositoryWorkflowStateStore(
        reopened, principal, ttl_seconds=600.0, wall_clock=lambda: 1010.0
    )
    request = server.AgentChatRequest(
        message="What were we reviewing?",
        agent_type="deviation-analyst",
        session_id=session.agent_session_id,
    )
    session_id, restored_scope, restored_revisions, result = (
        server._reconcile_workflow_state_store(
            request,
            ctx,
            store=restarted_store,
            accept_client_mirror=False,
            record_events=False,
        )
    )
    assert session_id == session.agent_session_id
    assert restored_scope == scope
    assert restored_revisions == revisions
    assert result.state is not None
    assert result.state["workflow_id"] == "supplier-fai-disposition"
    reopened.close()


def test_workflow_version_change_preserves_only_objective_and_audit_receipts(
    tmp_path: Path,
) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    session = _seed(repository, principal)
    store = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    )
    started = store.advance(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(effect=True),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    repository.update_agent_session_state(
        principal,
        session.agent_session_id,
        workflow_state={
            **started.state,
            "last_execution_receipts": [
                {
                    "receipt_id": "receipt:old-preview",
                    "tool_id": "set_part_highlight",
                    "status": "succeeded",
                }
            ],
        },
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        expected_workflow_state_revision=(
            repository.get_agent_session(
                principal, session.agent_session_id
            ).workflow_state_revision
        ),
    )

    reconciled = store.reconcile(
        session.agent_session_id,
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
        workflow_version="2.0.0",
        workflow_stages=("inspect_current_evidence", "report_result"),
        invalidate_authorizations=False,
    )

    assert reconciled.event == "workflow_version_changed"
    assert reconciled.state["objective"] == started.state["objective"]
    assert reconciled.state["version"] == "2.0.0"
    assert reconciled.state["stage"] == "inspect_current_evidence"
    assert reconciled.state["entities"] == {}
    assert reconciled.state["referents"] == {}
    assert reconciled.state["evidence_refs"] == []
    assert reconciled.state["last_execution_receipts"] == []
    assert reconciled.state["audit_receipts"][-1]["receipt_id"] == (
        "receipt:old-preview"
    )
    assert reconciled.state["invalidation_audit"][-1]["warning"] == (
        "workflow_state_migration_unavailable"
    )
    repository.close()


def test_facility_policy_revision_regresses_stage_and_drops_removed_placement(
    tmp_path: Path,
) -> None:
    principal = MemoryPrincipal("tenant-a", "user-a")
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    conversation = repository.create_conversation(
        principal, title="Facility policy reconciliation"
    )
    old_revisions = {
        "facilityLayoutRevision": "layout-a",
        "facilityShellRevision": "shell-a",
        "facilityPolicyRevision": "policy-a",
    }
    new_revisions = {**old_revisions, "facilityPolicyRevision": "policy-b"}
    scope = "scope-v1:facility-layout-a"
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="sage",
        scope_fingerprint=scope,
        revision_vector=old_revisions,
    )
    state = {
        "state_version": 2,
        "workflow_id": "facility-layout-generation",
        "version": "1.0.0",
        "status": "active",
        "stage": "draft_semantic_facility_plan",
        "objective": "Arrange the pilot machining cell",
        "entities": {
            "facility_layout_id": "layout-a",
            "facility_placement_ids": ["pl-keep", "pl-removed"],
        },
        "evidence_refs": ["facility-policy:policy-a"],
        "referents": {
            "last_facility_placement_ids": ["pl-removed"]
        },
        "milestones": {},
        "last_execution_receipts": [],
        "audit_receipts": [],
        "pending_clarification": None,
        "scope_fingerprint": scope,
        "revision_vector": old_revisions,
        "revision_vector_sha256": server.revision_vector_sha256(old_revisions),
        "invalidation_audit": [],
        "revision": 2,
        "created_at": "2026-08-07T12:00:00Z",
        "updated_at": "2026-08-07T12:00:00Z",
        "expires_at": "2026-08-08T12:00:00Z",
    }
    repository.update_agent_session_state(
        principal,
        session.agent_session_id,
        workflow_state=state,
        scope_fingerprint=scope,
        revision_vector=old_revisions,
        expected_workflow_state_revision=session.workflow_state_revision,
    )

    result = RepositoryWorkflowStateStore(
        repository, principal, ttl_seconds=600.0, wall_clock=lambda: 1000.0
    ).reconcile(
        session.agent_session_id,
        scope_fingerprint=scope,
        revision_vector=new_revisions,
        target_index={
            "facility_layout": ["layout-a"],
            "facility_placement": ["pl-keep"],
        },
        workflow_version="1.0.0",
        workflow_stages=(
            "observe_revision_bound_layout",
            "inspect_bounded_authority",
            "draft_semantic_facility_plan",
            "validate_semantics_and_evidence",
            "build_synchronized_ghost_preview",
            "await_explicit_approval",
        ),
        invalidate_authorizations=False,
    )

    assert result.event == "same_scope_revision_advanced"
    assert result.state["objective"] == state["objective"]
    assert result.state["stage"] == "inspect_bounded_authority"
    assert result.state["entities"]["facility_placement_ids"] == ["pl-keep"]
    assert result.state["referents"] == {}
    assert result.state["evidence_refs"] == []
    assert result.state["invalidation_audit"][-1]["changedDependencies"] == [
        "facilityPolicyRevision"
    ]
    repository.close()
