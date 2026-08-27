"""Server-owned, resumable Facility Layout generation coordination."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from typing import Any, Callable, Mapping

from .canonical import canonicalize_layout, layout_revision
from .diff import build_exact_layout_diff
from .feature_flags import FacilityLayoutFeatureFlags
from .g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
    default_g1_department_labels,
    g1_department_semantic_type,
    validate_g1_department_result,
)
from .generation_run_repository import (
    FacilityGenerationRunConflictError,
    FacilityGenerationRunRepository,
    FacilityGenerationRunRepositoryError,
)
from .knowledge_foundation import (
    FACILITY_GENERATION_RUN_SCHEMA_VERSION,
    FACILITY_GENERATION_STAGES,
    FacilityKnowledgeContractError,
    facility_knowledge_registry,
    facility_knowledge_revision,
    validate_department_partition_request,
    validate_facility_envelope_request,
    validate_facility_intent,
)
from .operations import apply_facility_layout_operations
from .provider_config import (
    FacilityProviderConfig,
    FacilityProviderConfigurationError,
    resolve_facility_provider_config,
)


G1_SCOPE = "facility_and_macro_departments"
G1_FACILITY_GENERATION_TOOL = "generate_facility_departments_draft"
G1_SKIPPED_STAGES = frozenset(
    {
        "primary_circulation",
        "department_subdivisions",
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "floor_communication",
    }
)


def g1_facility_generation_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for the G1 workflow."""

    return {
        "name": G1_FACILITY_GENERATION_TOOL,
        "description": (
            "Build or explicitly replace an unsaved prototype Facility Layout by "
            "setting the facility envelope and partitioning it into labeled macro "
            "departments. A complete whole-facility request may supersede current "
            "draft contents, while the saved layout remains unchanged until Save. "
            "Supply intent only. Never supply coordinates, boundaries, route points, "
            "placements, utilities, safety clearances, or approval. InspectorPro's "
            "deterministic G1 solver owns all geometry and validation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_envelope": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number", "exclusiveMinimum": 0},
                        "depth": {"type": "number", "exclusiveMinimum": 0},
                        "source_unit": {
                            "type": "string",
                            "enum": ["m", "mm", "ft", "in"],
                        },
                        "display_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 160,
                        },
                        "grid_size": {
                            "anyOf": [
                                {"type": "number", "exclusiveMinimum": 0},
                                {"type": "null"},
                            ]
                        },
                    },
                    "required": [
                        "width",
                        "depth",
                        "source_unit",
                        "display_name",
                        "grid_size",
                    ],
                    "additionalProperties": False,
                },
                "departments": {
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                        },
                        "labels": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 50,
                                    "uniqueItems": True,
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 120,
                                    },
                                },
                                {"type": "null"},
                            ]
                        },
                        "proportions": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 50,
                                    "items": {
                                        "type": "number",
                                        "exclusiveMinimum": 0,
                                    },
                                },
                                {"type": "null"},
                            ]
                        },
                        "arrangement": {
                            "type": "string",
                            "enum": [
                                "deterministic_grid",
                                "rows",
                                "columns",
                            ],
                        },
                        "orientation": {
                            "type": "string",
                            "enum": ["auto", "horizontal", "vertical"],
                        },
                    },
                    "required": [
                        "count",
                        "labels",
                        "proportions",
                        "arrangement",
                        "orientation",
                    ],
                    "additionalProperties": False,
                },
                "execution_mode": {
                    "type": "string",
                    "enum": [
                        "preview_only",
                        "authorized_draft_run",
                    ],
                },
            },
            "required": [
                "facility_envelope",
                "departments",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


class FacilityGenerationCoordinatorError(RuntimeError):
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


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{facility_knowledge_revision(value)[:24]}"


def _layout_matches_persisted_draft(
    current_layout: Mapping[str, Any],
    draft_layout: Mapping[str, Any],
) -> bool:
    """Compare saved content while allowing repository-owned timestamps."""

    current = canonicalize_layout(deepcopy(dict(current_layout)))
    draft = canonicalize_layout(deepcopy(dict(draft_layout)))
    for field in ("createdAt", "updatedAt"):
        if field in current:
            draft[field] = current[field]
    return canonicalize_layout(draft) == current


def _provider_fingerprint(config: FacilityProviderConfig) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "model": config.model,
        "reasoningEffort": config.reasoning_effort,
    }


def _public_run_view(
    artifacts: Mapping[str, Any],
    *,
    exact_diff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = artifacts["run"]
    run = envelope["run"]
    draft = artifacts.get("draft")
    intent_record = artifacts.get("intent")
    intent = intent_record.get("intent", {}) if isinstance(intent_record, Mapping) else {}
    stage_summaries = [
        {
            "stageId": stage["stageId"],
            "sequence": stage["sequence"],
            "label": stage.get("label") or stage["stageId"].replace("_", " ").title(),
            "status": stage["status"],
            "validation": deepcopy(stage["validation"]),
        }
        for stage in run["stageGraph"]
    ]
    return {
        "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
        "runId": run["runId"],
        "runRevision": envelope["runRevision"],
        "status": run["status"],
        "currentStageId": run["currentStageId"],
        "resumePoint": deepcopy(run["resumePoint"]),
        "stageGraph": stage_summaries,
        "receiptChain": list(run["receiptChain"]),
        "baseLayoutRevision": run["baseLayoutRevision"],
        "draftLayoutRevision": (
            draft.get("draftLayoutRevision")
            if isinstance(draft, Mapping)
            else None
        ),
        "executionMode": intent.get("executionMode"),
        "intentMode": intent.get("mode"),
        "prototypeMode": run["prototypeMode"],
        "writable": run["writable"],
        "effectiveProvider": run["effectiveProvider"],
        "effectiveModel": run["effectiveModel"],
        "reasoningEffort": run["reasoningEffort"],
        "saveEligibility": run["saveEligibility"],
        "cumulativeProposal": deepcopy(run["cumulativeProposal"]),
        "cumulativeDiff": deepcopy(dict(exact_diff)) if exact_diff else None,
        "terminalReason": run["terminalReason"],
        "expiresAt": run["expiresAt"],
    }


def build_g1_facility_intent(
    *,
    envelope_request: Mapping[str, Any],
    department_request: Mapping[str, Any],
    execution_mode: str = "authorized_draft_run",
    prototype_mode: bool = True,
    intent_mode: str = "greenfield",
    intent_id: str | None = None,
) -> dict[str, Any]:
    """Build a coordinate-free G1 intent from authored user requirements."""

    if intent_mode not in {"greenfield", "brownfield"}:
        raise FacilityKnowledgeContractError(
            "g1_intent_mode_invalid",
            "G1 supports greenfield creation or explicit whole-facility replacement.",
            details={"intentMode": intent_mode},
        )
    envelope = validate_facility_envelope_request(envelope_request)
    partition = validate_department_partition_request(department_request)
    labels = partition["labels"] or default_g1_department_labels(partition["count"])
    departments = []
    for index, (label, proportion) in enumerate(
        zip(labels, partition["proportions"], strict=True)
    ):
        _, semantic_type = g1_department_semantic_type(label)
        departments.append(
            {
                "requestId": f"department-{index + 1:02d}",
                "label": label,
                "semanticType": semantic_type,
                "quantity": 1,
                "proportion": proportion,
            }
        )
    identity_payload = {
        "scope": G1_SCOPE,
        "envelope": envelope,
        "departments": departments,
        "arrangement": partition["arrangement"],
        "orientation": partition["orientation"],
        "executionMode": execution_mode,
        "mode": intent_mode,
    }
    candidate = {
        "schemaVersion": 1,
        "intentId": intent_id or _stable_id("intent-g1", identity_payload),
        "mode": intent_mode,
        "facilityEnvelope": deepcopy(dict(envelope_request)),
        "originConvention": {
            "origin": "southwest_floor_corner",
            "northDirection": "positive_z",
            "source": "g1_deterministic_solver_contract",
        },
        "departments": departments,
        "circulation": [],
        "cells": [],
        "resources": [],
        "staging": [],
        "floorCommunication": [],
        "utilities": [],
        "expansion": None,
        "hardConstraints": [],
        "preferences": [
            {
                "preferenceId": "g1-department-partition",
                "kind": "department_partition",
                "arrangement": partition["arrangement"],
                "orientation": partition["orientation"],
            }
        ],
        "assumptions": list(partition["assumptions"]),
        "unresolvedItems": [],
        "sourceRevisionBindings": [],
        "authorityBindings": [],
        "executionMode": execution_mode,
        "savePolicy": "explicit_user_command",
        "prototypeMode": bool(prototype_mode),
    }
    return validate_facility_intent(candidate)


def _envelope_request_from_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    envelope = intent["facilityEnvelope"]
    source = envelope["source"]
    result = {
        "width": source["width"],
        "depth": source["depth"],
        "sourceUnit": source["unit"],
        "displayName": envelope["displayName"],
    }
    if "gridSizeMeters" in envelope:
        factors = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}
        result["gridSize"] = envelope["gridSizeMeters"] / factors[source["unit"]]
    return result


def _department_request_from_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    preferences = [
        item
        for item in intent["preferences"]
        if isinstance(item, Mapping) and item.get("kind") == "department_partition"
    ]
    preference = preferences[0] if preferences else {}
    departments = intent["departments"]
    return {
        "count": len(departments),
        "labels": [item["label"] for item in departments],
        "proportions": [item["proportion"] for item in departments],
        "arrangement": preference.get("arrangement", "deterministic_grid"),
        "orientation": preference.get("orientation", "auto"),
    }


class FacilityGenerationCoordinator:
    """Advance durable generation runs one deterministic stage at a time."""

    def __init__(
        self,
        repository: FacilityGenerationRunRepository,
        *,
        feature_flags: FacilityLayoutFeatureFlags,
        environ_provider: Callable[[], Mapping[str, str]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.feature_flags = feature_flags
        self._environ_provider = environ_provider or (lambda: os.environ)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _provider_config(self) -> FacilityProviderConfig:
        return resolve_facility_provider_config(self._environ_provider())

    def _require_mode_capability(self, execution_mode: str) -> None:
        capability = (
            "agent_preview" if execution_mode == "preview_only" else "agent_write"
        )
        self.feature_flags.require(capability)

    @staticmethod
    def _assert_provider_binding(
        run: Mapping[str, Any], config: FacilityProviderConfig
    ) -> None:
        observed = _provider_fingerprint(config)
        expected = {
            "provider": run["effectiveProvider"],
            "model": run["effectiveModel"],
            "reasoningEffort": run["reasoningEffort"],
        }
        if observed != expected:
            raise FacilityGenerationCoordinatorError(
                "facility_generation_provider_changed",
                "Facility provider configuration changed after the run started.",
                details={"expected": expected, "observed": observed},
            )

    def start_g1_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        workspace_id: str,
        layout_id: str,
        user_id: str,
        session_id: str,
        base_layout: Mapping[str, Any],
        base_layout_revision: str,
        envelope_request: Mapping[str, Any],
        department_request: Mapping[str, Any],
        execution_mode: str = "authorized_draft_run",
        prototype_mode: bool = True,
    ) -> dict[str, Any]:
        self._require_mode_capability(execution_mode)
        config = self._provider_config()
        normalized_base = canonicalize_layout(deepcopy(dict(base_layout)))
        if layout_revision(normalized_base) != base_layout_revision:
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_revision_mismatch",
                "The supplied base layout does not match its revision.",
            )
        nonempty_collections = [
            field
            for field in (
                "zones",
                "floorMarkings",
                "placements",
                "routes",
                "utilityNetworks",
                "processBindings",
            )
            if normalized_base.get(field)
        ]
        intent_mode = "brownfield" if nonempty_collections else "greenfield"
        intent = build_g1_facility_intent(
            envelope_request=envelope_request,
            department_request=department_request,
            execution_mode=execution_mode,
            prototype_mode=prototype_mode,
            intent_mode=intent_mode,
        )
        intent_hash = facility_knowledge_revision(intent)
        dependency_fingerprint = facility_knowledge_revision(
            {
                "scope": G1_SCOPE,
                "baseLayoutRevision": base_layout_revision,
                "intentHash": intent_hash,
                "knowledgeRegistryRevision": facility_knowledge_registry()[
                    "registryRevision"
                ],
                "provider": _provider_fingerprint(config),
                "featureFlags": self.feature_flags.to_dict(),
            }
        )
        created = self.repository.create_run(
            tenant_id=tenant_id,
            site_id=site_id,
            workspace_id=workspace_id,
            layout_id=layout_id,
            user_id=user_id,
            session_id=session_id,
            base_layout_revision=base_layout_revision,
            effective_provider=config.provider,
            effective_model=config.model,
            reasoning_effort=config.reasoning_effort,
            intent_hash=intent_hash,
            dependency_fingerprint=dependency_fingerprint,
            prototype_mode=prototype_mode,
            writable=execution_mode != "preview_only",
        )
        try:
            initialized = self.repository.initialize_execution_artifacts(
                tenant_id,
                site_id,
                created["run"]["runId"],
                intent=intent,
                base_layout=normalized_base,
            )
        except Exception:
            run = deepcopy(created["run"])
            run["status"] = "cancelled"
            run["terminalReason"] = "execution_artifact_initialization_failed"
            self.repository.update_run(
                run,
                expected_run_revision=created["runRevision"],
                lease_owner_token=(
                    run["writableLease"]["ownerToken"]
                    if run["writableLease"] is not None
                    else None
                ),
            )
            raise
        artifacts = {
            "run": created,
            "intent": initialized["intent"],
            "base": initialized["base"],
            "draft": initialized["draft"],
        }
        return _public_run_view(artifacts)

    def _compile_stage(
        self,
        stage_id: str,
        draft: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        if stage_id == "facility_envelope":
            return compile_g1_envelope_operations(
                draft,
                _envelope_request_from_intent(intent),
                replace_existing=intent.get("mode") == "brownfield",
            )
        if stage_id == "macro_departments":
            return compile_g1_department_operations(
                draft, _department_request_from_intent(intent)
            )
        if stage_id in G1_SKIPPED_STAGES:
            return {
                "stageId": stage_id,
                "selectedCommandIds": [],
                "operations": [],
                "plannedInstanceCount": 0,
                "normalizedRequest": {"scope": G1_SCOPE},
                "assumptions": [],
                "validationPlan": ["out_of_scope_for_g1"],
                "expectedSummary": {"saved": False},
            }
        if stage_id in {"deterministic_validation", "review_and_save"}:
            return {
                "stageId": stage_id,
                "selectedCommandIds": [],
                "operations": [],
                "plannedInstanceCount": 0,
                "normalizedRequest": {"scope": G1_SCOPE},
                "assumptions": [],
                "validationPlan": [
                    "full_g1_validation"
                    if stage_id == "deterministic_validation"
                    else "cumulative_diff_review"
                ],
                "expectedSummary": {"saved": False},
            }
        raise FacilityGenerationCoordinatorError(
            "generation_stage_not_supported",
            "The current generation stage is not implemented for G1.",
            details={"stageId": stage_id},
        )

    @staticmethod
    def _g1_validation(
        stage_id: str,
        result: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        errors = [
            item
            for item in result.get("findings", [])
            if isinstance(item, Mapping) and item.get("severity") == "error"
        ]
        checks: dict[str, Any] = {
            "operationFindings": deepcopy(result.get("findings", [])),
            "errorCount": len(errors),
        }
        if stage_id in {"macro_departments", "deterministic_validation"}:
            expected = compile_g1_department_operations(
                result["document"], _department_request_from_intent(intent)
            )["expectedSummary"]
            department_result = validate_g1_department_result(
                result["document"], expected
            )
            checks["departments"] = department_result
            if department_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g1_department_validation_failed",
                    }
                )
            prohibited = {
                field: len(result["document"].get(field, []))
                for field in (
                    "floorMarkings",
                    "placements",
                    "routes",
                    "utilityNetworks",
                    "processBindings",
                )
                if result["document"].get(field)
            }
            checks["unrequestedEntityCounts"] = prohibited
            if prohibited:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g1_unrequested_entities_present",
                    }
                )
        if stage_id == "facility_envelope":
            plan = result["document"].get("extensions", {}).get("facilityPlan")
            envelope = intent["facilityEnvelope"]
            envelope_valid = isinstance(plan, Mapping) and (
                float(plan.get("widthMeters", -1)) == float(envelope["widthMeters"])
                and float(plan.get("depthMeters", -1)) == float(envelope["depthMeters"])
            )
            checks["envelopeMatchesIntent"] = envelope_valid
            if not envelope_valid:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g1_envelope_validation_failed",
                    }
                )
        checks["errorCount"] = len(errors)
        return {
            "status": "valid" if not errors else "invalid",
            "findingIds": [
                str(item.get("code") or "facility_validation_error")
                for item in errors
            ],
            "checks": checks,
        }

    def continue_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        explicit_stage_acceptance: bool = False,
    ) -> dict[str, Any]:
        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        normalized_base = canonicalize_layout(deepcopy(dict(current_base_layout)))
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            self.repository.mark_stale_for_layout_revision(
                tenant_id,
                site_id,
                run_id,
                current_layout_revision=current_base_revision,
            )
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        if run["status"] in {"saved", "cancelled", "expired", "stale"}:
            raise FacilityGenerationCoordinatorError(
                "generation_run_not_continuable",
                "This generation run is terminal and cannot continue.",
                details={"status": run["status"]},
            )
        if run["status"] == "blocked":
            raise FacilityGenerationCoordinatorError(
                "generation_run_blocked",
                "The generation run is blocked and requires explicit resolution.",
            )
        if run["currentStageId"] is None:
            return _public_run_view(artifacts)
        if (
            intent["executionMode"] == "guided_draft"
            and not explicit_stage_acceptance
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_stage_approval_required",
                "Guided draft mode requires explicit acceptance for each stage.",
            )
        stage_id = run["currentStageId"]
        draft = artifacts["draft"]["document"]
        compiled = self._compile_stage(stage_id, draft, intent)
        operations = compiled["operations"]
        result = apply_facility_layout_operations(
            draft,
            operations,
            base_revision=artifacts["draft"]["draftLayoutRevision"],
        )
        validation = self._g1_validation(stage_id, result, intent)
        failed = validation["status"] != "valid"
        stage_status = (
            "blocked"
            if failed
            else "cancelled" if stage_id in G1_SKIPPED_STAGES else "complete"
        )
        sequence = next(
            item["sequence"]
            for item in FACILITY_GENERATION_STAGES
            if item["stageId"] == stage_id
        )
        stage_index = sequence - 1
        next_stage_id = (
            stage_id
            if failed
            else (
                FACILITY_GENERATION_STAGES[stage_index + 1]["stageId"]
                if stage_index + 1 < len(FACILITY_GENERATION_STAGES)
                else None
            )
        )
        receipt_identity = {
            "runId": run_id,
            "stageId": stage_id,
            "turnSequence": run["resumePoint"]["turnSequence"],
            "baseDraftRevision": artifacts["draft"]["draftLayoutRevision"],
            "resultDraftRevision": layout_revision(result["document"]),
            "dependencyFingerprint": run["dependencyFingerprint"],
            "operations": operations,
        }
        receipt_id = _stable_id("stage-receipt", receipt_identity)
        receipt = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "receiptId": receipt_id,
            "runId": run_id,
            "stageId": stage_id,
            "substageId": None,
            "stageSequence": sequence,
            "turnSequence": run["resumePoint"]["turnSequence"],
            "baseDraftRevision": artifacts["draft"]["draftLayoutRevision"],
            "resultDraftRevision": layout_revision(result["document"]),
            "dependencyFingerprint": run["dependencyFingerprint"],
            "selectedCommandIds": list(compiled["selectedCommandIds"]),
            "operationCount": len(operations),
            "plannedInstanceCount": int(compiled["plannedInstanceCount"]),
            "operationsHash": facility_knowledge_revision(operations),
            "affectedStableIds": list(result["affectedIds"]),
            "validation": validation,
            "status": "failed" if failed else "valid",
            "createdAt": run["updatedAt"],
        }
        stage_update = {
            "tenantId": tenant_id,
            "siteId": site_id,
            "status": stage_status,
            "inputs": deepcopy(compiled["normalizedRequest"]),
            "selectedCommandIds": list(compiled["selectedCommandIds"]),
            "previewId": _stable_id("preview", receipt_identity),
            "substageGraph": [
                {
                    "substageId": f"{stage_id}-01",
                    "sequence": 1,
                    "status": stage_status,
                    "operationCount": len(operations),
                    "plannedInstanceCount": int(compiled["plannedInstanceCount"]),
                    "operationReceiptIds": [receipt_id],
                    "validation": validation,
                    "affectedStableIds": list(result["affectedIds"]),
                }
            ],
            "validation": validation,
            "affectedStableIds": list(result["affectedIds"]),
            "assumptions": list(compiled["assumptions"]),
            "unresolvedFindings": list(validation["findingIds"]),
        }
        lease_token = (
            run["writableLease"]["ownerToken"]
            if run["writableLease"] is not None
            else None
        )
        checkpoint = self.repository.record_stage_checkpoint(
            receipt,
            result["document"],
            stage_update,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=lease_token,
            next_stage_id=next_stage_id,
        )
        checkpoint_artifacts = {
            "run": checkpoint["run"],
            "intent": artifacts["intent"],
            "base": artifacts["base"],
            "draft": checkpoint["draft"],
        }
        exact_diff = None
        if not failed and stage_id == "review_and_save":
            exact_diff = build_exact_layout_diff(
                normalized_base, checkpoint["draft"]["document"]
            )
            cumulative_hash = facility_knowledge_revision(
                {
                    "runId": run_id,
                    "baseLayoutRevision": run["baseLayoutRevision"],
                    "draftLayoutRevision": checkpoint["draft"][
                        "draftLayoutRevision"
                    ],
                    "receiptChain": checkpoint["run"]["run"]["receiptChain"],
                    "exactDiff": exact_diff,
                }
            )
            proposal = {
                "proposalId": _stable_id(
                    "generation-proposal",
                    {"runId": run_id, "cumulativeDiffHash": cumulative_hash},
                ),
                "runId": run_id,
                "baseLayoutRevision": run["baseLayoutRevision"],
                "draftLayoutRevision": checkpoint["draft"][
                    "draftLayoutRevision"
                ],
                "receiptChain": list(
                    checkpoint["run"]["run"]["receiptChain"]
                ),
                "dependencyFingerprint": run["dependencyFingerprint"],
                "cumulativeDiffHash": cumulative_hash,
                "validation": validation,
                "saveEligibility": (
                    "eligible"
                    if checkpoint["run"]["run"]["writable"]
                    else "blocked"
                ),
                "generatedAt": _timestamp(self._clock()),
            }
            proposal_run = deepcopy(checkpoint["run"]["run"])
            proposal_run["cumulativeDiffHash"] = cumulative_hash
            proposal_run["cumulativeProposal"] = proposal
            proposal_run["saveEligibility"] = proposal["saveEligibility"]
            updated = self.repository.update_run(
                proposal_run,
                expected_run_revision=checkpoint["run"]["runRevision"],
                lease_owner_token=lease_token,
            )
            checkpoint_artifacts["run"] = updated
        response = _public_run_view(checkpoint_artifacts, exact_diff=exact_diff)
        response["completedStageId"] = stage_id
        response["stageReceipt"] = deepcopy(checkpoint["stageReceipt"]["receipt"])
        response["draftLayout"] = deepcopy(checkpoint["draft"]["document"])
        return response

    def get_run(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        exact_diff = None
        run = artifacts["run"]["run"]
        if run["cumulativeProposal"] is not None:
            exact_diff = build_exact_layout_diff(
                artifacts["base"]["document"],
                artifacts["draft"]["document"],
            )
        result = _public_run_view(artifacts, exact_diff=exact_diff)
        result["draftLayout"] = deepcopy(artifacts["draft"]["document"])
        return result

    def invalidate_from_stage(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        upstream_stage_id: str,
        reason: str,
        dependency_fingerprint_after: str,
    ) -> dict[str, Any]:
        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run = artifacts["run"]["run"]
        if run["writableLease"] is None:
            raise FacilityGenerationCoordinatorError(
                "generation_invalidation_requires_writable_run",
                "Only a writable draft run can invalidate committed stages.",
            )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id=upstream_stage_id,
            reason=reason,
            dependency_fingerprint_after=dependency_fingerprint_after,
            expected_run_revision=artifacts["run"]["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        response = _public_run_view(
            {
                "run": invalidated["run"],
                "intent": artifacts["intent"],
                "base": artifacts["base"],
                "draft": invalidated["draft"],
            }
        )
        response["draftLayout"] = deepcopy(invalidated["draft"]["document"])
        response["invalidation"] = deepcopy(invalidated["invalidation"])
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        return response

    def undo_to_base(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run = artifacts["run"]["run"]
        if run["writableLease"] is None:
            raise FacilityGenerationCoordinatorError(
                "generation_undo_requires_writable_run",
                "Only a writable unsaved generation run can be undone.",
            )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="facility_envelope",
            reason="user_cancelled",
            dependency_fingerprint_after=run["dependencyFingerprint"],
            expected_run_revision=artifacts["run"]["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        cancelled_run = deepcopy(invalidated["run"]["run"])
        cancelled_run["status"] = "cancelled"
        cancelled_run["terminalReason"] = "user_undo_to_base"
        cancelled = self.repository.update_run(
            cancelled_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=cancelled_run["writableLease"]["ownerToken"],
        )
        return {
            "run": _public_run_view(
                {
                    "run": cancelled,
                    "intent": artifacts["intent"],
                    "base": artifacts["base"],
                    "draft": invalidated["draft"],
                }
            ),
            "restoredLayout": deepcopy(artifacts["base"]["document"]),
            "restoredLayoutRevision": artifacts["base"][
                "baseLayoutRevision"
            ],
            "supersededReceiptIds": list(
                invalidated["supersededReceiptIds"]
            ),
        }

    def save_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_cumulative_diff_hash: str,
        explicit_approval: bool,
        approved_by: str,
        persist: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
    ) -> dict[str, Any]:
        if explicit_approval is not True:
            raise FacilityGenerationCoordinatorError(
                "explicit_approval_required",
                "Saving a generated Facility Layout requires explicit approval.",
            )
        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if expected_cumulative_diff_hash != run["cumulativeDiffHash"]:
            raise FacilityGenerationCoordinatorError(
                "generation_approval_binding_mismatch",
                "Save approval does not bind the current cumulative diff.",
            )
        normalized_base = canonicalize_layout(deepcopy(dict(current_base_layout)))
        if layout_revision(normalized_base) != current_base_revision:
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The supplied saved layout revision does not match its content.",
            )
        draft_document = artifacts["draft"]["document"]
        persisted_draft_matches = _layout_matches_persisted_draft(
            normalized_base, draft_document
        )
        if run["status"] == "saved":
            if not persisted_draft_matches:
                raise FacilityGenerationCoordinatorError(
                    "generation_saved_layout_mismatch",
                    "The saved run no longer matches the current Facility Layout.",
                )
            save_receipt_id = _stable_id(
                "generation-save",
                {
                    "runId": run_id,
                    "savedLayoutRevision": current_base_revision,
                    "cumulativeDiffHash": run["cumulativeDiffHash"],
                },
            )
            saved_receipt = self.repository.get_saved_receipt(
                tenant_id,
                site_id,
                run["layoutId"],
                current_base_revision,
                save_receipt_id,
            )["receipt"]
            return {
                "run": _public_run_view(artifacts),
                "savedLayout": {
                    "layout": normalized_base,
                    "revision": current_base_revision,
                    "changed": False,
                    "recovered": True,
                },
                "saveReceipt": saved_receipt,
            }
        if (
            run["status"] != "complete"
            or run["saveEligibility"] != "eligible"
            or run["cumulativeProposal"] is None
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_run_not_save_eligible",
                "Generation must complete with a valid cumulative proposal before Save.",
            )
        base_is_current = current_base_revision == run["baseLayoutRevision"]
        if not base_is_current and not persisted_draft_matches:
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed before generated content was approved.",
            )
        for receipt_id in run["receiptChain"]:
            receipt = self.repository.get_stage_receipt(
                tenant_id, site_id, run_id, receipt_id
            )
            if receipt["effectiveStatus"] != "valid" or receipt["receipt"][
                "status"
            ] != "valid":
                raise FacilityGenerationCoordinatorError(
                    "generation_receipt_chain_invalid",
                    "Save is blocked by an invalid or superseded stage receipt.",
                    details={"receiptId": receipt_id},
                )
        save_intent = self.repository.prepare_save_intent(
            tenant_id,
            site_id,
            run_id,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
            cumulative_diff_hash=run["cumulativeDiffHash"],
            approved_by=approved_by,
        )
        if base_is_current:
            saved = deepcopy(
                dict(persist(draft_document, current_base_revision))
            )
        else:
            saved = {
                "layout": normalized_base,
                "revision": current_base_revision,
                "changed": False,
                "recovered": True,
            }
        saved_revision = str(saved.get("revision") or "")
        if not saved_revision:
            raise FacilityGenerationCoordinatorError(
                "generation_save_result_invalid",
                "The persistence service did not return a saved layout revision.",
            )
        saved_layout = saved.get("layout")
        if (
            not isinstance(saved_layout, Mapping)
            or layout_revision(canonicalize_layout(deepcopy(dict(saved_layout))))
            != saved_revision
            or not _layout_matches_persisted_draft(saved_layout, draft_document)
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_save_result_invalid",
                "The persisted Facility Layout does not match the approved draft.",
            )
        now = _timestamp(self._clock())
        save_receipt = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "saveReceiptId": _stable_id(
                "generation-save",
                {
                    "runId": run_id,
                    "savedLayoutRevision": saved_revision,
                    "cumulativeDiffHash": run["cumulativeDiffHash"],
                },
            ),
            "runId": run_id,
            "tenantId": tenant_id,
            "siteId": site_id,
            "workspaceId": run["workspaceId"],
            "layoutId": run["layoutId"],
            "baseLayoutRevision": run["baseLayoutRevision"],
            "savedLayoutRevision": saved_revision,
            "cumulativeDiffHash": run["cumulativeDiffHash"],
            "dependencyFingerprint": run["dependencyFingerprint"],
            "receiptChain": list(run["receiptChain"]),
            "approvedBy": save_intent["approvedBy"],
            "approvedAt": save_intent["approvedAt"],
            "persistedAt": now,
            "approvalSource": "explicit_user_command",
        }
        recorded = self.repository.record_saved_receipt(
            save_receipt,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        return {
            "run": _public_run_view(
                {
                    "run": recorded,
                    "intent": artifacts["intent"],
                    "base": artifacts["base"],
                    "draft": artifacts["draft"],
                }
            ),
            "savedLayout": saved,
            "saveReceipt": save_receipt,
        }


__all__ = [
    "G1_FACILITY_GENERATION_TOOL",
    "G1_SCOPE",
    "G1_SKIPPED_STAGES",
    "FacilityGenerationCoordinator",
    "FacilityGenerationCoordinatorError",
    "build_g1_facility_intent",
    "g1_facility_generation_tool_spec",
]
