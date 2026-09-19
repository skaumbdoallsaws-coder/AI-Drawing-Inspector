"""Durable bounded runtime for the first Facility persistent design loop."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .design_base import validate_facility_design_base
from .design_brief import design_revision, validate_facility_design_brief
from .design_candidates import (
    FACILITY_DESIGN_CANDIDATE_MAXIMUM_ATTEMPTS,
    FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES,
    FacilityDesignCandidateError,
    OperationBuilder,
    SourceOperationBuilder,
    deterministic_design_operation_builder,
    enumerate_facility_design_candidate_recipes,
    execute_facility_design_candidate,
)
from .design_evaluator import (
    build_facility_design_baseline,
    classify_facility_design_alternatives,
    evaluate_facility_design_candidate,
)
from .design_repository import FacilityDesignRepository
from .manufacturing_snapshot import build_facility_manufacturing_snapshot


FACILITY_DESIGN_RUN_SCHEMA_VERSION = "facility-design-run-v1"
FACILITY_DESIGN_RUNTIME_VERSION = "facility-design-runtime-v1"
FACILITY_DESIGN_MAXIMUM_WORKFLOW_TOOL_CALLS = 16
FACILITY_DESIGN_MAXIMUM_REPAIR_ATTEMPTS = 2
FACILITY_DESIGN_MAXIMUM_ELAPSED_MILLISECONDS = 300_000
FACILITY_DESIGN_MAXIMUM_TOOL_CALLS_PER_TURN = 10
FACILITY_DESIGN_MAXIMUM_PRESENTED_ALTERNATIVES = 2
FACILITY_DESIGN_RUN_IDLE_SECONDS = 24 * 60 * 60

_RUN_STATUSES = frozenset(
    {
        "active",
        "preview_ready",
        "blocked",
        "failed",
        "budget_exhausted",
        "cancelled",
        "stale",
        "expired",
    }
)
_TERMINAL_STATUSES = _RUN_STATUSES - {"active"}
_READINESS_STATES = frozenset(
    {
        "ready",
        "retrievable",
        "ambiguous",
        "choice_open",
        "missing_authority",
        "constraint_conflict",
        "rebind_required",
        "unsupported",
        "stale",
        "stale_local_restore",
    }
)


class FacilityDesignRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignRuntimeError(code, message, details=details)


def _timestamp(value: datetime) -> str:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityDesignRuntimeError(
            "facility_design_run_invalid", f"{field} must be an ISO timestamp."
        ) from exc
    if parsed.tzinfo is None:
        _fail("facility_design_run_invalid", f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if (
        not text
        or len(text) > 160
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        _fail("facility_design_run_invalid", f"{field} must be a stable ID.")
    return text


def _sha256(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        _fail(
            "facility_design_run_invalid",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return text


def _artifact_ref(
    artifact_kind: str, artifact_id: str, artifact_revision: str
) -> dict[str, str]:
    return {
        "artifactKind": _identifier(artifact_kind, "artifactKind"),
        "artifactId": _identifier(artifact_id, "artifactId"),
        "artifactRevision": _sha256(artifact_revision, "artifactRevision"),
    }


def _validate_artifact_ref(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "artifactKind",
        "artifactId",
        "artifactRevision",
    }:
        _fail("facility_design_run_invalid", f"{field} is not an artifact handle.")
    return _artifact_ref(
        str(value["artifactKind"]),
        str(value["artifactId"]),
        str(value["artifactRevision"]),
    )


def validate_facility_design_run(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_design_run_invalid", "Facility design run must be an object.")
    expected = {
        "schemaVersion",
        "runtimeVersion",
        "runId",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "briefId",
        "briefRevision",
        "briefSemanticFingerprint",
        "baseRef",
        "sourceBundleRef",
        "providerBinding",
        "dependencyFingerprint",
        "clientGenerationId",
        "mode",
        "status",
        "readiness",
        "nextStageId",
        "stageReceipts",
        "stageOutputs",
        "candidateQueue",
        "candidateCursor",
        "candidateResults",
        "evaluationResults",
        "proposalRefs",
        "findings",
        "recoveryActions",
        "counters",
        "budget",
        "searchStatus",
        "unexpandedFrontierCount",
        "cancelRequested",
        "terminalReason",
        "createdAt",
        "updatedAt",
        "expiresAt",
    }
    result = deepcopy(dict(value))
    if (
        set(result) != expected
        or result.get("schemaVersion") != FACILITY_DESIGN_RUN_SCHEMA_VERSION
        or result.get("runtimeVersion") != FACILITY_DESIGN_RUNTIME_VERSION
        or result.get("status") not in _RUN_STATUSES
        or result.get("readiness") not in _READINESS_STATES
        or result.get("mode") not in {"production_sage", "lab"}
    ):
        _fail("facility_design_run_invalid", "Facility design run fields are invalid.")
    for field in (
        "runId",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "briefId",
        "clientGenerationId",
    ):
        result[field] = _identifier(result[field], field)
    for field in (
        "briefRevision",
        "briefSemanticFingerprint",
        "dependencyFingerprint",
    ):
        result[field] = _sha256(result[field], field)
    result["baseRef"] = _validate_artifact_ref(result["baseRef"], "baseRef")
    result["sourceBundleRef"] = _validate_artifact_ref(
        result["sourceBundleRef"], "sourceBundleRef"
    )
    provider = result["providerBinding"]
    if not isinstance(provider, Mapping) or set(provider) != {
        "provider",
        "model",
        "reasoningEffort",
        "bindingRevision",
    }:
        _fail("facility_design_run_invalid", "providerBinding fields are invalid.")
    _identifier(provider["provider"], "provider")
    _identifier(provider["model"], "model")
    if provider["reasoningEffort"] is not None:
        _identifier(provider["reasoningEffort"], "reasoningEffort")
    _sha256(provider["bindingRevision"], "providerBinding.bindingRevision")
    if result["nextStageId"] is not None:
        _identifier(result["nextStageId"], "nextStageId")
    for field in ("stageReceipts", "candidateQueue", "candidateResults", "evaluationResults", "proposalRefs"):
        if not isinstance(result[field], list):
            _fail("facility_design_run_invalid", f"{field} must be an array.")
    result["stageReceipts"] = [
        _validate_artifact_ref(item, "stageReceipts[]")
        for item in result["stageReceipts"]
    ]
    result["candidateResults"] = [
        _validate_artifact_ref(item, "candidateResults[]")
        for item in result["candidateResults"]
    ]
    result["evaluationResults"] = [
        _validate_artifact_ref(item, "evaluationResults[]")
        for item in result["evaluationResults"]
    ]
    result["proposalRefs"] = [
        _validate_artifact_ref(item, "proposalRefs[]")
        for item in result["proposalRefs"]
    ]
    if not isinstance(result["stageOutputs"], Mapping):
        _fail("facility_design_run_invalid", "stageOutputs must be an object.")
    for key, handle in result["stageOutputs"].items():
        _identifier(key, "stageOutputs key")
        result["stageOutputs"][key] = _validate_artifact_ref(
            handle, f"stageOutputs.{key}"
        )
    if (
        isinstance(result["candidateCursor"], bool)
        or not isinstance(result["candidateCursor"], int)
        or result["candidateCursor"] < 0
        or result["candidateCursor"] > len(result["candidateQueue"])
    ):
        _fail("facility_design_run_invalid", "candidateCursor is invalid.")
    if len(result["candidateQueue"]) > FACILITY_DESIGN_CANDIDATE_MAXIMUM_ATTEMPTS:
        _fail("facility_design_run_invalid", "Candidate queue exceeds its bound.")
    if not isinstance(result["findings"], list) or not isinstance(
        result["recoveryActions"], list
    ):
        _fail("facility_design_run_invalid", "Run findings must be arrays.")
    counters = result["counters"]
    budget = result["budget"]
    counter_fields = {
        "workflowToolCalls",
        "repairAttempts",
        "candidateLineages",
        "candidateExecutionAttempts",
        "elapsedMs",
    }
    budget_fields = {
        "maximumWorkflowToolCalls",
        "maximumRepairAttempts",
        "maximumCandidateLineages",
        "maximumCandidateExecutionAttempts",
        "maximumElapsedMs",
    }
    if not isinstance(counters, Mapping) or set(counters) != counter_fields:
        _fail("facility_design_run_invalid", "Run counters are invalid.")
    if not isinstance(budget, Mapping) or set(budget) != budget_fields:
        _fail("facility_design_run_invalid", "Run budget is invalid.")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in counters.values()
    ):
        _fail("facility_design_run_invalid", "Run counters must be nonnegative integers.")
    if result["searchStatus"] not in {None, "complete", "truncated"}:
        _fail("facility_design_run_invalid", "searchStatus is invalid.")
    if (
        isinstance(result["unexpandedFrontierCount"], bool)
        or not isinstance(result["unexpandedFrontierCount"], int)
        or result["unexpandedFrontierCount"] < 0
    ):
        _fail("facility_design_run_invalid", "unexpandedFrontierCount is invalid.")
    if not isinstance(result["cancelRequested"], bool):
        _fail("facility_design_run_invalid", "cancelRequested must be boolean.")
    for field in ("createdAt", "updatedAt", "expiresAt"):
        result[field] = _timestamp(_parse_timestamp(result[field], field))
    return result


def facility_design_recovery_actions(
    findings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    registry = {
        "no_layout_alternative": (
            "next_deterministic_strategy",
            "run_facility_design_preview",
            "Try the next deterministic strategy already permitted by the brief.",
        ),
        "route_blocked": (
            "reflow_same_route",
            "run_facility_design_preview",
            "Reflow the same editable route through current free space.",
        ),
        "placement_no_fit": (
            "next_fit_orientation",
            "run_facility_design_preview",
            "Try the next deterministic fit for the same movable placement.",
        ),
        "ambiguous_reference": (
            "ask_exact_referent",
            "inspect_facility_design_brief",
            "Ask the user to choose among the exact highlighted referents.",
        ),
        "evidence_not_loaded": (
            "retrieve_evidence",
            "inspect_facility_design_brief",
            "Retrieve the named bounded evidence slice.",
        ),
        "derived_artifact_expired": (
            "recompile_retained_sources",
            "run_facility_design_preview",
            "Recompile only if every retained source revision still matches.",
        ),
        "frequency_unavailable": (
            "continue_unweighted",
            "run_facility_design_preview",
            "Continue with unweighted distance unless per-shift impact was requested.",
        ),
        "base_rebind_required": (
            "ask_exact_base",
            "inspect_facility_design_brief",
            "Ask the user to bind an exact current base.",
        ),
        "constraint_conflict": (
            "ask_constraint_resolution",
            "inspect_facility_design_brief",
            "Present exact conflicting constraints for a user decision.",
        ),
        "source_revision_changed": (
            "terminate_stale_attempt",
            "inspect_facility_design_brief",
            "Terminate and wait for an explicit current-base rebind.",
        ),
    }
    actions = []
    for finding in findings:
        code = str(finding.get("code") or "")
        if code not in registry:
            continue
        action_kind, tool, postcondition = registry[code]
        affected = sorted(set(str(item) for item in finding.get("affectedIds", [])))
        semantics = {
            "findingCode": code,
            "actionKind": action_kind,
            "affectedIds": affected,
            "permittedTool": tool,
        }
        actions.append(
            {
                "actionId": f"fdlra-{design_revision(semantics)[:24]}",
                "supportedFindingCodes": [code],
                "affectedIds": affected,
                "actionKind": action_kind,
                "permittedTool": tool,
                "allowedParameterBounds": deepcopy(
                    finding.get("allowedParameterBounds") or {}
                ),
                "preservedConstraintIds": sorted(
                    set(str(item) for item in finding.get("preservedConstraintIds", []))
                ),
                "expectedPostcondition": postcondition,
                "cost": {"workflowToolCalls": 1, "repairAttempts": 1},
                "recoverability": (
                    "automatic"
                    if code in {"no_layout_alternative", "route_blocked", "placement_no_fit"}
                    else "human_required"
                ),
            }
        )
    return sorted(actions, key=lambda item: item["actionId"])


CandidateRecipeProvider = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
]
RepairProvider = Callable[
    [Mapping[str, Any], Mapping[str, Any], int], Mapping[str, Any] | None
]
ContainmentChecker = Callable[..., tuple[str, Mapping[str, Any]]]


class FacilityDesignRuntime:
    """Advance one immutable-artifact-backed design run one bounded stage at a time."""

    def __init__(
        self,
        repository: FacilityDesignRepository,
        *,
        candidate_recipe_provider: CandidateRecipeProvider | None = None,
        operation_builder: OperationBuilder | None = None,
        source_operation_builder: SourceOperationBuilder | None = None,
        repair_provider: RepairProvider | None = None,
        containment_checker: ContainmentChecker | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.candidate_recipe_provider = (
            candidate_recipe_provider or self._default_recipe_provider
        )
        self.operation_builder = operation_builder
        self.source_operation_builder = (
            source_operation_builder or deterministic_design_operation_builder
        )
        self.repair_provider = repair_provider
        self.containment_checker = containment_checker
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            _fail("facility_design_clock_invalid", "Design runtime clock is invalid.")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _unsupported_operation_builder(
        recipe: Mapping[str, Any],
        _layout: Mapping[str, Any],
        _snapshot: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        raise FacilityDesignCandidateError(
            "no_layout_alternative",
            "The selected deterministic strategy has no registered operation compiler.",
            details={"strategyId": recipe.get("strategyId")},
        )

    @staticmethod
    def _default_recipe_provider(
        brief: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        _source_bundle: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return enumerate_facility_design_candidate_recipes(
            brief=brief, snapshot=snapshot
        )

    def _store(
        self,
        run: Mapping[str, Any],
        *,
        kind: str,
        artifact_id: str,
        artifact: Mapping[str, Any],
        intrinsic_revision: str | None = None,
    ) -> dict[str, str]:
        revision = intrinsic_revision or design_revision(artifact)
        self.repository.store_artifact(
            tenant_id=run["tenantId"],
            site_id=run["siteId"],
            artifact_kind=kind,
            artifact_id=artifact_id,
            artifact_revision=revision,
            artifact=artifact,
        )
        return _artifact_ref(kind, artifact_id, revision)

    def _load(self, run: Mapping[str, Any], handle: Mapping[str, Any]) -> dict[str, Any]:
        ref = _validate_artifact_ref(handle, "artifactRef")
        return self.repository.get_artifact(
            run["tenantId"],
            run["siteId"],
            ref["artifactKind"],
            ref["artifactId"],
            ref["artifactRevision"],
        )["artifact"]

    @staticmethod
    def _run_artifact_refs(run: Mapping[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for field in ("baseRef", "sourceBundleRef"):
            value = run.get(field)
            if isinstance(value, Mapping):
                refs.append(_validate_artifact_ref(value, field))
        for field in (
            "stageReceipts",
            "candidateResults",
            "evaluationResults",
            "proposalRefs",
        ):
            for value in run.get(field, []):
                refs.append(_validate_artifact_ref(value, f"{field}[]"))
        for key, value in (run.get("stageOutputs") or {}).items():
            refs.append(_validate_artifact_ref(value, f"stageOutputs.{key}"))
        unique = {
            (
                item["artifactKind"],
                item["artifactId"],
                item["artifactRevision"],
            ): item
            for item in refs
        }
        return [unique[key] for key in sorted(unique)]

    def start_preview(
        self,
        *,
        tenant_id: str,
        site_id: str,
        workspace_id: str,
        design_base: Mapping[str, Any],
        design_brief: Mapping[str, Any],
        source_bundle: Mapping[str, Any],
        provider: str,
        model: str,
        reasoning_effort: str | None,
        client_generation_id: str,
        mode: str = "production_sage",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        base = validate_facility_design_base(design_base)
        brief = validate_facility_design_brief(design_brief)
        if brief["semanticBody"]["baseStateRef"]["baseRevision"] != base["baseRevision"]:
            _fail(
                "facility_design_base_mismatch",
                "Design brief does not reference the supplied immutable base.",
            )
        if mode not in {"production_sage", "lab"}:
            _fail("facility_design_run_mode_invalid", "Design run mode is unsupported.")
        now = self._now()
        identifier = _identifier(run_id or f"fdlr-{uuid4().hex}", "runId")
        provider_binding = {
            "provider": _identifier(provider, "provider"),
            "model": _identifier(model, "model"),
            "reasoningEffort": (
                _identifier(reasoning_effort, "reasoningEffort")
                if reasoning_effort is not None
                else None
            ),
        }
        provider_binding["bindingRevision"] = design_revision(provider_binding)
        source = deepcopy(dict(source_bundle))
        source_revision = design_revision(source)
        seed = {
            "baseRevision": base["baseRevision"],
            "briefRevision": brief["briefRevision"],
            "briefSemanticFingerprint": brief["briefSemanticFingerprint"],
            "sourceBundleRevision": source_revision,
            "providerBindingRevision": provider_binding["bindingRevision"],
        }
        run_shell = {
            "tenantId": tenant_id,
            "siteId": site_id,
        }
        base_ref = self._store(
            run_shell,
            kind="design_base",
            artifact_id=base["baseId"],
            artifact=base,
            intrinsic_revision=base["baseRevision"],
        )
        source_ref = self._store(
            run_shell,
            kind="design_source_bundle",
            artifact_id=f"fdls-{source_revision[:24]}",
            artifact=source,
            intrinsic_revision=source_revision,
        )
        run = validate_facility_design_run(
            {
                "schemaVersion": FACILITY_DESIGN_RUN_SCHEMA_VERSION,
                "runtimeVersion": FACILITY_DESIGN_RUNTIME_VERSION,
                "runId": identifier,
                "tenantId": tenant_id,
                "siteId": site_id,
                "workspaceId": workspace_id,
                "layoutId": base["layoutId"],
                "briefId": brief["briefId"],
                "briefRevision": brief["briefRevision"],
                "briefSemanticFingerprint": brief["briefSemanticFingerprint"],
                "baseRef": base_ref,
                "sourceBundleRef": source_ref,
                "providerBinding": provider_binding,
                "dependencyFingerprint": design_revision(seed),
                "clientGenerationId": client_generation_id,
                "mode": mode,
                "status": "active",
                "readiness": "ready",
                "nextStageId": "validate_base",
                "stageReceipts": [],
                "stageOutputs": {},
                "candidateQueue": [],
                "candidateCursor": 0,
                "candidateResults": [],
                "evaluationResults": [],
                "proposalRefs": [],
                "findings": [],
                "recoveryActions": [],
                "counters": {
                    "workflowToolCalls": 0,
                    "repairAttempts": 0,
                    "candidateLineages": 0,
                    "candidateExecutionAttempts": 0,
                    "elapsedMs": 0,
                },
                "budget": {
                    "maximumWorkflowToolCalls": FACILITY_DESIGN_MAXIMUM_WORKFLOW_TOOL_CALLS,
                    "maximumRepairAttempts": FACILITY_DESIGN_MAXIMUM_REPAIR_ATTEMPTS,
                    "maximumCandidateLineages": FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES,
                    "maximumCandidateExecutionAttempts": FACILITY_DESIGN_CANDIDATE_MAXIMUM_ATTEMPTS,
                    "maximumElapsedMs": FACILITY_DESIGN_MAXIMUM_ELAPSED_MILLISECONDS,
                },
                "searchStatus": None,
                "unexpandedFrontierCount": 0,
                "cancelRequested": False,
                "terminalReason": None,
                "createdAt": _timestamp(now),
                "updatedAt": _timestamp(now),
                "expiresAt": _timestamp(
                    now + timedelta(seconds=FACILITY_DESIGN_RUN_IDLE_SECONDS)
                ),
            }
        )
        created = self.repository.create_run(
            tenant_id=tenant_id,
            site_id=site_id,
            run=run,
            artifact_refs=[base_ref, source_ref],
        )
        self.repository.pin_brief_artifacts(
            tenant_id=tenant_id,
            site_id=site_id,
            brief_id=brief["briefId"],
            artifact_refs=[base_ref],
        )
        return created

    def _elapsed_ms(self, run: Mapping[str, Any], now: datetime) -> int:
        return max(
            int(run["counters"]["elapsedMs"]),
            int(round((now - _parse_timestamp(run["createdAt"], "createdAt")).total_seconds() * 1000)),
        )

    def _budget_check(self, run: dict[str, Any], now: datetime) -> None:
        run["counters"]["elapsedMs"] = self._elapsed_ms(run, now)
        reason = None
        if run["counters"]["workflowToolCalls"] >= run["budget"]["maximumWorkflowToolCalls"]:
            reason = "facility_design_workflow_tool_call_budget_exceeded"
        elif run["counters"]["candidateExecutionAttempts"] >= run["budget"]["maximumCandidateExecutionAttempts"] and run["nextStageId"] == "execute_candidates":
            reason = "facility_design_candidate_attempt_budget_exceeded"
        elif run["counters"]["elapsedMs"] > run["budget"]["maximumElapsedMs"]:
            reason = "facility_design_elapsed_budget_exceeded"
        if reason is not None:
            run["status"] = "budget_exhausted"
            run["terminalReason"] = reason
            run["nextStageId"] = None
            run["findings"].append(
                {
                    "code": reason,
                    "severity": "blocked",
                    "recoverability": "terminal",
                    "affectedIds": [],
                    "message": "The bounded Facility design run exhausted its frozen budget.",
                }
            )
            raise FacilityDesignRuntimeError(
                reason,
                "The bounded Facility design run exhausted its frozen budget.",
            )

    def _persist_run(
        self,
        envelope: Mapping[str, Any],
        run: Mapping[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        candidate = deepcopy(dict(run))
        candidate["updatedAt"] = _timestamp(now)
        candidate["expiresAt"] = _timestamp(
            now + timedelta(seconds=FACILITY_DESIGN_RUN_IDLE_SECONDS)
        )
        candidate["counters"]["elapsedMs"] = self._elapsed_ms(candidate, now)
        normalized = validate_facility_design_run(candidate)
        return self.repository.update_run(
            tenant_id=normalized["tenantId"],
            site_id=normalized["siteId"],
            run=normalized,
            expected_run_revision=envelope["runRevision"],
            artifact_refs=self._run_artifact_refs(normalized),
            previous_artifact_refs=self._run_artifact_refs(envelope["run"]),
        )

    def _record_stage(
        self,
        envelope: Mapping[str, Any],
        *,
        stage_id: str,
        input_value: Mapping[str, Any],
        output_handles: Sequence[Mapping[str, Any]],
        next_stage_id: str | None,
        finding_codes: Sequence[str] = (),
    ) -> dict[str, Any]:
        run = deepcopy(dict(envelope["run"]))
        prior_receipt_revision = (
            run["stageReceipts"][-1]["artifactRevision"]
            if run["stageReceipts"]
            else None
        )
        receipt = {
            "schemaVersion": "facility-design-stage-receipt-v1",
            "receiptId": "",
            "runId": run["runId"],
            "stageId": _identifier(stage_id, "stageId"),
            "sequence": len(run["stageReceipts"]) + 1,
            "inputFingerprint": design_revision(input_value),
            "outputRefs": [deepcopy(dict(item)) for item in output_handles],
            "findingCodes": sorted(set(str(item) for item in finding_codes)),
            "priorReceiptRevision": prior_receipt_revision,
            "completedAt": _timestamp(self._now()),
        }
        receipt["receiptId"] = f"fdlsr-{design_revision(receipt)[:24]}"
        receipt_revision = design_revision(receipt)
        receipt_ref = self._store(
            run,
            kind="stage_receipt",
            artifact_id=receipt["receiptId"],
            artifact=receipt,
            intrinsic_revision=receipt_revision,
        )
        run["stageReceipts"].append(receipt_ref)
        run["counters"]["workflowToolCalls"] += 1
        run["nextStageId"] = next_stage_id
        if next_stage_id is None and run["status"] == "active":
            run["status"] = "preview_ready"
        return self._persist_run(envelope, run)

    def _brief(self, run: Mapping[str, Any]) -> dict[str, Any]:
        envelope = self.repository.get_brief(
            run["tenantId"], run["siteId"], run["briefId"],
            brief_revision=run["briefRevision"],
        )
        brief = envelope["brief"]
        if brief["briefSemanticFingerprint"] != run["briefSemanticFingerprint"]:
            _fail(
                "facility_design_brief_revision_mismatch",
                "Design run brief binding failed its integrity check.",
            )
        return brief

    def _stage_validate_base(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = envelope["run"]
        base = validate_facility_design_base(self._load(run, run["baseRef"]))
        brief = self._brief(run)
        if brief["semanticBody"]["baseStateRef"]["baseRevision"] != base["baseRevision"]:
            _fail("base_rebind_required", "The active brief no longer binds this base.")
        validation = {
            "schemaVersion": "facility-design-base-validation-v1",
            "baseRevision": base["baseRevision"],
            "layoutRevision": base["layoutRevision"],
            "briefRevision": brief["briefRevision"],
            "status": "valid",
        }
        handle = self._store(
            run,
            kind="base_validation",
            artifact_id=f"fdlbv-{run['runId']}",
            artifact=validation,
        )
        return self._record_stage(
            envelope,
            stage_id="validate_base",
            input_value={"baseRef": run["baseRef"], "briefRevision": brief["briefRevision"]},
            output_handles=[handle],
            next_stage_id="compile_snapshot",
        )

    def _stage_compile_snapshot(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = envelope["run"]
        base = self._load(run, run["baseRef"])
        brief = self._brief(run)
        source = self._load(run, run["sourceBundleRef"])
        required = {"processMap", "transfer", "validationContextRevision"}
        if not required <= set(source):
            _fail(
                "facility_design_source_bundle_invalid",
                "Manufacturing source bundle is incomplete.",
            )
        snapshot = build_facility_manufacturing_snapshot(
            snapshot_id=f"fdms-{run['runId']}",
            design_base=base,
            design_brief=brief,
            process_map=source["processMap"],
            transfer=source["transfer"],
            validation_context_revision=source["validationContextRevision"],
            created_at=run["createdAt"],
        )
        handle = self._store(
            run,
            kind="manufacturing_snapshot",
            artifact_id=snapshot["snapshotId"],
            artifact=snapshot,
            intrinsic_revision=snapshot["snapshotRevision"],
        )
        candidate = deepcopy(dict(envelope["run"]))
        candidate["stageOutputs"]["snapshot"] = handle
        persisted = self._persist_run(envelope, candidate)
        return self._record_stage(
            persisted,
            stage_id="compile_snapshot",
            input_value={"sourceBundleRef": run["sourceBundleRef"], "briefRevision": brief["briefRevision"]},
            output_handles=[handle],
            next_stage_id="evaluate_baseline",
        )

    def _stage_evaluate_baseline(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = envelope["run"]
        base = self._load(run, run["baseRef"])
        brief = self._brief(run)
        snapshot = self._load(run, run["stageOutputs"]["snapshot"])
        source = self._load(run, run["sourceBundleRef"])
        baseline = build_facility_design_baseline(
            baseline_id=f"fdlb-{run['runId']}",
            layout=base["document"],
            brief=brief,
            snapshot=snapshot,
            containment_checker=self.containment_checker,
            source_bundle=source,
        )
        handle = self._store(
            run,
            kind="design_baseline",
            artifact_id=baseline["baselineId"],
            artifact=baseline,
            intrinsic_revision=baseline["baselineRevision"],
        )
        candidate = deepcopy(dict(run))
        candidate["stageOutputs"]["baseline"] = handle
        persisted = self._persist_run(envelope, candidate)
        return self._record_stage(
            persisted,
            stage_id="evaluate_baseline",
            input_value={"snapshotRef": run["stageOutputs"]["snapshot"]},
            output_handles=[handle],
            next_stage_id="enumerate_recipes",
        )

    def _stage_enumerate_recipes(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = envelope["run"]
        brief = self._brief(run)
        snapshot = self._load(run, run["stageOutputs"]["snapshot"])
        source = self._load(run, run["sourceBundleRef"])
        search = deepcopy(dict(self.candidate_recipe_provider(brief, snapshot, source)))
        recipes = search.get("recipes")
        if not isinstance(recipes, list):
            _fail("facility_design_search_invalid", "Candidate search returned no recipe array.")
        if len(recipes) > FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES:
            _fail(
                "facility_design_candidate_lineage_limit_exceeded",
                "Candidate search exceeded its frozen lineage ceiling before execution.",
            )
        canonical_recipes = sorted(
            [deepcopy(dict(item)) for item in recipes if isinstance(item, Mapping)],
            key=lambda item: str(item.get("candidateId") or item.get("recipeId") or ""),
        )
        if len(canonical_recipes) != len(recipes):
            _fail("facility_design_search_invalid", "Candidate recipe must be an object.")
        search["recipes"] = canonical_recipes
        search.setdefault("searchStatus", "complete")
        search.setdefault("unexpandedFrontierCount", 0)
        search["searchFingerprint"] = design_revision(
            {key: item for key, item in search.items() if key != "searchFingerprint"}
        )
        handle = self._store(
            run,
            kind="candidate_search",
            artifact_id=f"fdlsearch-{run['runId']}",
            artifact=search,
            intrinsic_revision=search["searchFingerprint"],
        )
        candidate = deepcopy(dict(run))
        candidate["stageOutputs"]["search"] = handle
        candidate["candidateQueue"] = canonical_recipes
        candidate["candidateCursor"] = 0
        candidate["counters"]["candidateLineages"] = len(canonical_recipes)
        candidate["searchStatus"] = search["searchStatus"]
        candidate["unexpandedFrontierCount"] = int(
            search["unexpandedFrontierCount"]
        )
        persisted = self._persist_run(envelope, candidate)
        return self._record_stage(
            persisted,
            stage_id="enumerate_recipes",
            input_value={"snapshotRef": run["stageOutputs"]["snapshot"], "briefRevision": run["briefRevision"]},
            output_handles=[handle],
            next_stage_id=("execute_candidates" if canonical_recipes else "classify"),
        )

    @staticmethod
    def _candidate_finding(exc: Exception, recipe: Mapping[str, Any]) -> dict[str, Any]:
        code = str(getattr(exc, "code", "facility_design_candidate_failed"))
        details = deepcopy(dict(getattr(exc, "details", {}) or {}))
        affected = sorted(
            set(
                str(item)
                for item in (
                    details.get("affectedIds")
                    or recipe.get("targetIds")
                    or []
                )
            )
        )
        recovery_code = (
            code
            if code in {"no_layout_alternative", "route_blocked", "placement_no_fit"}
            else None
        )
        return {
            "code": recovery_code or code,
            "sourceCode": code,
            "severity": "error",
            "recoverability": "recoverable" if recovery_code else "terminal",
            "affectedIds": affected,
            "message": str(exc)[:600],
            "allowedParameterBounds": deepcopy(
                details.get("allowedParameterBounds") or {}
            ),
            "preservedConstraintIds": deepcopy(
                details.get("preservedConstraintIds") or []
            ),
        }

    def _stage_execute_candidate(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = deepcopy(dict(envelope["run"]))
        recipe = deepcopy(dict(run["candidateQueue"][run["candidateCursor"]]))
        candidate_id = str(
            recipe.get("candidateId")
            or recipe.get("recipeId")
            or f"fdlc-{design_revision(recipe)[:24]}"
        )
        run["counters"]["candidateExecutionAttempts"] += 1
        base = self._load(run, run["baseRef"])
        brief = self._brief(run)
        snapshot = self._load(run, run["stageOutputs"]["snapshot"])
        baseline = self._load(run, run["stageOutputs"]["baseline"])
        source = self._load(run, run["sourceBundleRef"])
        outputs: list[dict[str, Any]] = []
        finding_codes: list[str] = []
        try:
            operation_builder = self.operation_builder or (
                lambda recipe_value, layout_value, snapshot_value: (
                    self.source_operation_builder(
                        recipe_value,
                        layout_value,
                        snapshot_value,
                        source,
                    )
                )
            )
            candidate = execute_facility_design_candidate(
                candidate_id=candidate_id,
                recipe=recipe,
                design_base=base,
                brief=brief,
                snapshot=snapshot,
                operation_builder=operation_builder,
                updated_at=self._load(run, run["sourceBundleRef"]).get(
                    "candidateUpdatedAt", run["createdAt"]
                ),
                cancel_check=lambda: bool(run["cancelRequested"]),
            )
            candidate_ref = self._store(
                run,
                kind="design_candidate",
                artifact_id=candidate_id,
                artifact=candidate,
                intrinsic_revision=candidate["candidateRevision"],
            )
            evaluation = evaluate_facility_design_candidate(
                evaluation_id=f"fdle-{candidate_id}",
                baseline_layout=base["document"],
                candidate_layout=candidate["candidateLayout"],
                brief=brief,
                snapshot=snapshot,
                baseline=baseline,
                containment_checker=self.containment_checker,
                source_bundle=source,
            )
            evaluation_ref = self._store(
                run,
                kind="design_evaluation",
                artifact_id=evaluation["evaluationId"],
                artifact=evaluation,
                intrinsic_revision=evaluation["evaluationRevision"],
            )
            run["candidateResults"].append(candidate_ref)
            run["evaluationResults"].append(evaluation_ref)
            outputs.extend([candidate_ref, evaluation_ref])
        except Exception as exc:
            finding = self._candidate_finding(exc, recipe)
            run["findings"].append(finding)
            finding_codes.append(finding["code"])
            actions = facility_design_recovery_actions([finding])
            run["recoveryActions"].extend(actions)
            automatic = next(
                (item for item in actions if item["recoverability"] == "automatic"),
                None,
            )
            if (
                automatic is not None
                and self.repair_provider is not None
                and run["counters"]["repairAttempts"]
                < run["budget"]["maximumRepairAttempts"]
                and len(run["candidateQueue"])
                < run["budget"]["maximumCandidateExecutionAttempts"]
            ):
                repaired = self.repair_provider(
                    automatic,
                    recipe,
                    run["counters"]["repairAttempts"] + 1,
                )
                if repaired is not None:
                    run["candidateQueue"].append(deepcopy(dict(repaired)))
                    run["counters"]["repairAttempts"] += 1
        run["candidateCursor"] += 1
        more = run["candidateCursor"] < len(run["candidateQueue"])
        persisted = self._persist_run(envelope, run)
        return self._record_stage(
            persisted,
            stage_id=f"execute_candidate_{run['candidateCursor']}",
            input_value={"recipe": recipe, "attempt": run["counters"]["candidateExecutionAttempts"]},
            output_handles=outputs,
            finding_codes=finding_codes,
            next_stage_id="execute_candidates" if more else "classify",
        )

    def _stage_classify(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = envelope["run"]
        brief = self._brief(run)
        evaluations = [self._load(run, item) for item in run["evaluationResults"]]
        classified = classify_facility_design_alternatives(evaluations, brief=brief)
        artifact = {
            "schemaVersion": "facility-design-classification-v1",
            "runId": run["runId"],
            "briefRevision": brief["briefRevision"],
            "searchStatus": run["searchStatus"],
            "unexpandedFrontierCount": run["unexpandedFrontierCount"],
            "evaluations": classified,
            "globalBestClaimPermitted": False,
            "classificationRevision": "",
        }
        unsigned = deepcopy(artifact)
        unsigned.pop("classificationRevision")
        artifact["classificationRevision"] = design_revision(unsigned)
        handle = self._store(
            run,
            kind="design_classification",
            artifact_id=f"fdlclass-{run['runId']}",
            artifact=artifact,
            intrinsic_revision=artifact["classificationRevision"],
        )
        candidate = deepcopy(dict(run))
        candidate["stageOutputs"]["classification"] = handle
        persisted = self._persist_run(envelope, candidate)
        return self._record_stage(
            persisted,
            stage_id="classify",
            input_value={"evaluationRefs": run["evaluationResults"], "briefRevision": brief["briefRevision"]},
            output_handles=[handle],
            next_stage_id="create_proposals",
        )

    def _stage_create_proposals(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = deepcopy(dict(envelope["run"]))
        classification = self._load(run, run["stageOutputs"]["classification"])
        candidates = {
            item["candidateId"]: (ref, item)
            for ref in run["candidateResults"]
            for item in [self._load(run, ref)]
        }
        ranked = [
            item
            for item in classification["evaluations"]
            if item.get("objectiveImproved") and item.get("nonDominated")
        ]
        ranked.sort(
            key=lambda item: (
                not bool(item.get("preferred")),
                next(
                    float(metric["value"])
                    for metric in item["metrics"]
                    if metric["metricId"] == "loadedRouteDistanceMeters"
                ),
                item["evaluationId"],
            )
        )
        output_refs = []
        evaluation_by_id = {
            self._load(run, ref)["evaluationId"]: ref
            for ref in run["evaluationResults"]
        }
        for evaluation in ranked[:FACILITY_DESIGN_MAXIMUM_PRESENTED_ALTERNATIVES]:
            candidate_id = evaluation["evaluationId"].removeprefix("fdle-")
            candidate_entry = candidates.get(candidate_id)
            if candidate_entry is None:
                continue
            candidate_ref, candidate = candidate_entry
            semantics = {
                "runId": run["runId"],
                "candidateRevision": candidate["candidateRevision"],
                "evaluationRevision": evaluation["evaluationRevision"],
                "briefRevision": run["briefRevision"],
            }
            proposal_id = f"fdlp-{design_revision(semantics)[:24]}"
            proposal = {
                "schemaVersion": "facility-design-proposal-v1",
                "proposalId": proposal_id,
                "proposalRevision": "",
                "runId": run["runId"],
                "layoutId": run["layoutId"],
                "baseRef": deepcopy(run["baseRef"]),
                "briefId": run["briefId"],
                "briefRevision": run["briefRevision"],
                "briefSemanticFingerprint": run["briefSemanticFingerprint"],
                "snapshotRef": deepcopy(run["stageOutputs"]["snapshot"]),
                "candidateRef": deepcopy(candidate_ref),
                "evaluationRef": deepcopy(evaluation_by_id[evaluation["evaluationId"]]),
                "resultLayoutRevision": candidate["resultLayoutRevision"],
                "operationPlanRevision": candidate["operationPlanHash"],
                "diffHash": candidate["diffHash"],
                "dependencyFingerprint": run["dependencyFingerprint"],
                "stageReceiptRefs": deepcopy(run["stageReceipts"]),
                "searchStatus": run["searchStatus"],
                "unexpandedFrontierCount": run["unexpandedFrontierCount"],
                "classification": {
                    "feasible": evaluation["feasible"],
                    "objectiveImproved": evaluation["objectiveImproved"],
                    "nonDominated": evaluation["nonDominated"],
                    "preferred": evaluation["preferred"],
                    "preferenceReason": deepcopy(evaluation["preferenceReason"]),
                    "operationallyMeaningful": evaluation["operationallyMeaningful"],
                },
                "saveEligibility": "unsaved_draft_only",
            }
            unsigned = deepcopy(proposal)
            unsigned.pop("proposalRevision")
            proposal["proposalRevision"] = design_revision(unsigned)
            ref = self._store(
                run,
                kind="design_proposal",
                artifact_id=proposal_id,
                artifact=proposal,
                intrinsic_revision=proposal["proposalRevision"],
            )
            run["proposalRefs"].append(ref)
            output_refs.append(ref)
        persisted = self._persist_run(envelope, run)
        return self._record_stage(
            persisted,
            stage_id="create_proposals",
            input_value={"classificationRef": run["stageOutputs"]["classification"], "stageReceiptRefs": run["stageReceipts"]},
            output_handles=output_refs,
            next_stage_id="validate_preview",
        )

    def _stage_validate_preview(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = deepcopy(dict(envelope["run"]))
        status = "ready" if run["proposalRefs"] else "blocked"
        summary = {
            "schemaVersion": "facility-design-preview-summary-v1",
            "runId": run["runId"],
            "status": status,
            "proposalCount": len(run["proposalRefs"]),
            "proposalRefs": deepcopy(run["proposalRefs"]),
            "searchStatus": run["searchStatus"],
            "unexpandedFrontierCount": run["unexpandedFrontierCount"],
            "findingCodes": sorted(set(item["code"] for item in run["findings"])),
            "qualification": (
                "Measured against the exact bound evidence and evaluated bounded alternatives; no global optimum, safety, capacity, or compliance claim."
            ),
        }
        handle = self._store(
            run,
            kind="design_preview_summary",
            artifact_id=f"fdlpreview-{run['runId']}",
            artifact=summary,
        )
        run["stageOutputs"]["preview"] = handle
        if not run["proposalRefs"]:
            run["status"] = "blocked"
            run["readiness"] = "choice_open"
            run["terminalReason"] = "facility_design_no_improved_alternative"
        persisted = self._persist_run(envelope, run)
        return self._record_stage(
            persisted,
            stage_id="validate_preview",
            input_value={"proposalRefs": run["proposalRefs"], "findingCount": len(run["findings"])},
            output_handles=[handle],
            next_stage_id=None,
        )

    def continue_preview(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        maximum_tool_calls: int = FACILITY_DESIGN_MAXIMUM_TOOL_CALLS_PER_TURN,
    ) -> dict[str, Any]:
        if (
            isinstance(maximum_tool_calls, bool)
            or not isinstance(maximum_tool_calls, int)
            or maximum_tool_calls < 1
            or maximum_tool_calls > FACILITY_DESIGN_MAXIMUM_TOOL_CALLS_PER_TURN
        ):
            _fail(
                "facility_design_turn_budget_invalid",
                "maximum_tool_calls must be between one and ten.",
            )
        envelope = self.repository.get_run(tenant_id, site_id, run_id)
        run = validate_facility_design_run(envelope["run"])
        if _parse_timestamp(run["expiresAt"], "expiresAt") <= self._now():
            tombstone = self.repository.expire_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                expected_run_revision=envelope["runRevision"],
            )
            _fail(
                "facility_design_run_expired",
                "Facility design run expired after 24 hours idle.",
                tombstone=tombstone,
            )
        if run["status"] in _TERMINAL_STATUSES:
            return {**envelope, "turnToolCalls": 0, "continuationRequired": False}
        if run["cancelRequested"]:
            run["status"] = "cancelled"
            run["terminalReason"] = "user_cancelled"
            run["nextStageId"] = None
            envelope = self._persist_run(envelope, run)
            return {**envelope, "turnToolCalls": 0, "continuationRequired": False}
        start_calls = run["counters"]["workflowToolCalls"]
        dispatch = {
            "validate_base": self._stage_validate_base,
            "compile_snapshot": self._stage_compile_snapshot,
            "evaluate_baseline": self._stage_evaluate_baseline,
            "enumerate_recipes": self._stage_enumerate_recipes,
            "execute_candidates": self._stage_execute_candidate,
            "classify": self._stage_classify,
            "create_proposals": self._stage_create_proposals,
            "validate_preview": self._stage_validate_preview,
        }
        while envelope["run"]["status"] == "active":
            run = validate_facility_design_run(envelope["run"])
            calls_this_turn = run["counters"]["workflowToolCalls"] - start_calls
            if calls_this_turn >= maximum_tool_calls:
                break
            try:
                self._budget_check(run, self._now())
            except FacilityDesignRuntimeError:
                envelope = self._persist_run(envelope, run)
                break
            stage_id = run["nextStageId"]
            handler = dispatch.get(stage_id)
            if handler is None:
                run["status"] = "failed"
                run["terminalReason"] = "facility_design_stage_unknown"
                run["nextStageId"] = None
                envelope = self._persist_run(envelope, run)
                break
            try:
                envelope = handler(envelope)
            except Exception as exc:
                run = deepcopy(dict(envelope["run"]))
                code = str(getattr(exc, "code", "facility_design_stage_failed"))
                run["findings"].append(
                    {
                        "code": code,
                        "severity": "blocked",
                        "recoverability": "terminal",
                        "affectedIds": [],
                        "message": str(exc)[:600],
                    }
                )
                run["recoveryActions"] = facility_design_recovery_actions(
                    run["findings"]
                )
                run["status"] = "stale" if code in {
                    "source_revision_changed",
                    "facility_design_brief_revision_mismatch",
                } else "blocked"
                run["readiness"] = "stale" if run["status"] == "stale" else "unsupported"
                run["terminalReason"] = code
                run["nextStageId"] = None
                envelope = self._persist_run(envelope, run)
                break
        final = validate_facility_design_run(envelope["run"])
        calls = final["counters"]["workflowToolCalls"] - start_calls
        return {
            **envelope,
            "turnToolCalls": calls,
            "continuationRequired": final["status"] == "active",
        }

    def cancel(
        self, *, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        envelope = self.repository.get_run(tenant_id, site_id, run_id)
        run = validate_facility_design_run(envelope["run"])
        if run["status"] in _TERMINAL_STATUSES:
            return envelope
        run["cancelRequested"] = True
        run["status"] = "cancelled"
        run["terminalReason"] = "user_cancelled"
        run["nextStageId"] = None
        return self._persist_run(envelope, run)

    def mark_stale(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        source_code: str,
    ) -> dict[str, Any]:
        envelope = self.repository.get_run(tenant_id, site_id, run_id)
        run = validate_facility_design_run(envelope["run"])
        if run["status"] in {"cancelled", "expired"}:
            return envelope
        run["status"] = "stale"
        run["readiness"] = "stale"
        run["terminalReason"] = _identifier(source_code, "sourceCode")
        run["nextStageId"] = None
        return self._persist_run(envelope, run)

    def summary(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        run = validate_facility_design_run(envelope["run"])
        baseline = None
        objective_endpoints = None
        snapshot_ref = run["stageOutputs"].get("snapshot")
        if isinstance(snapshot_ref, Mapping):
            snapshot = self._load(run, snapshot_ref)
            endpoints = snapshot.get("endpoints")
            if isinstance(endpoints, Mapping):
                source = endpoints.get("source")
                target = endpoints.get("target")
                if isinstance(source, Mapping) and isinstance(target, Mapping):
                    objective_endpoints = {
                        "source": {
                            "entityKind": "placement",
                            "entityId": source["placementId"],
                            "connectorId": source["connectorId"],
                        },
                        "target": {
                            "entityKind": "placement",
                            "entityId": target["placementId"],
                            "connectorId": target["connectorId"],
                        },
                    }
        baseline_ref = run["stageOutputs"].get("baseline")
        if isinstance(baseline_ref, Mapping):
            record = self._load(run, baseline_ref)
            baseline = {
                "baselineId": record["baselineId"],
                "baselineRevision": record["baselineRevision"],
                "layoutRevision": record["layoutRevision"],
                "feasible": bool(record["feasible"]),
                "metrics": deepcopy(record["metrics"]),
            }
        return {
            "schemaVersion": FACILITY_DESIGN_RUN_SCHEMA_VERSION,
            "runId": run["runId"],
            "runRevision": envelope["runRevision"],
            "status": run["status"],
            "readiness": run["readiness"],
            "nextStageId": run["nextStageId"],
            "briefId": run["briefId"],
            "briefRevision": run["briefRevision"],
            "baseRef": deepcopy(run["baseRef"]),
            "objectiveEndpoints": objective_endpoints,
            "proposalRefs": deepcopy(run["proposalRefs"]),
            "baseline": baseline,
            "searchStatus": run["searchStatus"],
            "unexpandedFrontierCount": run["unexpandedFrontierCount"],
            "counters": deepcopy(run["counters"]),
            "findingCodes": sorted(set(item["code"] for item in run["findings"])),
            "terminalReason": run["terminalReason"],
            "continuationRequired": run["status"] == "active",
        }


def reviewed_fixture_recipe_provider(
    brief: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    source_bundle: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Select only reviewed fixture recipes still legal under current locks."""

    catalog = source_bundle.get("reviewedCandidateRecipes")
    if not isinstance(catalog, list):
        return enumerate_facility_design_candidate_recipes(
            brief=brief, snapshot=snapshot
        )
    active_lock_ids = {
        item["constraintId"]
        for item in brief["semanticBody"]["hardConstraints"]
        if item["status"] == "active"
    }
    recipes = [
        deepcopy(dict(item))
        for item in catalog
        if isinstance(item, Mapping)
        and not active_lock_ids.intersection(item.get("removedByLocks", []))
    ]
    recipes.sort(key=lambda item: item["candidateId"])
    selected = recipes[:FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES]
    return {
        "schemaVersion": "facility-design-search-v1",
        "briefRevision": brief["briefRevision"],
        "snapshotRevision": snapshot["snapshotRevision"],
        "searchStatus": "complete" if len(recipes) <= len(selected) else "truncated",
        "frontierCount": len(recipes),
        "unexpandedFrontierCount": max(0, len(recipes) - len(selected)),
        "recipes": selected,
    }


__all__ = [
    "FACILITY_DESIGN_MAXIMUM_ELAPSED_MILLISECONDS",
    "FACILITY_DESIGN_MAXIMUM_PRESENTED_ALTERNATIVES",
    "FACILITY_DESIGN_MAXIMUM_REPAIR_ATTEMPTS",
    "FACILITY_DESIGN_MAXIMUM_TOOL_CALLS_PER_TURN",
    "FACILITY_DESIGN_MAXIMUM_WORKFLOW_TOOL_CALLS",
    "FACILITY_DESIGN_RUN_IDLE_SECONDS",
    "FACILITY_DESIGN_RUN_SCHEMA_VERSION",
    "FACILITY_DESIGN_RUNTIME_VERSION",
    "FacilityDesignRuntime",
    "FacilityDesignRuntimeError",
    "facility_design_recovery_actions",
    "reviewed_fixture_recipe_provider",
    "validate_facility_design_run",
]
