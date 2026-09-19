"""Deterministic revision reconciliation for durable workflow state."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from .models import canonical_sha256


REVISION_VECTOR_FIELDS = (
    "processMapRevision",
    "productStructureRevision",
    "assemblyKnowledgeRevision",
    "facilityLayoutRevision",
    "facilityShellRevision",
    "facilityPolicyRevision",
    "partRevision",
    "drawingRevision",
    "faiRevision",
    "motionAssetPin",
)
INVALIDATION_ACTIONS = frozenset(
    {
        "reset",
        "preserve",
        "revalidate",
        "invalidate",
        "invalidate_affected",
        "retain_audit_only",
        "never_retain",
        "scope_gate",
        "mark_stale_refs",
        "mark_stale_decisions",
    }
)
AUTHORIZATION_KINDS = frozenset({"preview", "approval", "apply", "execution"})
RECONCILIATION_SCHEMA_VERSION = "sage-memory-reconciliation-1.0"
RECONCILIATION_OUTCOMES = frozenset(
    {
        "same_scope_same_revisions",
        "same_scope_revision_advanced",
        "same_scope_dependency_removed",
        "scope_changed",
        "workflow_version_changed",
        "memory_expired",
        "explicitly_abandoned",
    }
)
REVISION_DIMENSIONS = (
    "mapOrLayoutRevision",
    "structureOrEvidenceRevision",
    "policyRevision",
)
MAP_LAYOUT_REVISION_FIELDS = frozenset(
    {"processMapRevision", "facilityLayoutRevision"}
)
POLICY_REVISION_FIELDS = frozenset({"facilityPolicyRevision"})
STRUCTURE_EVIDENCE_REVISION_FIELDS = frozenset(REVISION_VECTOR_FIELDS).difference(
    MAP_LAYOUT_REVISION_FIELDS,
    POLICY_REVISION_FIELDS,
)
REVISION_INVALIDATION_MATRIX: Mapping[str, Mapping[str, str]] = {
    "objective": {
        "stableScopeChange": "reset",
        "mapOrLayoutRevision": "preserve",
        "structureOrEvidenceRevision": "preserve",
        "policyRevision": "preserve",
    },
    "workflowStage": {
        "stableScopeChange": "reset",
        "mapOrLayoutRevision": "revalidate",
        "structureOrEvidenceRevision": "revalidate",
        "policyRevision": "revalidate",
    },
    "entityIds": {
        "stableScopeChange": "reset",
        "mapOrLayoutRevision": "revalidate",
        "structureOrEvidenceRevision": "revalidate",
        "policyRevision": "preserve",
    },
    "referents": {
        "stableScopeChange": "reset",
        "mapOrLayoutRevision": "revalidate",
        "structureOrEvidenceRevision": "revalidate",
        "policyRevision": "preserve",
    },
    "evidenceRefs": {
        "stableScopeChange": "reset",
        "mapOrLayoutRevision": "invalidate_affected",
        "structureOrEvidenceRevision": "invalidate_affected",
        "policyRevision": "invalidate_affected",
    },
    "semanticPreview": {
        "stableScopeChange": "invalidate",
        "mapOrLayoutRevision": "invalidate",
        "structureOrEvidenceRevision": "invalidate",
        "policyRevision": "invalidate",
    },
    "approvalToken": {
        "stableScopeChange": "invalidate",
        "mapOrLayoutRevision": "invalidate",
        "structureOrEvidenceRevision": "invalidate",
        "policyRevision": "invalidate",
    },
    "pastReceiptAudit": {
        "stableScopeChange": "retain_audit_only",
        "mapOrLayoutRevision": "retain_audit_only",
        "structureOrEvidenceRevision": "retain_audit_only",
        "policyRevision": "retain_audit_only",
    },
    "priorToolAuthorization": {
        "stableScopeChange": "never_retain",
        "mapOrLayoutRevision": "never_retain",
        "structureOrEvidenceRevision": "never_retain",
        "policyRevision": "never_retain",
    },
    "continuitySummary": {
        "stableScopeChange": "scope_gate",
        "mapOrLayoutRevision": "mark_stale_refs",
        "structureOrEvidenceRevision": "mark_stale_refs",
        "policyRevision": "mark_stale_decisions",
    },
}


@dataclass(frozen=True)
class StagePolicy:
    dependencies: frozenset[str]
    authorization_kind: Optional[str]
    safe_predecessor: Optional[str]


@dataclass(frozen=True)
class WorkflowStagePolicy:
    version: str
    first_stage: str
    stages: Mapping[str, StagePolicy]


@dataclass(frozen=True)
class StageRevalidationResult:
    stage: str
    event: str
    warning: Optional[str] = None


@dataclass(frozen=True)
class InvalidationResult:
    value: Any
    active: bool
    audit_only: bool = False
    stale: bool = False


@dataclass(frozen=True)
class ContinuityReconciliationResult:
    summary: Optional[Dict[str, Any]]
    action: str
    stale_evidence_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _stage(
    dependencies: Sequence[str],
    authorization_kind: Optional[str] = None,
    safe_predecessor: Optional[str] = None,
) -> StagePolicy:
    return StagePolicy(frozenset(dependencies), authorization_kind, safe_predecessor)


WORKFLOW_STAGE_POLICIES: Mapping[str, WorkflowStagePolicy] = {
    "assembly-knowledge-preparation": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="inspect_trusted_package_state",
        stages={
            "inspect_trusted_package_state": _stage(["assemblyKnowledgeRevision"]),
            "report_readiness_and_source_currency": _stage(
                ["assemblyKnowledgeRevision"],
                safe_predecessor="inspect_trusted_package_state",
            ),
            "identify_review_or_preparation_blockers": _stage(
                ["assemblyKnowledgeRevision"],
                safe_predecessor="inspect_trusted_package_state",
            ),
            "name_the_next_operator_controlled_action": _stage(
                ["assemblyKnowledgeRevision"],
                safe_predecessor="report_readiness_and_source_currency",
            ),
        },
    ),
    "documentation-publication": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="inspect_current_manual_state",
        stages={
            "inspect_current_manual_state": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"]
            ),
            "resolve_publication_authority": _stage(
                ["assemblyKnowledgeRevision"],
                safe_predecessor="inspect_current_manual_state",
            ),
            "validate_or_propose_manual_structure": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"],
                safe_predecessor="resolve_publication_authority",
            ),
            "compile_documentation_scene": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"],
                safe_predecessor="validate_or_propose_manual_structure",
            ),
            "capture_revision_bound_technical_figures": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"],
                "execution",
                "compile_documentation_scene",
            ),
            "validate_plan_renders_bom_and_callouts": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"],
                safe_predecessor="capture_revision_bound_technical_figures",
            ),
            "publish_pdf": _stage(
                ["assemblyKnowledgeRevision", "productStructureRevision"],
                "execution",
                "validate_plan_renders_bom_and_callouts",
            ),
        },
    ),
    "facility-layout-generation": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="observe_revision_bound_layout",
        stages={
            "observe_revision_bound_layout": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                ]
            ),
            "inspect_bounded_authority": _stage(
                ["facilityShellRevision", "facilityPolicyRevision"],
                safe_predecessor="observe_revision_bound_layout",
            ),
            "draft_semantic_facility_plan": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                safe_predecessor="inspect_bounded_authority",
            ),
            "validate_semantics_and_evidence": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                safe_predecessor="draft_semantic_facility_plan",
            ),
            "build_synchronized_ghost_preview": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                "preview",
                "validate_semantics_and_evidence",
            ),
            "await_explicit_approval": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                "approval",
                "validate_semantics_and_evidence",
            ),
        },
    ),
    "facility-layout-analysis": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="observe_revision_bound_layout",
        stages={
            "observe_revision_bound_layout": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                ]
            ),
            "resolve_analysis_question": _stage(
                ["facilityLayoutRevision"],
                safe_predecessor="observe_revision_bound_layout",
            ),
            "inspect_bounded_authority": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                safe_predecessor="resolve_analysis_question",
            ),
            "compute_supported_analysis": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                safe_predecessor="inspect_bounded_authority",
            ),
            "present_findings": _stage(
                [
                    "facilityLayoutRevision",
                    "facilityShellRevision",
                    "facilityPolicyRevision",
                    "processMapRevision",
                ],
                safe_predecessor="compute_supported_analysis",
            ),
        },
    ),
    "process-map-analysis": WorkflowStagePolicy(
        version="1.1.0",
        first_stage="identify_map",
        stages={
            "identify_map": _stage(["processMapRevision"]),
            "validate_graph": _stage(
                ["processMapRevision", "productStructureRevision"],
                safe_predecessor="identify_map",
            ),
            "analyze_flow": _stage(
                ["processMapRevision", "productStructureRevision"],
                safe_predecessor="validate_graph",
            ),
            "report_findings": _stage(
                ["processMapRevision", "productStructureRevision"],
                safe_predecessor="analyze_flow",
            ),
        },
    ),
    "process-map-generation": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="observe_saved_and_live_state",
        stages={
            "observe_saved_and_live_state": _stage(
                [
                    "processMapRevision",
                    "productStructureRevision",
                    "assemblyKnowledgeRevision",
                ]
            ),
            "resolve_product_scope": _stage(
                ["productStructureRevision", "assemblyKnowledgeRevision"],
                safe_predecessor="observe_saved_and_live_state",
            ),
            "draft_semantic_process_plan": _stage(
                [
                    "processMapRevision",
                    "productStructureRevision",
                    "assemblyKnowledgeRevision",
                ],
                safe_predecessor="resolve_product_scope",
            ),
            "validate_semantics_and_evidence": _stage(
                [
                    "processMapRevision",
                    "productStructureRevision",
                    "assemblyKnowledgeRevision",
                ],
                safe_predecessor="draft_semantic_process_plan",
            ),
            "build_complete_ghost_preview": _stage(
                [
                    "processMapRevision",
                    "productStructureRevision",
                    "assemblyKnowledgeRevision",
                ],
                "preview",
                "validate_semantics_and_evidence",
            ),
            "await_explicit_approval": _stage(
                [
                    "processMapRevision",
                    "productStructureRevision",
                    "assemblyKnowledgeRevision",
                ],
                "approval",
                "validate_semantics_and_evidence",
            ),
        },
    ),
    "supplier-fai-disposition": WorkflowStagePolicy(
        version="1.0.0",
        first_stage="identify_characteristic",
        stages={
            "identify_characteristic": _stage(["faiRevision", "drawingRevision"]),
            "evaluate_result": _stage(
                ["faiRevision", "drawingRevision"],
                safe_predecessor="identify_characteristic",
            ),
            "explain_part_function": _stage(
                ["partRevision", "assemblyKnowledgeRevision"],
                safe_predecessor="evaluate_result",
            ),
            "trace_assembly_impact": _stage(
                [
                    "partRevision",
                    "drawingRevision",
                    "faiRevision",
                    "assemblyKnowledgeRevision",
                ],
                safe_predecessor="explain_part_function",
            ),
            "visualize_affected_context": _stage(
                ["partRevision", "assemblyKnowledgeRevision", "motionAssetPin"],
                "execution",
                "trace_assembly_impact",
            ),
            "recommend_disposition": _stage(
                [
                    "partRevision",
                    "drawingRevision",
                    "faiRevision",
                    "assemblyKnowledgeRevision",
                ],
                safe_predecessor="trace_assembly_impact",
            ),
        },
    ),
}


def normalize_revision_vector(value: Mapping[str, Any] | None) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("revision vector must be an object")
    unknown = set(value) - set(REVISION_VECTOR_FIELDS)
    if unknown:
        raise ValueError(f"revision vector contains unsupported fields: {sorted(unknown)}")
    normalized: Dict[str, str] = {}
    for field in REVISION_VECTOR_FIELDS:
        raw = value.get(field)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            raise ValueError(f"revision vector field {field} must be a string")
        normalized[field] = raw
    return normalized


def revision_vector_sha256(value: Mapping[str, Any] | None) -> str:
    return canonical_sha256(normalize_revision_vector(value))


def changed_revision_dependencies(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> frozenset[str]:
    before = normalize_revision_vector(previous)
    after = normalize_revision_vector(current)
    return frozenset(
        field
        for field in REVISION_VECTOR_FIELDS
        if before.get(field) != after.get(field)
    )


def revision_change_dimensions(
    changed_dependencies: Iterable[str],
) -> tuple[str, ...]:
    """Map revision fields onto the frozen invalidation-matrix dimensions."""

    changed = frozenset(str(value) for value in changed_dependencies)
    dimensions: list[str] = []
    if changed.intersection(MAP_LAYOUT_REVISION_FIELDS):
        dimensions.append("mapOrLayoutRevision")
    if changed.intersection(STRUCTURE_EVIDENCE_REVISION_FIELDS):
        dimensions.append("structureOrEvidenceRevision")
    if changed.intersection(POLICY_REVISION_FIELDS):
        dimensions.append("policyRevision")
    return tuple(dimensions)


def reconciliation_outcome(
    *,
    previous_scope_fingerprint: Optional[str],
    current_scope_fingerprint: Optional[str],
    previous_revision_vector: Mapping[str, Any] | None,
    current_revision_vector: Mapping[str, Any] | None,
    workflow_state_event: Optional[str] = None,
) -> str:
    """Resolve one closed reconciliation outcome from trusted state only."""

    workflow_event = str(workflow_state_event or "").split(":", 1)[0]
    if workflow_event == "memory_expired":
        return "memory_expired"
    if workflow_event in {"explicitly_abandoned", "abandoned"}:
        return "explicitly_abandoned"
    if workflow_event == "workflow_version_changed":
        return "workflow_version_changed"
    previous_scope = str(previous_scope_fingerprint or "")
    current_scope = str(current_scope_fingerprint or "")
    if previous_scope != current_scope:
        return "scope_changed"
    changed = changed_revision_dependencies(
        previous_revision_vector,
        current_revision_vector,
    )
    if not changed:
        return "same_scope_same_revisions"
    before = normalize_revision_vector(previous_revision_vector)
    after = normalize_revision_vector(current_revision_vector)
    if any(field in before and field not in after for field in changed):
        return "same_scope_dependency_removed"
    return "same_scope_revision_advanced"


def build_reconciliation_event(
    *,
    previous_scope_fingerprint: Optional[str],
    current_scope_fingerprint: Optional[str],
    previous_revision_vector: Mapping[str, Any] | None,
    current_revision_vector: Mapping[str, Any] | None,
    workflow_state_event: Optional[str],
    previous_workflow_state: Mapping[str, Any] | None,
    current_workflow_state: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Build the non-secret audit event for one closed matrix transition."""

    changed = changed_revision_dependencies(
        previous_revision_vector,
        current_revision_vector,
    )
    outcome = reconciliation_outcome(
        previous_scope_fingerprint=previous_scope_fingerprint,
        current_scope_fingerprint=current_scope_fingerprint,
        previous_revision_vector=previous_revision_vector,
        current_revision_vector=current_revision_vector,
        workflow_state_event=workflow_state_event,
    )
    if outcome == "scope_changed":
        dimensions = ("stableScopeChange",)
    elif outcome in {
        "same_scope_revision_advanced",
        "same_scope_dependency_removed",
    }:
        dimensions = revision_change_dimensions(changed)
    else:
        dimensions = ()

    actions: list[Dict[str, str]] = []
    for item, rules in REVISION_INVALIDATION_MATRIX.items():
        for dimension in dimensions:
            action = rules[dimension]
            row = {"item": item, "dimension": dimension, "action": action}
            if row not in actions:
                actions.append(row)

    workflow_event = str(workflow_state_event or "empty")
    if workflow_event == "authorization_stage_invalidated" and not dimensions:
        for item, action in (
            ("workflowStage", "revalidate"),
            ("semanticPreview", "invalidate"),
            ("approvalToken", "invalidate"),
            ("priorToolAuthorization", "never_retain"),
        ):
            actions.append(
                {
                    "item": item,
                    "dimension": "authorizationBoundary",
                    "action": action,
                }
            )

    if outcome in {"workflow_version_changed", "memory_expired"}:
        actions.extend(
            [
                {
                    "item": "workflowStage",
                    "dimension": outcome,
                    "action": "reset",
                },
                {
                    "item": "priorToolAuthorization",
                    "dimension": outcome,
                    "action": "never_retain",
                },
            ]
        )
    elif outcome == "explicitly_abandoned":
        actions.extend(
            [
                {
                    "item": "workflowStage",
                    "dimension": outcome,
                    "action": "reset",
                },
                {
                    "item": "semanticPreview",
                    "dimension": outcome,
                    "action": "invalidate",
                },
                {
                    "item": "approvalToken",
                    "dimension": outcome,
                    "action": "invalidate",
                },
                {
                    "item": "priorToolAuthorization",
                    "dimension": outcome,
                    "action": "never_retain",
                },
            ]
        )

    previous_state = dict(previous_workflow_state or {})
    current_state = dict(current_workflow_state or {})
    previous_entities = previous_state.get("entities") or {}
    current_entities = current_state.get("entities") or {}
    previous_referents = previous_state.get("referents") or {}
    current_referents = current_state.get("referents") or {}
    previous_evidence = previous_state.get("evidence_refs") or []
    current_evidence = current_state.get("evidence_refs") or []
    return {
        "schemaVersion": RECONCILIATION_SCHEMA_VERSION,
        "outcome": outcome,
        "workflowStateEvent": workflow_event,
        "previousScopeFingerprint": str(previous_scope_fingerprint or ""),
        "currentScopeFingerprint": str(current_scope_fingerprint or ""),
        "previousRevisionVectorSha256": revision_vector_sha256(
            previous_revision_vector
        ),
        "currentRevisionVectorSha256": revision_vector_sha256(
            current_revision_vector
        ),
        "changedDependencies": sorted(changed),
        "dimensions": list(dimensions),
        "actions": actions,
        "removedEntityFieldCount": max(
            0, len(previous_entities) - len(current_entities)
        ),
        "removedReferentFieldCount": max(
            0, len(previous_referents) - len(current_referents)
        ),
        "removedEvidenceRefCount": max(
            0, len(previous_evidence) - len(current_evidence)
        ),
        "continuityAction": "preserve",
        "staleContinuityEvidenceRefs": [],
        "warnings": [],
    }


def reconcile_continuity_summary(
    summary: Mapping[str, Any] | None,
    *,
    reconciliation_event: Mapping[str, Any],
    explicit_cross_scope_comparison: bool = False,
) -> ContinuityReconciliationResult:
    """Scope-gate or mark stale the untrusted structured continuity summary."""

    if summary is None:
        return ContinuityReconciliationResult(None, "preserve")
    outcome = str(reconciliation_event.get("outcome") or "")
    changed = frozenset(
        str(value)
        for value in reconciliation_event.get("changedDependencies") or []
    )
    current = copy.deepcopy(dict(summary))
    warnings = [str(value) for value in current.get("warnings") or []]
    source_refs = [str(value) for value in current.get("sourceEvidenceRefs") or []]
    if outcome == "scope_changed" and not explicit_cross_scope_comparison:
        return ContinuityReconciliationResult(
            None,
            "scope_gate",
            tuple(source_refs),
            ("continuity_summary_scope_gated",),
        )
    if outcome == "scope_changed":
        warning = "continuity_summary_cross_scope_comparison_only"
        warnings.append(warning)
        current["warnings"] = list(dict.fromkeys(warnings))
        return ContinuityReconciliationResult(
            current,
            "scope_gate",
            (),
            (warning,),
        )
    if outcome in {
        "same_scope_revision_advanced",
        "same_scope_dependency_removed",
    }:
        retained = filter_stale_evidence_refs(source_refs, changed)
        stale = tuple(value for value in source_refs if value not in retained)
        current["sourceEvidenceRefs"] = retained
        action = "mark_stale_refs"
        local_warnings: list[str] = []
        if stale:
            local_warnings.append("continuity_stale_evidence_refs_removed")
        if changed.intersection(POLICY_REVISION_FIELDS):
            action = "mark_stale_decisions"
            local_warnings.append("continuity_policy_decisions_require_reload")
        warnings.extend(local_warnings)
        current["warnings"] = list(dict.fromkeys(warnings))
        return ContinuityReconciliationResult(
            current,
            action,
            stale,
            tuple(local_warnings),
        )
    return ContinuityReconciliationResult(current, "preserve")


def reset_workflow_state_for_version(
    value: Mapping[str, Any],
    *,
    workflow_version: str,
    workflow_stages: Sequence[str],
    scope_fingerprint: str,
    revision_vector: Mapping[str, Any],
    now_epoch: float,
    ttl_seconds: float,
) -> Dict[str, Any]:
    """Fail closed when no explicit workflow-package migration is registered."""

    if not workflow_stages:
        raise ValueError("workflow version reset requires at least one stage")
    revisions = normalize_revision_vector(revision_vector)
    prior_receipts = [
        copy.deepcopy(item)
        for item in [
            *(value.get("audit_receipts") or []),
            *(value.get("last_execution_receipts") or []),
        ]
        if isinstance(item, Mapping)
    ][-40:]
    audit = [
        copy.deepcopy(item)
        for item in value.get("invalidation_audit") or []
        if isinstance(item, Mapping)
    ][-19:]
    audit.append(
        {
            "event": "workflow_version_changed",
            "actions": ["stage_specific_state_reset"],
            "warning": "workflow_state_migration_unavailable",
        }
    )
    now_iso = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    expires_iso = datetime.fromtimestamp(
        now_epoch + ttl_seconds, tz=timezone.utc
    ).isoformat().replace("+00:00", "Z")
    return {
        "state_version": 2,
        "workflow_id": str(value.get("workflow_id") or ""),
        "version": str(workflow_version),
        "status": "active",
        "stage": str(workflow_stages[0]),
        "objective": str(value.get("objective") or "Complete the selected workflow"),
        "entities": {},
        "evidence_refs": [],
        "referents": {},
        "milestones": {},
        "last_execution_receipts": [],
        "audit_receipts": prior_receipts,
        "pending_clarification": None,
        "scope_fingerprint": str(scope_fingerprint),
        "revision_vector": revisions,
        "revision_vector_sha256": revision_vector_sha256(revisions),
        "invalidation_audit": audit,
        "revision": int(value.get("revision") or 0) + 1,
        "created_at": str(value.get("created_at") or now_iso),
        "updated_at": now_iso,
        "expires_at": expires_iso,
    }


def revalidate_workflow_stage(
    workflow_id: str,
    current_stage: str,
    changed_dependencies: Iterable[str],
    *,
    fallback_stages: Sequence[str] = (),
) -> StageRevalidationResult:
    policy = WORKFLOW_STAGE_POLICIES.get(workflow_id)
    if policy is None or current_stage not in policy.stages:
        first_stage = policy.first_stage if policy else (fallback_stages[0] if fallback_stages else "")
        return StageRevalidationResult(
            stage=first_stage,
            event="stage_reset",
            warning="workflow_stage_revalidation_unavailable",
        )
    stage = policy.stages[current_stage]
    if stage.authorization_kind in AUTHORIZATION_KINDS:
        return _regress_stage(policy, stage, "authorization_stage_invalidated")
    changed = frozenset(changed_dependencies)
    if stage.dependencies.intersection(changed):
        return _regress_stage(policy, stage, "stage_regressed")
    return StageRevalidationResult(current_stage, "stage_preserved")


def apply_invalidation_action(
    action: str,
    item: Mapping[str, Any],
    current_context: Mapping[str, Any],
    changed_dependencies: Iterable[str],
) -> InvalidationResult:
    handlers: Mapping[str, Callable[..., InvalidationResult]] = {
        "reset": _reset_item,
        "preserve": _preserve_item,
        "revalidate": _revalidate_item,
        "invalidate": _invalidate_item,
        "invalidate_affected": _invalidate_affected,
        "retain_audit_only": _retain_audit_only,
        "never_retain": _never_retain,
        "scope_gate": _scope_gate,
        "mark_stale_refs": _mark_stale_refs,
        "mark_stale_decisions": _mark_stale_decisions,
    }
    handler = handlers.get(action)
    if handler is None:
        raise ValueError(f"unknown invalidation action: {action}")
    return handler(item, current_context, frozenset(changed_dependencies))


def revalidate_entities(
    entities: Mapping[str, Any], target_index: Mapping[str, Any]
) -> Dict[str, Any]:
    kind_by_key = {
        "characteristic_numbers": "fai_characteristic",
        "part_numbers": "part",
        "feature_ids": "feature",
        "motion_group_ids": "motion_group",
        "assembly_ids": "assembly",
        "process_map_ids": "process_map",
        "process_node_ids": "process_node",
        "process_edge_ids": "process_edge",
        "facility_layout_ids": "facility_layout",
        "facility_zone_ids": "facility_zone",
        "facility_placement_ids": "facility_placement",
        "facility_route_ids": "facility_route",
        "facility_utility_network_ids": "facility_utility_network",
        "facility_process_binding_ids": "facility_process_binding",
        "industrial_asset_ids": "industrial_asset",
    }
    singleton_kind_by_key = {
        "part_number": "part",
        "assembly_number": "assembly",
        "process_map_id": "process_map",
        "process_node_id": "process_node",
        "process_edge_id": "process_edge",
        "facility_layout_id": "facility_layout",
        "facility_zone_id": "facility_zone",
        "facility_placement_id": "facility_placement",
        "facility_route_id": "facility_route",
        "facility_utility_network_id": "facility_utility_network",
        "facility_process_binding_id": "facility_process_binding",
        "industrial_asset_id": "industrial_asset",
    }
    result = copy.deepcopy(dict(entities))
    for key, kind in kind_by_key.items():
        if key not in result or kind not in target_index:
            continue
        allowed = {str(value) for value in target_index.get(kind) or []}
        values = [str(value) for value in result.get(key) or []]
        retained = [value for value in values if value in allowed]
        if retained:
            result[key] = retained
        else:
            result.pop(key, None)
    for key, kind in singleton_kind_by_key.items():
        if key not in result or kind not in target_index:
            continue
        allowed = {str(value) for value in target_index.get(kind) or []}
        if str(result[key]) not in allowed:
            result.pop(key, None)
    return result


def revalidate_referents(
    referents: Mapping[str, Any], target_index: Mapping[str, Any]
) -> Dict[str, Any]:
    kind_by_key = {
        "last_characteristic_numbers": "fai_characteristic",
        "last_part_numbers": "part",
        "last_feature_ids": "feature",
        "last_motion_group_ids": "motion_group",
        "last_process_map_ids": "process_map",
        "last_process_node_ids": "process_node",
        "last_process_edge_ids": "process_edge",
        "last_facility_layout_ids": "facility_layout",
        "last_facility_zone_ids": "facility_zone",
        "last_facility_placement_ids": "facility_placement",
        "last_facility_route_ids": "facility_route",
        "last_facility_utility_network_ids": "facility_utility_network",
        "last_facility_process_binding_ids": "facility_process_binding",
        "last_industrial_asset_ids": "industrial_asset",
    }
    result = copy.deepcopy(dict(referents))
    for key, kind in kind_by_key.items():
        if key not in result or kind not in target_index:
            continue
        allowed = {str(value) for value in target_index.get(kind) or []}
        retained = [str(value) for value in result.get(key) or [] if str(value) in allowed]
        if retained:
            result[key] = retained
        else:
            result.pop(key, None)
    targets = result.get("last_targets")
    if isinstance(targets, list):
        retained_targets = []
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            kind = str(target.get("kind") or "")
            target_id = str(target.get("id") or "")
            if kind not in target_index or target_id in {
                str(value) for value in target_index.get(kind) or []
            }:
                retained_targets.append(copy.deepcopy(dict(target)))
        if retained_targets:
            result["last_targets"] = retained_targets
        else:
            result.pop("last_targets", None)
    return result


def filter_stale_evidence_refs(
    evidence_refs: Sequence[Any], changed_dependencies: Iterable[str]
) -> list[str]:
    changed = frozenset(changed_dependencies)
    retained: list[str] = []
    for raw in evidence_refs:
        value = str(raw)
        dependencies = _evidence_dependencies(value)
        if dependencies.intersection(changed):
            continue
        retained.append(value)
    return list(dict.fromkeys(retained))


def _regress_stage(
    policy: WorkflowStagePolicy,
    stage: StagePolicy,
    event: str,
) -> StageRevalidationResult:
    target = stage.safe_predecessor or policy.first_stage
    if not target or target not in policy.stages:
        return StageRevalidationResult(
            policy.first_stage,
            "stage_reset",
            "workflow_stage_revalidation_unavailable",
        )
    return StageRevalidationResult(target, event)


def _item_value(item: Mapping[str, Any]) -> Any:
    return copy.deepcopy(item.get("value"))


def _reset_item(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    defaults = current.get("defaults") if isinstance(current.get("defaults"), Mapping) else {}
    return InvalidationResult(copy.deepcopy(defaults.get(item.get("name"))), True)


def _preserve_item(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(_item_value(item), True)


def _revalidate_item(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    revalidator = current.get("revalidator")
    if not callable(revalidator):
        return InvalidationResult(None, False)
    value = revalidator(_item_value(item), changed)
    return InvalidationResult(copy.deepcopy(value), value is not None)


def _invalidate_item(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(None, False)


def _invalidate_affected(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    dependencies = frozenset(str(value) for value in item.get("dependencies") or [])
    if dependencies.intersection(changed):
        return InvalidationResult(None, False)
    return InvalidationResult(_item_value(item), True)


def _retain_audit_only(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(_item_value(item), False, audit_only=True)


def _never_retain(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(None, False)


def _scope_gate(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    allowed = bool(current.get("sameScope") or current.get("explicitCrossScopeComparison"))
    return InvalidationResult(_item_value(item) if allowed else None, allowed)


def _mark_stale_refs(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(_item_value(item), True, stale=True)


def _mark_stale_decisions(
    item: Mapping[str, Any], current: Mapping[str, Any], changed: frozenset[str]
) -> InvalidationResult:
    return InvalidationResult(_item_value(item), True, stale=True)


def _evidence_dependencies(value: str) -> frozenset[str]:
    if value.startswith("process-map:"):
        return frozenset({"processMapRevision", "productStructureRevision"})
    if value.startswith("fai:"):
        return frozenset({"faiRevision", "drawingRevision"})
    if value.startswith("feature:"):
        return frozenset({"partRevision", "drawingRevision"})
    if value.startswith("motion-group:") or value.startswith("motion-package:"):
        return frozenset({"motionAssetPin", "assemblyKnowledgeRevision"})
    return frozenset(REVISION_VECTOR_FIELDS)
