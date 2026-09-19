"""Contract tests for the domain-neutral verified workflow runtime."""

from __future__ import annotations

from ai_inspector.verified_workflows import (
    VerifiedWorkflowBudget,
    VerifiedWorkflowIssue,
    VerifiedWorkflowRepair,
    VerifiedWorkflowRuntime,
)


def _runtime():
    return VerifiedWorkflowRuntime()


def _base_kwargs():
    return {
        "owner_key": "owner-test",
        "workflow_id": "facility-layout-preview",
        "goal": "Arrange the selected machines",
        "request_identity": {"requestId": "request-1"},
        "source_binding": {
            "layoutId": "layout-1",
            "revision": "a" * 64,
        },
        "hard_constraints": ["Preserve locked placements"],
        "soft_objectives": ["Minimize travel distance"],
        "observe": lambda: {"revision": "a" * 64},
        "build_plan": lambda observation: {
            "planId": "plan-1",
            "revision": observation["revision"],
            "strategy": "balanced",
        },
        "validate_plan": lambda plan, observation: [],
        "simulate": lambda plan, observation, attempt: {
            "previewId": f"preview-{attempt}",
            "strategy": plan["strategy"],
        },
        "validate_result": lambda output, plan, observation, attempt: [],
    }


def test_successful_preview_records_truthful_operational_steps():
    runtime = _runtime()
    result = runtime.run_preview(**_base_kwargs())

    assert result.trace["status"] == "preview_ready"
    assert result.trace["result"] == {
        "previewCreated": True,
        "attempt": 1,
    }
    assert [step["stepId"] for step in result.trace["steps"]] == [
        "observe",
        "build-plan",
        "validate-plan",
        "simulate-1",
        "validate-result-1",
        "preview",
    ]
    assert all(
        step["status"] == "succeeded"
        for step in result.trace["steps"]
    )
    assert result.output["previewId"] == "preview-1"
    assert runtime.get_run(
        "owner-test", result.trace["runId"]
    ) == result.trace
    assert runtime.get_run("another-owner", result.trace["runId"]) is None


def test_recoverable_validation_failure_is_repaired_within_budget():
    kwargs = _base_kwargs()

    def validate(output, plan, _observation, _attempt):
        if plan["strategy"] == "balanced":
            return [
                VerifiedWorkflowIssue(
                    code="aisle_overlap",
                    severity="error",
                    message="The proposed row overlaps the aisle.",
                    recoverability="recoverable",
                )
            ]
        return []

    def repair(plan, _observation, issues, _attempt):
        assert [issue.code for issue in issues] == ["aisle_overlap"]
        return VerifiedWorkflowRepair(
            plan={**plan, "strategy": "flow-lanes"},
            code="select_flow_lane_strategy",
            message="Use the deterministic flow-lane strategy.",
        )

    kwargs["validate_result"] = validate
    kwargs["repair"] = repair
    result = _runtime().run_preview(**kwargs)

    assert result.trace["status"] == "preview_ready"
    assert result.trace["counters"]["repairAttempts"] == 1
    assert result.trace["attempts"][0]["status"] == "rejected"
    assert result.trace["attempts"][1]["status"] == "succeeded"
    assert result.trace["corrections"][0]["code"] == (
        "select_flow_lane_strategy"
    )
    assert result.plan["strategy"] == "flow-lanes"


def test_human_required_issue_stops_without_repairing():
    kwargs = _base_kwargs()
    repair_calls = []
    kwargs["validate_result"] = lambda *_args: [
        VerifiedWorkflowIssue(
            code="conflicting_hard_constraints",
            severity="blocked",
            message="The requested clearances cannot both fit.",
            recoverability="human_required",
        )
    ]
    kwargs["repair"] = lambda *_args: repair_calls.append(True)

    result = _runtime().run_preview(**kwargs)

    assert result.trace["status"] == "blocked"
    assert result.trace["result"]["previewCreated"] is False
    assert repair_calls == []
    assert result.trace["issues"][-1]["code"] == (
        "conflicting_hard_constraints"
    )


def test_repair_attempt_limit_fails_closed():
    kwargs = _base_kwargs()
    kwargs["budget"] = VerifiedWorkflowBudget(
        max_repair_attempts=1,
        max_tool_calls=16,
        max_elapsed_ms=30_000,
    )
    kwargs["validate_result"] = lambda *_args: [
        VerifiedWorkflowIssue(
            code="no_valid_candidate",
            severity="error",
            message="No valid candidate was found.",
            recoverability="recoverable",
        )
    ]
    kwargs["repair"] = lambda plan, *_args: VerifiedWorkflowRepair(
        plan={**plan, "strategy": "fallback"},
        code="try_fallback",
        message="Try one bounded fallback.",
    )

    result = _runtime().run_preview(**kwargs)

    assert result.trace["status"] == "budget_exhausted"
    assert result.trace["counters"]["repairAttempts"] == 1
    assert len(result.trace["attempts"]) == 2


def test_tool_call_budget_stops_before_unbounded_execution():
    kwargs = _base_kwargs()
    kwargs["budget"] = VerifiedWorkflowBudget(
        max_repair_attempts=0,
        max_tool_calls=3,
        max_elapsed_ms=30_000,
    )

    result = _runtime().run_preview(**kwargs)

    assert result.trace["status"] == "budget_exhausted"
    assert result.trace["counters"]["toolCalls"] == 3
    assert result.trace["issues"][-1]["code"] == (
        "workflow_tool_call_budget_exceeded"
    )
    assert result.output is None
