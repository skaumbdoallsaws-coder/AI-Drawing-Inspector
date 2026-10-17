"""Server-owned, resumable Facility Layout generation coordination."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
from typing import Any, Callable, Mapping

from .asset_placement import (
    G4_ASSET_PLACEMENT_SCOPE,
    G4_FACILITY_ASSET_PLACEMENT_TOOL,
    FacilityAssetPlacementError,
    asset_placement_tool_spec,
    build_asset_catalog_snapshot,
    compile_asset_placement_program,
    normalize_asset_placement_request,
    validate_asset_placement_result,
)
from .canonical import canonicalize_layout, layout_revision
from .cell_composition import (
    G5_CELL_COMPOSITION_SCOPE,
    G5_FACILITY_CELL_COMPOSITION_TOOL,
    FacilityCellCompositionError,
    cell_composition_tool_spec,
    compile_cell_composition_program,
    normalize_cell_composition_request,
    validate_cell_composition_result,
)
from .cell_replication import (
    G6_CELL_REPLICATION_SCOPE,
    G6_FACILITY_CELL_REPLICATION_TOOL,
    FacilityCellReplicationError,
    cell_replication_tool_spec,
    compile_cell_replication_program,
    normalize_cell_replication_request,
    validate_cell_replication_result,
)
from .circulation import (
    G2_CIRCULATION_SCOPE,
    G2_FACILITY_CIRCULATION_TOOL,
    FacilityCirculationError,
    analyze_primary_circulation_network,
    analyze_primary_circulation_obstacles,
    analyze_primary_circulation_conflicts,
    circulation_tool_spec,
    compile_circulation_conflict_resolution_operations,
    compile_circulation_crossing_operations,
    compile_obstacle_aware_circulation_operations,
    compile_primary_circulation_operations,
    normalize_circulation_obstacle_context,
    normalize_circulation_request,
    validate_obstacle_aware_circulation_result,
    validate_circulation_crossing_result,
    validate_primary_circulation_result,
)
from .diff import build_exact_layout_diff
from .feature_flags import FacilityLayoutFeatureFlags
from .full_factory import (
    FULL_FACTORY_SCOPE,
    FULL_FACTORY_TOOL,
    FacilityFullFactoryError,
    compile_full_factory_program,
    full_factory_tool_spec,
)
from .facility_program import (
    FacilityProgramError,
    canonicalize_facility_program,
    facility_program_model_summary,
)
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
    FACILITY_MAXIMUM_OPERATION_BATCH,
    FACILITY_MAXIMUM_PLANNED_INSTANCES,
    FacilityKnowledgeContractError,
    facility_knowledge_registry,
    facility_knowledge_revision,
    validate_department_partition_request,
    validate_facility_envelope_request,
    validate_facility_intent,
)
from .operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations,
)
from .provider_config import (
    FacilityProviderConfig,
    FacilityProviderConfigurationError,
    resolve_facility_provider_config,
)
from .program_execution import (
    FACILITY_PROGRAM_STAGE_INPUT_SCOPE,
    FACILITY_PROGRAM_WORKFLOW_SCOPE,
    FacilityProgramExecutionError,
    amend_facility_program_resource_batch as execute_program_resource_amendment,
    compile_facility_program_operation_plan,
)
from .subdivisions import (
    G3_FACILITY_SUBDIVISION_TOOL,
    G3_SUBDIVISION_SCOPE,
    FacilitySubdivisionError,
    compile_department_subdivision_program,
    normalize_subdivision_request,
    subdivision_tool_spec,
    validate_department_subdivision_result,
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
_GENERATION_PLAN_INPUT_KEY = "_generationOperationPlan"
_FACILITY_PROGRAM_RESOLVED_STAGE_KEY = "_resolvedFacilityProgramStage"


def g2_facility_circulation_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for primary circulation."""

    return circulation_tool_spec()


def g3_facility_subdivision_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for department subdivisions."""

    return subdivision_tool_spec()


def g4_facility_asset_placement_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for department resources."""

    return asset_placement_tool_spec()


def g5_facility_cell_composition_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for seed cells."""

    return cell_composition_tool_spec()


def g6_facility_cell_replication_tool_spec() -> dict[str, Any]:
    """Return the coordinate-free Sage contract for repeated cell modules."""

    return cell_replication_tool_spec()


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
                                "row_stack",
                            ],
                        },
                        "orientation": {
                            "type": "string",
                            "enum": ["auto", "horizontal", "vertical"],
                        },
                        "rows": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 50,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "labels": {
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
                                            "proportion": {
                                                "anyOf": [
                                                    {
                                                        "type": "number",
                                                        "exclusiveMinimum": 0,
                                                    },
                                                    {"type": "null"},
                                                ]
                                            },
                                        },
                                        "required": ["labels", "proportion"],
                                        "additionalProperties": False,
                                    },
                                },
                                {"type": "null"},
                            ]
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


def _bounded_substage_counts(total: int, count: int, maximum: int) -> list[int]:
    remaining = int(total)
    values: list[int] = []
    for _ in range(count):
        value = min(maximum, remaining)
        values.append(value)
        remaining -= value
    if remaining != 0:
        raise FacilityGenerationCoordinatorError(
            "generation_substage_budget_invalid",
            "The generation stage could not be divided within its frozen budget.",
        )
    return values


def _operation_plan_chunks(plan: Mapping[str, Any]) -> list[list[dict[str, Any]]]:
    operations = [deepcopy(dict(item)) for item in plan["operations"]]
    chunks: list[list[dict[str, Any]]] = []
    offset = 0
    for count in plan["substageOperationCounts"]:
        chunks.append(operations[offset : offset + int(count)])
        offset += int(count)
    if offset != len(operations):
        raise FacilityGenerationCoordinatorError(
            "generation_operation_plan_invalid",
            "The durable stage operation plan no longer closes exactly.",
        )
    return chunks


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
        **({"gatewayRevision": config.gateway_route.config_revision} if config.gateway_route else {}),
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
    full_factory_preference = next(
        (
            item
            for item in intent.get("preferences", [])
            if isinstance(item, Mapping)
            and item.get("kind") == "full_factory_program"
        ),
        None,
    )
    facility_program_preference = next(
        (
            item
            for item in intent.get("preferences", [])
            if isinstance(item, Mapping)
            and item.get("kind") == "facility_program"
        ),
        None,
    )
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
        "workflowScope": (
            FACILITY_PROGRAM_WORKFLOW_SCOPE
            if isinstance(facility_program_preference, Mapping)
            else (
                FULL_FACTORY_SCOPE
                if isinstance(full_factory_preference, Mapping)
                else G1_SCOPE
            )
        ),
        "fullFactoryProgramRevision": (
            full_factory_preference.get("programRevision")
            if isinstance(full_factory_preference, Mapping)
            else None
        ),
        "facilityProgramRevision": (
            facility_program_preference.get("programRevision")
            if isinstance(facility_program_preference, Mapping)
            else None
        ),
        "facilityOperationPlanRevision": (
            facility_program_preference.get("operationPlanRevision")
            if isinstance(facility_program_preference, Mapping)
            else None
        ),
        "departmentLabels": [
            item.get("label")
            for item in intent.get("departments", [])
            if isinstance(item, Mapping)
        ],
        "departmentAreaShares": [
            item.get("proportion")
            for item in intent.get("departments", [])
            if isinstance(item, Mapping)
        ],
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
        "departmentPartition": deepcopy(
            next(
                (
                    item
                    for item in intent.get("preferences", [])
                    if isinstance(item, Mapping)
                    and item.get("kind") == "department_partition"
                ),
                None,
            )
        ),
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
        "rows": partition["rows"],
        "areaSizing": partition["areaSizing"],
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
                "rows": deepcopy(partition["rows"]),
                "rowOrder": partition["rowOrder"],
                "areaSizing": partition["areaSizing"],
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
        "rows": deepcopy(preference.get("rows")),
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
            **({"gatewayRevision": run["gatewayRevision"]} if "gatewayRevision" in run else {}),
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
            gateway_route=config.gateway_route,
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

    def start_full_factory_run(
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
        full_factory_request: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
        prototype_mode: bool = True,
    ) -> dict[str, Any]:
        """Create one immutable, restart-safe G1-G6 factory program."""

        execution_mode = str(
            full_factory_request.get("execution_mode")
            if isinstance(full_factory_request, Mapping)
            else ""
        )
        self._require_mode_capability(execution_mode)
        config = self._provider_config()
        normalized_base = canonicalize_layout(deepcopy(dict(base_layout)))
        if layout_revision(normalized_base) != base_layout_revision:
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_revision_mismatch",
                "The supplied base layout does not match its revision.",
            )
        try:
            compiled = compile_full_factory_program(
                full_factory_request,
                asset_catalog,
            )
        except FacilityFullFactoryError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        canonical = compiled["canonicalRequest"]
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
        intent = build_g1_facility_intent(
            envelope_request={
                "width": canonical["facility_envelope"]["width"],
                "depth": canonical["facility_envelope"]["depth"],
                "sourceUnit": canonical["facility_envelope"]["source_unit"],
                "displayName": canonical["facility_envelope"]["display_name"],
                **(
                    {
                        "gridSize": canonical["facility_envelope"][
                            "grid_size"
                        ]
                    }
                    if canonical["facility_envelope"]["grid_size"] is not None
                    else {}
                ),
            },
            department_request=canonical["departments"],
            execution_mode="authorized_draft_run",
            prototype_mode=prototype_mode,
            intent_mode=(
                "brownfield" if nonempty_collections else "greenfield"
            ),
        )
        intent["circulation"] = deepcopy(
            canonical["circulation"]["routes"]
        )
        intent["floorCommunication"] = deepcopy(
            canonical["circulation"]["crossings"]
        )
        intent["resources"] = deepcopy(compiled["resolvedAssets"])
        intent["cells"] = [
            *deepcopy(canonical.get("cell_recipes") or []),
            *deepcopy(canonical.get("module_families") or []),
        ]
        intent["staging"] = deepcopy(canonical["subdivisions"])
        intent["sourceRevisionBindings"] = [
            {
                "sourceId": item["assetId"],
                "revision": item["assetDefinitionRevision"],
                "evidenceStatus": "authored",
            }
            for item in compiled["resolvedAssets"]
        ]
        intent["preferences"].append(
            {
                "kind": "full_factory_program",
                "programRevision": compiled["programRevision"],
                "stageIds": sorted(compiled["stageInputs"]),
            }
        )
        intent["intentId"] = _stable_id(
            "intent-full-factory",
            {
                "programRevision": compiled["programRevision"],
                "baseLayoutRevision": base_layout_revision,
                "mode": intent["mode"],
            },
        )
        intent = validate_facility_intent(intent)
        intent_hash = facility_knowledge_revision(intent)
        dependency_fingerprint = facility_knowledge_revision(
            {
                "scope": FULL_FACTORY_SCOPE,
                "baseLayoutRevision": base_layout_revision,
                "intentHash": intent_hash,
                "programRevision": compiled["programRevision"],
                "stageInputsRevision": facility_knowledge_revision(
                    compiled["stageInputs"]
                ),
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
            gateway_route=config.gateway_route,
            intent_hash=intent_hash,
            dependency_fingerprint=dependency_fingerprint,
            prototype_mode=prototype_mode,
            writable=True,
            stage_inputs_by_id=compiled["stageInputs"],
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
                lease_owner_token=run["writableLease"]["ownerToken"],
            )
            raise
        return _public_run_view(
            {
                "run": created,
                "intent": initialized["intent"],
                "base": initialized["base"],
                "draft": initialized["draft"],
            }
        )

    def start_facility_program_run(
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
        facility_program: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
        prototype_mode: bool = True,
    ) -> dict[str, Any]:
        """Persist one resolved FacilityProgram and start its durable draft run."""

        self._require_mode_capability("authorized_draft_run")
        config = self._provider_config()
        normalized_base = canonicalize_layout(deepcopy(dict(base_layout)))
        if layout_revision(normalized_base) != base_layout_revision:
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_revision_mismatch",
                "The supplied base layout does not match its revision.",
            )
        try:
            canonical = canonicalize_facility_program(facility_program)
            if canonical["authority_and_mode"]["mode"] == "reference_reproduction":
                raise FacilityProgramExecutionError(
                    "facility_program_reference_adapter_required",
                    "Reference reproduction requires the reviewed manifest adapter.",
                )
            operation_plan = compile_facility_program_operation_plan(
                canonical,
                normalized_base,
                asset_catalog,
            )
        except (FacilityProgramError, FacilityProgramExecutionError) as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        macro_groups = canonical["macro_departments"]
        if len(macro_groups) != 1 or "count" not in macro_groups[0]:
            raise FacilityGenerationCoordinatorError(
                "facility_program_macro_partition_invalid",
                "A live intent-driven FacilityProgram requires one deterministic macro partition.",
            )
        envelope = canonical["facility_envelope"]
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
        intent = build_g1_facility_intent(
            envelope_request={
                "width": envelope["width"],
                "depth": envelope["depth"],
                "sourceUnit": envelope["source_unit"],
                "displayName": envelope["display_name"],
                **(
                    {"gridSize": envelope["grid_size"]}
                    if envelope["grid_size"] is not None
                    else {}
                ),
            },
            department_request=macro_groups[0],
            execution_mode="authorized_draft_run",
            prototype_mode=prototype_mode,
            intent_mode="brownfield" if nonempty_collections else "greenfield",
        )
        intent["circulation"] = deepcopy(
            canonical["route_network"]["primary_routes"]
        )
        intent["floorCommunication"] = deepcopy(
            canonical["floor_communication"]
        )
        intent["resources"] = [
            {
                "requestId": batch["batch_id"],
                "assetId": batch["exact_catalog_identity"]["asset_id"],
                "assetDefinitionRevision": batch["exact_catalog_identity"][
                    "asset_definition_revision"
                ],
                "assetName": batch["exact_catalog_identity"]["display_name"],
                "quantity": batch["quantity"],
                "targetArea": batch["target_area"],
                "placementPattern": batch["placement_pattern"],
                "orientationMode": batch["semantic_orientation"],
                "resourceRole": batch["resource_role"],
            }
            for batch in canonical["resource_batches"]
        ]
        intent["cells"] = [
            *deepcopy(canonical["cell_recipes"]),
            *deepcopy(canonical["module_families"]),
        ]
        intent["staging"] = deepcopy(canonical["area_hierarchy"])
        intent["unresolvedItems"] = deepcopy(
            canonical["unresolved_requirements"]
        )
        intent["sourceRevisionBindings"] = [
            {
                "sourceId": batch["exact_catalog_identity"]["asset_id"],
                "revision": batch["exact_catalog_identity"][
                    "asset_definition_revision"
                ],
                "evidenceStatus": canonical["authority_and_mode"][
                    "evidence_status"
                ],
            }
            for batch in canonical["resource_batches"]
        ]
        intent["authorityBindings"] = [
            {
                "authorityId": canonical["identity"]["program_id"],
                "status": "pending",
                "source": "prototype_program",
            }
        ]
        summary = facility_program_model_summary(canonical)
        intent["preferences"].append(
            {
                "kind": "facility_program",
                "programId": canonical["identity"]["program_id"],
                "programRevision": operation_plan["programRevision"],
                "operationPlanRevision": operation_plan["planRevision"],
                "mode": canonical["authority_and_mode"]["mode"],
                "summary": summary,
            }
        )
        intent["intentId"] = _stable_id(
            "intent-facility-program",
            {
                "programRevision": operation_plan["programRevision"],
                "planRevision": operation_plan["planRevision"],
                "baseLayoutRevision": base_layout_revision,
            },
        )
        intent = validate_facility_intent(intent)
        intent_hash = facility_knowledge_revision(intent)
        dependency_fingerprint = facility_knowledge_revision(
            {
                "scope": FACILITY_PROGRAM_WORKFLOW_SCOPE,
                "baseLayoutRevision": base_layout_revision,
                "intentHash": intent_hash,
                "programRevision": operation_plan["programRevision"],
                "operationPlanRevision": operation_plan["planRevision"],
                "knowledgeRegistryRevision": facility_knowledge_registry()[
                    "registryRevision"
                ],
                "provider": _provider_fingerprint(config),
                "featureFlags": self.feature_flags.to_dict(),
            }
        )
        stage_inputs_by_id = {
            stage["stageId"]: {
                "scope": FACILITY_PROGRAM_STAGE_INPUT_SCOPE,
                "programRevision": operation_plan["programRevision"],
                "operationPlanRevision": operation_plan["planRevision"],
                "stageId": stage["stageId"],
            }
            for stage in operation_plan["stages"]
        }
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
            gateway_route=config.gateway_route,
            intent_hash=intent_hash,
            dependency_fingerprint=dependency_fingerprint,
            prototype_mode=prototype_mode,
            writable=True,
            stage_inputs_by_id=stage_inputs_by_id,
        )
        run = created["run"]
        lease_token = run["writableLease"]["ownerToken"]
        try:
            self.repository.put_facility_program_artifact(
                tenant_id,
                site_id,
                run_id=run["runId"],
                program=canonical,
                operation_plan=operation_plan,
                expected_run_revision=created["runRevision"],
                lease_owner_token=lease_token,
            )
            initialized = self.repository.initialize_execution_artifacts(
                tenant_id,
                site_id,
                run["runId"],
                intent=intent,
                base_layout=normalized_base,
            )
        except Exception:
            cancelled = deepcopy(run)
            cancelled["status"] = "cancelled"
            cancelled["terminalReason"] = "facility_program_artifact_initialization_failed"
            self.repository.update_run(
                cancelled,
                expected_run_revision=created["runRevision"],
                lease_owner_token=lease_token,
            )
            raise
        return _public_run_view(
            {
                "run": created,
                "intent": initialized["intent"],
                "base": initialized["base"],
                "draft": initialized["draft"],
            }
        )

    def _compile_stage(
        self,
        stage_id: str,
        draft: Mapping[str, Any],
        intent: Mapping[str, Any],
        stage_inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (
            isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == FACILITY_PROGRAM_STAGE_INPUT_SCOPE
        ):
            resolved_stage = stage_inputs.get(_FACILITY_PROGRAM_RESOLVED_STAGE_KEY)
            if not isinstance(resolved_stage, Mapping) or resolved_stage.get(
                "stageId"
            ) != stage_id:
                raise FacilityGenerationCoordinatorError(
                    "facility_program_stage_artifact_missing",
                    "The immutable FacilityProgram stage artifact is unavailable.",
                )
            operations = [
                deepcopy(dict(operation))
                for batch in resolved_stage.get("batches", [])
                if isinstance(batch, Mapping)
                for operation in batch.get("operations", [])
                if isinstance(operation, Mapping)
            ]
            compact_request = {
                key: deepcopy(value)
                for key, value in stage_inputs.items()
                if key != _FACILITY_PROGRAM_RESOLVED_STAGE_KEY
            }
            command_ids = {
                "facility_envelope": (
                    ["clear-all"]
                    if any(
                        operation.get("op") == "clear_layout_contents"
                        for operation in operations
                    )
                    else []
                ),
                "macro_departments": ["bulk-zones"],
                "primary_circulation": ["aisle"] if operations else [],
                "department_subdivisions": ["bulk-zones"],
                "department_resources": ["assets"],
                "seed_cells": ["cell-layout", "create-cell-group"],
                "repeated_modules": ["duplicate", "create-cell-group"],
                "floor_communication": list(
                    dict.fromkeys(
                        command_id
                        for operation in operations
                        for command_id in (
                            ["aisle"]
                            if operation.get("op") in {"add_route", "edit_route"}
                            else ["floor-marking"]
                        )
                    )
                ),
                "deterministic_validation": [],
                "review_and_save": [],
            }[stage_id]
            return {
                "stageId": stage_id,
                "selectedCommandIds": command_ids,
                "operations": operations,
                "plannedInstanceCount": int(
                    resolved_stage.get("plannedInstanceCount") or 0
                ),
                "normalizedRequest": compact_request,
                "assumptions": [],
                "validationPlan": ["facility_program_revision_bound_stage"],
                "expectedSummary": {
                    "scope": FACILITY_PROGRAM_STAGE_INPUT_SCOPE,
                    "stageId": stage_id,
                    "operationPlanRevision": stage_inputs.get(
                        "operationPlanRevision"
                    ),
                    "expectedCounts": deepcopy(
                        resolved_stage.get("expectedCounts") or {}
                    ),
                    "expectedDraftRevision": resolved_stage.get(
                        "expectedDraftRevision"
                    ),
                    "saved": False,
                },
            }
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
        if (
            stage_id == "primary_circulation"
            and isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == G2_CIRCULATION_SCOPE
        ):
            requests = stage_inputs.get("requests")
            if not isinstance(requests, list) or not requests:
                requests = [stage_inputs]
            working = canonicalize_layout(deepcopy(dict(draft)))
            operations: list[dict[str, Any]] = []
            expectations: list[dict[str, Any]] = []
            assumptions: list[str] = []
            obstacle_context = normalize_circulation_obstacle_context(
                stage_inputs.get("obstacleContext")
                if isinstance(stage_inputs.get("obstacleContext"), Mapping)
                else None
            )
            for request in requests:
                if not isinstance(request, Mapping):
                    raise FacilityGenerationCoordinatorError(
                        "facility_circulation_program_invalid",
                        "Circulation stage requests must be objects.",
                    )
                compiled = compile_primary_circulation_operations(
                    working, request
                )
                operations.extend(compiled["operations"])
                expectations.append(compiled["expectedSummary"])
                assumptions.extend(compiled["assumptions"])
                working = apply_facility_layout_operations(
                    working,
                    compiled["operations"],
                    base_revision=layout_revision(working),
                )["document"]
            conflict_resolution = None
            resolution_request = stage_inputs.get("conflictResolution")
            if isinstance(resolution_request, Mapping):
                before_resolution = canonicalize_layout(deepcopy(working))
                resolved = compile_circulation_conflict_resolution_operations(
                    working,
                    resolution_request,
                )
                operations.extend(resolved["operations"])
                assumptions.extend(resolved["assumptions"])
                if resolved["operations"]:
                    working = apply_facility_layout_operations(
                        working,
                        resolved["operations"],
                        base_revision=layout_revision(working),
                    )["document"]
                conflict_resolution = deepcopy(resolved["expectedSummary"])
                conflict_resolution["beforeLayoutRevision"] = layout_revision(
                    before_resolution
                )
                by_id = {
                    str(route.get("routeId") or ""): route
                    for route in working.get("routes", [])
                    if isinstance(route, Mapping)
                }
                for expectation in expectations:
                    route = by_id.get(str(expectation.get("routeId") or ""))
                    if route is not None:
                        expectation["centerline"] = deepcopy(
                            route.get("centerline") or []
                        )
            obstacle_avoidance = None
            obstacle_request = stage_inputs.get("obstacleAvoidance")
            if isinstance(obstacle_request, Mapping):
                resolved_obstacles = compile_obstacle_aware_circulation_operations(
                    working,
                    obstacle_request,
                    obstacle_context,
                )
                operations.extend(resolved_obstacles["operations"])
                assumptions.extend(resolved_obstacles["assumptions"])
                if resolved_obstacles["operations"]:
                    working = apply_facility_layout_operations(
                        working,
                        resolved_obstacles["operations"],
                        base_revision=layout_revision(working),
                    )["document"]
                obstacle_avoidance = deepcopy(
                    resolved_obstacles["expectedSummary"]
                )
                by_id = {
                    str(route.get("routeId") or ""): route
                    for route in working.get("routes", [])
                    if isinstance(route, Mapping)
                }
                for expectation in expectations:
                    route = by_id.get(str(expectation.get("routeId") or ""))
                    if route is not None:
                        expectation["centerline"] = deepcopy(
                            route.get("centerline") or []
                        )
            crossing_expectations: list[dict[str, Any]] = []
            crossing_requests = stage_inputs.get("crossingRequests")
            if isinstance(crossing_requests, list):
                for crossing_request in crossing_requests:
                    if not isinstance(crossing_request, Mapping):
                        raise FacilityGenerationCoordinatorError(
                            "facility_circulation_program_invalid",
                            "Circulation crossing requests must be objects.",
                        )
                    effective_crossing = deepcopy(dict(crossing_request))
                    route_labels = effective_crossing.pop(
                        "routeLabels", None
                    )
                    if isinstance(route_labels, list):
                        routes_by_label: dict[str, list[Mapping[str, Any]]] = {}
                        for route in working.get("routes", []):
                            if not isinstance(route, Mapping):
                                continue
                            label = str(route.get("label") or "").strip()
                            if label:
                                routes_by_label.setdefault(
                                    label.casefold(), []
                                ).append(route)
                        resolved_routes = [
                            routes_by_label.get(str(label).casefold(), [])
                            for label in route_labels
                        ]
                        if len(route_labels) != 2 or any(
                            len(matches) != 1
                            for matches in resolved_routes
                        ):
                            raise FacilityGenerationCoordinatorError(
                                "full_factory_crossing_route_unresolved",
                                "Each crossing route label must resolve to one generated route.",
                                details={"routeLabels": route_labels},
                            )
                        effective_crossing = {
                            "action": "add_crossing",
                            "route_kind": None,
                            "width": None,
                            "source_unit": None,
                            "source_department": None,
                            "target_department": None,
                            "via_departments": [],
                            "direction": None,
                            "label": effective_crossing.get("label"),
                            "conflict_scope": None,
                            "minimum_separation": None,
                            "separation_unit": None,
                            "preserve_departments": True,
                            "adjust_route_kind": None,
                            "obstacle_scope": None,
                            "minimum_clearance": None,
                            "clearance_unit": None,
                            "preserve_route_identity": None,
                            "route_id": None,
                            "vehicle_profile_id": None,
                            "vehicle_profile_revision": None,
                            "allow_reverse": None,
                            "network_scope": "route_network",
                            "crossing_route_ids": [
                                str(matches[0]["routeId"])
                                for matches in resolved_routes
                            ],
                            "crossing_width": effective_crossing.get(
                                "crossingWidth"
                            ),
                            "crossing_depth": effective_crossing.get(
                                "crossingDepth"
                            ),
                            "crossing_width_unit": effective_crossing.get(
                                "crossingWidthUnit"
                            ),
                            "crossing_depth_unit": effective_crossing.get(
                                "crossingDepthUnit"
                            ),
                            "preserve_routes": True,
                            "execution_mode": "authorized_draft_run",
                        }
                    compiled_crossing = compile_circulation_crossing_operations(
                        working,
                        effective_crossing,
                    )
                    operations.extend(compiled_crossing["operations"])
                    assumptions.extend(compiled_crossing["assumptions"])
                    crossing_expectations.append(
                        deepcopy(compiled_crossing["expectedSummary"])
                    )
                    working = apply_facility_layout_operations(
                        working,
                        compiled_crossing["operations"],
                        base_revision=layout_revision(working),
                    )["document"]
            for expectation in expectations:
                expectation["routeCount"] = len(expectations)
            return {
                "stageId": stage_id,
                "selectedCommandIds": [
                    "aisle",
                    *(["floor-marking"] if crossing_expectations else []),
                ],
                "operations": operations,
                "plannedInstanceCount": (
                    len(expectations) + len(crossing_expectations)
                ),
                "normalizedRequest": deepcopy(dict(stage_inputs)),
                "assumptions": list(dict.fromkeys(assumptions)),
                "validationPlan": [
                    "route_identity",
                    "department_bindings",
                    "ordered_waypoints",
                    "facility_containment",
                    "route_width_exact",
                    "overlay_area_accounting",
                    *(
                        [
                            "mixed_traffic_geometric_non_overlap",
                            "department_geometry_byte_parity",
                        ]
                        if conflict_resolution is not None
                        else []
                    ),
                    *(
                        [
                            "static_obstacle_geometric_non_overlap",
                            "route_and_department_identity_preserved",
                            "authority_bound_clearance",
                        ]
                        if obstacle_avoidance is not None
                        else []
                    ),
                    *(
                        [
                            "exact_point_crossing",
                            "user_authored_crossing_dimensions",
                            "crosswalk_coverage_without_safety_claim",
                        ]
                        if crossing_expectations
                        else []
                    ),
                ],
                "expectedSummary": {
                    "routeCount": len(expectations),
                    "routes": expectations,
                    "conflictResolution": conflict_resolution,
                    "obstacleAvoidance": obstacle_avoidance,
                    "crossingCreations": crossing_expectations,
                    "saved": False,
                },
            }
        if (
            stage_id == "department_subdivisions"
            and isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == G3_SUBDIVISION_SCOPE
        ):
            requests = stage_inputs.get("requests")
            if not isinstance(requests, list):
                raise FacilityGenerationCoordinatorError(
                    "facility_subdivision_program_invalid",
                    "Subdivision stage inputs require an ordered request array.",
                )
            try:
                return compile_department_subdivision_program(draft, requests)
            except FacilitySubdivisionError as exc:
                raise FacilityGenerationCoordinatorError(
                    exc.code, str(exc), details=exc.details
                ) from exc
        if (
            stage_id == "department_resources"
            and isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == G4_ASSET_PLACEMENT_SCOPE
        ):
            requests = stage_inputs.get("requests")
            asset_catalog = stage_inputs.get("assetCatalog")
            if not isinstance(requests, list) or not isinstance(
                asset_catalog, list
            ):
                raise FacilityGenerationCoordinatorError(
                    "facility_asset_program_invalid",
                    "Asset-placement stage inputs require requests and an exact catalog snapshot.",
                )
            evidence_authority = stage_inputs.get("evidenceAuthority")
            try:
                return compile_asset_placement_program(
                    draft,
                    requests,
                    asset_catalog,
                    evidence_authority=(
                        evidence_authority
                        if isinstance(evidence_authority, Mapping)
                        else None
                    ),
                )
            except FacilityAssetPlacementError as exc:
                raise FacilityGenerationCoordinatorError(
                    exc.code, str(exc), details=exc.details
                ) from exc
        if (
            stage_id == "seed_cells"
            and isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == G5_CELL_COMPOSITION_SCOPE
        ):
            requests = stage_inputs.get("requests")
            if not isinstance(requests, list) or not requests:
                request = stage_inputs.get("request")
                requests = [request] if isinstance(request, Mapping) else []
            asset_catalog = stage_inputs.get("assetCatalog")
            if not requests or any(
                not isinstance(item, Mapping) for item in requests
            ) or not isinstance(asset_catalog, list):
                raise FacilityGenerationCoordinatorError(
                    "facility_cell_program_invalid",
                    "Cell-composition stage inputs require ordered requests and an exact catalog snapshot.",
                )
            evidence_authority = stage_inputs.get("evidenceAuthority")
            try:
                working = canonicalize_layout(deepcopy(dict(draft)))
                compiled_items = []
                for request in requests:
                    compiled_item = compile_cell_composition_program(
                        working,
                        request,
                        asset_catalog,
                        evidence_authority=(
                            evidence_authority
                            if isinstance(evidence_authority, Mapping)
                            else None
                        ),
                    )
                    compiled_items.append(compiled_item)
                    working = apply_facility_layout_operations(
                        working,
                        compiled_item["operations"],
                        base_revision=layout_revision(working),
                    )["document"]
                if len(compiled_items) == 1:
                    return compiled_items[0]
                operations = [
                    deepcopy(operation)
                    for item in compiled_items
                    for operation in item["operations"]
                ]
                return {
                    "stageId": stage_id,
                    "selectedCommandIds": ["cell-layout", "create-cell-group"],
                    "operations": operations,
                    "plannedInstanceCount": sum(
                        int(item["plannedInstanceCount"]) for item in compiled_items
                    ),
                    "normalizedRequest": deepcopy(dict(stage_inputs)),
                    "assumptions": list(
                        dict.fromkeys(
                            assumption
                            for item in compiled_items
                            for assumption in item["assumptions"]
                        )
                    ),
                    "validationPlan": ["multiple_independent_cell_recipes"],
                    "expectedSummary": {
                        "scope": G5_CELL_COMPOSITION_SCOPE,
                        "composite": True,
                        "items": [
                            deepcopy(item["expectedSummary"])
                            for item in compiled_items
                        ],
                        "saved": False,
                    },
                }
            except FacilityCellCompositionError as exc:
                raise FacilityGenerationCoordinatorError(
                    exc.code, str(exc), details=exc.details
                ) from exc
        if (
            stage_id == "repeated_modules"
            and isinstance(stage_inputs, Mapping)
            and stage_inputs.get("scope") == G6_CELL_REPLICATION_SCOPE
        ):
            requests = stage_inputs.get("requests")
            if not isinstance(requests, list) or not requests:
                request = stage_inputs.get("request")
                requests = [request] if isinstance(request, Mapping) else []
            asset_catalog = stage_inputs.get("assetCatalog")
            if not requests or any(
                not isinstance(item, Mapping) for item in requests
            ) or not isinstance(asset_catalog, list):
                raise FacilityGenerationCoordinatorError(
                    "facility_cell_module_program_invalid",
                    "Cell-replication stage inputs require ordered requests and an exact catalog snapshot.",
                )
            try:
                working = canonicalize_layout(deepcopy(dict(draft)))
                compiled_items = []
                for request in requests:
                    compiled_item = compile_cell_replication_program(
                        working, request, asset_catalog
                    )
                    compiled_items.append(compiled_item)
                    working = apply_facility_layout_operations(
                        working,
                        compiled_item["operations"],
                        base_revision=layout_revision(working),
                    )["document"]
                if len(compiled_items) == 1:
                    return compiled_items[0]
                operations = [
                    deepcopy(operation)
                    for item in compiled_items
                    for operation in item["operations"]
                ]
                return {
                    "stageId": stage_id,
                    "selectedCommandIds": ["duplicate", "create-cell-group"],
                    "operations": operations,
                    "plannedInstanceCount": sum(
                        int(item["plannedInstanceCount"]) for item in compiled_items
                    ),
                    "normalizedRequest": deepcopy(dict(stage_inputs)),
                    "assumptions": [],
                    "validationPlan": ["multiple_independent_module_families"],
                    "expectedSummary": {
                        "scope": G6_CELL_REPLICATION_SCOPE,
                        "composite": True,
                        "items": [
                            deepcopy(item["expectedSummary"])
                            for item in compiled_items
                        ],
                        "saved": False,
                    },
                }
            except FacilityCellReplicationError as exc:
                raise FacilityGenerationCoordinatorError(
                    exc.code, str(exc), details=exc.details
                ) from exc
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

    def _persist_oversized_stage_plan(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_envelope: Mapping[str, Any],
        stage_id: str,
        draft: Mapping[str, Any],
        compiled: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        operations = [deepcopy(dict(item)) for item in compiled["operations"]]
        operation_count = len(operations)
        planned_count = int(compiled["plannedInstanceCount"])
        if (
            operation_count <= FACILITY_MAXIMUM_OPERATION_BATCH
            and planned_count <= FACILITY_MAXIMUM_PLANNED_INSTANCES
        ):
            return None
        if operation_count == 0:
            raise FacilityGenerationCoordinatorError(
                "generation_stage_not_splittable",
                "A stage that plans more than 500 instances must expose bounded deterministic operations.",
            )
        substage_count = max(
            math.ceil(operation_count / FACILITY_MAXIMUM_OPERATION_BATCH),
            math.ceil(planned_count / FACILITY_MAXIMUM_PLANNED_INSTANCES),
        )
        operation_counts = _bounded_substage_counts(
            operation_count,
            substage_count,
            FACILITY_MAXIMUM_OPERATION_BATCH,
        )
        planned_counts = _bounded_substage_counts(
            planned_count,
            substage_count,
            FACILITY_MAXIMUM_PLANNED_INSTANCES,
        )
        run = run_envelope["run"]
        base_draft = canonicalize_layout(deepcopy(dict(draft)))
        operations_hash = facility_knowledge_revision(operations)
        plan_identity = {
            "runId": run["runId"],
            "stageId": stage_id,
            "baseDraftRevision": layout_revision(base_draft),
            "dependencyFingerprint": run["dependencyFingerprint"],
            "operationsHash": operations_hash,
            "substageOperationCounts": operation_counts,
            "substagePlannedInstanceCounts": planned_counts,
        }
        plan = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_stage_operation_plan",
            "planId": _stable_id("operation-plan", plan_identity),
            "runId": run["runId"],
            "stageId": stage_id,
            "baseDraftRevision": layout_revision(base_draft),
            "dependencyFingerprint": run["dependencyFingerprint"],
            "selectedCommandIds": list(compiled["selectedCommandIds"]),
            "normalizedRequest": deepcopy(compiled["normalizedRequest"]),
            "assumptions": list(compiled["assumptions"]),
            "expectedSummary": deepcopy(compiled.get("expectedSummary") or {}),
            "plannedInstanceCount": planned_count,
            "operationCount": operation_count,
            "operationsHash": operations_hash,
            "operations": operations,
            "substageCount": substage_count,
            "substageOperationCounts": operation_counts,
            "substagePlannedInstanceCounts": planned_counts,
            "baseDraft": base_draft,
            "createdAt": run["updatedAt"],
        }
        plan["planRevision"] = facility_knowledge_revision(plan)
        lease_token = (
            run["writableLease"]["ownerToken"]
            if run["writableLease"] is not None
            else None
        )
        return self.repository.put_stage_operation_plan(
            tenant_id,
            site_id,
            plan,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=lease_token,
        )

    def _load_oversized_stage_plan(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        stage_id: str,
        stage_inputs: Mapping[str, Any],
        dependency_fingerprint: str,
    ) -> dict[str, Any] | None:
        reference = stage_inputs.get(_GENERATION_PLAN_INPUT_KEY)
        if not isinstance(reference, Mapping):
            return None
        plan_id = str(reference.get("planId") or "")
        plan = self.repository.get_stage_operation_plan(
            tenant_id, site_id, run_id, plan_id
        )
        if (
            plan["stageId"] != stage_id
            or plan["dependencyFingerprint"] != dependency_fingerprint
            or plan["planRevision"] != reference.get("planRevision")
            or plan["substageCount"] != reference.get("substageCount")
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_operation_plan_stale",
                "The durable stage operation plan no longer matches this run.",
            )
        return plan

    @staticmethod
    def _g1_validation(
        stage_id: str,
        result: Mapping[str, Any],
        intent: Mapping[str, Any],
        circulation_expected: Mapping[str, Any] | None = None,
        circulation_obstacle_context: Mapping[str, Any] | None = None,
        subdivision_expected: Mapping[str, Any] | None = None,
        asset_expected: Mapping[str, Any] | None = None,
        asset_catalog: list[Mapping[str, Any]] | None = None,
        asset_evidence_authority: Mapping[str, Any] | None = None,
        cell_expected: Mapping[str, Any] | None = None,
        cell_catalog: list[Mapping[str, Any]] | None = None,
        cell_evidence_authority: Mapping[str, Any] | None = None,
        cell_base_layout: Mapping[str, Any] | None = None,
        module_expected: Mapping[str, Any] | None = None,
        module_catalog: list[Mapping[str, Any]] | None = None,
        module_base_layout: Mapping[str, Any] | None = None,
        facility_program_expected: Mapping[str, Any] | None = None,
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
        facility_program_mode = any(
            isinstance(item, Mapping) and item.get("kind") == "facility_program"
            for item in intent.get("preferences", [])
        )
        if (
            facility_program_mode
            and isinstance(facility_program_expected, Mapping)
            and facility_program_expected.get("scope")
            == FACILITY_PROGRAM_STAGE_INPUT_SCOPE
        ):
            actual_counts = {
                "zones": len(result["document"].get("zones", [])),
                "routes": len(result["document"].get("routes", [])),
                "placements": len(result["document"].get("placements", [])),
                "floorMarkings": len(result["document"].get("floorMarkings", [])),
            }
            expected_counts = dict(
                facility_program_expected.get("expectedCounts") or {}
            )
            expected_revision = facility_program_expected.get(
                "expectedDraftRevision"
            )
            actual_revision = layout_revision(result["document"])
            program_valid = (
                not errors
                and actual_counts == expected_counts
                and actual_revision == expected_revision
            )
            checks["facilityProgramStage"] = {
                "status": "valid" if program_valid else "invalid",
                "stageId": stage_id,
                "expectedCounts": expected_counts,
                "actualCounts": actual_counts,
                "expectedDraftRevision": expected_revision,
                "actualDraftRevision": actual_revision,
            }
            if stage_id == "deterministic_validation":
                checks["facilityProgram"] = deepcopy(
                    checks["facilityProgramStage"]
                )
            if not program_valid:
                errors.append(
                    {
                        "severity": "error",
                        "code": "facility_program_stage_execution_drift",
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
        if stage_id in {
            "macro_departments",
            "primary_circulation",
            "department_subdivisions",
            "department_resources",
            "seed_cells",
            "repeated_modules",
            "deterministic_validation",
        }:
            generated_child_ids = [
                str(zone.get("zoneId"))
                for zone in result["document"].get("zones", [])
                if isinstance(zone, Mapping)
                and isinstance(zone.get("extensions"), Mapping)
                and isinstance(
                    zone["extensions"].get("knowledgeFoundation"), Mapping
                )
                and zone["extensions"]["knowledgeFoundation"].get(
                    "generatedBy"
                )
                == "facility_subdivision_g3"
            ]
            expected = compile_g1_department_operations(
                result["document"], _department_request_from_intent(intent)
            )["expectedSummary"]
            department_result = validate_g1_department_result(
                result["document"],
                expected,
                allowed_extra_zone_ids=generated_child_ids,
            )
            checks["departments"] = department_result
            if department_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g1_department_validation_failed",
                    }
                )
            allowed_route_count = (
                len(result["document"].get("routes", []))
                if stage_id in {
                    "primary_circulation",
                    "department_subdivisions",
                    "department_resources",
                    "seed_cells",
                    "repeated_modules",
                    "deterministic_validation",
                }
                and all(
                    isinstance(route, Mapping)
                    and isinstance(route.get("extensions"), Mapping)
                    and isinstance(
                        route["extensions"].get("facilityAisle"), Mapping
                    )
                    and route["extensions"]["facilityAisle"].get(
                        "sourceZoneId"
                    )
                    and route["extensions"]["facilityAisle"].get(
                        "targetZoneId"
                    )
                    for route in result["document"].get("routes", [])
                )
                else 0
            )
            obstacle_stage = (
                stage_id == "primary_circulation"
                and isinstance(circulation_expected, Mapping)
                and isinstance(
                    circulation_expected.get("obstacleAvoidance"), Mapping
                )
            )
            crossing_stage = (
                stage_id == "primary_circulation"
                and isinstance(circulation_expected, Mapping)
                and bool(circulation_expected.get("crossingCreations"))
            )
            floor_markings = result["document"].get("floorMarkings", [])
            generated_crossing_markings = bool(floor_markings) and all(
                isinstance(marking, Mapping)
                and isinstance(marking.get("metadata"), Mapping)
                and marking["metadata"].get("generatedBy")
                == "facility_circulation_g23"
                for marking in floor_markings
            )
            generated_program_markings = (
                facility_program_mode
                and bool(floor_markings)
                and all(
                    isinstance(marking, Mapping)
                    and isinstance(marking.get("metadata"), Mapping)
                    and marking["metadata"].get("generatedBy")
                    in {
                        "facility_circulation_g23",
                        "facility_floor_communication_rq5",
                    }
                    for marking in floor_markings
                )
            )
            placements = result["document"].get("placements", [])
            generated_asset_placements = bool(placements) and all(
                isinstance(placement, Mapping)
                and isinstance(placement.get("metadata"), Mapping)
                and placement["metadata"].get("generatedBy")
                in (
                    {"facility_asset_placement_g4", "facility_industrial_patterns_rq3"}
                    if facility_program_mode
                    else {"facility_asset_placement_g4"}
                )
                for placement in placements
            )
            generated_module_placements = bool(placements) and all(
                isinstance(placement, Mapping)
                and isinstance(placement.get("metadata"), Mapping)
                and placement["metadata"].get("generatedBy")
                in {
                    "facility_asset_placement_g4",
                    "facility_cell_replication_g6",
                    *(
                        {"facility_industrial_patterns_rq3"}
                        if facility_program_mode
                        else set()
                    ),
                }
                for placement in placements
            )
            prohibited = {
                field: len(result["document"].get(field, []))
                for field in (
                    "floorMarkings",
                    "placements",
                    "utilityNetworks",
                    "processBindings",
                )
                if result["document"].get(field)
                and not (
                    (obstacle_stage and field in {"floorMarkings", "placements"})
                    or (
                        field == "placements"
                        and stage_id
                        in {
                            "department_resources",
                            "seed_cells",
                            "repeated_modules",
                            "deterministic_validation",
                        }
                        and (
                            generated_asset_placements
                            or generated_module_placements
                        )
                    )
                    or (
                        field == "floorMarkings"
                        and (
                            crossing_stage
                            or generated_crossing_markings
                            or generated_program_markings
                        )
                    )
                )
            }
            if (
                result["document"].get("routes")
                and allowed_route_count != len(result["document"]["routes"])
            ):
                prohibited["routes"] = len(result["document"]["routes"])
            checks["unrequestedEntityCounts"] = prohibited
            if prohibited:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g1_unrequested_entities_present",
                    }
                )
        if (
            stage_id == "deterministic_validation"
            and isinstance(facility_program_expected, Mapping)
            and facility_program_expected.get("scope")
            == FACILITY_PROGRAM_STAGE_INPUT_SCOPE
        ):
            actual_counts = {
                "zones": len(result["document"].get("zones", [])),
                "routes": len(result["document"].get("routes", [])),
                "placements": len(result["document"].get("placements", [])),
                "floorMarkings": len(result["document"].get("floorMarkings", [])),
            }
            expected_counts = dict(
                facility_program_expected.get("expectedCounts") or {}
            )
            expected_revision = facility_program_expected.get(
                "expectedDraftRevision"
            )
            program_valid = (
                actual_counts == expected_counts
                and layout_revision(result["document"]) == expected_revision
            )
            checks["facilityProgram"] = {
                "status": "valid" if program_valid else "invalid",
                "expectedCounts": expected_counts,
                "actualCounts": actual_counts,
                "expectedDraftRevision": expected_revision,
                "actualDraftRevision": layout_revision(result["document"]),
            }
            if not program_valid:
                errors.append(
                    {
                        "severity": "error",
                        "code": "facility_program_execution_drift",
                    }
                )
        if (
            stage_id == "repeated_modules"
            and isinstance(module_expected, Mapping)
            and module_expected.get("composite") is True
        ):
            zones_by_id = {
                str(item.get("zoneId") or ""): item
                for item in result["document"].get("zones", [])
                if isinstance(item, Mapping)
            }
            placements_by_id = {
                str(item.get("placementId") or ""): item
                for item in result["document"].get("placements", [])
                if isinstance(item, Mapping)
            }
            composite_errors = []
            for item in module_expected.get("items", []):
                for target_zone_id in item.get("targetZoneIds", []):
                    if target_zone_id not in zones_by_id:
                        composite_errors.append(
                            f"target_zone_missing:{target_zone_id}"
                        )
                for replica in item.get("replicas", []):
                    for copied in replica.get("copiedPlacements", []):
                        copied_id = str(copied.get("copiedPlacementId") or "")
                        actual = placements_by_id.get(copied_id)
                        if actual is None:
                            composite_errors.append(
                                f"copied_placement_missing:{copied_id}"
                            )
                        elif actual.get("assetDefinitionRevision") != copied.get(
                            "assetDefinitionRevision"
                        ):
                            composite_errors.append(
                                f"copied_revision_changed:{copied_id}"
                            )
            module_result = {
                "status": "valid" if not composite_errors else "invalid",
                "familyCount": len(module_expected.get("items", [])),
                "errors": composite_errors,
            }
            checks["repeatedModules"] = module_result
            if composite_errors:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g6_cell_replication_validation_failed",
                    }
                )
        elif (
            stage_id == "repeated_modules"
            and isinstance(module_expected, Mapping)
            and isinstance(module_catalog, list)
            and isinstance(module_base_layout, Mapping)
        ):
            module_result = validate_cell_replication_result(
                result["document"],
                module_expected,
                module_catalog,
                base_layout=module_base_layout,
            )
            checks["repeatedModules"] = module_result
            if module_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g6_cell_replication_validation_failed",
                    }
                )
        if (
            stage_id == "department_resources"
            and isinstance(asset_expected, Mapping)
            and isinstance(asset_catalog, list)
        ):
            asset_result = validate_asset_placement_result(
                result["document"],
                asset_expected,
                asset_catalog,
                evidence_authority=asset_evidence_authority,
            )
            checks["departmentResources"] = asset_result
            if asset_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g4_asset_placement_validation_failed",
                    }
                )
        if (
            stage_id == "seed_cells"
            and isinstance(cell_expected, Mapping)
            and cell_expected.get("composite") is True
        ):
            zones_by_id = {
                str(item.get("zoneId") or ""): item
                for item in result["document"].get("zones", [])
                if isinstance(item, Mapping)
            }
            placement_ids = {
                str(item.get("placementId") or "")
                for item in result["document"].get("placements", [])
                if isinstance(item, Mapping)
            }
            composite_errors = []
            for item in cell_expected.get("items", []):
                target_zone_id = str(item.get("targetZoneId") or "")
                target = zones_by_id.get(target_zone_id)
                if target is None:
                    composite_errors.append(
                        f"target_zone_missing:{target_zone_id}"
                    )
                else:
                    provenance = (
                        (target.get("extensions") or {}).get("layoutProvenance")
                    )
                    if not isinstance(provenance, Mapping) or provenance.get(
                        "command"
                    ) != "cell_layout":
                        composite_errors.append(
                            f"cell_provenance_missing:{target_zone_id}"
                        )
                for placement_id in item.get("memberPlacementIds", []):
                    if placement_id not in placement_ids:
                        composite_errors.append(
                            f"member_placement_missing:{placement_id}"
                        )
            cell_result = {
                "status": "valid" if not composite_errors else "invalid",
                "recipeCount": len(cell_expected.get("items", [])),
                "errors": composite_errors,
            }
            checks["seedCells"] = cell_result
            if composite_errors:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g5_cell_composition_validation_failed",
                    }
                )
        elif (
            stage_id == "seed_cells"
            and isinstance(cell_expected, Mapping)
            and isinstance(cell_catalog, list)
            and isinstance(cell_base_layout, Mapping)
        ):
            cell_result = validate_cell_composition_result(
                result["document"],
                cell_expected,
                cell_catalog,
                base_layout=cell_base_layout,
                evidence_authority=cell_evidence_authority,
            )
            checks["seedCells"] = cell_result
            if cell_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g5_cell_composition_validation_failed",
                    }
                )
        if stage_id == "department_subdivisions" and isinstance(
            subdivision_expected, Mapping
        ):
            subdivision_result = validate_department_subdivision_result(
                result["document"], subdivision_expected
            )
            checks["departmentSubdivisions"] = subdivision_result
            if subdivision_result["status"] != "valid":
                errors.append(
                    {
                        "severity": "error",
                        "code": "g3_department_subdivision_validation_failed",
                    }
                )
        if stage_id == "primary_circulation" and isinstance(
            circulation_expected, Mapping
        ):
            route_expectations = circulation_expected.get("routes")
            if not isinstance(route_expectations, list):
                route_expectations = [circulation_expected]
            circulation_results = [
                validate_primary_circulation_result(
                    result["document"], expected_route
                )
                for expected_route in route_expectations
                if isinstance(expected_route, Mapping)
            ]
            circulation_valid = (
                len(circulation_results) == len(route_expectations)
                and len(result["document"].get("routes", []))
                == int(circulation_expected.get("routeCount") or 0)
                and all(
                    item["status"] == "valid"
                    for item in circulation_results
                )
            )
            checks["primaryCirculation"] = {
                "status": "valid" if circulation_valid else "invalid",
                "routes": circulation_results,
                "routeCount": len(result["document"].get("routes", [])),
            }
            if not circulation_valid:
                errors.append(
                    {
                        "severity": "error",
                        "code": "g2_circulation_validation_failed",
                    }
                )
            conflict_expected = circulation_expected.get(
                "conflictResolution"
            )
            if isinstance(conflict_expected, Mapping):
                # Identity, width, binding, and zone byte-parity are guaranteed by
                # the deterministic compiler before its operations are returned.
                # Recompute the postcondition from the applied stage document.
                conflict_analysis = analyze_primary_circulation_conflicts(
                    result["document"]
                )
                requested_separation = float(
                    conflict_expected.get("minimumSeparationMeters") or 0.0
                )
                actual_separation = conflict_analysis.get(
                    "mixedTrafficPairMinimumSeparationMeters"
                )
                conflict_errors = []
                if conflict_analysis["mixedTrafficConflictCount"] != int(
                    conflict_expected.get("afterConflictCount") or 0
                ):
                    conflict_errors.append("mixed_traffic_conflict_remains")
                if requested_separation > 0 and (
                    actual_separation is None
                    or float(actual_separation) + 1e-6 < requested_separation
                ):
                    conflict_errors.append("authored_separation_not_met")
                conflict_validation = {
                    "status": "valid" if not conflict_errors else "invalid",
                    "mixedTrafficConflictCount": conflict_analysis[
                        "mixedTrafficConflictCount"
                    ],
                    "minimumSeparationMeters": actual_separation,
                    "adjustmentMode": conflict_expected.get("adjustmentMode"),
                    "selectedAlternativeId": conflict_expected.get(
                        "selectedAlternativeId"
                    ),
                    "alternatives": deepcopy(
                        conflict_expected.get("alternatives") or []
                    ),
                    "selectionQualification": conflict_expected.get(
                        "selectionQualification"
                    ),
                    "errors": conflict_errors,
                }
                checks["circulationConflictResolution"] = conflict_validation
                if conflict_validation["status"] != "valid":
                    errors.append({
                        "severity": "error",
                        "code": "g21_circulation_conflict_resolution_failed",
                    })
            obstacle_expected = circulation_expected.get(
                "obstacleAvoidance"
            )
            if isinstance(obstacle_expected, Mapping):
                obstacle_validation = validate_obstacle_aware_circulation_result(
                    result["document"],
                    obstacle_expected,
                    circulation_obstacle_context,
                )
                checks["circulationObstacleAvoidance"] = obstacle_validation
                if obstacle_validation["status"] != "valid":
                    errors.append({
                        "severity": "error",
                        "code": "g22_circulation_obstacle_avoidance_failed",
                    })
            crossing_expectations = circulation_expected.get(
                "crossingCreations"
            )
            if isinstance(crossing_expectations, list):
                crossing_results = [
                    validate_circulation_crossing_result(
                        result["document"], crossing_expected
                    )
                    for crossing_expected in crossing_expectations
                    if isinstance(crossing_expected, Mapping)
                ]
                crossing_valid = (
                    len(crossing_results) == len(crossing_expectations)
                    and all(
                        item["status"] == "valid"
                        for item in crossing_results
                    )
                )
                checks["circulationCrossings"] = {
                    "status": "valid" if crossing_valid else "invalid",
                    "crossings": crossing_results,
                }
                if not crossing_valid:
                    errors.append({
                        "severity": "error",
                        "code": "g23_circulation_crossing_failed",
                    })
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
        stage_record = next(
            item for item in run["stageGraph"] if item["stageId"] == stage_id
        )
        draft = artifacts["draft"]["document"]
        raw_stage_inputs = (
            stage_record.get("inputs")
            if isinstance(stage_record.get("inputs"), Mapping)
            else {}
        )
        operation_plan = self._load_oversized_stage_plan(
            tenant_id=tenant_id,
            site_id=site_id,
            run_id=run_id,
            stage_id=stage_id,
            stage_inputs=raw_stage_inputs,
            dependency_fingerprint=run["dependencyFingerprint"],
        )
        if operation_plan is None:
            compiler_inputs = {
                key: deepcopy(value)
                for key, value in raw_stage_inputs.items()
                if key != _GENERATION_PLAN_INPUT_KEY
            }
            if (
                compiler_inputs.get("scope")
                == FACILITY_PROGRAM_STAGE_INPUT_SCOPE
            ):
                artifact = self.repository.get_facility_program_artifact(
                    tenant_id, site_id, run_id
                )
                program_plan = artifact["operationPlan"]
                if (
                    artifact["programRevision"]
                    != compiler_inputs.get("programRevision")
                    or artifact["planRevision"]
                    != compiler_inputs.get("operationPlanRevision")
                    or artifact["baseLayoutRevision"]
                    != run["baseLayoutRevision"]
                ):
                    raise FacilityGenerationCoordinatorError(
                        "facility_program_stage_artifact_stale",
                        "The durable FacilityProgram no longer matches this run.",
                    )
                resolved_stage = next(
                    (
                        item
                        for item in program_plan["stages"]
                        if item.get("stageId") == stage_id
                    ),
                    None,
                )
                if not isinstance(resolved_stage, Mapping):
                    raise FacilityGenerationCoordinatorError(
                        "facility_program_stage_artifact_missing",
                        "The FacilityProgram does not contain the current stage.",
                    )
                compiler_inputs[_FACILITY_PROGRAM_RESOLVED_STAGE_KEY] = deepcopy(
                    resolved_stage
                )
                compiler_inputs["expectedCounts"] = deepcopy(
                    program_plan["expectedCounts"]
                )
                compiler_inputs["expectedDraftRevision"] = program_plan[
                    "expectedDraftRevision"
                ]
            compiled = self._compile_stage(
                stage_id,
                draft,
                intent,
                compiler_inputs,
            )
            operation_plan = self._persist_oversized_stage_plan(
                tenant_id=tenant_id,
                site_id=site_id,
                run_envelope=run_envelope,
                stage_id=stage_id,
                draft=draft,
                compiled=compiled,
            )
        else:
            compiled = {
                "stageId": stage_id,
                "selectedCommandIds": list(operation_plan["selectedCommandIds"]),
                "operations": deepcopy(operation_plan["operations"]),
                "plannedInstanceCount": operation_plan["plannedInstanceCount"],
                "normalizedRequest": deepcopy(operation_plan["normalizedRequest"]),
                "assumptions": list(operation_plan["assumptions"]),
                "expectedSummary": deepcopy(operation_plan["expectedSummary"]),
            }

        split_stage = operation_plan is not None
        validation_base_draft = (
            operation_plan["baseDraft"] if split_stage else draft
        )
        effective_stage_inputs = compiled["normalizedRequest"]
        if split_stage:
            chunks = _operation_plan_chunks(operation_plan)
            substage_ids = [
                f"{stage_id}-{index:02d}"
                for index in range(1, operation_plan["substageCount"] + 1)
            ]
            requested_substage_id = run["resumePoint"].get("substageId")
            if requested_substage_id is None:
                substage_index = 0
            else:
                try:
                    substage_index = substage_ids.index(requested_substage_id)
                except ValueError as exc:
                    raise FacilityGenerationCoordinatorError(
                        "generation_substage_resume_invalid",
                        "The durable generation resume point is not in its operation plan.",
                    ) from exc
            operations = chunks[substage_index]
            planned_instance_count = operation_plan[
                "substagePlannedInstanceCounts"
            ][substage_index]
            substage_id = substage_ids[substage_index]
            final_substage = substage_index == len(substage_ids) - 1
            next_substage_id = (
                None if final_substage else substage_ids[substage_index + 1]
            )
            stage_inputs_update = deepcopy(compiled["normalizedRequest"])
            stage_inputs_update[_GENERATION_PLAN_INPUT_KEY] = {
                "planId": operation_plan["planId"],
                "planRevision": operation_plan["planRevision"],
                "substageCount": operation_plan["substageCount"],
            }
        else:
            operations = compiled["operations"]
            planned_instance_count = int(compiled["plannedInstanceCount"])
            substage_id = None
            final_substage = True
            next_substage_id = None
            stage_inputs_update = deepcopy(compiled["normalizedRequest"])

        try:
            result = apply_facility_layout_operations(
                draft,
                operations,
                base_revision=artifacts["draft"]["draftLayoutRevision"],
            )
            operation_error = None
        except FacilityLayoutOperationError as exc:
            result = {
                "document": canonicalize_layout(deepcopy(dict(draft))),
                "affectedIds": [],
            }
            operation_error = exc

        if operation_error is not None:
            validation = {
                "status": "invalid",
                "findingIds": [str(operation_error.code)],
                "checks": {
                    "operationBatch": {
                        "status": "invalid",
                        "operationCount": len(operations),
                        "maximum": FACILITY_MAXIMUM_OPERATION_BATCH,
                        "errorCode": str(operation_error.code),
                    }
                },
            }
        elif split_stage and not final_substage:
            validation = {
                "status": "valid",
                "findingIds": [],
                "checks": {
                    "operationBatch": {
                        "status": "valid",
                        "operationCount": len(operations),
                        "maximum": FACILITY_MAXIMUM_OPERATION_BATCH,
                    },
                    "finalStageValidationDeferred": True,
                },
            }
        else:
            validation = self._g1_validation(
                stage_id,
                result,
                intent,
                circulation_expected=(
                    compiled.get("expectedSummary")
                    if stage_id == "primary_circulation"
                    and compiled.get("operations")
                    else None
                ),
                circulation_obstacle_context=(
                    effective_stage_inputs.get("obstacleContext")
                    if stage_id == "primary_circulation"
                    and isinstance(
                        effective_stage_inputs.get("obstacleContext"), Mapping
                    )
                    else None
                ),
                subdivision_expected=(
                    compiled.get("expectedSummary")
                    if stage_id == "department_subdivisions"
                    and compiled.get("operations")
                    else None
                ),
                asset_expected=(
                    compiled.get("expectedSummary")
                    if stage_id == "department_resources"
                    and compiled.get("operations")
                    else None
                ),
                asset_catalog=(
                    effective_stage_inputs.get("assetCatalog")
                    if stage_id == "department_resources"
                    and isinstance(effective_stage_inputs.get("assetCatalog"), list)
                    else None
                ),
                asset_evidence_authority=(
                    effective_stage_inputs.get("evidenceAuthority")
                    if stage_id == "department_resources"
                    and isinstance(
                        effective_stage_inputs.get("evidenceAuthority"), Mapping
                    )
                    else None
                ),
                cell_expected=(
                    compiled.get("expectedSummary")
                    if stage_id == "seed_cells" and compiled.get("operations")
                    else None
                ),
                cell_catalog=(
                    effective_stage_inputs.get("assetCatalog")
                    if stage_id == "seed_cells"
                    and isinstance(effective_stage_inputs.get("assetCatalog"), list)
                    else None
                ),
                cell_evidence_authority=(
                    effective_stage_inputs.get("evidenceAuthority")
                    if stage_id == "seed_cells"
                    and isinstance(
                        effective_stage_inputs.get("evidenceAuthority"), Mapping
                    )
                    else None
                ),
                cell_base_layout=(
                    validation_base_draft if stage_id == "seed_cells" else None
                ),
                module_expected=(
                    compiled.get("expectedSummary")
                    if stage_id == "repeated_modules"
                    and compiled.get("operations")
                    else None
                ),
                module_catalog=(
                    effective_stage_inputs.get("assetCatalog")
                    if stage_id == "repeated_modules"
                    and isinstance(effective_stage_inputs.get("assetCatalog"), list)
                    else None
                ),
                module_base_layout=(
                    validation_base_draft
                    if stage_id == "repeated_modules"
                    else None
                ),
                facility_program_expected=(
                    compiled.get("expectedSummary")
                    if isinstance(compiled.get("expectedSummary"), Mapping)
                    and compiled["expectedSummary"].get("scope")
                    == FACILITY_PROGRAM_STAGE_INPUT_SCOPE
                    else None
                ),
            )
        failed = validation["status"] != "valid"
        stage_status = (
            "blocked"
            if failed
            else (
                "running"
                if split_stage and not final_substage
                else (
                "cancelled"
                if stage_id in G1_SKIPPED_STAGES and not operations
                else "complete"
                )
            )
        )
        sequence = next(
            item["sequence"]
            for item in FACILITY_GENERATION_STAGES
            if item["stageId"] == stage_id
        )
        stage_index = sequence - 1
        next_stage_id = (
            stage_id
            if failed or (split_stage and not final_substage)
            else (
                FACILITY_GENERATION_STAGES[stage_index + 1]["stageId"]
                if stage_index + 1 < len(FACILITY_GENERATION_STAGES)
                else None
            )
        )
        receipt_identity = {
            "runId": run_id,
            "stageId": stage_id,
            "substageId": substage_id,
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
            "substageId": substage_id,
            "stageSequence": sequence,
            "turnSequence": run["resumePoint"]["turnSequence"],
            "baseDraftRevision": artifacts["draft"]["draftLayoutRevision"],
            "resultDraftRevision": layout_revision(result["document"]),
            "dependencyFingerprint": run["dependencyFingerprint"],
            "selectedCommandIds": list(compiled["selectedCommandIds"]),
            "operationCount": len(operations),
            "plannedInstanceCount": planned_instance_count,
            "operationsHash": facility_knowledge_revision(operations),
            "affectedStableIds": list(result["affectedIds"]),
            "validation": validation,
            "status": "failed" if failed else "valid",
            "createdAt": run["updatedAt"],
        }
        if split_stage:
            existing_substages = {
                item["substageId"]: deepcopy(item)
                for item in stage_record.get("substageGraph", [])
            }
            substage_graph = []
            for index, planned_substage_id in enumerate(substage_ids):
                record = existing_substages.get(planned_substage_id, {
                    "substageId": planned_substage_id,
                    "sequence": index + 1,
                    "status": "pending",
                    "operationCount": operation_plan[
                        "substageOperationCounts"
                    ][index],
                    "plannedInstanceCount": operation_plan[
                        "substagePlannedInstanceCounts"
                    ][index],
                    "operationReceiptIds": [],
                    "validation": {
                        "status": "pending",
                        "findingIds": [],
                    },
                    "affectedStableIds": [],
                })
                if index == substage_index:
                    record["status"] = "blocked" if failed else "complete"
                    record["operationReceiptIds"] = [
                        *record["operationReceiptIds"],
                        receipt_id,
                    ]
                    record["validation"] = deepcopy(validation)
                    record["affectedStableIds"] = list(
                        dict.fromkeys(
                            [
                                *record["affectedStableIds"],
                                *result["affectedIds"],
                            ]
                        )
                    )
                substage_graph.append(record)
            stage_affected_ids = list(
                dict.fromkeys(
                    [
                        *stage_record.get("affectedStableIds", []),
                        *result["affectedIds"],
                    ]
                )
            )
        else:
            substage_graph = [
                {
                    "substageId": f"{stage_id}-01",
                    "sequence": 1,
                    "status": stage_status,
                    "operationCount": len(operations),
                    "plannedInstanceCount": planned_instance_count,
                    "operationReceiptIds": [receipt_id],
                    "validation": validation,
                    "affectedStableIds": list(result["affectedIds"]),
                }
            ]
            stage_affected_ids = list(result["affectedIds"])
        stage_update = {
            "tenantId": tenant_id,
            "siteId": site_id,
            "status": stage_status,
            "inputs": stage_inputs_update,
            "selectedCommandIds": list(compiled["selectedCommandIds"]),
            "previewId": _stable_id("preview", receipt_identity),
            "substageGraph": substage_graph,
            "validation": validation,
            "affectedStableIds": stage_affected_ids,
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
            next_substage_id=next_substage_id,
        )
        checkpoint_artifacts = {
            "run": checkpoint["run"],
            "intent": artifacts["intent"],
            "base": artifacts["base"],
            "draft": checkpoint["draft"],
        }
        exact_diff = None
        if (
            not failed
            and final_substage
            and stage_id == "review_and_save"
        ):
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
        response["completedStageId"] = (
            stage_id if failed or final_substage else None
        )
        response["completedSubstageId"] = substage_id
        response["stageReceipt"] = deepcopy(checkpoint["stageReceipt"]["receipt"])
        response["draftLayout"] = deepcopy(checkpoint["draft"]["document"])
        return response

    def amend_facility_program_resource_batch(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        resource_batch_id: str,
        patch: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Apply one semantic, dependency-independent FacilityProgram amendment."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        facility_program_preference = next(
            (
                item
                for item in intent.get("preferences", [])
                if isinstance(item, Mapping)
                and item.get("kind") == "facility_program"
            ),
            None,
        )
        if not isinstance(facility_program_preference, Mapping):
            raise FacilityGenerationCoordinatorError(
                "facility_program_amendment_run_required",
                "Local FacilityProgram amendments require a Facility Planning draft.",
            )
        if (
            run["status"] != "complete"
            or run["currentStageId"] is not None
            or run["writable"] is not True
            or run["prototypeMode"] is not True
        ):
            raise FacilityGenerationCoordinatorError(
                "facility_program_amendment_requires_completed_draft",
                "Complete the active prototype FacilityProgram draft before amending it.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_program_amendment_draft_revision_conflict",
                "The active FacilityProgram draft changed before the amendment.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(
            deepcopy(dict(current_base_layout))
        )
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this FacilityProgram run started.",
            )

        effective = self.repository.get_effective_facility_program(
            tenant_id, site_id, run_id
        )
        try:
            amended = execute_program_resource_amendment(
                artifacts["draft"]["document"],
                effective["program"],
                asset_catalog,
                batch_id=resource_batch_id,
                patch=patch,
            )
        except FacilityProgramExecutionError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc

        amended_batch_ids = set(amended["amendedBatchIds"])

        def affected_ids(document: Mapping[str, Any]) -> list[str]:
            return sorted(
                str(item.get("placementId") or "")
                for item in document.get("placements", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("metadata"), Mapping)
                and str(item["metadata"].get("batchId") or "")
                in amended_batch_ids
                and str(item.get("placementId") or "")
            )

        before_ids = affected_ids(artifacts["draft"]["document"])
        after_ids = affected_ids(amended["draftLayout"])
        affected_stable_ids = sorted(set(before_ids) | set(after_ids))
        planned_instance_count = max(len(before_ids), len(after_ids))
        if planned_instance_count > FACILITY_MAXIMUM_PLANNED_INSTANCES:
            raise FacilityGenerationCoordinatorError(
                "facility_program_local_amendment_batch_budget_exceeded",
                "A local amendment cannot exceed the 500-instance receipt budget.",
                details={
                    "plannedInstanceCount": planned_instance_count,
                    "maximum": FACILITY_MAXIMUM_PLANNED_INSTANCES,
                },
            )

        semantic_operation = {
            "op": "amend_facility_program_resource_batch",
            "resourceBatchId": amended["batchId"],
            "patch": deepcopy(amended["appliedPatch"]),
            "programRevisionBefore": amended["programRevisionBefore"],
            "programRevisionAfter": amended["programRevisionAfter"],
        }
        operations_hash = facility_knowledge_revision([semantic_operation])
        dependency_fingerprint_after = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "resourceBatchId": amended["batchId"],
                "patch": amended["appliedPatch"],
                "programRevision": amended["programRevisionAfter"],
                "baseDraftRevision": expected_draft_revision,
                "resultDraftRevision": amended["draftLayoutRevision"],
            }
        )
        sequence = len(effective["amendments"]) + 1
        amendment_id = _stable_id(
            "program-amendment",
            {
                "runId": run_id,
                "sequence": sequence,
                "semanticOperation": semantic_operation,
                "baseDraftRevision": expected_draft_revision,
                "resultDraftRevision": amended["draftLayoutRevision"],
            },
        )
        created_at = _timestamp(self._clock())
        amendment_artifact = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_program_amendment",
            "amendmentId": amendment_id,
            "runId": run_id,
            "sequence": sequence,
            "baseProgramRevision": effective["programRevision"],
            "programRevision": amended["programRevisionAfter"],
            "resourceBatchId": amended["batchId"],
            "patch": deepcopy(amended["appliedPatch"]),
            "program": deepcopy(amended["facilityProgram"]),
            "baseDraftRevision": expected_draft_revision,
            "resultDraftRevision": amended["draftLayoutRevision"],
            "dependencyFingerprintBefore": run["dependencyFingerprint"],
            "dependencyFingerprintAfter": dependency_fingerprint_after,
            "operationsHash": operations_hash,
            "affectedStableIds": affected_stable_ids,
            "createdAt": created_at,
        }
        amendment_artifact["amendmentRevision"] = (
            facility_knowledge_revision(amendment_artifact)
        )
        lease_token = run["writableLease"]["ownerToken"]
        self.repository.put_facility_program_amendment(
            tenant_id,
            site_id,
            amendment=amendment_artifact,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=lease_token,
        )

        receipt_id = _stable_id(
            "stage-receipt",
            {
                "runId": run_id,
                "amendmentId": amendment_id,
                "operationsHash": operations_hash,
                "baseDraftRevision": expected_draft_revision,
                "resultDraftRevision": amended["draftLayoutRevision"],
            },
        )
        validation = {
            "status": "valid",
            "findingIds": [],
            "checks": {
                "localResourceAmendment": deepcopy(
                    amended["validation"]
                ),
                "protectedCollections": {
                    "status": "valid",
                    "collections": ["zones", "routes", "floorMarkings"],
                },
                "unrelatedPlacements": {"status": "valid"},
            },
        }
        receipt = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "receiptId": receipt_id,
            "runId": run_id,
            "stageId": "department_resources",
            "substageId": amendment_id,
            "stageSequence": next(
                item["sequence"]
                for item in FACILITY_GENERATION_STAGES
                if item["stageId"] == "department_resources"
            ),
            "turnSequence": len(run["receiptChain"]),
            "baseDraftRevision": expected_draft_revision,
            "resultDraftRevision": amended["draftLayoutRevision"],
            "dependencyFingerprint": dependency_fingerprint_after,
            "selectedCommandIds": ["assets"],
            "operationCount": 1,
            "plannedInstanceCount": planned_instance_count,
            "operationsHash": operations_hash,
            "affectedStableIds": affected_stable_ids,
            "validation": validation,
            "status": "valid",
            "createdAt": created_at,
        }
        next_receipt_chain = [*run["receiptChain"], receipt_id]
        exact_diff = build_exact_layout_diff(
            normalized_base, amended["draftLayout"]
        )
        cumulative_hash = facility_knowledge_revision(
            {
                "runId": run_id,
                "baseLayoutRevision": run["baseLayoutRevision"],
                "draftLayoutRevision": amended["draftLayoutRevision"],
                "receiptChain": next_receipt_chain,
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
            "draftLayoutRevision": amended["draftLayoutRevision"],
            "receiptChain": next_receipt_chain,
            "dependencyFingerprint": dependency_fingerprint_after,
            "cumulativeDiffHash": cumulative_hash,
            "validation": validation,
            "saveEligibility": "eligible",
            "generatedAt": created_at,
        }
        checkpoint = self.repository.record_completed_amendment_checkpoint(
            receipt,
            amended["draftLayout"],
            tenant_id=tenant_id,
            site_id=site_id,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=lease_token,
            amendment_id=amendment_id,
            dependency_fingerprint_before=run["dependencyFingerprint"],
            dependency_fingerprint_after=dependency_fingerprint_after,
            cumulative_proposal=proposal,
        )
        response = _public_run_view(
            {
                "run": checkpoint["run"],
                "intent": artifacts["intent"],
                "base": artifacts["base"],
                "draft": checkpoint["draft"],
            },
            exact_diff=exact_diff,
        )
        response["draftLayout"] = deepcopy(checkpoint["draft"]["document"])
        response["stageReceipt"] = deepcopy(
            checkpoint["stageReceipt"]["receipt"]
        )
        response["baseFacilityProgramRevision"] = effective[
            "baseProgramRevision"
        ]
        response["facilityProgramRevision"] = amended[
            "programRevisionAfter"
        ]
        response["facilityProgramAmendmentCount"] = sequence
        response["facilityProgramAmendment"] = {
            "amendmentId": amendment_id,
            "sequence": sequence,
            "resourceBatchId": amended["batchId"],
            "targetArea": amended["targetArea"],
            "patch": deepcopy(amended["appliedPatch"]),
            "removedPlacementCount": amended["removedPlacementCount"],
            "placedPlacementCount": amended["placedPlacementCount"],
            "protectedGeometryPreserved": True,
            "unrelatedPlacementsPreserved": True,
            "validationStatus": amended["validation"]["status"],
            "saved": False,
        }
        return response

    @staticmethod
    def _circulation_request_from_route(
        route: Mapping[str, Any],
        zones_by_id: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        extensions = route.get("extensions")
        aisle = (
            extensions.get("facilityAisle")
            if isinstance(extensions, Mapping)
            else None
        )
        if not isinstance(aisle, Mapping):
            raise FacilityGenerationCoordinatorError(
                "facility_circulation_route_unbound",
                "The active draft contains a route that is not a generated aisle.",
            )
        source_id = str(aisle.get("sourceZoneId") or "")
        target_id = str(aisle.get("targetZoneId") or "")
        via_ids = [str(item) for item in aisle.get("viaZoneIds", [])]
        missing = [
            item
            for item in [source_id, *via_ids, target_id]
            if item not in zones_by_id
        ]
        if not source_id or not target_id or missing:
            raise FacilityGenerationCoordinatorError(
                "facility_circulation_route_binding_missing",
                "A generated aisle no longer resolves to its departments.",
                details={"missingZoneIds": missing},
            )
        return {
            "scope": G2_CIRCULATION_SCOPE,
            "action": "create",
            "routeKind": str(aisle.get("aisleKind") or "material"),
            "sourceWidth": float(route.get("corridorWidth") or 0),
            "sourceUnit": "m",
            "widthMeters": float(route.get("corridorWidth") or 0),
            "sourceDepartment": str(zones_by_id[source_id].get("label") or ""),
            "targetDepartment": str(zones_by_id[target_id].get("label") or ""),
            "viaDepartments": [
                str(zones_by_id[item].get("label") or "") for item in via_ids
            ],
            "direction": str(aisle.get("direction") or "two_way"),
            "label": str(route.get("label") or ""),
            "executionMode": "authorized_draft_run",
            "areaAccounting": "overlay",
            "widthAuthority": str(
                aisle.get("widthAuthority") or "user_authored"
            ),
            "routeId": str(route.get("routeId") or ""),
            "compiledCenterline": deepcopy(route.get("centerline") or []),
            "assumptions": [],
        }

    def amend_primary_circulation(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        circulation_request: Mapping[str, Any],
        obstacle_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Supersede circulation descendants and finish one amended draft run."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if run["status"] != "complete" or run["writable"] is not True:
            raise FacilityGenerationCoordinatorError(
                "facility_circulation_requires_completed_draft",
                "Complete the active Facility generation draft before adding circulation.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_circulation_draft_revision_conflict",
                "The active Facility draft changed before circulation was applied.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(
            deepcopy(dict(current_base_layout))
        )
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        current_draft = artifacts["draft"]["document"]
        try:
            requested = normalize_circulation_request(
                circulation_request, current_draft
            )
            normalized_obstacle_context = normalize_circulation_obstacle_context(
                obstacle_context
            )
        except FacilityCirculationError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        zones_by_id = {
            str(zone.get("zoneId") or ""): zone
            for zone in current_draft.get("zones", [])
            if isinstance(zone, Mapping) and zone.get("zoneId")
        }
        prior_requests = [
            self._circulation_request_from_route(route, zones_by_id)
            for route in current_draft.get("routes", [])
            if isinstance(route, Mapping)
        ]
        existing_primary_stage = next(
            (
                stage
                for stage in run.get("stageGraph", [])
                if stage.get("stageId") == "primary_circulation"
            ),
            {},
        )
        existing_primary_inputs = existing_primary_stage.get("inputs")
        prior_crossing_requests = (
            deepcopy(existing_primary_inputs.get("crossingRequests"))
            if isinstance(existing_primary_inputs, Mapping)
            and isinstance(existing_primary_inputs.get("crossingRequests"), list)
            else []
        )
        action = requested["action"]
        conflict_resolution = None
        obstacle_avoidance = None
        if action == "edit_recent":
            if not prior_requests:
                raise FacilityGenerationCoordinatorError(
                    "facility_circulation_recent_route_missing",
                    "There is no active generated aisle to amend.",
                )
            amended = deepcopy(prior_requests[-1])
            amended.update(
                {
                    "routeKind": requested["routeKind"],
                    "sourceWidth": requested["sourceWidth"],
                    "sourceUnit": requested["sourceUnit"],
                    "widthMeters": requested["widthMeters"],
                    "direction": requested["direction"],
                    "widthAuthority": requested["widthAuthority"],
                    "sourceDepartment": requested["sourceDepartment"],
                    "targetDepartment": requested["targetDepartment"],
                    "viaDepartments": deepcopy(requested["viaDepartments"]),
                    "compiledCenterline": (
                        None
                        if requested.get("pathChanged") is True
                        else amended.get("compiledCenterline")
                    ),
                }
            )
            prior_requests[-1] = amended
        elif action == "resolve_conflicts":
            if len(prior_requests) < 2:
                raise FacilityGenerationCoordinatorError(
                    "facility_circulation_conflict_pair_required",
                    "At least two generated routes are required for conflict resolution.",
                )
            conflict_resolution = requested
        elif action == "avoid_obstacles":
            if not prior_requests:
                raise FacilityGenerationCoordinatorError(
                    "facility_circulation_recent_route_missing",
                    "There is no active generated aisle to reroute.",
                )
            obstacle_avoidance = requested
        elif action == "add_crossing":
            prior_crossing_requests.append(requested)
        else:
            prior_requests.append(requested)
        program = {
            "scope": G2_CIRCULATION_SCOPE,
            "requests": prior_requests,
            "amendmentAction": action,
            "conflictResolution": conflict_resolution,
            "obstacleAvoidance": obstacle_avoidance,
            "crossingRequests": prior_crossing_requests,
            "obstacleContext": normalized_obstacle_context,
        }
        dependency_fingerprint = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "circulationProgram": program,
                "draftRevision": expected_draft_revision,
            }
        )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="primary_circulation",
            reason="upstream_dependency_changed",
            dependency_fingerprint_after=dependency_fingerprint,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        amended_run = deepcopy(invalidated["run"]["run"])
        primary_stage = next(
            stage
            for stage in amended_run["stageGraph"]
            if stage["stageId"] == "primary_circulation"
        )
        primary_stage["inputs"] = program
        updated = self.repository.update_run(
            amended_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=amended_run["writableLease"]["ownerToken"],
        )
        response: dict[str, Any] | None = None
        remaining = len(FACILITY_GENERATION_STAGES)
        while updated["run"]["currentStageId"] is not None and remaining > 0:
            response = self.continue_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                current_base_layout=normalized_base,
                current_base_revision=current_base_revision,
            )
            updated = self.repository.get_run(tenant_id, site_id, run_id)
            if response.get("status") == "blocked":
                validation = response.get("stageReceipt", {}).get(
                    "validation", {}
                )
                finding_ids = validation.get("findingIds", [])
                crossing_errors = [
                    str(error)
                    for crossing in (
                        validation.get("checks", {})
                        .get("circulationCrossings", {})
                        .get("crossings", [])
                    )
                    if isinstance(crossing, Mapping)
                    for error in crossing.get("errors", [])
                ]
                raise FacilityGenerationCoordinatorError(
                    "facility_circulation_run_blocked",
                    "The circulation amendment failed deterministic validation"
                    + (
                        ": " + ", ".join(str(item) for item in finding_ids)
                        if finding_ids
                        else "."
                    )
                    + (
                        " (" + ", ".join(crossing_errors) + ")"
                        if crossing_errors
                        else ""
                    ),
                    details={
                        "stageId": response.get("completedStageId"),
                        "findingIds": finding_ids,
                        "crossingErrors": crossing_errors,
                    },
                )
            remaining -= 1
        if response is None or response.get("status") != "complete":
            raise FacilityGenerationCoordinatorError(
                "facility_circulation_run_incomplete",
                "The circulation amendment did not reach review-ready state.",
            )
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        primary_stage = next(
            (
                stage for stage in updated["run"]["stageGraph"]
                if stage.get("stageId") == "primary_circulation"
            ),
            {},
        )
        conflict_validation = (
            primary_stage.get("validation", {})
            .get("checks", {})
            .get("circulationConflictResolution")
        )
        obstacle_validation = (
            primary_stage.get("validation", {})
            .get("checks", {})
            .get("circulationObstacleAvoidance")
        )
        crossing_validation = (
            primary_stage.get("validation", {})
            .get("checks", {})
            .get("circulationCrossings")
        )
        obstacle_analysis = analyze_primary_circulation_obstacles(
            response["draftLayout"],
            normalized_obstacle_context,
            minimum_clearance_meters=float(
                requested.get("minimumClearanceMeters") or 0.0
            ),
        )
        response["circulation"] = {
            "action": action,
            "routeCount": len(response["draftLayout"].get("routes", [])),
            "saved": False,
            "areaAccounting": "overlay",
            **(
                {
                    "conflictAnalysis": analyze_primary_circulation_conflicts(
                        response["draftLayout"]
                    ),
                    "conflictResolution": {
                        "status": (
                            "resolved"
                            if analyze_primary_circulation_conflicts(
                                response["draftLayout"]
                            )["mixedTrafficConflictCount"] == 0
                            else "unresolved"
                        ),
                        "minimumSeparationMeters": requested.get(
                            "minimumSeparationMeters"
                        ),
                        "separationAuthority": requested.get(
                            "separationAuthority"
                        ),
                        "preservedDepartments": True,
                        "adjustmentMode": (
                            conflict_validation.get("adjustmentMode")
                            if isinstance(conflict_validation, Mapping)
                            else requested.get("adjustRouteKind")
                        ),
                        "selectedAlternativeId": (
                            conflict_validation.get("selectedAlternativeId")
                            if isinstance(conflict_validation, Mapping)
                            else None
                        ),
                        "alternatives": (
                            deepcopy(conflict_validation.get("alternatives") or [])
                            if isinstance(conflict_validation, Mapping)
                            else []
                        ),
                        "selectionQualification": (
                            conflict_validation.get("selectionQualification")
                            if isinstance(conflict_validation, Mapping)
                            else None
                        ),
                    }
                }
                if action == "resolve_conflicts"
                else {}
            ),
            **(
                {
                    "obstacleAnalysis": obstacle_analysis,
                    "obstacleAvoidance": {
                        "status": (
                            "clear"
                            if obstacle_analysis[
                                "routeObstacleConflictCount"
                            ] == 0
                            else "conflict"
                        ),
                        "routeId": requested.get("routeId"),
                        "minimumClearanceMeters": requested.get(
                            "minimumClearanceMeters"
                        ),
                        "clearanceAuthority": requested.get(
                            "clearanceAuthority"
                        ),
                        "vehicleTurningValidated": (
                            obstacle_validation.get(
                                "vehicleTurningValidated"
                            )
                            if isinstance(obstacle_validation, Mapping)
                            else False
                        ),
                        "preservedDepartments": True,
                        "preservedRouteIdentity": True,
                    },
                }
                if action == "avoid_obstacles"
                else {}
            ),
            **(
                {
                    "crossingCreation": {
                        "status": (
                            "marked"
                            if isinstance(crossing_validation, Mapping)
                            and crossing_validation.get("status") == "valid"
                            else "invalid"
                        ),
                        "crossingId": requested.get("crossingId"),
                        "routeIds": deepcopy(
                            requested.get("crossingRouteIds") or []
                        ),
                        "widthMeters": requested.get(
                            "crossingWidthMeters"
                        ),
                        "depthMeters": requested.get(
                            "crossingDepthMeters"
                        ),
                        "dimensionAuthority": requested.get(
                            "crossingDimensionAuthority"
                        ),
                        "positionAuthority": requested.get(
                            "crossingPositionAuthority"
                        ),
                        "qualification": (
                            "Marks the exact route-centerline crossing only; it "
                            "does not establish traffic safety or regulatory "
                            "compliance."
                        ),
                    }
                }
                if action == "add_crossing"
                else {}
            ),
            **(
                {
                    "networkAnalysis": analyze_primary_circulation_network(
                        response["draftLayout"]
                    )
                }
                if action == "add_crossing"
                else {}
            ),
        }
        return response

    def amend_department_subdivisions(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        subdivision_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Replace or append one G3 subdivision in the durable draft run."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if run["status"] != "complete" or run["writable"] is not True:
            raise FacilityGenerationCoordinatorError(
                "facility_subdivision_requires_completed_draft",
                "Complete the active Facility generation draft before subdividing it.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_subdivision_draft_revision_conflict",
                "The active Facility draft changed before subdivision was applied.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(
            deepcopy(dict(current_base_layout))
        )
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        try:
            requested = normalize_subdivision_request(
                subdivision_request, artifacts["draft"]["document"]
            )
        except FacilitySubdivisionError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc

        subdivision_stage = next(
            stage
            for stage in run["stageGraph"]
            if stage["stageId"] == "department_subdivisions"
        )
        prior_inputs = subdivision_stage.get("inputs")
        prior_requests = (
            deepcopy(prior_inputs.get("requests"))
            if isinstance(prior_inputs, Mapping)
            and isinstance(prior_inputs.get("requests"), list)
            else []
        )
        action = "add"
        replaced = False
        for index, prior in enumerate(prior_requests):
            if (
                isinstance(prior, Mapping)
                and str(prior.get("parentZoneId") or "")
                == requested["parentZoneId"]
            ):
                prior_requests[index] = requested
                action = "replace"
                replaced = True
                break
        if not replaced:
            prior_requests.append(requested)
        program = {
            "scope": G3_SUBDIVISION_SCOPE,
            "requests": prior_requests,
            "amendmentAction": action,
        }
        dependency_fingerprint = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "subdivisionProgram": program,
                "draftRevision": expected_draft_revision,
            }
        )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="department_subdivisions",
            reason="upstream_dependency_changed",
            dependency_fingerprint_after=dependency_fingerprint,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        amended_run = deepcopy(invalidated["run"]["run"])
        next_stage = next(
            stage
            for stage in amended_run["stageGraph"]
            if stage["stageId"] == "department_subdivisions"
        )
        next_stage["inputs"] = program
        updated = self.repository.update_run(
            amended_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=amended_run["writableLease"]["ownerToken"],
        )
        response: dict[str, Any] | None = None
        remaining = len(FACILITY_GENERATION_STAGES)
        while updated["run"]["currentStageId"] is not None and remaining > 0:
            response = self.continue_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                current_base_layout=normalized_base,
                current_base_revision=current_base_revision,
            )
            updated = self.repository.get_run(tenant_id, site_id, run_id)
            if response.get("status") == "blocked":
                finding_ids = (
                    response.get("stageReceipt", {})
                    .get("validation", {})
                    .get("findingIds", [])
                )
                raise FacilityGenerationCoordinatorError(
                    "facility_subdivision_run_blocked",
                    "The subdivision amendment failed deterministic validation.",
                    details={
                        "stageId": response.get("completedStageId"),
                        "findingIds": finding_ids,
                    },
                )
            remaining -= 1
        if response is None or response.get("status") != "complete":
            raise FacilityGenerationCoordinatorError(
                "facility_subdivision_run_incomplete",
                "The subdivision amendment did not reach review-ready state.",
            )
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        generated = [
            zone
            for zone in response["draftLayout"].get("zones", [])
            if isinstance(zone, Mapping)
            and isinstance(zone.get("extensions"), Mapping)
            and isinstance(
                zone["extensions"].get("knowledgeFoundation"), Mapping
            )
            and zone["extensions"]["knowledgeFoundation"].get("generatedBy")
            == "facility_subdivision_g3"
        ]
        response["subdivisions"] = {
            "action": action,
            "parentDepartment": requested["parentDepartment"],
            "parentZoneId": requested["parentZoneId"],
            "childLabels": list(requested["labels"]),
            "childZoneCount": len(generated),
            "subdivisionCount": len(prior_requests),
            "assumptions": list(requested["assumptions"]),
            "saved": False,
            "parentPreserved": True,
            "unrelatedLayoutPreserved": True,
        }
        return response

    def amend_asset_placements(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        asset_request: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
        evidence_authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one revision-bound G4 placement request to a durable run."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if run["status"] != "complete" or run["writable"] is not True:
            raise FacilityGenerationCoordinatorError(
                "facility_asset_requires_completed_draft",
                "Complete the active Facility generation draft before placing assets.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_asset_draft_revision_conflict",
                "The active Facility draft changed before assets were placed.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(deepcopy(dict(current_base_layout)))
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        try:
            normalized = normalize_asset_placement_request(
                asset_request,
                artifacts["draft"]["document"],
                asset_catalog,
            )
        except FacilityAssetPlacementError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc

        resource_stage = next(
            stage
            for stage in run["stageGraph"]
            if stage["stageId"] == "department_resources"
        )
        prior_inputs = resource_stage.get("inputs")
        prior_requests = (
            deepcopy(prior_inputs.get("requests"))
            if isinstance(prior_inputs, Mapping)
            and isinstance(prior_inputs.get("requests"), list)
            else []
        )
        request_id = f"asset-request-{len(prior_requests) + 1:03d}"
        requested = {
            "request_id": request_id,
            "asset_id": normalized["assetId"],
            "asset_definition_revision": normalized[
                "assetDefinitionRevision"
            ],
            "quantity": normalized["quantity"],
            "target_area": normalized["targetArea"],
            "orientation_mode": normalized["orientationMode"],
            "facing_direction": normalized["facingDirection"],
            "resource_role": normalized["resourceRole"],
            "access_requirement": normalized["accessRequirement"],
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        }
        prior_requests.append(requested)
        prior_catalog = (
            deepcopy(prior_inputs.get("assetCatalog"))
            if isinstance(prior_inputs, Mapping)
            and isinstance(prior_inputs.get("assetCatalog"), list)
            else []
        )
        try:
            snapshot = build_asset_catalog_snapshot(
                [*prior_catalog, *asset_catalog], prior_requests
            )
        except FacilityAssetPlacementError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        program: dict[str, Any] = {
            "scope": G4_ASSET_PLACEMENT_SCOPE,
            "requests": prior_requests,
            "assetCatalog": snapshot,
        }
        if isinstance(evidence_authority, Mapping):
            program["evidenceAuthority"] = deepcopy(dict(evidence_authority))
        preflight_document = deepcopy(artifacts["draft"]["document"])
        preflight_document["placements"] = [
            deepcopy(placement)
            for placement in preflight_document.get("placements", [])
            if not (
                isinstance(placement, Mapping)
                and isinstance(placement.get("metadata"), Mapping)
                and placement["metadata"].get("generatedBy")
                == "facility_asset_placement_g4"
            )
        ]
        preflight_document = canonicalize_layout(preflight_document)
        try:
            compile_asset_placement_program(
                preflight_document,
                prior_requests,
                snapshot,
                evidence_authority=evidence_authority,
            )
        except FacilityAssetPlacementError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        dependency_fingerprint = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "assetRequests": prior_requests,
                "assetCatalogRevision": facility_knowledge_revision(snapshot),
                "draftRevision": expected_draft_revision,
            }
        )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="department_resources",
            reason="upstream_dependency_changed",
            dependency_fingerprint_after=dependency_fingerprint,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        amended_run = deepcopy(invalidated["run"]["run"])
        next_stage = next(
            stage
            for stage in amended_run["stageGraph"]
            if stage["stageId"] == "department_resources"
        )
        next_stage["inputs"] = program
        updated = self.repository.update_run(
            amended_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=amended_run["writableLease"]["ownerToken"],
        )
        response: dict[str, Any] | None = None
        remaining = len(FACILITY_GENERATION_STAGES)
        while updated["run"]["currentStageId"] is not None and remaining > 0:
            response = self.continue_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                current_base_layout=normalized_base,
                current_base_revision=current_base_revision,
            )
            updated = self.repository.get_run(tenant_id, site_id, run_id)
            if response.get("status") == "blocked":
                finding_ids = (
                    response.get("stageReceipt", {})
                    .get("validation", {})
                    .get("findingIds", [])
                )
                raise FacilityGenerationCoordinatorError(
                    "facility_asset_run_blocked",
                    "The asset-placement amendment failed deterministic validation.",
                    details={
                        "stageId": response.get("completedStageId"),
                        "findingIds": finding_ids,
                    },
                )
            remaining -= 1
        if response is None or response.get("status") != "complete":
            raise FacilityGenerationCoordinatorError(
                "facility_asset_run_incomplete",
                "The asset-placement amendment did not reach review-ready state.",
            )
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        generated = [
            placement
            for placement in response["draftLayout"].get("placements", [])
            if isinstance(placement, Mapping)
            and isinstance(placement.get("metadata"), Mapping)
            and placement["metadata"].get("generatedBy")
            == "facility_asset_placement_g4"
        ]
        current_placements = [
            placement
            for placement in generated
            if placement["metadata"].get("requestId") == request_id
        ]
        access_validated = sum(
            placement["metadata"].get("accessStatus") == "validated"
            for placement in current_placements
        )
        response["assetPlacements"] = {
            "requestId": request_id,
            "assetId": normalized["assetId"],
            "assetDefinitionRevision": normalized[
                "assetDefinitionRevision"
            ],
            "displayName": normalized["displayName"],
            "quantity": normalized["quantity"],
            "targetArea": normalized["targetArea"],
            "targetZoneId": normalized["targetZoneId"],
            "orientationMode": normalized["orientationMode"],
            "resourceRole": normalized["resourceRole"],
            "placementIds": [
                str(placement.get("placementId") or "")
                for placement in current_placements
            ],
            "requestCount": len(prior_requests),
            "totalPlacementCount": len(generated),
            "accessValidatedCount": access_validated,
            "accessUnverifiedCount": len(current_placements)
            - access_validated,
            "geometricValidation": "valid",
            "saved": False,
            "hierarchyPreserved": True,
        }
        return response

    def amend_cell_composition(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        cell_request: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
        evidence_authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace the G5 seed-cell stage while preserving all upstream receipts."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if run["status"] != "complete" or run["writable"] is not True:
            raise FacilityGenerationCoordinatorError(
                "facility_cell_requires_completed_draft",
                "Complete the active Facility generation draft before composing a cell.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_cell_draft_revision_conflict",
                "The active Facility draft changed before the cell was composed.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(
            deepcopy(dict(current_base_layout))
        )
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        try:
            normalized = normalize_cell_composition_request(
                cell_request,
                artifacts["draft"]["document"],
            )
            placements = {
                str(item.get("placementId") or ""): item
                for item in artifacts["draft"]["document"].get(
                    "placements", []
                )
                if isinstance(item, Mapping) and item.get("placementId")
            }
            member_references = [
                placements[item]
                for item in normalized["memberPlacementIds"]
                if item in placements
            ]
            snapshot = build_asset_catalog_snapshot(
                asset_catalog, member_references
            )
        except (
            FacilityCellCompositionError,
            FacilityAssetPlacementError,
        ) as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc

        replay_request = {
            "request_id": normalized["requestId"],
            "target_area": normalized["targetArea"],
            "candidate_strategies": list(
                normalized["candidateStrategies"]
            ),
            "selected_strategy": normalized["selectedStrategy"],
            "objective": normalized["objective"],
            "preferred_gap_meters": (
                normalized["preferredGapMeters"]
                if normalized["preferredGapAuthority"] == "user_authored"
                else None
            ),
            "invert_u": normalized["invertU"],
            "process_sequence_placement_ids": list(
                normalized["processSequencePlacementIds"]
            ),
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        }
        try:
            compile_cell_composition_program(
                artifacts["draft"]["document"],
                replay_request,
                snapshot,
                evidence_authority=evidence_authority,
            )
        except FacilityCellCompositionError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc

        dependency_fingerprint = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "cellRequest": normalized,
                "assetCatalogRevision": facility_knowledge_revision(snapshot),
                "draftRevision": expected_draft_revision,
            }
        )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="seed_cells",
            reason="upstream_dependency_changed",
            dependency_fingerprint_after=dependency_fingerprint,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        try:
            compiled = compile_cell_composition_program(
                invalidated["draft"]["document"],
                replay_request,
                snapshot,
                evidence_authority=evidence_authority,
            )
        except FacilityCellCompositionError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        program = deepcopy(compiled["normalizedRequest"])
        amended_run = deepcopy(invalidated["run"]["run"])
        next_stage = next(
            stage
            for stage in amended_run["stageGraph"]
            if stage["stageId"] == "seed_cells"
        )
        next_stage["inputs"] = program
        updated = self.repository.update_run(
            amended_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=amended_run["writableLease"]["ownerToken"],
        )
        response: dict[str, Any] | None = None
        remaining = len(FACILITY_GENERATION_STAGES)
        while updated["run"]["currentStageId"] is not None and remaining > 0:
            response = self.continue_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                current_base_layout=normalized_base,
                current_base_revision=current_base_revision,
            )
            updated = self.repository.get_run(tenant_id, site_id, run_id)
            if response.get("status") == "blocked":
                finding_ids = (
                    response.get("stageReceipt", {})
                    .get("validation", {})
                    .get("findingIds", [])
                )
                raise FacilityGenerationCoordinatorError(
                    "facility_cell_run_blocked",
                    "The cell-composition amendment failed deterministic validation.",
                    details={
                        "stageId": response.get("completedStageId"),
                        "findingIds": finding_ids,
                    },
                )
            remaining -= 1
        if response is None or response.get("status") != "complete":
            raise FacilityGenerationCoordinatorError(
                "facility_cell_run_incomplete",
                "The cell-composition amendment did not reach review-ready state.",
            )
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        summary = compiled["expectedSummary"]
        response["cellComposition"] = {
            "requestId": summary["requestId"],
            "targetArea": summary["targetArea"],
            "targetZoneId": summary["targetZoneId"],
            "memberPlacementIds": list(summary["memberPlacementIds"]),
            "memberPlacementCount": len(summary["memberPlacementIds"]),
            "candidateStrategies": list(summary["candidateStrategies"]),
            "selectedStrategy": summary["selectedStrategy"],
            "selectedStrategyLabel": summary["selectedStrategyLabel"],
            "objective": summary["objective"],
            "preferredGapMeters": summary["preferredGapMeters"],
            "preferredGapAuthority": summary["preferredGapAuthority"],
            "validationStatus": summary["validationStatus"],
            "clearanceEvidenceComplete": summary[
                "clearanceEvidenceComplete"
            ],
            "selectedMetrics": deepcopy(summary["selectedMetrics"]),
            "rejectedStrategies": deepcopy(summary["rejectedStrategies"]),
            "departmentGeometryPreserved": True,
            "circulationPreserved": True,
            "markingsPreserved": True,
            "saved": False,
        }
        return response

    def amend_cell_replication(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        current_base_layout: Mapping[str, Any],
        current_base_revision: str,
        expected_draft_revision: str,
        replication_request: Mapping[str, Any],
        asset_catalog: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Replace G6 repeated modules while retaining every upstream receipt."""

        artifacts = self.repository.get_execution_artifacts(
            tenant_id, site_id, run_id
        )
        run_envelope = artifacts["run"]
        run = run_envelope["run"]
        intent = artifacts["intent"]["intent"]
        self._require_mode_capability(intent["executionMode"])
        self._assert_provider_binding(run, self._provider_config())
        if run["status"] != "complete" or run["writable"] is not True:
            raise FacilityGenerationCoordinatorError(
                "facility_cell_module_requires_completed_draft",
                "Complete the active Facility generation draft before replicating a cell.",
                details={"status": run["status"]},
            )
        if artifacts["draft"]["draftLayoutRevision"] != expected_draft_revision:
            raise FacilityGenerationCoordinatorError(
                "facility_cell_module_draft_revision_conflict",
                "The active Facility draft changed before the cell was replicated.",
                details={
                    "currentDraftRevision": artifacts["draft"][
                        "draftLayoutRevision"
                    ]
                },
            )
        normalized_base = canonicalize_layout(
            deepcopy(dict(current_base_layout))
        )
        if (
            layout_revision(normalized_base) != current_base_revision
            or current_base_revision != run["baseLayoutRevision"]
        ):
            raise FacilityGenerationCoordinatorError(
                "generation_base_layout_changed",
                "The saved layout changed after this generation run started.",
            )
        try:
            normalized = normalize_cell_replication_request(
                replication_request, artifacts["draft"]["document"]
            )
            placements = {
                str(item.get("placementId") or ""): item
                for item in artifacts["draft"]["document"].get(
                    "placements", []
                )
                if isinstance(item, Mapping) and item.get("placementId")
            }
            source_references = [
                placements[item]
                for item in normalized["sourceMemberPlacementIds"]
                if item in placements
            ]
            snapshot = build_asset_catalog_snapshot(
                asset_catalog, source_references
            )
        except (
            FacilityCellReplicationError,
            FacilityAssetPlacementError,
        ) as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        replay_request = {
            "request_id": normalized["requestId"],
            "source_cell": normalized["sourceCell"],
            "target_areas": list(normalized["targetAreas"]),
            "copy_current_edited_state": normalized[
                "copyCurrentEditedState"
            ],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_source_cell": True,
            "preserve_manual_and_locked": True,
            "execution_mode": "authorized_draft_run",
        }
        try:
            compile_cell_replication_program(
                artifacts["draft"]["document"], replay_request, snapshot
            )
        except FacilityCellReplicationError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        dependency_fingerprint = facility_knowledge_revision(
            {
                "prior": run["dependencyFingerprint"],
                "cellReplicationRequest": normalized,
                "assetCatalogRevision": facility_knowledge_revision(snapshot),
                "draftRevision": expected_draft_revision,
            }
        )
        invalidated = self.repository.invalidate_stage_chain(
            tenant_id,
            site_id,
            run_id,
            upstream_stage_id="repeated_modules",
            reason="upstream_dependency_changed",
            dependency_fingerprint_after=dependency_fingerprint,
            expected_run_revision=run_envelope["runRevision"],
            lease_owner_token=run["writableLease"]["ownerToken"],
        )
        try:
            compiled = compile_cell_replication_program(
                invalidated["draft"]["document"], replay_request, snapshot
            )
        except FacilityCellReplicationError as exc:
            raise FacilityGenerationCoordinatorError(
                exc.code, str(exc), details=exc.details
            ) from exc
        amended_run = deepcopy(invalidated["run"]["run"])
        next_stage = next(
            stage
            for stage in amended_run["stageGraph"]
            if stage["stageId"] == "repeated_modules"
        )
        next_stage["inputs"] = deepcopy(compiled["normalizedRequest"])
        updated = self.repository.update_run(
            amended_run,
            expected_run_revision=invalidated["run"]["runRevision"],
            lease_owner_token=amended_run["writableLease"]["ownerToken"],
        )
        response: dict[str, Any] | None = None
        remaining = len(FACILITY_GENERATION_STAGES)
        while updated["run"]["currentStageId"] is not None and remaining > 0:
            response = self.continue_run(
                tenant_id=tenant_id,
                site_id=site_id,
                run_id=run_id,
                current_base_layout=normalized_base,
                current_base_revision=current_base_revision,
            )
            updated = self.repository.get_run(tenant_id, site_id, run_id)
            if response.get("status") == "blocked":
                finding_ids = (
                    response.get("stageReceipt", {})
                    .get("validation", {})
                    .get("findingIds", [])
                )
                raise FacilityGenerationCoordinatorError(
                    "facility_cell_module_run_blocked",
                    "The cell-replication amendment failed deterministic validation.",
                    details={
                        "stageId": response.get("completedStageId"),
                        "findingIds": finding_ids,
                    },
                )
            remaining -= 1
        if response is None or response.get("status") != "complete":
            raise FacilityGenerationCoordinatorError(
                "facility_cell_module_run_incomplete",
                "The cell-replication amendment did not reach review-ready state.",
            )
        response["supersededReceiptIds"] = list(
            invalidated["supersededReceiptIds"]
        )
        summary = compiled["expectedSummary"]
        response["cellReplication"] = {
            "requestId": summary["requestId"],
            "sourceCell": summary["sourceCell"],
            "sourceCellZoneId": summary["sourceCellZoneId"],
            "sourceStatus": summary["sourceStatus"],
            "sourceStateAuthority": summary["sourceStateAuthority"],
            "sourceModuleRevision": summary["sourceModuleRevision"],
            "moduleId": summary["moduleId"],
            "authoredStrategy": summary["authoredStrategy"],
            "targetAreas": list(summary["targetAreas"]),
            "targetZoneIds": list(summary["targetZoneIds"]),
            "replicaCount": summary["replicaCount"],
            "copiedPlacementCount": summary["copiedPlacementCount"],
            "replicas": deepcopy(summary["replicas"]),
            "validationStatus": "valid",
            "departmentGeometryPreserved": True,
            "sourceCellPreserved": True,
            "saved": False,
        }
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
        if result["workflowScope"] == FACILITY_PROGRAM_WORKFLOW_SCOPE:
            effective = self.repository.get_effective_facility_program(
                tenant_id, site_id, run_id
            )
            result["baseFacilityProgramRevision"] = effective[
                "baseProgramRevision"
            ]
            result["facilityProgramRevision"] = effective[
                "programRevision"
            ]
            result["facilityProgramAmendmentCount"] = len(
                effective["amendments"]
            )
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
    "FULL_FACTORY_SCOPE",
    "FULL_FACTORY_TOOL",
    "G1_FACILITY_GENERATION_TOOL",
    "G1_SCOPE",
    "G1_SKIPPED_STAGES",
    "G3_FACILITY_SUBDIVISION_TOOL",
    "G3_SUBDIVISION_SCOPE",
    "G4_ASSET_PLACEMENT_SCOPE",
    "G4_FACILITY_ASSET_PLACEMENT_TOOL",
    "G5_CELL_COMPOSITION_SCOPE",
    "G5_FACILITY_CELL_COMPOSITION_TOOL",
    "G6_CELL_REPLICATION_SCOPE",
    "G6_FACILITY_CELL_REPLICATION_TOOL",
    "FacilityGenerationCoordinator",
    "FacilityGenerationCoordinatorError",
    "build_g1_facility_intent",
    "full_factory_tool_spec",
    "g1_facility_generation_tool_spec",
    "g3_facility_subdivision_tool_spec",
    "g4_facility_asset_placement_tool_spec",
    "g5_facility_cell_composition_tool_spec",
    "g6_facility_cell_replication_tool_spec",
]
