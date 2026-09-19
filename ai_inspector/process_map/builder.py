"""Proposal, approval, and CAS-apply runtime for process-map Builder edits."""

from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeRepository,
    EvidenceCompilationError,
    resolve_process_map_evidence_package,
)
from ai_inspector.transactions import (
    CommitResult,
    MutationPlan,
    ReconciliationResult,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionCancelledError,
    TransactionError,
    TransactionExpiredError,
    TransactionIdempotencyConflictError,
    TransactionNotFoundError,
    TransactionReplayError,
)

from .asset_write_policy import authorize_process_map_asset_write
from .demo_metadata import compile_demo_metadata_operations
from .operations import (
    ProcessMapOperationError,
    apply_process_map_operations,
    build_process_map_diff,
    diff_hash,
    find_process_map_records,
)
from .repository import (
    ProcessMapConflictError,
    ProcessMapNotFoundError,
    ProcessMapValidationError,
    list_named_process_map_revisions,
    list_process_maps,
    load_named_process_map,
    load_named_process_map_revision,
    process_map_revision,
    save_named_process_map,
)
from .schema_v3 import validate_placement_map
from .semantic_plan import (
    MAX_SEMANTIC_PLAN_OPERATIONS,
    SemanticProcessPlanError,
    compile_semantic_process_plan,
)
from .spatial_tools import (
    ProcessMapSpatialToolError,
    inspect_process_map_spatial_layout,
    plan_process_map_spatial_tool,
)
from .transaction_adapter import (
    ProcessMapTransactionRuntime,
    process_map_binding,
)
from .validate import has_structural_errors
from .visual_validation import (
    ProcessMapVisualValidationError,
    public_process_map_visual_validation_report,
    render_process_map_visual_review,
    review_semantic_process_plan_visuals,
)


class ProcessMapBuilderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProcessMapAuthorizationError(ProcessMapBuilderError):
    pass


class ProcessMapProposalNotFoundError(ProcessMapBuilderError):
    pass


class ProcessMapApprovalReplayError(ProcessMapBuilderError):
    pass


_TRANSACTION_RUNTIME: Optional[ProcessMapTransactionRuntime] = None


def _store_ttl_seconds() -> int:
    raw = (os.getenv("INSPECTORPRO_BUILDER_APPROVAL_TTL_SECONDS") or "1800").strip()
    try:
        return max(60, min(86400, int(raw)))
    except ValueError:
        return 1800


def _store_limit() -> int:
    raw = (os.getenv("INSPECTORPRO_BUILDER_APPROVAL_LIMIT") or "512").strip()
    try:
        return max(32, min(4096, int(raw)))
    except ValueError:
        return 512


def _transaction_runtime() -> ProcessMapTransactionRuntime:
    global _TRANSACTION_RUNTIME
    if _TRANSACTION_RUNTIME is None:
        _TRANSACTION_RUNTIME = ProcessMapTransactionRuntime(
            ttl_seconds=_store_ttl_seconds(),
            limit=_store_limit(),
        )
    return _TRANSACTION_RUNTIME


def reset_process_map_builder_state_for_tests() -> None:
    global _TRANSACTION_RUNTIME
    _TRANSACTION_RUNTIME = ProcessMapTransactionRuntime(
        ttl_seconds=_store_ttl_seconds(),
        limit=_store_limit(),
    )


def resolve_process_map_receipts(
    receipts: Any,
    *,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Resolve browser receipt references to canonical server-issued receipts."""

    if (
        not isinstance(receipts, Sequence)
        or isinstance(receipts, (str, bytes, bytearray))
    ):
        return []
    requested_ids: List[str] = []
    for item in list(receipts)[-max(1, min(24, int(limit))):]:
        if not isinstance(item, Mapping):
            continue
        receipt_id = item.get("receiptId")
        if (
            isinstance(receipt_id, str)
            and receipt_id
            and receipt_id not in requested_ids
        ):
            requested_ids.append(receipt_id)
    if not requested_ids:
        return []

    return _transaction_runtime().resolve_receipts(
        [{"receiptId": receipt_id} for receipt_id in requested_ids],
        limit=limit,
    )


def _raise_transaction_error(error: TransactionError) -> None:
    if isinstance(
        error,
        (TransactionNotFoundError, TransactionExpiredError, TransactionCancelledError),
    ):
        code = (
            "approval_not_found"
            if "approval" in error.code
            else "proposal_not_found"
        )
        raise ProcessMapProposalNotFoundError(code, str(error)) from error
    if isinstance(
        error,
        (TransactionReplayError, TransactionIdempotencyConflictError),
    ):
        raise ProcessMapApprovalReplayError(
            "idempotency_replay",
            str(error),
        ) from error
    if isinstance(
        error,
        (TransactionBindingError, TransactionAuthorizationError),
    ):
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch",
            str(error),
        ) from error
    raise ProcessMapBuilderError(error.code, str(error)) from error


def _assert_revision(base_revision: str, current_revision: str) -> str:
    supplied = base_revision.strip() if isinstance(base_revision, str) else ""
    if supplied != current_revision:
        raise ProcessMapConflictError(current_revision)
    return supplied


def _occurrence_ids(product_structure: Mapping[str, Any]) -> set[str]:
    return {
        str(item["occurrenceId"])
        for item in product_structure.get("occurrences", [])
        if isinstance(item, dict) and isinstance(item.get("occurrenceId"), str)
    }


def _proposal_response(record: Mapping[str, Any]) -> Dict[str, Any]:
    response = {
        "proposalId": record.get("proposalId"),
        "productId": record["productId"],
        "mapId": record["mapId"],
        "baseRevision": record["baseRevision"],
        "action": record["action"],
        "diff": deepcopy(record["diff"]),
        "diffHash": record["diffHash"],
        "findings": deepcopy(record["findings"]),
        "operationResults": deepcopy(record.get("operationResults", [])),
        "wouldSave": bool(record["wouldSave"]),
        "targetRevision": record.get("targetRevision"),
    }
    if record.get("semanticBindingHash"):
        proposal_id = record.get("proposalId")
        visual_report = record.get("visualValidation")
        public_visual_report = None
        if isinstance(visual_report, Mapping):
            artifact_url = (
                f"/api/builder/process-map-proposals/{proposal_id}"
                "/visual-validation-image"
                if proposal_id
                and isinstance(visual_report.get("artifact"), Mapping)
                else None
            )
            public_visual_report = public_process_map_visual_validation_report(
                visual_report,
                artifact_url=artifact_url,
            )
        response.update(
            {
                "managedProposalType": "semantic_process_map",
                "semanticBinding": deepcopy(record.get("semanticBinding") or {}),
                "semanticBindingHash": record.get("semanticBindingHash"),
                "preview": deepcopy(record.get("managedPreview") or {}),
                "summary": deepcopy(record.get("semanticSummary") or {}),
                "createdIds": deepcopy(record.get("semanticCreatedIds") or {}),
                "warnings": deepcopy(record.get("semanticWarnings") or []),
                "unresolvedItems": deepcopy(record.get("semanticUnresolvedItems") or []),
                "visualValidation": public_visual_report,
            }
        )
    elif record.get("spatialBindingHash"):
        response.update(
            {
                "spatialTool": record.get("spatialTool"),
                "spatialBinding": deepcopy(record.get("spatialBinding")),
                "spatialBindingHash": record.get("spatialBindingHash"),
                "preview": deepcopy(record.get("spatialPreview") or {}),
                "summary": deepcopy(record.get("spatialSummary") or {}),
            }
        )
    elif record.get("managedProposalType"):
        response.update(
            {
                "managedProposalType": record.get("managedProposalType"),
                "preview": deepcopy(record.get("managedPreview") or {}),
                "summary": deepcopy(record.get("managedSummary") or {}),
                "source": deepcopy(record.get("managedSource") or {}),
            }
        )
    return response


def _store_proposal(record: Dict[str, Any]) -> Dict[str, Any]:
    if not record["wouldSave"]:
        record["proposalId"] = None
        return _proposal_response(record)
    try:
        proposal = _transaction_runtime().propose(record)
    except TransactionError as error:
        _raise_transaction_error(error)
    record["proposalId"] = proposal.proposal_id
    return _proposal_response(record)


def _propose_loaded_process_map_operations(
    product_id: str,
    map_id: str,
    base_revision: str,
    loaded: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    spatial: Optional[Mapping[str, Any]] = None,
    managed: Optional[Mapping[str, Any]] = None,
    semantic: Optional[Mapping[str, Any]] = None,
    maximum_operations: int = 100,
) -> Dict[str, Any]:
    applied = apply_process_map_operations(
        loaded["map"],
        loaded["productStructure"],
        operations,
        maximum_operations=maximum_operations,
    )
    structural_error = has_structural_errors(applied["findings"])
    would_save = bool(applied["changed"] and not structural_error)
    calculated_hash = diff_hash(
        map_id=map_id,
        base_revision=base_revision,
        operations=operations,
        after=applied["map"],
        diff=applied["diff"],
    )
    record = {
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "action": "apply_operations",
        "operations": deepcopy(list(operations)),
        "after": deepcopy(applied["map"]),
        "diff": deepcopy(applied["diff"]),
        "diffHash": calculated_hash,
        "findings": deepcopy(applied["findings"]),
        "operationResults": deepcopy(applied["operationResults"]),
        "wouldSave": would_save,
    }
    if spatial:
        record.update(
            {
                "spatialTool": spatial["tool"],
                "spatialRequest": deepcopy(spatial["request"]),
                "spatialBinding": deepcopy(spatial["binding"]),
                "spatialBindingHash": spatial["bindingHash"],
                "spatialPreview": deepcopy(spatial.get("preview") or {}),
                "spatialSummary": deepcopy(spatial.get("summary") or {}),
            }
        )
    if managed:
        changed_node_ids = set(applied["diff"]["nodes"]["added"])
        changed_node_ids.update(applied["diff"]["nodes"]["modified"])
        changed_edge_ids = set(applied["diff"]["edges"]["added"])
        changed_edge_ids.update(applied["diff"]["edges"]["modified"])
        changed_group_ids = set(applied["diff"]["groups"]["added"])
        changed_group_ids.update(applied["diff"]["groups"]["modified"])
        record.update(
            {
                "managedProposalType": str(managed["type"]),
                "managedPreview": {
                    "nodes": sorted(
                        (
                            deepcopy(item)
                            for item in applied["map"].get("canvasNodes", [])
                            if isinstance(item, dict) and item.get("nodeId") in changed_node_ids
                        ),
                        key=lambda item: str(item.get("nodeId") or ""),
                    ),
                    "edges": sorted(
                        (
                            deepcopy(item)
                            for item in applied["map"].get("canvasEdges", [])
                            if isinstance(item, dict) and item.get("edgeId") in changed_edge_ids
                        ),
                        key=lambda item: str(item.get("edgeId") or ""),
                    ),
                    "groups": sorted(
                        (
                            deepcopy(item)
                            for item in applied["map"].get("canvasGroups", [])
                            if isinstance(item, dict) and item.get("groupId") in changed_group_ids
                        ),
                        key=lambda item: str(item.get("groupId") or ""),
                    ),
                },
                "managedSummary": deepcopy(managed.get("summary") or {}),
                "managedSource": deepcopy(managed.get("source") or {}),
            }
        )
    if semantic:
        record.update(
            {
                "semanticPlan": deepcopy(semantic["plan"]),
                "semanticScopeOccurrenceId": semantic["scopeOccurrenceId"],
                "semanticBinding": deepcopy(semantic["binding"]),
                "semanticBindingHash": semantic["bindingHash"],
                "semanticSummary": deepcopy(semantic.get("summary") or {}),
                "semanticCreatedIds": deepcopy(semantic.get("createdIds") or {}),
                "semanticWarnings": deepcopy(semantic.get("warnings") or []),
                "semanticUnresolvedItems": deepcopy(
                    semantic.get("unresolvedItems") or []
                ),
                "visualValidation": deepcopy(
                    semantic.get("visualValidation")
                ),
            }
        )
    return _store_proposal(record)


def propose_process_map_operations(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    operations: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Dry-run an operation batch. This function never writes."""
    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    return _propose_loaded_process_map_operations(
        product_id,
        map_id,
        base,
        loaded,
        operations,
    )


def propose_process_map_demo_metadata(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    *,
    scope_occurrence_id: str,
    fill_mode: str = "fill_missing",
) -> Dict[str, Any]:
    """Compile trusted illustrative metadata into one reviewable proposal."""

    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    compiled = compile_demo_metadata_operations(
        training_root,
        product_id,
        loaded["map"],
        loaded["productStructure"],
        scope_occurrence_id=scope_occurrence_id,
        fill_mode=fill_mode,
    )
    operations = compiled["operations"]
    if not operations:
        empty_diff = build_process_map_diff(loaded["map"], loaded["map"])
        return _store_proposal(
            {
                "productId": product_id,
                "mapId": map_id,
                "baseRevision": base,
                "action": "apply_operations",
                "operations": [],
                "after": deepcopy(loaded["map"]),
                "diff": empty_diff,
                "diffHash": diff_hash(
                    map_id=map_id,
                    base_revision=base,
                    operations=[],
                    after=loaded["map"],
                    diff=empty_diff,
                ),
                "findings": deepcopy(loaded.get("findings") or []),
                "operationResults": [],
                "wouldSave": False,
                "managedProposalType": "process_metadata",
                "managedPreview": {"nodes": [], "edges": [], "groups": []},
                "managedSummary": deepcopy(compiled["summary"]),
                "managedSource": deepcopy(compiled["source"]),
            }
        )
    return _propose_loaded_process_map_operations(
        product_id,
        map_id,
        base,
        loaded,
        operations,
        managed={
            "type": "process_metadata",
            "summary": compiled["summary"],
            "source": compiled["source"],
        },
    )


def inspect_process_map_spatial(
    training_root,
    product_id: str,
    map_id: str,
    revision: str,
    *,
    scope_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(revision, loaded["revision"])
    return inspect_process_map_spatial_layout(
        loaded["map"],
        revision=base,
        scope_ids=scope_ids,
    )


def propose_process_map_spatial_tool(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    tool_name: str,
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compile a semantic spatial request and store its exact dry-run diff."""

    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    plan = plan_process_map_spatial_tool(
        loaded["map"],
        loaded["productStructure"],
        base,
        tool_name,
        request,
    )
    return _propose_loaded_process_map_operations(
        product_id,
        map_id,
        base,
        loaded,
        plan["operations"],
        spatial={
            "tool": tool_name,
            "request": deepcopy(dict(request)),
            **plan,
        },
    )


def propose_semantic_process_map_preview(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    *,
    scope_occurrence_id: str,
    semantic_plan: Mapping[str, Any],
    visual_validation_provider: Any = None,
    visual_validation_artifact_root: str | Path | None = None,
) -> Dict[str, Any]:
    """Compile meaning into one deterministic, review-only Builder proposal."""

    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    assembly_knowledge = _resolve_semantic_assembly_knowledge(
        training_root,
        product_id,
        semantic_plan,
    )
    compiled = compile_semantic_process_plan(
        semantic_plan,
        scope_occurrence_id=scope_occurrence_id,
        base_revision=base,
        process_map=loaded["map"],
        product_structure=loaded["productStructure"],
        structure_revision=loaded["structureRevision"],
        assembly_knowledge=assembly_knowledge,
    )
    visual_report = None
    if visual_validation_provider is not None and assembly_knowledge is not None:
        repository = AssemblyKnowledgeRepository(training_root)
        package_id = str(assembly_knowledge["binding"]["packageId"])
        package_dir = repository.package_dir(product_id, package_id)
        artifact_root = (
            Path(visual_validation_artifact_root).resolve()
            if visual_validation_artifact_root is not None
            else (
                Path(training_root).resolve().parents[1]
                / ".runtime"
                / "process_map_visual_validation"
            )
        )
        try:
            reviewed = review_semantic_process_plan_visuals(
                compiled["plan"],
                assembly_knowledge,
                package_dir=package_dir,
                artifact_root=artifact_root,
                provider=visual_validation_provider,
            )
            visual_report = reviewed["report"]
            if reviewed["plan"] != compiled["plan"]:
                try:
                    compiled = compile_semantic_process_plan(
                        reviewed["plan"],
                        scope_occurrence_id=scope_occurrence_id,
                        base_revision=base,
                        process_map=loaded["map"],
                        product_structure=loaded["productStructure"],
                        structure_revision=loaded["structureRevision"],
                        assembly_knowledge=assembly_knowledge,
                    )
                except SemanticProcessPlanError as exc:
                    rejected = deepcopy(
                        visual_report.get("appliedCorrections") or []
                    )
                    visual_report["status"] = "needs_review"
                    visual_report["rejectedCorrections"] = rejected
                    visual_report["appliedCorrections"] = []
                    visual_report["reviewedPlanHash"] = visual_report[
                        "originalPlanHash"
                    ]
                    if isinstance(
                        visual_report.get("originalArtifact"),
                        Mapping,
                    ):
                        visual_report["artifact"] = deepcopy(
                            visual_report["originalArtifact"]
                        )
                    visual_report.setdefault("unresolvedItems", []).append(
                        {
                            "message": (
                                "The visual correction was not applied because "
                                f"semantic validation rejected it ({exc.code})."
                            ),
                            "operationIds": sorted(
                                {
                                    str(item.get("operationId"))
                                    for item in rejected
                                    if item.get("operationId")
                                }
                            ),
                            "occurrenceIds": sorted(
                                {
                                    str(item.get("occurrenceId"))
                                    for item in rejected
                                    if item.get("occurrenceId")
                                }
                            ),
                        }
                    )
        except Exception as exc:
            artifact = None
            try:
                rendered = render_process_map_visual_review(
                    compiled["plan"],
                    assembly_knowledge,
                    package_dir=package_dir,
                    artifact_root=artifact_root,
                    provider_name=str(
                        getattr(
                            visual_validation_provider,
                            "provider_name",
                            "unknown",
                        )
                    ),
                    model=str(
                        getattr(
                            visual_validation_provider,
                            "model",
                            "unknown",
                        )
                    ),
                )
                artifact = rendered["artifact"]
            except Exception:
                artifact = None
            code = (
                exc.code
                if isinstance(exc, ProcessMapVisualValidationError)
                else "visual_review_unavailable"
            )
            visual_report = {
                "schemaVersion": 1,
                "status": "unavailable",
                "provider": str(
                    getattr(visual_validation_provider, "provider_name", "unknown")
                ),
                "model": str(
                    getattr(visual_validation_provider, "model", "unknown")
                ),
                "fromCache": False,
                "overallVerdict": "needs_review",
                "appliedCorrections": [],
                "operationReviews": [],
                "unresolvedItems": [
                    {
                        "message": (
                            "Automated visual validation was unavailable "
                            f"({code}); review the occurrence views manually."
                        ),
                        "operationIds": [],
                        "occurrenceIds": [],
                    }
                ],
                "artifact": artifact,
            }
    if visual_report is not None:
        applied_corrections = visual_report.get("appliedCorrections") or []
        compiled["summary"] = {
            **compiled["summary"],
            "visualValidationStatus": visual_report.get("status"),
            "visualCorrectionCount": len(applied_corrections),
            "visualLabelCorrectionCount": sum(
                1
                for item in applied_corrections
                if item.get("kind") == "rename_operation"
            ),
            "visualMembershipCorrectionCount": sum(
                1
                for item in applied_corrections
                if item.get("kind") == "move_occurrence"
            ),
            "visualUnresolvedCount": len(
                visual_report.get("unresolvedItems") or []
            ),
        }
    warnings = [
        item for item in compiled.get("findings", [])
        if item.get("severity") != "error"
    ]
    if visual_report is not None and visual_report.get("status") in {
        "needs_review",
        "unavailable",
    }:
        warnings.append(
            {
                "severity": "warning",
                "code": "visual_validation_requires_review",
                "message": (
                    "The visual stage review has unresolved items; the "
                    "proposal remains inferred and requires user review."
                ),
            }
        )
    return _propose_loaded_process_map_operations(
        product_id,
        map_id,
        base,
        loaded,
        compiled["operations"],
        managed={
            "type": "semantic_process_map",
            "summary": compiled["summary"],
            "source": {
                "planId": compiled["plan"]["planId"],
                "planHash": compiled["planHash"],
            },
        },
        semantic={
            **compiled,
            "scopeOccurrenceId": scope_occurrence_id,
            "warnings": warnings,
            "visualValidation": visual_report,
        },
        maximum_operations=MAX_SEMANTIC_PLAN_OPERATIONS,
    )


def resolve_process_map_visual_validation_artifact(
    proposal_id: str,
) -> Path:
    """Resolve one hash-verified review image for an active proposal."""

    try:
        proposal = _transaction_runtime().get_record(proposal_id)
    except TransactionError as error:
        _raise_transaction_error(error)
    report = proposal.get("visualValidation")
    artifact = report.get("artifact") if isinstance(report, Mapping) else None
    if not isinstance(artifact, Mapping):
        raise ProcessMapProposalNotFoundError(
            "visual_validation_artifact_not_found",
            "The proposal has no visual-validation artifact.",
        )
    path = Path(str(artifact.get("absolutePath") or "")).resolve()
    expected_hash = str(artifact.get("assetHash") or "")
    if (
        not path.is_file()
        or not expected_hash
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
    ):
        raise ProcessMapProposalNotFoundError(
            "visual_validation_artifact_not_found",
            "The proposal visual-validation artifact is unavailable.",
        )
    return path


def _resolve_semantic_assembly_knowledge(
    training_root,
    product_id: str,
    semantic_plan: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    repository = AssemblyKnowledgeRepository(training_root)
    packages = repository.list_packages(product_id)
    supplied = semantic_plan.get("evidenceBinding")
    if not packages:
        if isinstance(supplied, Mapping):
            raise ProcessMapBuilderError(
                "assembly_knowledge_unavailable",
                "The cited Assembly Knowledge Package is not available.",
            )
        return None
    if not isinstance(supplied, Mapping):
        raise ProcessMapBuilderError(
            "assembly_knowledge_binding_required",
            (
                "A planning-ready Assembly Knowledge Package exists for this "
                "product; the semantic plan must cite its trusted identity."
            ),
        )
    package_id = supplied.get("packageId")
    if not isinstance(package_id, str) or not package_id:
        raise ProcessMapBuilderError(
            "assembly_knowledge_binding_required",
            "evidenceBinding.packageId is required.",
        )
    try:
        resolved = resolve_process_map_evidence_package(
            training_root,
            product_id,
            package_id=package_id,
            expected_binding=supplied,
            require_planning_ready=True,
            require_current_sources=True,
        )
    except EvidenceCompilationError as exc:
        raise ProcessMapBuilderError(
            "assembly_knowledge_stale",
            str(exc),
        ) from exc
    if resolved is None:
        raise ProcessMapBuilderError(
            "assembly_knowledge_unavailable",
            "Assembly Knowledge Package is not available.",
        )
    return resolved


def _replan_spatial_proposal(
    proposal: Mapping[str, Any],
    loaded: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    if not proposal.get("spatialBindingHash"):
        return None
    plan = plan_process_map_spatial_tool(
        loaded["map"],
        loaded["productStructure"],
        loaded["revision"],
        str(proposal["spatialTool"]),
        proposal["spatialRequest"],
    )
    if (
        plan["bindingHash"] != proposal["spatialBindingHash"]
        or plan["binding"] != proposal["spatialBinding"]
        or plan["operations"] != proposal["operations"]
    ):
        raise ProcessMapAuthorizationError(
            "spatial_proposal_stale",
            "The map geometry changed after the spatial preview was created.",
        )
    return plan


def _replan_semantic_proposal(
    training_root,
    proposal: Mapping[str, Any],
    loaded: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    if not proposal.get("semanticBindingHash"):
        return None
    assembly_knowledge = _resolve_semantic_assembly_knowledge(
        training_root,
        str(proposal["productId"]),
        proposal["semanticPlan"],
    )
    compiled = compile_semantic_process_plan(
        proposal["semanticPlan"],
        scope_occurrence_id=str(proposal["semanticScopeOccurrenceId"]),
        base_revision=loaded["revision"],
        process_map=loaded["map"],
        product_structure=loaded["productStructure"],
        structure_revision=loaded["structureRevision"],
        assembly_knowledge=assembly_knowledge,
    )
    if (
        compiled["bindingHash"] != proposal["semanticBindingHash"]
        or compiled["binding"] != proposal["semanticBinding"]
        or compiled["operations"] != proposal["operations"]
    ):
        raise ProcessMapAuthorizationError(
            "semantic_proposal_stale",
            "The map, product structure, or semantic plan changed after preview.",
        )
    return compiled


def propose_process_map_revert(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    target_revision: str,
) -> Dict[str, Any]:
    """Dry-run a revert to one retained named revision."""
    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    target = load_named_process_map_revision(
        training_root,
        product_id,
        map_id,
        target_revision,
    )
    after = deepcopy(target["map"])
    after["mapId"] = map_id
    after["productId"] = product_id
    after["sourceStructureRevision"] = loaded["structureRevision"]
    findings = validate_placement_map(after, _occurrence_ids(loaded["productStructure"]))
    diff = build_process_map_diff(loaded["map"], after)
    operations = [{"op": "revert_to_revision", "targetRevision": target_revision}]
    changed = process_map_revision(after) != process_map_revision(loaded["map"])
    would_save = bool(changed and not has_structural_errors(findings))
    calculated_hash = diff_hash(
        map_id=map_id,
        base_revision=base,
        operations=operations,
        after=after,
        diff=diff,
    )
    return _store_proposal(
        {
            "productId": product_id,
            "mapId": map_id,
            "baseRevision": base,
            "action": "revert_to_revision",
            "targetRevision": target_revision,
            "operations": operations,
            "after": after,
            "diff": diff,
            "diffHash": calculated_hash,
            "findings": findings,
            "operationResults": [],
            "wouldSave": would_save,
        }
    )


def show_process_map_proposal(proposal_id: str) -> Dict[str, Any]:
    try:
        record = _transaction_runtime().get_record(proposal_id)
    except TransactionError as error:
        _raise_transaction_error(error)
    return _proposal_response(record)


def approve_process_map_proposal(
    training_root,
    proposal_id: str,
    *,
    product_id: str,
    map_id: str,
    base_revision: str,
    diff_hash_value: str,
    user_id: str,
    session_id: str,
    idempotency_key: str,
    explicit_approval: bool,
    spatial_binding_hash: Optional[str] = None,
    semantic_binding_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue an opaque token only after an exact diff is explicitly approved."""
    runtime = _transaction_runtime()
    try:
        proposal = runtime.get_record(proposal_id)
    except TransactionError as error:
        _raise_transaction_error(error)
    supplied_binding = {
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
    }
    expected_binding = {
        "productId": proposal["productId"],
        "mapId": proposal["mapId"],
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
    }
    if supplied_binding != expected_binding:
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch",
            "Approval does not match the exact proposed map, revision, and diff.",
        )
    expected_spatial_hash = proposal.get("spatialBindingHash")
    supplied_spatial_hash = spatial_binding_hash or None
    if supplied_spatial_hash != expected_spatial_hash:
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch",
            "Approval does not match the deterministic spatial preview.",
        )
    expected_semantic_hash = proposal.get("semanticBindingHash")
    if (semantic_binding_hash or None) != expected_semantic_hash:
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch",
            "Approval does not match the validated semantic process plan.",
        )
    loaded = load_named_process_map(training_root, product_id, map_id)
    _assert_revision(base_revision, loaded["revision"])
    _replan_spatial_proposal(proposal, loaded)
    _replan_semantic_proposal(training_root, proposal, loaded)
    gate_request = {
        "action": proposal["action"],
        "explicitApproval": explicit_approval,
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
        "userId": user_id,
        "sessionId": session_id,
        "idempotencyKey": idempotency_key,
        "spatialBindingHash": expected_spatial_hash,
        "semanticBindingHash": expected_semantic_hash,
    }
    authorization = authorize_process_map_asset_write(gate_request)
    if not authorization["authorized"]:
        raise ProcessMapAuthorizationError(
            "asset_write_not_authorized",
            f"Process-map asset write denied: {authorization['reason']}.",
        )
    try:
        approval = runtime.approve(
            proposal_id=proposal_id,
            binding=runtime.binding_from_record(proposal),
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            explicit_approval=explicit_approval,
        )
    except TransactionError as error:
        _raise_transaction_error(error)
    return {
        "approvalToken": approval.approval_token,
        "proposalId": proposal_id,
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
        "spatialBindingHash": expected_spatial_hash,
        "semanticBindingHash": expected_semantic_hash,
        "expiresInSeconds": int(approval.expires_at - approval.created_at),
        "authorization": authorization,
    }


def apply_approved_process_map_operations(
    training_root,
    approval_token: str,
    *,
    product_id: str,
    map_id: str,
    base_revision: str,
    diff_hash_value: str,
    user_id: str,
    session_id: str,
    idempotency_key: str,
    spatial_binding_hash: Optional[str] = None,
    semantic_binding_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Revalidate and CAS-save the exact approved result once."""
    runtime = _transaction_runtime()
    binding = process_map_binding(
        product_id=product_id,
        map_id=map_id,
        base_revision=base_revision,
        diff_hash=diff_hash_value,
        spatial_binding_hash=spatial_binding_hash,
        semantic_binding_hash=semantic_binding_hash,
    )
    saved_result: Dict[str, Any] = {}

    class _ProcessMapApplyAdapter:
        def regenerate(self, proposal_record):
            proposal = proposal_record.payload.get("record")
            if not isinstance(proposal, Mapping):
                raise ProcessMapProposalNotFoundError(
                    "proposal_not_found",
                    "The process-map proposal payload is unavailable.",
                )
            proposal = deepcopy(dict(proposal))
            authorization = authorize_process_map_asset_write(
                {
                    "action": proposal["action"],
                    "explicitApproval": True,
                    "productId": product_id,
                    "mapId": map_id,
                    "baseRevision": base_revision,
                    "diffHash": diff_hash_value,
                    "userId": user_id,
                    "sessionId": session_id,
                    "idempotencyKey": idempotency_key,
                    "spatialBindingHash": spatial_binding_hash,
                    "semanticBindingHash": semantic_binding_hash,
                }
            )
            if not authorization["authorized"]:
                raise ProcessMapAuthorizationError(
                    "asset_write_not_authorized",
                    (
                        "Process-map asset write denied: "
                        f"{authorization['reason']}."
                    ),
                )

            loaded = load_named_process_map(
                training_root,
                product_id,
                map_id,
            )
            _assert_revision(base_revision, loaded["revision"])
            spatial_plan = _replan_spatial_proposal(proposal, loaded)
            semantic_plan = _replan_semantic_proposal(
                training_root,
                proposal,
                loaded,
            )

            if proposal["action"] == "apply_operations":
                operations = (
                    semantic_plan["operations"]
                    if semantic_plan
                    else (
                        spatial_plan["operations"]
                        if spatial_plan
                        else proposal["operations"]
                    )
                )
                applied = apply_process_map_operations(
                    loaded["map"],
                    loaded["productStructure"],
                    operations,
                    maximum_operations=(
                        MAX_SEMANTIC_PLAN_OPERATIONS
                        if semantic_plan
                        else 100
                    ),
                )
                after = applied["map"]
                findings = applied["findings"]
                calculated_diff = applied["diff"]
            else:
                after = deepcopy(proposal["after"])
                after["sourceStructureRevision"] = loaded[
                    "structureRevision"
                ]
                findings = validate_placement_map(
                    after,
                    _occurrence_ids(loaded["productStructure"]),
                )
                calculated_diff = build_process_map_diff(
                    loaded["map"],
                    after,
                )
            if has_structural_errors(findings):
                raise ProcessMapValidationError(findings)
            recalculated_hash = diff_hash(
                map_id=map_id,
                base_revision=base_revision,
                operations=proposal["operations"],
                after=after,
                diff=calculated_diff,
            )
            if recalculated_hash != proposal["diffHash"]:
                raise ProcessMapAuthorizationError(
                    "approved_diff_changed",
                    "The approved process-map diff no longer matches.",
                )
            return MutationPlan(
                binding=proposal_record.binding,
                payload={
                    "after": after,
                    "proposal": proposal,
                },
            )

        def commit(self, plan):
            proposal = plan.payload["proposal"]
            saved = save_named_process_map(
                training_root,
                product_id,
                map_id,
                plan.payload["after"],
                base_revision,
            )
            saved_result["value"] = saved
            receipt_metadata = {
                "userId": user_id.strip(),
                "sessionId": session_id.strip(),
            }
            expected_spatial_hash = proposal.get("spatialBindingHash")
            expected_semantic_hash = proposal.get("semanticBindingHash")
            if (
                expected_spatial_hash
                or expected_semantic_hash
                or proposal.get("managedProposalType")
            ):
                receipt_metadata["outcome"] = deepcopy(
                    proposal.get("spatialSummary")
                    or proposal.get("semanticSummary")
                    or proposal.get("managedSummary")
                    or {}
                )
                if expected_spatial_hash:
                    receipt_metadata[
                        "spatialBindingHash"
                    ] = expected_spatial_hash
                if expected_semantic_hash:
                    receipt_metadata.update(
                        {
                            "semanticBindingHash": expected_semantic_hash,
                            "semanticBinding": deepcopy(
                                proposal.get("semanticBinding") or {}
                            ),
                            "createdIds": deepcopy(
                                proposal.get("semanticCreatedIds") or {}
                            ),
                            "warnings": deepcopy(
                                proposal.get("semanticWarnings") or []
                            ),
                            "unresolvedItems": deepcopy(
                                proposal.get("semanticUnresolvedItems") or []
                            ),
                            "visualValidation": (
                                public_process_map_visual_validation_report(
                                    proposal["visualValidation"],
                                )
                                if isinstance(
                                    proposal.get("visualValidation"),
                                    Mapping,
                                )
                                else None
                            ),
                        }
                    )
            return CommitResult(
                revision=saved["revision"],
                payload={"legacyReceipt": receipt_metadata},
            )

        def reconcile_prepared(self, _prepared):
            return ReconciliationResult.not_committed()

    try:
        outcome = runtime.apply(
            approval_token=approval_token,
            binding=binding,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            adapter=_ProcessMapApplyAdapter(),
        )
    except TransactionError as error:
        _raise_transaction_error(error)
    saved = saved_result.get("value")
    if not isinstance(saved, Mapping):
        raise ProcessMapBuilderError(
            "process_map_commit_result_missing",
            "The process-map commit did not return a saved map.",
        )
    return {
        **deepcopy(dict(saved)),
        "receipt": runtime.legacy_receipt(outcome),
    }


def builder_list_process_maps(training_root, product_id: str) -> Dict[str, Any]:
    return list_process_maps(training_root, product_id, include_archived=True)


def builder_read_process_map(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    return load_named_process_map(training_root, product_id, map_id)


def builder_find_process_map_records(
    training_root,
    product_id: str,
    map_id: str,
    query: str,
    *,
    limit: int = 50,
) -> Dict[str, Any]:
    loaded = load_named_process_map(training_root, product_id, map_id)
    return {
        "productId": product_id,
        "mapId": map_id,
        "revision": loaded["revision"],
        "matches": find_process_map_records(
            loaded["map"], loaded["productStructure"], query, limit=limit
        ),
    }


def builder_validate_process_map(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    loaded = load_named_process_map(training_root, product_id, map_id)
    return {
        "productId": product_id,
        "mapId": map_id,
        "revision": loaded["revision"],
        "findings": loaded["findings"],
        "valid": not has_structural_errors(loaded["findings"]),
    }


def builder_list_process_map_revisions(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    return {
        "productId": product_id,
        "mapId": map_id,
        "revisions": list_named_process_map_revisions(training_root, product_id, map_id),
    }
