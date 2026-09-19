"""Domain-neutral observe, plan, validate, repair, and preview runtime.

The runtime deliberately does not expose model reasoning and does not commit
domain state. Domain adapters supply trusted observations, semantic planning,
deterministic simulation, validation, and a narrowly scoped repair function.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
import threading
import time
from typing import Any, Callable, Mapping, Sequence


VERIFIED_WORKFLOW_SCHEMA_VERSION = 1
_ISSUE_SEVERITIES = frozenset({"info", "warning", "error", "blocked"})
_RECOVERABILITY = frozenset(
    {"not_applicable", "recoverable", "human_required", "terminal"}
)
_BLOCKING_SEVERITIES = frozenset({"error", "blocked"})
_TERMINAL_STATUSES = frozenset(
    {"preview_ready", "blocked", "failed", "budget_exhausted"}
)
_MAX_ISSUE_DETAILS_BYTES = 8_192


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("verified workflow values must be finite JSON") from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_text(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _token(value: Any, field_name: str, maximum: int = 120) -> str:
    text = _clean_text(value, maximum)
    if (
        not text
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        raise ValueError(f"{field_name} must be a stable ASCII token")
    return text


def _bounded_details(value: Mapping[str, Any] | None) -> dict[str, Any]:
    details = deepcopy(dict(value or {}))
    encoded = _canonical_bytes(details)
    if len(encoded) <= _MAX_ISSUE_DETAILS_BYTES:
        return details
    return {
        "detailsTruncated": True,
        "detailsSha256": hashlib.sha256(encoded).hexdigest(),
        "originalBytes": len(encoded),
    }


@dataclass(frozen=True)
class VerifiedWorkflowBudget:
    """Fail-closed limits for one preview-only workflow run."""

    max_repair_attempts: int = 2
    max_tool_calls: int = 16
    max_elapsed_ms: int = 30_000

    def __post_init__(self) -> None:
        for field_name, value, maximum in (
            ("max_repair_attempts", self.max_repair_attempts, 10),
            ("max_tool_calls", self.max_tool_calls, 100),
            ("max_elapsed_ms", self.max_elapsed_ms, 300_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (0 if field_name == "max_repair_attempts" else 1)
                or value > maximum
            ):
                raise ValueError(f"{field_name} is outside its supported bound")

    def public_dict(self) -> dict[str, int]:
        return {
            "maxRepairAttempts": self.max_repair_attempts,
            "maxToolCalls": self.max_tool_calls,
            "maxElapsedMs": self.max_elapsed_ms,
        }


@dataclass(frozen=True)
class VerifiedWorkflowIssue:
    """Typed validator or execution finding used for repair decisions."""

    code: str
    severity: str
    message: str
    recoverability: str = "not_applicable"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _token(self.code, "issue code")
        if self.severity not in _ISSUE_SEVERITIES:
            raise ValueError("unsupported workflow issue severity")
        if self.recoverability not in _RECOVERABILITY:
            raise ValueError("unsupported workflow issue recoverability")
        if not _clean_text(self.message, 600):
            raise ValueError("workflow issue message is required")
        _bounded_details(self.details)

    @property
    def blocking(self) -> bool:
        return self.severity in _BLOCKING_SEVERITIES

    def public_dict(self) -> dict[str, Any]:
        value = {
            "code": self.code,
            "severity": self.severity,
            "message": _clean_text(self.message, 600),
            "recoverability": self.recoverability,
        }
        details = _bounded_details(self.details)
        if details:
            value["details"] = details
        return value


@dataclass(frozen=True)
class VerifiedWorkflowRepair:
    """A permitted deterministic plan correction."""

    plan: Any
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _token(self.code, "repair code")
        if not _clean_text(self.message, 600):
            raise ValueError("repair message is required")
        _bounded_details(self.details)

    def public_dict(self, *, attempt: int) -> dict[str, Any]:
        value = {
            "attempt": attempt,
            "code": self.code,
            "message": _clean_text(self.message, 600),
            "resultingPlanHash": _fingerprint(self.plan),
        }
        details = _bounded_details(self.details)
        if details:
            value["details"] = details
        return value


@dataclass(frozen=True)
class VerifiedWorkflowResult:
    """Terminal preview run plus the final domain plan and output."""

    trace: Mapping[str, Any]
    plan: Any = None
    output: Any = None


class _BudgetExceeded(RuntimeError):
    pass


class BoundedWorkflowRunStore:
    """Owner-scoped TTL/LRU store for public operational run traces."""

    def __init__(
        self,
        *,
        max_runs: int = 256,
        ttl_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_runs < 1 or max_runs > 10_000:
            raise ValueError("max_runs is outside its supported bound")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive and finite")
        self.max_runs = int(max_runs)
        self.ttl_seconds = float(ttl_seconds)
        self.clock = clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[
            tuple[str, str], tuple[float, dict[str, Any]]
        ] = OrderedDict()

    def _prune(self, now: float) -> None:
        expired = [
            key for key, (expires_at, _) in self._entries.items()
            if expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_runs:
            self._entries.popitem(last=False)

    def put(
        self,
        owner_key: str,
        trace: Mapping[str, Any],
    ) -> None:
        owner = _token(owner_key, "owner key", 160)
        run_id = _token(trace.get("runId"), "runId")
        now = float(self.clock())
        with self._lock:
            key = (owner, run_id)
            self._entries[key] = (
                now + self.ttl_seconds,
                deepcopy(dict(trace)),
            )
            self._entries.move_to_end(key)
            self._prune(now)

    def get(self, owner_key: str, run_id: str) -> dict[str, Any] | None:
        owner = _token(owner_key, "owner key", 160)
        identifier = _token(run_id, "runId")
        now = float(self.clock())
        with self._lock:
            self._prune(now)
            key = (owner, identifier)
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return deepcopy(entry[1])


class VerifiedWorkflowRuntime:
    """Execute one bounded preview workflow against trusted domain callbacks."""

    def __init__(
        self,
        *,
        run_store: BoundedWorkflowRunStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.clock = clock
        self.run_store = run_store or BoundedWorkflowRunStore(clock=clock)

    @staticmethod
    def _blocking(issues: Sequence[VerifiedWorkflowIssue]) -> list[VerifiedWorkflowIssue]:
        return [issue for issue in issues if issue.blocking]

    @staticmethod
    def _public_issues(
        issues: Sequence[VerifiedWorkflowIssue],
    ) -> list[dict[str, Any]]:
        return [issue.public_dict() for issue in issues]

    def run_preview(
        self,
        *,
        owner_key: str,
        workflow_id: str,
        goal: str,
        request_identity: Mapping[str, Any],
        source_binding: Mapping[str, Any],
        hard_constraints: Sequence[str],
        soft_objectives: Sequence[str],
        observe: Callable[[], Any],
        build_plan: Callable[[Any], Any],
        validate_plan: Callable[[Any, Any], Sequence[VerifiedWorkflowIssue]],
        simulate: Callable[[Any, Any, int], Any],
        validate_result: Callable[
            [Any, Any, Any, int], Sequence[VerifiedWorkflowIssue]
        ],
        repair: Callable[
            [Any, Any, Sequence[VerifiedWorkflowIssue], int],
            VerifiedWorkflowRepair | None,
        ]
        | None = None,
        classify_error: Callable[[Exception, str], VerifiedWorkflowIssue]
        | None = None,
        budget: VerifiedWorkflowBudget | None = None,
    ) -> VerifiedWorkflowResult:
        """Run through preview only; this method has no commit callback."""

        workflow = _token(workflow_id, "workflowId")
        owner = _token(owner_key, "owner key", 160)
        objective = _clean_text(goal, 600)
        if not objective:
            raise ValueError("workflow goal is required")
        limits = budget or VerifiedWorkflowBudget()
        binding = deepcopy(dict(source_binding))
        identity = deepcopy(dict(request_identity))
        run_id = "vwr-" + _fingerprint(
            {
                "workflowId": workflow,
                "requestIdentity": identity,
                "sourceBinding": binding,
            }
        )[:24]
        started = float(self.clock())
        trace: dict[str, Any] = {
            "schemaVersion": VERIFIED_WORKFLOW_SCHEMA_VERSION,
            "runId": run_id,
            "workflowId": workflow,
            "mode": "preview",
            "goal": objective,
            "status": "running",
            "sourceBinding": binding,
            "requestFingerprint": _fingerprint(identity),
            "hardConstraints": [
                _clean_text(item, 240) for item in hard_constraints
                if _clean_text(item, 240)
            ],
            "softObjectives": [
                _clean_text(item, 240) for item in soft_objectives
                if _clean_text(item, 240)
            ],
            "budget": limits.public_dict(),
            "counters": {
                "toolCalls": 0,
                "repairAttempts": 0,
                "elapsedMs": 0,
            },
            "steps": [],
            "attempts": [],
            "corrections": [],
            "issues": [],
            "result": None,
        }

        def elapsed_ms() -> int:
            return max(0, int(round((float(self.clock()) - started) * 1000)))

        def persist() -> None:
            trace["counters"]["elapsedMs"] = elapsed_ms()
            self.run_store.put(owner, trace)

        def ensure_budget() -> None:
            trace["counters"]["elapsedMs"] = elapsed_ms()
            if trace["counters"]["elapsedMs"] > limits.max_elapsed_ms:
                raise _BudgetExceeded("workflow_elapsed_budget_exceeded")
            if trace["counters"]["toolCalls"] >= limits.max_tool_calls:
                raise _BudgetExceeded("workflow_tool_call_budget_exceeded")

        def execute_step(
            step_id: str,
            label: str,
            callback: Callable[[], Any],
            *,
            attempt: int | None = None,
        ) -> Any:
            ensure_budget()
            step = {
                "stepId": _token(step_id, "stepId"),
                "label": _clean_text(label, 160),
                "status": "running",
                "attempt": attempt,
                "startedAtMs": elapsed_ms(),
                "durationMs": 0,
                "issueCodes": [],
            }
            trace["steps"].append(step)
            trace["counters"]["toolCalls"] += 1
            persist()
            before = float(self.clock())
            try:
                result = callback()
                ensure_budget()
            except Exception:
                step["status"] = "failed"
                step["durationMs"] = max(
                    0, int(round((float(self.clock()) - before) * 1000))
                )
                persist()
                raise
            step["status"] = "succeeded"
            step["durationMs"] = max(
                0, int(round((float(self.clock()) - before) * 1000))
            )
            persist()
            return result

        def add_issues(
            values: Sequence[VerifiedWorkflowIssue],
            *,
            step_id: str,
        ) -> list[VerifiedWorkflowIssue]:
            issues = list(values or [])
            for issue in issues:
                if not isinstance(issue, VerifiedWorkflowIssue):
                    raise TypeError("validators must return VerifiedWorkflowIssue values")
            trace["issues"].extend(self._public_issues(issues))
            for step in reversed(trace["steps"]):
                if step["stepId"] == step_id:
                    step["issueCodes"] = [issue.code for issue in issues]
                    break
            persist()
            return issues

        def classify(exc: Exception, phase: str) -> VerifiedWorkflowIssue:
            if isinstance(exc, _BudgetExceeded):
                return VerifiedWorkflowIssue(
                    code=str(exc),
                    severity="blocked",
                    message="The verified workflow exhausted its configured budget.",
                    recoverability="human_required",
                    details={"phase": phase},
                )
            if classify_error is not None:
                value = classify_error(exc, phase)
                if not isinstance(value, VerifiedWorkflowIssue):
                    raise TypeError("classify_error must return VerifiedWorkflowIssue")
                return value
            return VerifiedWorkflowIssue(
                code="workflow_execution_failed",
                severity="error",
                message="The verified workflow could not complete this phase.",
                recoverability="terminal",
                details={"phase": phase, "exceptionType": type(exc).__name__},
            )

        observation = None
        plan = None
        output = None
        try:
            observation = execute_step(
                "observe",
                "Observe trusted current state",
                observe,
            )
            plan = execute_step(
                "build-plan",
                "Build semantic execution plan",
                lambda: build_plan(observation),
            )
            plan_issues = execute_step(
                "validate-plan",
                "Validate plan and authority",
                lambda: list(validate_plan(plan, observation)),
            )
            plan_issues = add_issues(plan_issues, step_id="validate-plan")
            if self._blocking(plan_issues):
                trace["status"] = "blocked"
                trace["result"] = {"previewCreated": False}
                persist()
                return VerifiedWorkflowResult(trace=trace, plan=plan)

            maximum_attempts = limits.max_repair_attempts + 1
            for attempt in range(1, maximum_attempts + 1):
                attempt_record = {
                    "attempt": attempt,
                    "planHash": _fingerprint(plan),
                    "status": "running",
                    "issueCodes": [],
                }
                trace["attempts"].append(attempt_record)
                try:
                    output = execute_step(
                        f"simulate-{attempt}",
                        "Simulate deterministic proposal",
                        lambda: simulate(plan, observation, attempt),
                        attempt=attempt,
                    )
                    result_issues = execute_step(
                        f"validate-result-{attempt}",
                        "Validate simulated result",
                        lambda: list(
                            validate_result(output, plan, observation, attempt)
                        ),
                        attempt=attempt,
                    )
                    result_issues = add_issues(
                        result_issues,
                        step_id=f"validate-result-{attempt}",
                    )
                except Exception as exc:
                    issue = classify(exc, f"simulate-{attempt}")
                    result_issues = [issue]
                    trace["issues"].append(issue.public_dict())
                    persist()

                blocking = self._blocking(result_issues)
                attempt_record["issueCodes"] = [
                    issue.code for issue in result_issues
                ]
                if not blocking:
                    attempt_record["status"] = "succeeded"
                    trace["steps"].append(
                        {
                            "stepId": "preview",
                            "label": "Publish one complete ghost preview",
                            "status": "succeeded",
                            "attempt": attempt,
                            "startedAtMs": elapsed_ms(),
                            "durationMs": 0,
                            "issueCodes": [],
                        }
                    )
                    trace["status"] = "preview_ready"
                    trace["result"] = {
                        "previewCreated": True,
                        "attempt": attempt,
                    }
                    persist()
                    return VerifiedWorkflowResult(
                        trace=trace,
                        plan=plan,
                        output=output,
                    )

                attempt_record["status"] = "rejected"
                recoverable = all(
                    issue.recoverability == "recoverable"
                    for issue in blocking
                )
                repairs_used = trace["counters"]["repairAttempts"]
                if (
                    not recoverable
                    or repair is None
                    or repairs_used >= limits.max_repair_attempts
                ):
                    trace["status"] = (
                        "budget_exhausted"
                        if repairs_used >= limits.max_repair_attempts
                        and recoverable
                        else "blocked"
                    )
                    trace["result"] = {"previewCreated": False}
                    persist()
                    return VerifiedWorkflowResult(trace=trace, plan=plan)

                decision = execute_step(
                    f"repair-{attempt}",
                    "Apply permitted deterministic repair",
                    lambda: repair(plan, observation, blocking, attempt),
                    attempt=attempt,
                )
                if decision is None:
                    trace["status"] = "blocked"
                    trace["result"] = {"previewCreated": False}
                    persist()
                    return VerifiedWorkflowResult(trace=trace, plan=plan)
                if not isinstance(decision, VerifiedWorkflowRepair):
                    raise TypeError("repair must return VerifiedWorkflowRepair")
                if _fingerprint(decision.plan) == _fingerprint(plan):
                    issue = VerifiedWorkflowIssue(
                        code="workflow_repair_made_no_change",
                        severity="blocked",
                        message="The permitted repair did not change the plan.",
                        recoverability="human_required",
                    )
                    trace["issues"].append(issue.public_dict())
                    trace["status"] = "blocked"
                    trace["result"] = {"previewCreated": False}
                    persist()
                    return VerifiedWorkflowResult(trace=trace, plan=plan)
                trace["counters"]["repairAttempts"] += 1
                trace["corrections"].append(
                    decision.public_dict(attempt=attempt)
                )
                plan = decision.plan
                persist()
        except Exception as exc:
            issue = classify(exc, "workflow")
            trace["issues"].append(issue.public_dict())
            trace["status"] = (
                "budget_exhausted"
                if isinstance(exc, _BudgetExceeded)
                else "failed"
            )
            trace["result"] = {"previewCreated": False}
            persist()
            return VerifiedWorkflowResult(trace=trace, plan=plan)

        trace["status"] = "failed"
        trace["result"] = {"previewCreated": False}
        persist()
        return VerifiedWorkflowResult(trace=trace, plan=plan, output=output)

    def get_run(self, owner_key: str, run_id: str) -> dict[str, Any] | None:
        return self.run_store.get(owner_key, run_id)


__all__ = [
    "VERIFIED_WORKFLOW_SCHEMA_VERSION",
    "BoundedWorkflowRunStore",
    "VerifiedWorkflowBudget",
    "VerifiedWorkflowIssue",
    "VerifiedWorkflowRepair",
    "VerifiedWorkflowResult",
    "VerifiedWorkflowRuntime",
]
