from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from ai_inspector.memory import (
    ContinuityConfig,
    ContinuityError,
    ContinuityService,
    MemoryPrincipal,
    SqliteMemoryRepository,
    SummaryProviderError,
    SummaryProviderResult,
    canonical_sha256,
    estimate_turn_tokens,
    source_turn_range_sha256,
    validate_continuity_summary,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "memory"
SHA_A = "a" * 64


class FakeSummaryProvider:
    def __init__(self, factory=None, *, fail: bool = False) -> None:
        self.factory = factory
        self.fail = fail
        self.calls = []

    async def generate(self, **request):
        self.calls.append(copy.deepcopy(request))
        if self.fail:
            raise SummaryProviderError(
                "summary_provider_failed", "intentional summary failure"
            )
        if self.factory is not None:
            summary = self.factory(len(self.calls), request)
        else:
            source_id = request["turns"][0]["turnId"]
            summary = _summary(
                request["expected_summary_revision"],
                request["through_turn_sequence"],
                source_id,
            )
        return SummaryProviderResult(
            summary=summary,
            metadata={"provider": "fake", "model": "deterministic-test"},
        )


class DelayedSummaryProvider:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = []

    async def generate(self, **request):
        self.calls.append(copy.deepcopy(request))
        await asyncio.sleep(self.delay_seconds)
        source_id = request["turns"][0]["turnId"]
        return SummaryProviderResult(
            summary=_summary(
                request["expected_summary_revision"],
                request["through_turn_sequence"],
                source_id,
            ),
            metadata={"provider": "delayed-fake", "model": "deterministic-test"},
        )


def _summary(revision: int, through: int, source_id: str) -> dict:
    return {
        "schemaVersion": "sage-continuity-summary-1.0",
        "summaryRevision": revision,
        "throughTurnSequence": through,
        "objective": {
            "text": "Continue the active engineering workflow",
            "sourceTurnIds": [source_id],
        },
        "userClaims": [],
        "continuityDecisions": [],
        "assumptions": [],
        "corrections": [],
        "openQuestions": [],
        "referencedEntities": [],
        "sourceEvidenceRefs": [],
        "warnings": [],
    }


def _graph(tmp_path: Path):
    repository = SqliteMemoryRepository(tmp_path / "memory.sqlite3")
    principal = MemoryPrincipal("tenant-a", "user-a", ("operator",))
    conversation = repository.create_conversation(
        principal, title="Continuity tests"
    )
    session = repository.create_agent_session(
        principal,
        conversation.conversation_id,
        agent_type="deviation-analyst",
        scope_fingerprint="scope-v1:test",
        revision_vector={"processMapRevision": "rev-a"},
    )
    return repository, principal, conversation, session


def _request_identity(message: str) -> dict:
    fixture = json.loads(
        (FIXTURES / "request-hash-v1-cases.json").read_text(encoding="ascii")
    )
    identity = copy.deepcopy(fixture["baseRaw"])
    identity["message"] = message
    return identity


def _commit_turns(
    repository,
    principal,
    conversation_id,
    session_id,
    count: int,
    *,
    start: int = 1,
    correction_last: bool = False,
):
    records = []
    for index in range(start, start + count):
        message = f"User turn {index:03d}: preserve the selected target."
        if correction_last and index == start + count - 1:
            message = "Correction: use 30 mm, not the earlier 32 mm claim."
        started = repository.start_turn(
            principal,
            conversation_id,
            session_id,
            client_turn_id=f"client-{index:03d}",
            request_identity=_request_identity(message),
            user_message={"role": "user", "content": message},
            scope_fingerprint="scope-v1:test",
            source_revision_vector={"processMapRevision": "rev-a"},
        ).turn
        committed = repository.commit_turn(
            principal,
            started.turn_id,
            assistant_result={
                "response": (
                    f"Assistant turn {index:03d}: retained conversation-only "
                    "continuity without asserting a new engineering fact."
                )
            },
            tool_receipts=[],
            resulting_revision_vector={"processMapRevision": "rev-a"},
            revision_barrier={
                "classification": "read_only",
                "outcome": "matched",
            },
            memory_envelope_sha256=SHA_A,
        )
        records.append(committed)
    return records


def _scope() -> dict:
    return {
        "kind": "process_map",
        "ids": {"productId": "tricycle", "mapId": "default"},
    }


def test_frozen_continuity_summary_contract_is_strict_and_provenanced() -> None:
    fixture = json.loads(
        (FIXTURES / "sage-memory-contract-examples-v1.json").read_text(
            encoding="ascii"
        )
    )["continuitySummary"]
    allowed = {
        "turn-001",
        "turn-005",
        "turn-009",
        "turn-012",
        "turn-014",
        "turn-016",
    }
    validated = validate_continuity_summary(
        fixture,
        expected_summary_revision=3,
        expected_through_turn_sequence=18,
        allowed_turn_ids=allowed,
        maximum_tokens=1200,
    )
    assert validated == fixture

    missing_source = copy.deepcopy(fixture)
    missing_source["objective"]["sourceTurnIds"] = []
    with pytest.raises(Exception, match="must not be empty"):
        validate_continuity_summary(
            missing_source,
            expected_summary_revision=3,
            expected_through_turn_sequence=18,
            allowed_turn_ids=allowed,
            maximum_tokens=1200,
        )

    elevated = copy.deepcopy(fixture)
    elevated["continuityDecisions"][0]["authority"] = "authoritative"
    with pytest.raises(Exception, match="conversation_only"):
        validate_continuity_summary(
            elevated,
            expected_summary_revision=3,
            expected_through_turn_sequence=18,
            allowed_turn_ids=allowed,
            maximum_tokens=1200,
        )


def test_summary_job_survives_restart_and_uses_a_lease(tmp_path: Path) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    turns = _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        1,
    )
    source_hash = source_turn_range_sha256(turns, turns[-1].sequence)
    job = repository.enqueue_summary_job(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        target_through_turn_sequence=turns[-1].sequence,
        source_turn_sha256=source_hash,
    )
    repository.close()

    reopened = SqliteMemoryRepository(repository.database_path)
    restored = reopened.get_pending_summary_job(
        principal, session.agent_session_id
    )
    assert restored == job
    claimed = reopened.claim_summary_job(
        principal, restored.job_id, lease_seconds=30
    )
    assert claimed.status == "running"
    assert claimed.attempt_count == 1
    with pytest.raises(Exception, match="already running"):
        reopened.claim_summary_job(principal, restored.job_id, lease_seconds=30)
    failed = reopened.fail_summary_job(
        principal, restored.job_id, error_code="test_failure"
    )
    assert failed.status == "failed"
    requeued = reopened.enqueue_summary_job(
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        target_through_turn_sequence=turns[-1].sequence,
        source_turn_sha256=source_hash,
    )
    assert requeued.status == "pending"
    assert requeued.attempt_count == 1


def test_one_hundred_turn_projection_is_bounded_and_reports_the_missing_range(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        100,
    )
    service = ContinuityService(
        repository, FakeSummaryProvider(), config=ContinuityConfig()
    )
    projection = service.snapshot(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
    )
    recent_records = repository.list_agent_session_turns(
        principal,
        session.agent_session_id,
        after_sequence=0,
        limit=1000,
    )[-len(projection.recent_turn_ids):]
    assert len(projection.recent_turn_ids) <= 6
    assert sum(estimate_turn_tokens(turn) for turn in recent_records) <= 2400
    assert projection.unsummarized_turn_count == 100
    assert projection.oldest_unsummarized_turn_sequence == 1
    assert projection.all_unsummarized_turns_included is False
    assert projection.staleness == "hard"
    assert projection.status == "degraded"


def test_soft_stale_action_performs_one_bounded_refresh(tmp_path: Path) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        7,
    )
    provider = FakeSummaryProvider()
    service = ContinuityService(
        repository, provider, config=ContinuityConfig()
    )

    projection = asyncio.run(service.prepare_turn(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
        classification="action_write",
        message="Build the requested preview.",
        stable_scope=_scope(),
        apply_to_prompt=True,
    ))

    assert len(provider.calls) == 1
    assert projection.status == "healthy"
    assert projection.staleness == "fresh"
    assert projection.unsummarized_turn_count == 0
    assert projection.applied_to_prompt is True
    current = repository.get_current_summary(principal, session.agent_session_id)
    assert current is not None
    assert current.through_turn_sequence == 7
    assert current.summary["objective"]["sourceTurnIds"]
    assert repository.get_latest_summary_job(
        principal, session.agent_session_id
    ).status == "succeeded"


def test_summary_timeout_blocks_action_before_context_is_used(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        7,
    )
    provider = DelayedSummaryProvider(0.25)
    service = ContinuityService(
        repository,
        provider,
        config=ContinuityConfig(sync_refresh_timeout_seconds=0.1),
    )

    async def exercise_timeout() -> None:
        with pytest.raises(ContinuityError) as error:
            await service.prepare_turn(
                principal=principal,
                conversation_id=conversation.conversation_id,
                agent_session_id=session.agent_session_id,
                classification="action_write",
                message="Apply the revision-bound change.",
                stable_scope=_scope(),
                apply_to_prompt=True,
            )
        assert error.value.code == "continuity_summary_refresh_required"
        assert len(provider.calls) == 1
        assert repository.get_current_summary(
            principal, session.agent_session_id
        ) is None

        # The shielded refresh may finish for a later retry, but the timed-out
        # action itself must remain blocked.
        await asyncio.sleep(0.2)
        summary = repository.get_current_summary(
            principal, session.agent_session_id
        )
        assert summary is not None
        assert summary.through_turn_sequence == 7

    asyncio.run(exercise_timeout())


def test_sustained_summary_failure_is_visible_and_blocks_actions(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        7,
    )
    provider = FakeSummaryProvider(fail=True)
    service = ContinuityService(
        repository, provider, config=ContinuityConfig()
    )
    with pytest.raises(ContinuityError) as soft:
        asyncio.run(service.prepare_turn(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            classification="preview",
            message="Show a preview.",
            stable_scope=_scope(),
            apply_to_prompt=True,
        ))
    assert soft.value.code == "continuity_summary_refresh_required"
    assert len(provider.calls) == 1
    degraded = service.snapshot(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
    )
    assert "continuity_summary_refresh_failed" in degraded.warnings

    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        13,
        start=8,
    )
    with pytest.raises(ContinuityError) as hard:
        asyncio.run(service.prepare_turn(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            classification="action_write",
            message="Apply the change.",
            stable_scope=_scope(),
            apply_to_prompt=True,
        ))
    assert hard.value.code == "continuity_summary_stale"
    assert len(provider.calls) == 1

    fallback = ContinuityService(
        repository,
        provider,
        config=ContinuityConfig(stateless_read_fallback=True),
    )
    stateless = asyncio.run(fallback.prepare_turn(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
        classification="read_only",
        message="Describe the current saved process map.",
        stable_scope=_scope(),
        apply_to_prompt=True,
    ))
    assert stateless.status == "stateless"
    assert stateless.recent_history == ()
    with pytest.raises(ContinuityError):
        asyncio.run(fallback.prepare_turn(
            principal=principal,
            conversation_id=conversation.conversation_id,
            agent_session_id=session.agent_session_id,
            classification="read_only",
            message="Continue the previous decision.",
            stable_scope=_scope(),
            apply_to_prompt=True,
        ))


def test_incremental_correction_supersedes_prior_claim_without_deleting_it(
    tmp_path: Path,
) -> None:
    repository, principal, conversation, session = _graph(tmp_path)
    first = _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        7,
    )

    def factory(call_number, request):
        if call_number == 1:
            summary = _summary(
                request["expected_summary_revision"],
                request["through_turn_sequence"],
                first[0].turn_id,
            )
            summary["userClaims"] = [{
                "claimId": "claim-nominal-32",
                "text": "The user stated a 32 mm nominal.",
                "status": "active",
                "sourceTurnIds": [first[0].turn_id],
                "supersedesClaimId": None,
            }]
            return summary
        correction_turn = request["turns"][-1]["turnId"]
        summary = copy.deepcopy(request["previous_summary"])
        summary["summaryRevision"] = request["expected_summary_revision"]
        summary["throughTurnSequence"] = request["through_turn_sequence"]
        summary["userClaims"][0]["status"] = "superseded"
        summary["userClaims"].append({
            "claimId": "claim-nominal-30",
            "text": "The user corrected the nominal to 30 mm.",
            "status": "active",
            "sourceTurnIds": [correction_turn],
            "supersedesClaimId": "claim-nominal-32",
        })
        summary["corrections"] = [{
            "text": "Use 30 mm, not the earlier 32 mm claim.",
            "sourceTurnIds": [correction_turn],
            "supersededClaimIds": ["claim-nominal-32"],
        }]
        return summary

    provider = FakeSummaryProvider(factory)
    service = ContinuityService(
        repository, provider, config=ContinuityConfig()
    )
    asyncio.run(service.prepare_turn(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
        classification="action_write",
        message="Build the first preview.",
        stable_scope=_scope(),
        apply_to_prompt=True,
    ))
    _commit_turns(
        repository,
        principal,
        conversation.conversation_id,
        session.agent_session_id,
        7,
        start=8,
        correction_last=True,
    )
    asyncio.run(service.prepare_turn(
        principal=principal,
        conversation_id=conversation.conversation_id,
        agent_session_id=session.agent_session_id,
        classification="action_write",
        message="Use my correction in the next preview.",
        stable_scope=_scope(),
        apply_to_prompt=True,
    ))
    current = repository.get_current_summary(principal, session.agent_session_id)
    assert current.summary_revision == 2
    claims = {item["claimId"]: item for item in current.summary["userClaims"]}
    assert claims["claim-nominal-32"]["status"] == "superseded"
    assert claims["claim-nominal-30"]["status"] == "active"
    assert current.summary["corrections"][0]["supersededClaimIds"] == [
        "claim-nominal-32"
    ]
