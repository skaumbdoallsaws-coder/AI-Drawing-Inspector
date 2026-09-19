"""Bounded, provenance-preserving conversation continuity for Sage."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from .models import (
    MemoryPrincipal,
    SummaryJobRecord,
    SummaryRecord,
    TurnRecord,
    canonical_json,
    canonical_sha256,
)
from .repository import MemoryConflictError, MemoryRepository, MemoryValidationError
from .summary_provider import (
    ContinuitySummaryProvider,
    SummaryProviderError,
    SummaryProviderResult,
)
from .telemetry import record_memory_event


SUMMARY_SCHEMA_VERSION = "sage-continuity-summary-1.0"
CONTINUITY_STATUSES = frozenset({"healthy", "degraded", "stateless"})
CONTINUITY_STALENESS = frozenset({"fresh", "soft", "hard"})


class ContinuityError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code)
        self.details = copy.deepcopy(dict(details or {}))


@dataclass(frozen=True)
class ContinuityConfig:
    recent_turns: int = 6
    summary_max_tokens: int = 1200
    history_max_tokens: int = 2400
    cross_agent_max_tokens: int = 600
    soft_stale_turns: int = 8
    soft_stale_tokens: int = 3200
    hard_stale_turns: int = 16
    hard_stale_tokens: int = 6400
    sync_refresh_timeout_seconds: float = 5.0
    summary_job_lease_seconds: float = 30.0
    stateless_read_fallback: bool = False

    @classmethod
    def from_environment(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "ContinuityConfig":
        values = os.environ if environ is None else environ
        config = cls(
            recent_turns=_env_int(values, "INSPECTORPRO_MEMORY_RECENT_TURNS", 6),
            summary_max_tokens=_env_int(
                values, "INSPECTORPRO_MEMORY_SUMMARY_MAX_TOKENS", 1200
            ),
            history_max_tokens=_env_int(
                values, "INSPECTORPRO_MEMORY_HISTORY_MAX_TOKENS", 2400
            ),
            cross_agent_max_tokens=_env_int(
                values, "INSPECTORPRO_MEMORY_CROSS_AGENT_MAX_TOKENS", 600
            ),
            soft_stale_turns=_env_int(
                values, "INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TURNS", 8
            ),
            soft_stale_tokens=_env_int(
                values, "INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TOKENS", 3200
            ),
            hard_stale_turns=_env_int(
                values, "INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TURNS", 16
            ),
            hard_stale_tokens=_env_int(
                values, "INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TOKENS", 6400
            ),
            sync_refresh_timeout_seconds=(
                _env_int(
                    values,
                    "INSPECTORPRO_MEMORY_SUMMARY_SYNC_REFRESH_TIMEOUT_MS",
                    5000,
                )
                / 1000.0
            ),
            summary_job_lease_seconds=float(
                str(
                    values.get("INSPECTORPRO_MEMORY_SUMMARY_JOB_LEASE_SECONDS")
                    or "30"
                ).strip()
            ),
            stateless_read_fallback=_env_bool(
                values, "INSPECTORPRO_MEMORY_STATELESS_READ_FALLBACK", False
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 1 <= self.recent_turns <= 20:
            raise MemoryValidationError("recent turn count must be 1-20")
        for name, value in (
            ("summary_max_tokens", self.summary_max_tokens),
            ("history_max_tokens", self.history_max_tokens),
            ("cross_agent_max_tokens", self.cross_agent_max_tokens),
            ("soft_stale_tokens", self.soft_stale_tokens),
            ("hard_stale_tokens", self.hard_stale_tokens),
        ):
            if int(value) < 1:
                raise MemoryValidationError(f"{name} must be positive")
        if self.soft_stale_turns < self.recent_turns:
            raise MemoryValidationError(
                "soft stale turns must not be below the recent-turn count"
            )
        if self.hard_stale_turns <= self.soft_stale_turns:
            raise MemoryValidationError(
                "hard stale turns must exceed soft stale turns"
            )
        if self.hard_stale_tokens <= self.soft_stale_tokens:
            raise MemoryValidationError(
                "hard stale tokens must exceed soft stale tokens"
            )
        if not 0.1 <= self.sync_refresh_timeout_seconds <= 60.0:
            raise MemoryValidationError(
                "summary refresh timeout must be between 0.1 and 60 seconds"
            )
        if not 1.0 <= self.summary_job_lease_seconds <= 3600.0:
            raise MemoryValidationError(
                "summary job lease must be between 1 and 3600 seconds"
            )


@dataclass(frozen=True)
class ContinuityProjection:
    status: str
    staleness: str
    summary: Optional[Dict[str, Any]]
    summary_revision: int
    through_turn_sequence: int
    recent_history: tuple[Dict[str, str], ...]
    recent_turn_ids: tuple[str, ...]
    omitted_turn_count: int
    unsummarized_turn_count: int
    unsummarized_token_estimate: int
    oldest_unsummarized_turn_sequence: Optional[int]
    all_unsummarized_turns_included: bool
    warnings: tuple[str, ...]
    applied_to_prompt: bool = False

    def with_prompt_application(self, applied: bool) -> "ContinuityProjection":
        return ContinuityProjection(
            **{
                **self.__dict__,
                "applied_to_prompt": bool(applied),
            }
        )

    def metadata(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "staleness": self.staleness,
            "summaryRevision": self.summary_revision,
            "throughTurnSequence": self.through_turn_sequence,
            "recentTurnIds": list(self.recent_turn_ids),
            "omittedTurnCount": self.omitted_turn_count,
            "unsummarizedTurnCount": self.unsummarized_turn_count,
            "unsummarizedTokenEstimate": self.unsummarized_token_estimate,
            "oldestUnsummarizedTurnSequence": (
                self.oldest_unsummarized_turn_sequence
            ),
            "allUnsummarizedTurnsIncluded": (
                self.all_unsummarized_turns_included
            ),
            "appliedToPrompt": self.applied_to_prompt,
            "warnings": list(self.warnings),
        }

    def prompt_summary(self) -> Optional[str]:
        if self.summary is None or self.status == "stateless":
            return None
        return canonical_json(self.summary)


class ContinuityService:
    def __init__(
        self,
        repository: MemoryRepository,
        provider: ContinuitySummaryProvider,
        *,
        config: ContinuityConfig,
        telemetry_mode: Optional[str] = None,
    ) -> None:
        config.validate()
        self.repository = repository
        self.provider = provider
        self.config = config
        self.telemetry_mode = telemetry_mode
        self._tasks: Dict[str, asyncio.Task[bool]] = {}

    async def prepare_turn(
        self,
        *,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        classification: str,
        message: str,
        stable_scope: Mapping[str, Any],
        apply_to_prompt: bool,
    ) -> ContinuityProjection:
        projection = self.snapshot(
            principal=principal,
            conversation_id=conversation_id,
            agent_session_id=agent_session_id,
        )
        if projection.staleness == "hard":
            if (
                classification == "read_only"
                and self.config.stateless_read_fallback
                and _stateless_read_candidate(message, stable_scope)
            ):
                return _stateless_projection(projection).with_prompt_application(
                    apply_to_prompt
                )
            raise ContinuityError(
                "continuity_summary_stale",
                "conversation continuity is too stale to use safely",
                details=projection.metadata(),
            )

        if (
            projection.staleness == "soft"
            and classification in {"preview", "action_write"}
        ):
            refreshed = await self._refresh_to_latest(
                principal=principal,
                conversation_id=conversation_id,
                agent_session_id=agent_session_id,
                stable_scope=stable_scope,
                timeout=self.config.sync_refresh_timeout_seconds,
            )
            projection = self.snapshot(
                principal=principal,
                conversation_id=conversation_id,
                agent_session_id=agent_session_id,
            )
            if not refreshed or projection.staleness != "fresh":
                code = (
                    "continuity_summary_stale"
                    if projection.staleness == "hard"
                    else "continuity_summary_refresh_required"
                )
                raise ContinuityError(
                    code,
                    "continuity summary must be refreshed before this action",
                    details=projection.metadata(),
                )

        pending = self.repository.get_pending_summary_job(
            principal, agent_session_id
        )
        if pending is not None and pending.job_id not in self._tasks:
            self._schedule_job(principal, pending, stable_scope)
        return projection.with_prompt_application(apply_to_prompt)

    def snapshot(
        self,
        *,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
    ) -> ContinuityProjection:
        turns = _all_committed_turns(
            self.repository, principal, agent_session_id
        )
        if turns and turns[0].conversation_id != conversation_id:
            raise MemoryValidationError("agent session does not belong to conversation")
        current = self.repository.get_current_summary(principal, agent_session_id)
        warnings: list[str] = []
        summary: Optional[Dict[str, Any]] = None
        through = 0
        summary_revision = 0
        if current is not None:
            try:
                summary = validate_continuity_summary(
                    current.summary,
                    expected_summary_revision=current.summary_revision,
                    expected_through_turn_sequence=current.through_turn_sequence,
                    allowed_turn_ids={turn.turn_id for turn in turns},
                    maximum_tokens=self.config.summary_max_tokens,
                )
                through = current.through_turn_sequence
                summary_revision = current.summary_revision
            except MemoryValidationError:
                warnings.append("continuity_summary_invalid")
        latest_job = self.repository.get_latest_summary_job(
            principal, agent_session_id
        )
        if (
            latest_job is not None
            and latest_job.status == "failed"
            and latest_job.target_through_turn_sequence > through
        ):
            warnings.append("continuity_summary_refresh_failed")

        unsummarized = [turn for turn in turns if turn.sequence > through]
        unsummarized_tokens = sum(estimate_turn_tokens(turn) for turn in unsummarized)
        selected = select_recent_complete_turns(
            turns,
            maximum_turns=self.config.recent_turns,
            maximum_tokens=self.config.history_max_tokens,
        )
        selected_ids = {turn.turn_id for turn in selected}
        all_unsummarized = all(
            turn.turn_id in selected_ids for turn in unsummarized
        )
        hard = (
            len(unsummarized) > self.config.hard_stale_turns
            or unsummarized_tokens > self.config.hard_stale_tokens
        )
        soft = (
            hard
            or len(unsummarized) > self.config.soft_stale_turns
            or unsummarized_tokens > self.config.soft_stale_tokens
            or not all_unsummarized
        )
        if hard:
            staleness = "hard"
            warnings.append("continuity_summary_hard_stale")
        elif soft:
            staleness = "soft"
            warnings.append("continuity_summary_soft_stale")
        else:
            staleness = "fresh"
        history: list[Dict[str, str]] = []
        for turn in selected:
            history.extend(turn_history_messages(turn))
        return ContinuityProjection(
            status="degraded" if soft else "healthy",
            staleness=staleness,
            summary=copy.deepcopy(summary),
            summary_revision=summary_revision,
            through_turn_sequence=through,
            recent_history=tuple(history),
            recent_turn_ids=tuple(turn.turn_id for turn in selected),
            omitted_turn_count=max(0, len(turns) - len(selected)),
            unsummarized_turn_count=len(unsummarized),
            unsummarized_token_estimate=unsummarized_tokens,
            oldest_unsummarized_turn_sequence=(
                unsummarized[0].sequence if unsummarized else None
            ),
            all_unsummarized_turns_included=all_unsummarized,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def schedule_after_commit(
        self,
        *,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        stable_scope: Mapping[str, Any],
    ) -> Optional[SummaryJobRecord]:
        turns = _all_committed_turns(
            self.repository, principal, agent_session_id
        )
        current = self.repository.get_current_summary(principal, agent_session_id)
        through = current.through_turn_sequence if current is not None else 0
        unsummarized = [turn for turn in turns if turn.sequence > through]
        if not unsummarized:
            return None
        token_estimate = sum(estimate_turn_tokens(turn) for turn in unsummarized)
        if (
            len(unsummarized) <= self.config.soft_stale_turns
            and token_estimate <= self.config.soft_stale_tokens
        ):
            return None
        target = unsummarized[-1].sequence
        job = self.repository.enqueue_summary_job(
            principal,
            conversation_id,
            agent_session_id,
            target_through_turn_sequence=target,
            source_turn_sha256=source_turn_range_sha256(turns, target),
        )
        if job.status in {"pending", "running"}:
            self._schedule_job(principal, job, stable_scope)
        return job

    async def _refresh_to_latest(
        self,
        *,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        stable_scope: Mapping[str, Any],
        timeout: float,
    ) -> bool:
        turns = _all_committed_turns(
            self.repository, principal, agent_session_id
        )
        if not turns:
            return True
        target = turns[-1].sequence
        current = self.repository.get_current_summary(principal, agent_session_id)
        if current is not None and current.through_turn_sequence >= target:
            return True
        job = self.repository.enqueue_summary_job(
            principal,
            conversation_id,
            agent_session_id,
            target_through_turn_sequence=target,
            source_turn_sha256=source_turn_range_sha256(turns, target),
        )
        task = self._tasks.get(job.job_id)
        if task is None:
            task = asyncio.create_task(
                self._process_job(principal, job, stable_scope)
            )
            self._track_task(job.job_id, task)
        try:
            return bool(await asyncio.wait_for(asyncio.shield(task), timeout=timeout))
        except asyncio.TimeoutError:
            return False

    def _schedule_job(
        self,
        principal: MemoryPrincipal,
        job: SummaryJobRecord,
        stable_scope: Mapping[str, Any],
    ) -> None:
        existing = self._tasks.get(job.job_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._process_job(principal, job, stable_scope))
        self._track_task(job.job_id, task)

    def _track_task(self, job_id: str, task: asyncio.Task[bool]) -> None:
        self._tasks[job_id] = task

        def done(_task: asyncio.Task[bool]) -> None:
            self._tasks.pop(job_id, None)

        task.add_done_callback(done)

    async def _process_job(
        self,
        principal: MemoryPrincipal,
        job: SummaryJobRecord,
        stable_scope: Mapping[str, Any],
    ) -> bool:
        started = time.perf_counter()
        try:
            claimed = self.repository.claim_summary_job(
                principal,
                job.job_id,
                lease_seconds=self.config.summary_job_lease_seconds,
            )
        except MemoryConflictError:
            return False
        if self.telemetry_mode is not None:
            record_memory_event(
                "memory.summary.started",
                mode=self.telemetry_mode,
                session_id=claimed.agent_session_id,
            )
        try:
            turns = _all_committed_turns(
                self.repository, principal, claimed.agent_session_id
            )
            turns = [
                turn
                for turn in turns
                if turn.sequence <= claimed.target_through_turn_sequence
            ]
            if not turns or turns[-1].sequence != claimed.target_through_turn_sequence:
                raise MemoryValidationError("summary job turn range is incomplete")
            current = self.repository.get_current_summary(
                principal, claimed.agent_session_id
            )
            if (
                current is not None
                and current.through_turn_sequence
                >= claimed.target_through_turn_sequence
            ):
                self.repository.complete_summary_job(principal, claimed.job_id)
                return True
            through = current.through_turn_sequence if current is not None else 0
            incremental = [turn for turn in turns if turn.sequence > through]
            session = self.repository.get_agent_session(
                principal, claimed.agent_session_id
            )
            provider_result = await self.provider.generate(
                previous_summary=current.summary if current is not None else None,
                turns=[summary_turn_payload(turn) for turn in incremental],
                stable_scope=stable_scope,
                expected_summary_revision=session.summary_revision + 1,
                through_turn_sequence=claimed.target_through_turn_sequence,
            )
            summary = validate_continuity_summary(
                provider_result.summary,
                expected_summary_revision=session.summary_revision + 1,
                expected_through_turn_sequence=(
                    claimed.target_through_turn_sequence
                ),
                allowed_turn_ids={turn.turn_id for turn in turns},
                maximum_tokens=self.config.summary_max_tokens,
            )
            committed = self.repository.create_summary(
                principal,
                claimed.conversation_id,
                claimed.agent_session_id,
                through_turn_sequence=claimed.target_through_turn_sequence,
                source_turn_sha256=claimed.source_turn_sha256,
                summary=summary,
                model_metadata=provider_result.metadata,
                expected_summary_revision=session.summary_revision,
            )
            self.repository.complete_summary_job(principal, claimed.job_id)
            if self.telemetry_mode is not None:
                record_memory_event(
                    "memory.summary.committed",
                    mode=self.telemetry_mode,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    session_id=claimed.agent_session_id,
                    summary_revision=committed.summary_revision,
                )
            return True
        except asyncio.CancelledError:
            try:
                self.repository.fail_summary_job(
                    principal,
                    claimed.job_id,
                    error_code="summary_job_interrupted",
                )
            finally:
                raise
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "summary_generation_failed")
            try:
                self.repository.fail_summary_job(
                    principal, claimed.job_id, error_code=code
                )
            except Exception:
                pass
            if self.telemetry_mode is not None:
                record_memory_event(
                    "memory.summary.invalid",
                    mode=self.telemetry_mode,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    status="error",
                    error_code=code,
                    session_id=claimed.agent_session_id,
                )
            return False

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        self.cancel_pending_tasks()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def cancel_pending_tasks(self) -> None:
        for task in tuple(self._tasks.values()):
            task.cancel()


def validate_continuity_summary(
    value: Mapping[str, Any],
    *,
    expected_summary_revision: int,
    expected_through_turn_sequence: int,
    allowed_turn_ids: set[str],
    maximum_tokens: int,
) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MemoryValidationError("continuity summary must be an object")
    summary = json.loads(canonical_json(dict(value)))
    required = {
        "schemaVersion",
        "summaryRevision",
        "throughTurnSequence",
        "objective",
        "userClaims",
        "continuityDecisions",
        "assumptions",
        "corrections",
        "openQuestions",
        "referencedEntities",
        "sourceEvidenceRefs",
        "warnings",
    }
    _exact_keys(summary, required, "continuity summary")
    if summary["schemaVersion"] != SUMMARY_SCHEMA_VERSION:
        raise MemoryValidationError("unsupported continuity summary schema")
    if not _is_int(summary["summaryRevision"]) or (
        summary["summaryRevision"] != int(expected_summary_revision)
    ):
        raise MemoryValidationError("continuity summary revision is invalid")
    if not _is_int(summary["throughTurnSequence"]) or (
        summary["throughTurnSequence"]
        != int(expected_through_turn_sequence)
    ):
        raise MemoryValidationError("continuity summary turn range is invalid")

    _source_item(summary["objective"], "objective", allowed_turn_ids)
    claims = _array(summary["userClaims"], "userClaims")
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        path = f"userClaims[{index}]"
        _exact_keys(
            claim,
            {"claimId", "text", "status", "sourceTurnIds", "supersedesClaimId"},
            path,
        )
        claim_id = _text(claim["claimId"], f"{path}.claimId")
        if claim_id in claim_ids:
            raise MemoryValidationError("user claim IDs must be unique")
        claim_ids.add(claim_id)
        _text(claim["text"], f"{path}.text")
        if claim["status"] not in {"active", "superseded", "withdrawn"}:
            raise MemoryValidationError(f"{path}.status is invalid")
        _source_ids(claim["sourceTurnIds"], path, allowed_turn_ids)
        supersedes = claim["supersedesClaimId"]
        if supersedes is not None:
            _text(supersedes, f"{path}.supersedesClaimId")

    decisions = _array(summary["continuityDecisions"], "continuityDecisions")
    for index, decision in enumerate(decisions):
        path = f"continuityDecisions[{index}]"
        _exact_keys(decision, {"text", "authority", "sourceTurnIds"}, path)
        _text(decision["text"], f"{path}.text")
        if decision["authority"] != "conversation_only":
            raise MemoryValidationError(
                "continuity decisions must remain conversation_only"
            )
        _source_ids(decision["sourceTurnIds"], path, allowed_turn_ids)

    assumptions = _array(summary["assumptions"], "assumptions")
    for index, assumption in enumerate(assumptions):
        path = f"assumptions[{index}]"
        _exact_keys(assumption, {"text", "status", "sourceTurnIds"}, path)
        _text(assumption["text"], f"{path}.text")
        if assumption["status"] not in {"open", "resolved", "dismissed"}:
            raise MemoryValidationError(f"{path}.status is invalid")
        _source_ids(assumption["sourceTurnIds"], path, allowed_turn_ids)

    corrections = _array(summary["corrections"], "corrections")
    for index, correction in enumerate(corrections):
        path = f"corrections[{index}]"
        _exact_keys(
            correction,
            {"text", "sourceTurnIds", "supersededClaimIds"},
            path,
        )
        _text(correction["text"], f"{path}.text")
        _source_ids(correction["sourceTurnIds"], path, allowed_turn_ids)
        _unique_text_array(
            correction["supersededClaimIds"], f"{path}.supersededClaimIds"
        )

    for index, question in enumerate(_array(summary["openQuestions"], "openQuestions")):
        _source_item(question, f"openQuestions[{index}]", allowed_turn_ids)

    for index, entity in enumerate(
        _array(summary["referencedEntities"], "referencedEntities")
    ):
        path = f"referencedEntities[{index}]"
        _exact_keys(entity, {"kind", "id", "label"}, path)
        for field in ("kind", "id", "label"):
            _text(entity[field], f"{path}.{field}")
    _unique_text_array(summary["sourceEvidenceRefs"], "sourceEvidenceRefs")
    _text_array(summary["warnings"], "warnings")
    if estimate_tokens(canonical_json(summary)) > int(maximum_tokens):
        raise MemoryValidationError("continuity summary exceeds its token budget")
    return summary


def estimate_tokens(value: str) -> int:
    escaped = json.dumps(str(value or ""), ensure_ascii=True)[1:-1]
    return int(math.ceil(len(escaped) / 4.0))


def estimate_turn_tokens(turn: TurnRecord) -> int:
    text = "\n".join(
        f"[{item['role']}]\n{item['content']}" for item in turn_history_messages(turn)
    )
    return estimate_tokens(text)


def turn_history_messages(turn: TurnRecord) -> list[Dict[str, str]]:
    messages: list[Dict[str, str]] = []
    user = _message_text(turn.user_message)
    if user:
        messages.append({"role": "user", "content": user})
    assistant = _assistant_text(turn.assistant_result)
    if assistant:
        messages.append({"role": "assistant", "content": assistant})
    return messages


def select_recent_complete_turns(
    turns: Sequence[TurnRecord],
    *,
    maximum_turns: int,
    maximum_tokens: int,
) -> tuple[TurnRecord, ...]:
    selected: list[TurnRecord] = []
    used = 0
    for turn in reversed(tuple(turns)):
        if len(selected) >= int(maximum_turns):
            break
        cost = estimate_turn_tokens(turn)
        if used + cost > int(maximum_tokens):
            break
        selected.append(turn)
        used += cost
    selected.reverse()
    return tuple(selected)


def summary_turn_payload(turn: TurnRecord) -> Dict[str, Any]:
    return {
        "turnId": turn.turn_id,
        "sequence": turn.sequence,
        "user": _message_text(turn.user_message),
        "assistant": _assistant_text(turn.assistant_result),
    }


def source_turn_range_sha256(
    turns: Sequence[TurnRecord], target_sequence: int
) -> str:
    return canonical_sha256(
        [
            {
                "turnId": turn.turn_id,
                "sequence": turn.sequence,
                "requestSha256": turn.request_sha256,
                "assistantResultSha256": canonical_sha256(
                    turn.assistant_result or {}
                ),
            }
            for turn in turns
            if turn.sequence <= int(target_sequence)
        ]
    )


def validate_cross_agent_projection(text: Optional[str], maximum_tokens: int) -> None:
    if text is None or text == "":
        return
    if estimate_tokens(text) > int(maximum_tokens):
        raise ContinuityError(
            "cross_agent_projection_budget_exceeded",
            "cross-agent continuity projection exceeds its bounded allocation",
            status_code=422,
        )


def _all_committed_turns(
    repository: MemoryRepository,
    principal: MemoryPrincipal,
    agent_session_id: str,
) -> list[TurnRecord]:
    turns: list[TurnRecord] = []
    after = 0
    while True:
        page = list(
            repository.list_agent_session_turns(
                principal,
                agent_session_id,
                after_sequence=after,
                limit=500,
                committed_only=True,
            )
        )
        turns.extend(page)
        if len(page) < 500:
            return turns
        after = page[-1].sequence


def _message_text(message: Mapping[str, Any]) -> str:
    value = message.get("content") or message.get("text") or ""
    return str(value).strip() if isinstance(value, str) else ""


def _assistant_text(result: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(result, Mapping):
        return ""
    for key in ("response", "content", "text", "message"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _stateless_projection(projection: ContinuityProjection) -> ContinuityProjection:
    warnings = tuple(
        dict.fromkeys((*projection.warnings, "continuity_stateless_fallback"))
    )
    return ContinuityProjection(
        status="stateless",
        staleness=projection.staleness,
        summary=None,
        summary_revision=projection.summary_revision,
        through_turn_sequence=projection.through_turn_sequence,
        recent_history=(),
        recent_turn_ids=(),
        omitted_turn_count=(
            projection.omitted_turn_count + len(projection.recent_turn_ids)
        ),
        unsummarized_turn_count=projection.unsummarized_turn_count,
        unsummarized_token_estimate=projection.unsummarized_token_estimate,
        oldest_unsummarized_turn_sequence=(
            projection.oldest_unsummarized_turn_sequence
        ),
        all_unsummarized_turns_included=False,
        warnings=warnings,
    )


def _stateless_read_candidate(
    message: str, stable_scope: Mapping[str, Any]
) -> bool:
    if str(stable_scope.get("kind") or "none") == "none":
        return False
    normalized = " ".join(str(message or "").lower().split())
    continuity_markers = (
        " earlier ",
        " previous ",
        " we decided ",
        " you said ",
        " continue ",
        " same one ",
        " that one ",
        " again ",
        " correction ",
    )
    padded = f" {normalized} "
    return not any(marker in padded for marker in continuity_markers)


def _source_item(value: Any, path: str, allowed_turn_ids: set[str]) -> None:
    _exact_keys(value, {"text", "sourceTurnIds"}, path)
    _text(value["text"], f"{path}.text")
    _source_ids(value["sourceTurnIds"], path, allowed_turn_ids)


def _source_ids(value: Any, path: str, allowed_turn_ids: set[str]) -> None:
    ids = _unique_text_array(value, f"{path}.sourceTurnIds")
    if not ids:
        raise MemoryValidationError(f"{path}.sourceTurnIds must not be empty")
    unknown = sorted(set(ids) - set(allowed_turn_ids))
    if unknown:
        raise MemoryValidationError(f"{path} cites unknown source turn IDs")


def _exact_keys(value: Any, expected: set[str], path: str) -> None:
    if not isinstance(value, dict):
        raise MemoryValidationError(f"{path} must be an object")
    keys = set(value)
    if keys != expected:
        raise MemoryValidationError(
            f"{path} fields are invalid: missing={sorted(expected - keys)}, "
            f"unknown={sorted(keys - expected)}"
        )


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise MemoryValidationError(f"{path} must be an array")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{path} must be a non-empty string")
    return value


def _text_array(value: Any, path: str) -> list[str]:
    result = _array(value, path)
    for index, item in enumerate(result):
        _text(item, f"{path}[{index}]")
    return result


def _unique_text_array(value: Any, path: str) -> list[str]:
    result = _text_array(value, path)
    if len(result) != len(set(result)):
        raise MemoryValidationError(f"{path} values must be unique")
    return result


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _env_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = str(values.get(name) or str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise MemoryValidationError(f"{name} must be an integer") from exc


def _env_bool(
    values: Mapping[str, str], name: str, default: bool
) -> bool:
    raw = values.get(name)
    if raw is None:
        return bool(default)
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise MemoryValidationError(f"{name} must be a boolean")


__all__ = [
    "CONTINUITY_STATUSES",
    "CONTINUITY_STALENESS",
    "ContinuityConfig",
    "ContinuityError",
    "ContinuityProjection",
    "ContinuityService",
    "SUMMARY_SCHEMA_VERSION",
    "estimate_tokens",
    "estimate_turn_tokens",
    "select_recent_complete_turns",
    "source_turn_range_sha256",
    "summary_turn_payload",
    "turn_history_messages",
    "validate_continuity_summary",
    "validate_cross_agent_projection",
]
