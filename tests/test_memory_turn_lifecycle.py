from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from ai_inspector.memory import (
    MemoryPrincipal,
    SqliteMemoryRepository,
    TrustedTurnContext,
    TurnLifecycleError,
    TurnLifecycleService,
    build_request_identity_v1,
    evaluate_revision_barrier,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "memory"


def _principal() -> MemoryPrincipal:
    return MemoryPrincipal("local", "local-user", ("admin",))


def _context(revision: str = "rev-a") -> TrustedTurnContext:
    revisions = {"processMapRevision": revision}
    return TrustedTurnContext(
        asset_scope={
            "kind": "process_map",
            "ids": {"productId": "tricycle", "mapId": "default"},
            "expectedRevisionVector": revisions,
        },
        scope_fingerprint="scope-v1:test",
        revision_vector=revisions,
        workflow_mode="process_map",
    )


def _identity(context: TrustedTurnContext, message: str = "Explain this map."):
    return build_request_identity_v1(
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
    )[0]


def _graph(tmp_path: Path):
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    principal = _principal()
    conversation = repository.create_conversation(principal, title="Lifecycle")
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="deviation-analyst",
        scope_fingerprint=_context().scope_fingerprint,
        revision_vector=_context().revision_vector,
    )
    return repository, principal, conversation, session


def test_pending_turn_revision_barrier_fixture() -> None:
    fixture = json.loads(
        (FIXTURE_ROOT / "pending-turn-revision-barrier-v1.json").read_text(
            encoding="ascii"
        )
    )
    for scenario in fixture["scenarios"]:
        receipt = scenario.get("receipt")
        result = evaluate_revision_barrier(
            classification=scenario["classification"],
            source_revision_vector=scenario["sourceRevisionVector"],
            pre_effect_revision_vector=scenario["preEffectRevisionVector"],
            current_revision_vector=scenario["currentRevisionVector"],
            receipts=[receipt] if receipt else [],
            cas_outcome=scenario["casOutcome"],
        )
        expected = scenario["expected"]
        assert result["terminalStatus"] == expected["terminalStatus"]
        assert result["errorCode"] == expected["errorCode"]
        assert result["effectCount"] == expected["effectCount"]
        assert (
            result["revisionAdvancedDuringTurn"]
            == expected["revisionAdvancedDuringTurn"]
        )
        assert result["postEffectRevisionDrift"] == expected["postEffectRevisionDrift"]


@pytest.mark.parametrize(
    "cas_outcome",
    (
        "conflict",
        "cas_conflict",
        "revision_conflict",
        "rejected",
        "failed",
        "error",
    ),
)
def test_action_write_rejects_every_non_success_cas_outcome(
    cas_outcome: str,
) -> None:
    result = evaluate_revision_barrier(
        classification="action_write",
        source_revision_vector={"processMapRevision": "rev-a"},
        pre_effect_revision_vector={"processMapRevision": "rev-a"},
        current_revision_vector={"processMapRevision": "rev-a"},
        cas_outcome=cas_outcome,
    )

    assert result["terminalStatus"] == "failed"
    assert result["errorCode"] == "cas_conflict"
    assert result["effectCount"] == 0


@pytest.mark.parametrize("cas_outcome", ("not_attempted", "not_applicable"))
def test_action_write_without_an_attempted_effect_can_commit_a_response(
    cas_outcome: str,
) -> None:
    result = evaluate_revision_barrier(
        classification="action_write",
        source_revision_vector={"processMapRevision": "rev-a"},
        pre_effect_revision_vector={"processMapRevision": "rev-a"},
        current_revision_vector={"processMapRevision": "rev-a"},
        cas_outcome=cas_outcome,
    )

    assert result["terminalStatus"] == "committed"
    assert result["errorCode"] is None
    assert result["effectCount"] == 0


@pytest.mark.parametrize(
    "cas_outcome", ("applied", "committed", "success", "succeeded")
)
def test_action_write_accepts_only_closed_success_cas_outcomes(
    cas_outcome: str,
) -> None:
    result = evaluate_revision_barrier(
        classification="action_write",
        source_revision_vector={"processMapRevision": "rev-a"},
        pre_effect_revision_vector={"processMapRevision": "rev-a"},
        current_revision_vector={"processMapRevision": "rev-a"},
        cas_outcome=cas_outcome,
    )

    assert result["terminalStatus"] == "committed"
    assert result["errorCode"] is None


def test_successful_effect_without_result_vector_reports_post_effect_drift() -> None:
    result = evaluate_revision_barrier(
        classification="action_write",
        source_revision_vector={
            "processMapRevision": "rev-a",
            "productStructureRevision": "struct-a",
        },
        pre_effect_revision_vector={
            "processMapRevision": "rev-a",
            "productStructureRevision": "struct-a",
        },
        current_revision_vector={
            "processMapRevision": "rev-b",
            "productStructureRevision": "struct-a",
        },
        receipts=[{"casOutcome": "applied", "idempotencyKey": "apply-001"}],
        cas_outcome="applied",
    )

    assert result["terminalStatus"] == "committed"
    assert result["effectCount"] == 1
    assert result["resultingRevisionVector"] == {
        "processMapRevision": "rev-a",
        "productStructureRevision": "struct-a",
    }
    assert result["postEffectRevisionDrift"] is True


def test_committed_retry_returns_canonical_result_without_reexecution(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    service = TurnLifecycleService(repository, mode="enforce")
    context = _context()
    calls = 0

    async def execute():
        nonlocal calls
        calls += 1
        return {"response": "Deterministic answer."}

    async def run():
        first = await service.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id="browser-turn-1",
            request_identity=_identity(context),
            user_message={"role": "user", "content": "Explain this map."},
            trusted_context=context,
            classification="read_only",
            execute=execute,
            resolve_current_context=lambda: context,
        )
        second = await service.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id="browser-turn-1",
            request_identity=_identity(context),
            user_message={"role": "user", "content": "Explain this map."},
            trusted_context=context,
            classification="read_only",
            execute=execute,
            resolve_current_context=lambda: context,
        )
        return first, second

    first, second = asyncio.run(run())
    assert calls == 1
    assert first.replayed is False
    assert second.replayed is True
    assert first.result["response"] == second.result["response"]
    assert second.result["memory"]["turnId"] == first.turn.turn_id
    assert len(repository.list_turns(principal, conversation.conversation_id)) == 1


def test_action_revision_advance_fails_before_tool_bundle_is_released(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    service = TurnLifecycleService(repository, mode="enforce")
    source = _context("rev-a")
    resolutions = iter((source, _context("rev-b")))
    calls = 0

    async def execute():
        nonlocal calls
        calls += 1
        return {
            "response": "I prepared an action.",
            "tool_calls": [{"name": "build_process_map_preview", "args": {}}],
        }

    async def run():
        return await service.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id="browser-turn-action",
            request_identity=_identity(source, "Build a preview."),
            user_message={"role": "user", "content": "Build a preview."},
            trusted_context=source,
            classification="preview",
            execute=execute,
            resolve_current_context=lambda: next(resolutions),
        )

    with pytest.raises(TurnLifecycleError) as error:
        asyncio.run(run())
    assert error.value.code == "revision_advanced_during_turn"
    turn = repository.list_turns(principal, conversation.conversation_id)[0]
    assert turn.status == "failed"
    assert turn.assistant_result is None
    assert turn.tool_receipts == []
    assert calls == 1

    with pytest.raises(TurnLifecycleError) as retry_error:
        asyncio.run(run())
    assert retry_error.value.code == "turn_already_terminal"
    assert calls == 1


def test_stale_pending_turn_is_terminally_recovered_without_replay(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    context = _context()
    repository.start_turn(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        client_turn_id="browser-turn-stale",
        request_identity=_identity(context),
        user_message={"role": "user", "content": "Explain this map."},
        scope_fingerprint=context.scope_fingerprint,
        source_revision_vector=context.revision_vector,
    )
    time.sleep(0.01)
    recovered = TurnLifecycleService(
        repository,
        mode="enforce",
        stale_pending_seconds=0.001,
    )
    calls = 0

    async def execute():
        nonlocal calls
        calls += 1
        return {"response": "must not run"}

    async def run():
        return await recovered.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id="browser-turn-stale",
            request_identity=_identity(context),
            user_message={"role": "user", "content": "Explain this map."},
            trusted_context=context,
            classification="read_only",
            execute=execute,
            resolve_current_context=lambda: context,
        )

    with pytest.raises(TurnLifecycleError) as error:
        asyncio.run(run())
    assert error.value.code == "stale_pending_recovered"
    assert calls == 0
    assert repository.list_turns(principal, conversation.conversation_id)[0].status == "failed"


def test_cancelled_execution_terminalizes_pending_turn(tmp_path: Path) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    service = TurnLifecycleService(repository, mode="enforce")
    context = _context()
    started = asyncio.Event()

    async def execute():
        started.set()
        await asyncio.sleep(30)
        return {"response": "must not commit"}

    async def run():
        task = asyncio.create_task(service.execute(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            client_turn_id="browser-turn-cancelled",
            request_identity=_identity(context),
            user_message={"role": "user", "content": "Explain this map."},
            trusted_context=context,
            classification="read_only",
            execute=execute,
            resolve_current_context=lambda: context,
        ))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    turn = repository.list_turns(principal, conversation.conversation_id)[0]
    assert turn.status == "cancelled"
    assert turn.assistant_result is None
