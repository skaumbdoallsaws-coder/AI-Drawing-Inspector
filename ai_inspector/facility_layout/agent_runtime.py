"""Trusted Sage runtime for Facility Layout observation and preview.

The browser supplies only revision-bound identity and ephemeral editor facts.
This adapter reloads every authoritative document, compiles the bounded P9
contexts, serves signed read cursors, and delegates preview creation to the P8
transaction service. It never accepts model-authored geometry or commits a
layout.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from ai_inspector.verified_workflows import (
    VerifiedWorkflowBudget,
    VerifiedWorkflowIssue,
    VerifiedWorkflowRepair,
    VerifiedWorkflowRuntime,
)

from .authorization import FacilityPrincipal, require_facility_action
from .canonical import canonicalize_layout, layout_revision
from .digest import build_facility_layout_digest
from .errors import (
    FacilityConflictError,
    FacilityLayoutError,
    FacilityNotFoundError,
)
from .fit_analysis import (
    FacilityFitAnalysisError,
    analyze_facility_asset_fit,
)
from .journey_planning import journey_solution_summary
from .navigation_intent import (
    COMPARE_JOURNEY_ALTERNATIVES_TOOL,
    COMPILE_NAVIGATION_SNAPSHOT_TOOL,
    NAVIGATION_READ_TOOL_NAMES,
    OBSERVE_NAVIGATION_CONTEXT_TOOL,
    PLAN_ACTOR_JOURNEY_TOOL,
    VALIDATE_ACTOR_JOURNEY_TOOL,
    compare_journey_summaries,
    navigation_context_summary,
)
from .observation import (
    MAXIMUM_READ_IDS,
    MAXIMUM_READ_PAGE_SIZE,
    TrustedFacilityContext,
    TrustedFacilitySource,
    build_facility_layout_observation,
    trusted_facility_source,
)
from .plan_settings import shell_with_plan_boundary
from .operations import apply_facility_layout_operations
from .semantic_plan import (
    SemanticFacilityPlanError,
    compile_semantic_facility_plan,
)
from .semantic_model import (
    CELL_FEASIBILITY_STRATEGIES,
    analyze_facility_asset_access,
    analyze_facility_cell_access,
    analyze_facility_cell_alternatives,
    analyze_facility_clearances,
    analyze_facility_drone_clearance,
    analyze_facility_free_space,
    analyze_facility_layout_provenance,
    analyze_facility_module_fit,
    analyze_facility_operator_travel,
    analyze_facility_protected_intrusions,
    analyze_facility_render_consistency,
    analyze_facility_route_access,
    analyze_facility_route_widths,
    build_facility_semantic_map,
    resolve_facility_entities,
)


FACILITY_LAYOUT_AGENT_RUNTIME_VERSION = 1
FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN = 10
FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES = 16_384
FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS = 300
FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS = 600
FACILITY_LAYOUT_VERIFIED_WORKFLOW_ID = "facility-layout-preview"
FACILITY_LAYOUT_VERIFIED_WORKFLOW_BUDGET = VerifiedWorkflowBudget(
    max_repair_attempts=2,
    max_tool_calls=16,
    # Full-factory validation is intentionally bounded, but a cold browser and
    # a large catalog can make the first authoritative collision pass exceed
    # two minutes. Keep one shared five-minute server/client ceiling.
    max_elapsed_ms=300_000,
)
_DETERMINISTIC_STRATEGY_ORDER = (
    "compact_rows",
    "balanced_grid",
    "flow_lanes",
)

_READ_TOOLS = frozenset(
    {
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "inspect_pattern_provenance",
        "inspect_cell_layout_provenance",
        "analyze_facility_spatial",
        "analyze_facility_fit",
        *NAVIGATION_READ_TOOL_NAMES,
    }
)
_ENTITY_COLLECTIONS = {
    "placement": ("placements", "placementId"),
    "zone": ("zones", "zoneId"),
    "floor_marking": ("floorMarkings", "markingId"),
    "route": ("routes", "routeId"),
    "utility_network": ("utilityNetworks", "utilityNetworkId"),
}


class FacilityLayoutAgentRuntimeError(ValueError):
    """Fail-closed P9 runtime error with a stable public code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = deepcopy(dict(details or {}))


@dataclass(frozen=True)
class FacilityAgentContextBundle:
    state: TrustedFacilityContext
    evidence: TrustedFacilityContext
    digest: dict[str, Any]
    shell_document: dict[str, Any]
    policy_document: dict[str, Any]
    asset_documents: tuple[dict[str, Any], ...]
    evidence_authority: dict[str, dict[str, Any]]
    layout_document: dict[str, Any]
    base_layout_revision: str
    generation_run_id: str | None


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
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_payload_invalid",
            "Facility Layout agent payload must be finite JSON.",
        ) from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_text(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _stable_id(value: Any, label: str) -> str:
    text = _clean_text(value, 128)
    if (
        not text
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_id_invalid",
            f"{label} must be a stable ID.",
        )
    return text


def _revision(value: Any, label: str) -> str:
    text = str(value or "")
    if (
        len(text) != 64
        or any(character not in "0123456789abcdef" for character in text)
    ):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_revision_invalid",
            f"{label} must be a lowercase SHA-256 revision.",
        )
    return text


def _search_terms(text: str) -> set[str]:
    """Lowercase words of text, each with simple singular forms ("shelves" -> "shelf")."""
    terms: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        terms.add(word)
        if len(word) > 4 and word.endswith("ves"):
            terms.update((word[:-3] + "f", word[:-3] + "fe"))
        elif len(word) > 4 and word.endswith("ies"):
            terms.add(word[:-3] + "y")
        elif len(word) > 3 and word.endswith("es"):
            terms.update((word[:-2], word[:-1]))
        elif len(word) > 3 and word.endswith("s"):
            terms.add(word[:-1])
    return terms


def _asset_query_matches(query: str, haystack: str) -> bool:
    """The exact phrase as before, or every query word ignoring plurals.

    A query word of four or more letters may also start a longer word, so "mill"
    finds "milling". Matching only the exact phrase, "tooling shelf" missed
    "Tooling Shelves" and the agent substituted an office bookshelf.
    """
    if not query or query in haystack:
        return True
    words = re.findall(r"[a-z0-9]+", query)
    available = _search_terms(haystack)

    def found(word: str) -> bool:
        forms = _search_terms(word)
        return bool(forms & available) or (len(word) >= 4 and any(
            term.startswith(form) for form in forms for term in available))

    return bool(words) and all(found(word) for word in words)


def _bounded_page_size(value: Any) -> int:
    if value is None:
        return min(25, MAXIMUM_READ_PAGE_SIZE)
    if isinstance(value, bool):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            "pageSize must be an integer.",
        )
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            "pageSize must be an integer.",
        ) from exc
    if result < 1 or result > MAXIMUM_READ_PAGE_SIZE:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_page_size_invalid",
            f"pageSize must be between 1 and {MAXIMUM_READ_PAGE_SIZE}.",
        )
    return result


def _bounded_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_ids_invalid",
            "ids must be an array.",
        )
    if len(value) > MAXIMUM_READ_IDS:
        raise FacilityLayoutAgentRuntimeError(
            "facility_agent_ids_exceeded",
            f"At most {MAXIMUM_READ_IDS} IDs may be inspected.",
        )
    return sorted({_stable_id(item, "id") for item in value})


def _extract_created_ids(operations: Sequence[Mapping[str, Any]]) -> list[str]:
    identifiers: set[str] = set()
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        for key, value in operation.items():
            if (
                isinstance(key, str)
                and key.endswith("Id")
                and isinstance(value, str)
                and value
            ):
                identifiers.add(value)
    return sorted(identifiers)


class FacilityLayoutAgentRuntime:
    """Revision-bound Facility Layout context, reads, and preview gateway."""

    def __init__(
        self,
        *,
        service: Any,
        shell_repository: Any,
        policy_repository: Any,
        vehicle_repository: Any,
        asset_catalog_provider: Callable[
            [FacilityPrincipal, str], Sequence[Mapping[str, Any]]
        ],
        process_catalog_provider: Callable[
            [FacilityPrincipal, str, Mapping[str, Any]],
            Sequence[Mapping[str, Any]],
        ]
        | None = None,
        evidence_provider: Callable[
            [
                FacilityPrincipal,
                str,
                Mapping[str, Any],
                Mapping[str, Any],
                Mapping[str, Any],
                Sequence[Mapping[str, Any]],
            ],
            Mapping[str, Any],
        ]
        | None = None,
        capabilities_provider: Callable[
            [FacilityPrincipal, str], Mapping[str, Any]
        ]
        | None = None,
        generation_layout_provider: Callable[
            [
                FacilityPrincipal,
                str,
                str,
                str,
                Mapping[str, Any] | None,
            ],
            Mapping[str, Any] | None,
        ]
        | None = None,
        cursor_secret: bytes | None = None,
        clock: Callable[[], float] | None = None,
        workflow_runtime: VerifiedWorkflowRuntime | None = None,
    ) -> None:
        self.service = service
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_catalog_provider = asset_catalog_provider
        self.process_catalog_provider = process_catalog_provider
        self.evidence_provider = evidence_provider
        self.capabilities_provider = capabilities_provider
        self.generation_layout_provider = generation_layout_provider
        self.cursor_secret = cursor_secret or secrets.token_bytes(32)
        if len(self.cursor_secret) < 32:
            raise ValueError("cursor_secret must contain at least 32 bytes")
        self.clock = clock or time.time
        self.workflow_runtime = workflow_runtime or VerifiedWorkflowRuntime()
        self._turn_lock = threading.RLock()
        self._turn_calls: dict[tuple[str, str, str, str], tuple[float, int]] = {}

    @staticmethod
    def _asset_source_document(
        values: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        assets = []
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            definition = raw.get("definition")
            if not isinstance(definition, Mapping):
                definition = raw.get("document")
            if not isinstance(definition, Mapping):
                definition = raw
            revision = (
                raw.get("assetDefinitionRevision")
                or raw.get("revision")
                or _fingerprint(definition)
            )
            document = deepcopy(dict(definition))
            # Reviewed functional sides sit on the catalog record beside the
            # revisioned definition (asset_orientation.attach_registered_semantics).
            # Without them library search reported no sides at all, and the agent
            # fell back to an unverified default rotation for reviewed models.
            semantics = raw.get("facilitySemantics")
            if "facilitySemantics" not in document and isinstance(semantics, Mapping):
                document["facilitySemantics"] = deepcopy(dict(semantics))
            assets.append(
                {
                    "revision": _revision(
                        revision,
                        "assetDefinitionRevision",
                    ),
                    "previewPlanningEligible": (
                        raw.get("previewPlanningEligible") is True
                    ),
                    "document": document,
                }
            )
        assets.sort(
            key=lambda item: (
                str(item["document"].get("assetId") or ""),
                item["revision"],
            )
        )
        return {"assets": assets}

    def _published_vehicles(
        self,
        principal: FacilityPrincipal,
        site_id: str,
    ) -> list[dict[str, Any]]:
        vehicles = []
        for summary in self.vehicle_repository.list_documents(
            principal,
            site_id=site_id,
        ):
            if not isinstance(summary, Mapping):
                continue
            vehicle_id = summary.get("vehicleProfileId")
            revision = summary.get("publishedRevision")
            if not vehicle_id or not revision:
                continue
            try:
                envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=str(vehicle_id),
                    revision=str(revision),
                )
            except FacilityNotFoundError:
                continue
            vehicles.append(
                {
                    "revision": envelope.revision,
                    "document": deepcopy(dict(envelope.document)),
                }
            )
        return vehicles

    @staticmethod
    def _workflow_owner_key(
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
    ) -> str:
        return "facility-owner-" + _fingerprint(
            {
                "tenantId": principal.tenant_id,
                "principalId": principal.principal_id,
                "siteId": site_id,
                "layoutId": layout_id,
            }
        )[:40]

    @staticmethod
    def _workflow_goal(semantic_plan: Mapping[str, Any]) -> str:
        scope = semantic_plan.get("scope")
        label = (
            _clean_text(scope.get("label"), 240)
            if isinstance(scope, Mapping)
            else ""
        )
        objective = _clean_text(semantic_plan.get("objective"), 120)
        if label and objective:
            return f"{objective}: {label}"
        return label or objective or "Build a verified Facility Layout preview"

    @staticmethod
    def _workflow_hard_constraints() -> list[str]:
        return [
            "Use the exact trusted Facility Layout and dependency revisions.",
            "Never accept model-authored coordinates or low-level geometry.",
            "Preserve locked placements.",
            "Preserve manually positioned placements by default.",
            "Cover every requested asset occurrence.",
            "Introduce no new hard spatial or routing finding.",
            "Create a preview only; require explicit approval before atomic apply.",
        ]

    @staticmethod
    def _workflow_soft_objectives(
        semantic_plan: Mapping[str, Any],
    ) -> list[str]:
        hints = semantic_plan.get("layoutHints")
        density = (
            _clean_text(hints.get("density"), 80)
            if isinstance(hints, Mapping)
            else ""
        )
        strategies = [
            _clean_text(item.get("strategy"), 80)
            for item in semantic_plan.get("alternatives", [])
            if isinstance(item, Mapping) and item.get("strategy")
        ]
        values = [
            f"Prefer {density} layout density." if density else "",
            (
                "Evaluate deterministic strategies: " + ", ".join(strategies)
                if strategies else ""
            ),
        ]
        return [value for value in values if value]

    @staticmethod
    def _workflow_issue_from_finding(
        finding: Mapping[str, Any],
    ) -> VerifiedWorkflowIssue:
        raw_severity = str(finding.get("severity") or "warning").lower()
        severity = (
            raw_severity
            if raw_severity in {"info", "warning", "error", "blocked"}
            else "warning"
        )
        return VerifiedWorkflowIssue(
            code=str(finding.get("code") or "facility_plan_finding"),
            severity=severity,
            message=str(
                finding.get("message")
                or "The Facility Layout plan produced a validation finding."
            ),
            recoverability=(
                "terminal" if severity in {"error", "blocked"}
                else "not_applicable"
            ),
            details={
                key: deepcopy(value)
                for key, value in finding.items()
                if key not in {"code", "severity", "message"}
            },
        )

    @staticmethod
    def _classify_workflow_error(
        error: Exception,
        phase: str,
    ) -> VerifiedWorkflowIssue:
        if isinstance(error, SemanticFacilityPlanError):
            return VerifiedWorkflowIssue(
                code=error.code,
                severity="error",
                message=str(error),
                recoverability="terminal",
                details={
                    "phase": phase,
                    "findings": deepcopy(error.findings),
                    "statusCode": 422,
                },
            )
        if isinstance(error, FacilityLayoutAgentRuntimeError):
            return VerifiedWorkflowIssue(
                code=error.code,
                severity="blocked" if error.status_code == 409 else "error",
                message=str(error),
                recoverability="terminal",
                details={
                    **deepcopy(error.details),
                    "phase": phase,
                    "statusCode": error.status_code,
                },
            )
        if isinstance(error, FacilityLayoutError):
            recoverable = error.code == "no_layout_alternative"
            return VerifiedWorkflowIssue(
                code=error.code,
                severity="error",
                message=str(error),
                recoverability=("recoverable" if recoverable else "terminal"),
                details={
                    **deepcopy(error.details),
                    "phase": phase,
                    "statusCode": error.status_code,
                },
            )
        return VerifiedWorkflowIssue(
            code="facility_verified_workflow_failed",
            severity="error",
            message="The verified Facility Layout workflow failed.",
            recoverability="terminal",
            details={
                "phase": phase,
                "exceptionType": type(error).__name__,
                "statusCode": 500,
            },
        )

    @staticmethod
    def _validate_workflow_plan(
        plan: Mapping[str, Any],
        bundle: FacilityAgentContextBundle,
    ) -> list[VerifiedWorkflowIssue]:
        issues = [
            FacilityLayoutAgentRuntime._workflow_issue_from_finding(item)
            for item in plan["compiled"].get("findings", [])
            if isinstance(item, Mapping)
        ]
        if not bundle.state.get("savedStateCurrent"):
            planner_request = plan.get("compiled", {}).get(
                "plannerRequest", {}
            )
            cleanup = (
                planner_request.get("cleanup", {})
                if isinstance(planner_request, Mapping)
                else {}
            )
            explicit_replacement = (
                isinstance(cleanup, Mapping)
                and cleanup.get("replaceExistingContents") is True
            )
            if explicit_replacement:
                issues.append(
                    VerifiedWorkflowIssue(
                        code="facility_dirty_draft_excluded_from_replacement",
                        severity="warning",
                        message=(
                            "The replacement preview is bound to the saved "
                            "layout revision; unsaved editor contents are not "
                            "used as planning evidence."
                        ),
                        recoverability="human_required",
                    )
                )
            else:
                issues.append(
                    VerifiedWorkflowIssue(
                        code="facility_layout_saved_state_required",
                        severity="blocked",
                        message=(
                            "Save or discard editor changes before building "
                            "a proposal."
                        ),
                        recoverability="human_required",
                        details={"statusCode": 409},
                    )
                )
        return issues

    @staticmethod
    def _validate_workflow_preview(
        proposals: Any,
        _plan: Mapping[str, Any],
        _bundle: FacilityAgentContextBundle,
        _attempt: int,
    ) -> list[VerifiedWorkflowIssue]:
        issues: list[VerifiedWorkflowIssue] = []
        if not isinstance(proposals, Mapping):
            return [
                VerifiedWorkflowIssue(
                    code="facility_preview_result_invalid",
                    severity="error",
                    message="The deterministic planner returned no structured preview.",
                    recoverability="terminal",
                )
            ]
        if proposals.get("previewPure") is not True:
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_not_pure",
                    severity="error",
                    message="The Facility Layout result was not a pure preview.",
                    recoverability="terminal",
                )
            )
        alternatives = [
            item for item in proposals.get("alternatives", [])
            if isinstance(item, Mapping)
        ]
        selected_proposal_id = str(proposals.get("selectedProposalId") or "")
        selected = next(
            (
                item for item in alternatives
                if str(item.get("proposalId") or "") == selected_proposal_id
            ),
            None,
        )
        if not alternatives or not selected_proposal_id or selected is None:
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_selection_invalid",
                    severity="error",
                    message="The deterministic planner did not select a complete alternative.",
                    recoverability="terminal",
                )
            )
            return issues
        if selected.get("newHardFindingIds"):
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_contains_new_hard_findings",
                    severity="blocked",
                    message="The selected preview introduced a hard spatial finding.",
                    recoverability="terminal",
                    details={
                        "findingIds": deepcopy(selected["newHardFindingIds"]),
                    },
                )
            )
        metrics = selected.get("metrics")
        if not isinstance(metrics, Mapping) or metrics.get("completeAssetSet") is not True:
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_asset_coverage_incomplete",
                    severity="blocked",
                    message="The selected preview did not cover every requested asset.",
                    recoverability="terminal",
                )
            )
        elif int(metrics.get("spatialUnverifiedCount") or 0) > 0:
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_contains_unverified_spatial_evidence",
                    severity="warning",
                    message="Some preview geometry remains unverified and requires review.",
                    recoverability="human_required",
                    details={
                        "count": int(metrics.get("spatialUnverifiedCount") or 0),
                    },
                )
            )
        rejected = [
            item for item in proposals.get("rejectedAlternatives", [])
            if isinstance(item, Mapping)
        ]
        if rejected:
            issues.append(
                VerifiedWorkflowIssue(
                    code="facility_preview_alternatives_rejected",
                    severity="info",
                    message="Some deterministic alternatives were rejected before preview.",
                    recoverability="not_applicable",
                    details={
                        "count": len(rejected),
                        "strategies": sorted(
                            {
                                str(item.get("strategy") or "unknown")
                                for item in rejected
                            }
                        ),
                    },
                )
            )
        return issues

    @staticmethod
    def _repair_workflow_plan(
        plan: Mapping[str, Any],
        bundle: FacilityAgentContextBundle,
        issues: Sequence[VerifiedWorkflowIssue],
        _attempt: int,
    ) -> VerifiedWorkflowRepair | None:
        if {issue.code for issue in issues} != {"no_layout_alternative"}:
            return None
        semantic_plan = deepcopy(dict(plan["semanticPlan"]))
        alternatives = [
            deepcopy(dict(item))
            for item in semantic_plan.get("alternatives", [])
            if isinstance(item, Mapping)
        ]
        existing = {
            str(item.get("strategy") or "") for item in alternatives
        }
        strategy = next(
            (
                value for value in _DETERMINISTIC_STRATEGY_ORDER
                if value not in existing
            ),
            None,
        )
        if strategy is None:
            return None
        alternatives.append(
            {
                "alternativeId": f"verified-repair-{strategy.replace('_', '-')}",
                "strategy": strategy,
                "label": "Verified deterministic fallback",
            }
        )
        semantic_plan["alternatives"] = alternatives
        compiled = compile_semantic_facility_plan(
            semantic_plan,
            state=bundle.state,
            evidence=bundle.evidence,
        )
        repaired = {
            "semanticPlan": semantic_plan,
            "compiled": compiled,
        }
        return VerifiedWorkflowRepair(
            plan=repaired,
            code="add_deterministic_layout_strategy",
            message=(
                "Added one permitted layout strategy without changing any "
                "hard constraint."
            ),
            details={"strategy": strategy},
        )

    @staticmethod
    def _default_evidence(
        _principal: FacilityPrincipal,
        _site_id: str,
        layout: Mapping[str, Any],
        shell: Mapping[str, Any],
        policy: Mapping[str, Any],
        assets: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        unresolved = []
        for source_kind, document in (
            ("layout", layout),
            ("facility_shell", shell),
            ("facility_policy", policy),
        ):
            for index, raw in enumerate(document.get("unresolvedItems", [])):
                if not isinstance(raw, Mapping):
                    continue
                unresolved.append(
                    {
                        "findingId": str(
                            raw.get("findingId")
                            or f"{source_kind}-unresolved-{index + 1}"
                        ),
                        "code": str(
                            raw.get("code") or "authority_review_required"
                        ),
                        "message": _clean_text(raw.get("message"), 600),
                        "subjectRefs": [source_kind],
                    }
                )
        records = []
        for source in (layout, shell, policy, *assets):
            for raw in source.get("evidenceRecords", []):
                if isinstance(raw, Mapping):
                    records.append(deepcopy(dict(raw)))
        return {
            "records": records,
            "unresolvedFacts": unresolved,
        }

    def _proposal_document(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        proposal_id: str | None,
    ) -> Mapping[str, Any] | None:
        if not proposal_id:
            return None
        try:
            preview = self.service.get_layout_proposal_preview(
                principal,
                site_id,
                layout_id,
                _stable_id(proposal_id, "proposalId"),
            )
        except (FacilityNotFoundError, FacilityConflictError):
            return None
        alternative = (
            preview.get("alternative")
            if isinstance(preview.get("alternative"), Mapping)
            else {}
        )
        binding = (
            preview.get("transactionBinding")
            if isinstance(preview.get("transactionBinding"), Mapping)
            else {}
        )
        operations = [
            item
            for item in alternative.get("operations", [])
            if isinstance(item, Mapping)
        ]
        return {
            "proposalId": preview.get("proposalId"),
            "layoutId": layout_id,
            "baseRevision": binding.get("baseRevision"),
            "status": "preview",
            "selectedAlternativeId": alternative.get("alternativeId"),
            "entityIds": _extract_created_ids(operations),
            "counts": {
                "operations": len(operations),
                "routeProposals": len(
                    alternative.get("routeProposals", [])
                    if isinstance(
                        alternative.get("routeProposals"),
                        list,
                    )
                    else []
                ),
            },
            "pendingApproval": True,
        }

    def _receipt_documents(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        receipt_ids: Sequence[Any] | None,
    ) -> list[dict[str, Any]]:
        result = []
        for raw_id in list(receipt_ids or [])[-6:]:
            try:
                receipt_id = _stable_id(raw_id, "receiptId")
                receipt = self.service.get_layout_receipt(
                    principal,
                    site_id,
                    layout_id,
                    receipt_id,
                )
            except (FacilityNotFoundError, FacilityLayoutAgentRuntimeError):
                continue
            result.append(deepcopy(dict(receipt)))
        return result

    def resolve_context(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str | None = None,
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> FacilityAgentContextBundle:
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        layout_receipt = self.service.get_layout(
            principal,
            site_id,
            layout_id,
        )
        layout = deepcopy(dict(layout_receipt["layout"]))
        saved_revision = _revision(
            layout_receipt["revision"],
            "layout revision",
        )
        requested_revision = (
            _revision(expected_revision, "expected revision")
            if expected_revision is not None
            else None
        )
        current_revision = saved_revision
        layout_provider = "facility-layout-repository"
        generation_run_id = None
        if self.generation_layout_provider is not None:
            generated = self.generation_layout_provider(
                principal,
                site_id,
                layout_id,
                saved_revision,
                live_facts,
            )
            if generated is not None:
                raw_layout = generated.get("layout")
                if not isinstance(raw_layout, Mapping):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_generation_context_invalid",
                        "The active Facility generation draft is invalid.",
                        status_code=409,
                    )
                layout = canonicalize_layout(deepcopy(dict(raw_layout)))
                current_revision = _revision(
                    generated.get("revision"),
                    "generation draft revision",
                )
                if layout_revision(layout) != current_revision:
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_generation_context_revision_mismatch",
                        "The active Facility generation draft revision is invalid.",
                        status_code=409,
                    )
                layout_provider = str(
                    generated.get("provider")
                    or "facility-generation-run-repository"
                )
                generation_run_id = str(
                    generated.get("runId") or ""
                ).strip() or None
        pending_operations = (
            live_facts.get("pendingOperations")
            if isinstance(live_facts, Mapping)
            else None
        )
        if generation_run_id is None and pending_operations:
            if (
                not isinstance(pending_operations, list)
                or len(pending_operations) > 500
                or any(not isinstance(item, Mapping) for item in pending_operations)
            ):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_navigation_pending_operations_invalid",
                    "The active Facility draft operation batch is invalid.",
                    status_code=409,
                )
            try:
                layout = apply_facility_layout_operations(
                    layout,
                    [deepcopy(dict(item)) for item in pending_operations],
                    base_revision=saved_revision,
                )["document"]
            except FacilityLayoutError as error:
                raise FacilityLayoutAgentRuntimeError(
                    getattr(error, "code", "facility_navigation_pending_operations_invalid"),
                    str(error),
                    status_code=getattr(error, "status_code", 409),
                    details=getattr(error, "details", {}),
                ) from error
            current_revision = layout_revision(layout)
            layout_provider = "facility-layout-session-validated-draft"
        if requested_revision not in {None, saved_revision, current_revision}:
            raise FacilityLayoutAgentRuntimeError(
                "facility_layout_revision_conflict",
                "The Facility Layout changed before Sage observed it.",
                status_code=409,
                details={
                    "currentRevision": current_revision,
                    "savedRevision": saved_revision,
                },
            )
        shell_ref = layout.get("sourceShellRef")
        policy_ref = layout.get("policySetRef")
        if not isinstance(shell_ref, Mapping) or not isinstance(
            policy_ref,
            Mapping,
        ):
            raise FacilityLayoutAgentRuntimeError(
                "facility_layout_authority_missing",
                "Facility Layout shell or policy authority is missing.",
                status_code=409,
            )
        shell = self.shell_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=str(shell_ref.get("shellId") or ""),
            revision=str(shell_ref.get("shellRevision") or ""),
        )
        policy = self.policy_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=str(policy_ref.get("policySetId") or ""),
            revision=str(policy_ref.get("policySetRevision") or ""),
        )
        # The published shell remains the authority source, while an authored
        # facilityPlan extension is the active planning boundary. The service
        # validation path already applies this projection; Sage must observe
        # the same effective floor instead of a stale starter-shell footprint.
        effective_shell = shell_with_plan_boundary(shell.document, layout)
        raw_assets = list(self.asset_catalog_provider(principal, site_id))
        asset_source_document = self._asset_source_document(raw_assets)
        process_maps = (
            list(self.process_catalog_provider(principal, site_id, layout))
            if self.process_catalog_provider is not None
            else []
        )
        evidence_document = (
            self.evidence_provider(
                principal,
                site_id,
                layout,
                effective_shell,
                policy.document,
                [
                    item["document"]
                    for item in asset_source_document["assets"]
                ],
            )
            if self.evidence_provider is not None
            else self._default_evidence(
                principal,
                site_id,
                layout,
                effective_shell,
                policy.document,
                [
                    item["document"]
                    for item in asset_source_document["assets"]
                ],
            )
        )
        capabilities = (
            dict(self.capabilities_provider(principal, site_id))
            if self.capabilities_provider is not None
            else {
                "read": True,
                "semanticPlanning": True,
                "semanticPreview": (
                    "*" in principal.action_set
                    or "proposal.create" in principal.action_set
                ),
                "approval": (
                    "*" in principal.action_set
                    or "proposal.approve" in principal.action_set
                ),
                "apply": (
                    "*" in principal.action_set
                    or "proposal.apply" in principal.action_set
                ),
            }
        )
        proposal_document = self._proposal_document(
            principal,
            site_id,
            layout_id,
            proposal_id,
        )
        receipts = self._receipt_documents(
            principal,
            site_id,
            layout_id,
            receipt_ids,
        )
        sources: dict[str, TrustedFacilitySource | None] = {
            "layout": trusted_facility_source(
                "facility_layout",
                layout,
                revision=current_revision,
                provider=layout_provider,
            ),
            "assets": trusted_facility_source(
                "industrial_asset_catalog",
                asset_source_document,
                provider="industrial-asset-catalog",
            ),
            "shell": trusted_facility_source(
                "facility_shell",
                effective_shell,
                revision=shell.revision,
                provider="facility-shell-with-active-plan-boundary",
            ),
            "policy": trusted_facility_source(
                "facility_policy",
                policy.document,
                revision=policy.revision,
                provider="facility-policy-repository",
            ),
            "evidence": trusted_facility_source(
                "facility_evidence",
                evidence_document,
                provider="facility-evidence-resolver",
            ),
            "vehicles": trusted_facility_source(
                "vehicle_profiles",
                {"vehicles": self._published_vehicles(principal, site_id)},
                provider="vehicle-profile-repository",
            ),
            "process": trusted_facility_source(
                "process_maps",
                {"processMaps": process_maps},
                provider="process-map-repository",
            ),
            "diagnostics": trusted_facility_source(
                "facility_diagnostics",
                {
                    "findings": deepcopy(
                        (
                            []
                            if generation_run_id is not None
                            else layout_receipt.get("findings", [])
                        )
                    ),
                    "metrics": {},
                },
                provider="facility-layout-validator",
            ),
            "capabilities": trusted_facility_source(
                "facility_capabilities",
                capabilities,
                provider="facility-layout-authorization",
            ),
            "proposal": (
                trusted_facility_source(
                    "facility_proposal",
                    proposal_document,
                    provider="facility-layout-transaction-runtime",
                )
                if proposal_document is not None
                else None
            ),
            "receipts": (
                trusted_facility_source(
                    "facility_receipts",
                    {"receipts": receipts},
                    provider="facility-layout-receipt-store",
                )
                if receipts
                else None
            ),
        }
        observation = build_facility_layout_observation(
            sources["layout"],
            sources["assets"],
            shell_source=sources["shell"],
            policy_source=sources["policy"],
            evidence_source=sources["evidence"],
            vehicle_source=sources["vehicles"],
            process_source=sources["process"],
            diagnostics_source=sources["diagnostics"],
            capabilities_source=sources["capabilities"],
            proposal_source=sources["proposal"],
            receipts_source=sources["receipts"],
            live_facts=live_facts,
        )
        digest = build_facility_layout_digest(
            observation["state"],
            observation["evidence"],
        )
        asset_documents = []
        for item in asset_source_document["assets"]:
            document = deepcopy(dict(item["document"]))
            document["assetDefinitionRevision"] = item["revision"]
            asset_documents.append(document)
        evidence_authority = {
            str(item["evidenceId"]): deepcopy(dict(item))
            for item in observation["evidence"].get("records", [])
            if isinstance(item, Mapping) and item.get("evidenceId")
        }
        return FacilityAgentContextBundle(
            state=observation["state"],
            evidence=observation["evidence"],
            digest=digest,
            shell_document=deepcopy(dict(effective_shell)),
            policy_document=deepcopy(dict(policy.document)),
            asset_documents=tuple(asset_documents),
            evidence_authority=evidence_authority,
            layout_document=deepcopy(layout),
            base_layout_revision=saved_revision,
            generation_run_id=generation_run_id,
        )

    def _principal_binding(
        self,
        principal: FacilityPrincipal,
    ) -> dict[str, Any]:
        return {
            "tenantId": principal.tenant_id,
            "principalId": principal.principal_id,
            "roles": list(principal.roles),
        }

    def _encode_cursor(self, payload: Mapping[str, Any]) -> str:
        raw = _canonical_bytes(payload)
        signature = hmac.new(
            self.cursor_secret,
            raw,
            hashlib.sha256,
        ).digest()
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        encoded_signature = (
            base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        )
        return f"flc1.{encoded}.{encoded_signature}"

    def _decode_cursor(
        self,
        cursor: str,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
        tool_name: str,
        filter_hash: str,
    ) -> int:
        try:
            prefix, encoded, encoded_signature = str(cursor).split(".", 2)
            if prefix != "flc1":
                raise ValueError
            raw = base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
            signature = base64.urlsafe_b64decode(
                encoded_signature + "=" * (-len(encoded_signature) % 4)
            )
            expected = hmac.new(
                self.cursor_secret,
                raw,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(raw.decode("ascii"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_invalid",
                "The Facility Layout read cursor is invalid.",
            ) from exc
        expected_binding = {
            **self._principal_binding(principal),
            "siteId": site_id,
            "layoutId": layout_id,
            "revision": revision,
            "tool": tool_name,
            "filterHash": filter_hash,
        }
        if any(
            payload.get(key) != value
            for key, value in expected_binding.items()
        ):
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_scope_mismatch",
                "The Facility Layout read cursor belongs to another scope.",
                status_code=404,
            )
        if float(payload.get("expiresAt") or 0) < self.clock():
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_expired",
                "The Facility Layout read cursor expired.",
                status_code=409,
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_cursor_invalid",
                "The Facility Layout read cursor is invalid.",
            )
        return offset

    def _next_cursor(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
        tool_name: str,
        filter_hash: str,
        offset: int,
    ) -> str:
        return self._encode_cursor(
            {
                **self._principal_binding(principal),
                "siteId": site_id,
                "layoutId": layout_id,
                "revision": revision,
                "tool": tool_name,
                "filterHash": filter_hash,
                "offset": offset,
                "expiresAt": round(
                    self.clock()
                    + FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS,
                    3,
                ),
            }
        )

    def _consume_turn_call(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        turn_id: str,
    ) -> None:
        turn_id = _stable_id(turn_id, "turnId")
        now = self.clock()
        key = (
            principal.tenant_id,
            principal.principal_id,
            site_id,
            f"{layout_id}:{turn_id}",
        )
        with self._turn_lock:
            stale = [
                item
                for item, (updated, _) in self._turn_calls.items()
                if now - updated > FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS
            ]
            for item in stale:
                self._turn_calls.pop(item, None)
            _, count = self._turn_calls.get(key, (now, 0))
            if count >= FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_turn_budget_exceeded",
                    "The Facility Layout observation budget is exhausted.",
                    status_code=429,
                )
            self._turn_calls[key] = (now, count + 1)

    def _page(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        offset: int,
        page_size: int,
        envelope: Mapping[str, Any],
        cursor_factory: Callable[[int], str],
    ) -> dict[str, Any]:
        end = min(len(records), offset + page_size)
        page = [deepcopy(dict(item)) for item in records[offset:end]]
        result = {
            **deepcopy(dict(envelope)),
            "records": page,
            "returnedCount": len(page),
            "totalCount": len(records),
            "nextCursor": cursor_factory(end) if end < len(records) else None,
            "nextOffset": end if end < len(records) else None,
        }
        while (
            len(_canonical_bytes(result))
            > FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
            and result["records"]
        ):
            result["records"].pop()
            result["returnedCount"] = len(result["records"])
            next_offset = offset + len(result["records"])
            result["nextCursor"] = cursor_factory(next_offset)
            result["nextOffset"] = next_offset
        if len(_canonical_bytes(result)) > FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_response_budget_exceeded",
                "The Facility Layout read response exceeded its bound.",
            )
        return result

    def execute_read_tool(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        turn_id: str,
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        if tool_name not in _READ_TOOLS:
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_tool_unknown",
                "The Facility Layout observation tool is unavailable.",
                status_code=404,
            )
        if not isinstance(arguments, Mapping):
            raise FacilityLayoutAgentRuntimeError(
                "facility_agent_arguments_invalid",
                "Facility Layout tool arguments must be an object.",
            )
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        expected_revision = _revision(
            expected_revision,
            "expectedRevision",
        )
        self._consume_turn_call(
            principal,
            site_id,
            layout_id,
            turn_id,
        )
        bundle = self.resolve_context(
            principal,
            site_id=site_id,
            layout_id=layout_id,
            expected_revision=expected_revision,
            live_facts=live_facts,
            proposal_id=proposal_id,
            receipt_ids=receipt_ids,
        )
        state = bundle.state
        revision = str(state["identity"]["revision"])
        args = deepcopy(dict(arguments))
        cursor = args.pop("cursor", None)
        requested_offset = args.pop("offset", None)
        # The page size changes how many records come back, not which records match,
        # so it does not scope a cursor; agents changed it between pages and lost theirs.
        filter_hash = _fingerprint(
            {key: value for key, value in args.items() if key != "pageSize"}
        )
        if cursor:
            offset = self._decode_cursor(
                str(cursor),
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                revision=revision,
                tool_name=tool_name,
                filter_hash=filter_hash,
            )
        elif requested_offset is not None:
            # A plain record offset (the previous page's nextOffset) pages the same
            # authorized results; agents can repeat a number without mistakes, unlike a
            # long signed cursor.
            if (
                isinstance(requested_offset, bool)
                or not isinstance(requested_offset, int)
                or requested_offset < 0
            ):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_arguments_invalid",
                    "offset must be a whole number of records, 0 or more.",
                )
            offset = requested_offset
        else:
            offset = 0
        page_size = _bounded_page_size(args.get("pageSize"))
        base_envelope = {
            "ok": True,
            "runtimeVersion": FACILITY_LAYOUT_AGENT_RUNTIME_VERSION,
            "tool": tool_name,
            "siteId": site_id,
            "layoutId": layout_id,
            "revision": revision,
            "authoritative": True,
        }

        def next_cursor(next_offset: int) -> str:
            return self._next_cursor(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                revision=revision,
                tool_name=tool_name,
                filter_hash=filter_hash,
                offset=next_offset,
            )

        if tool_name in NAVIGATION_READ_TOOL_NAMES:
            if cursor:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_navigation_agent_arguments_invalid",
                    "Navigation tools do not accept read cursors.",
                )

            def navigation_result(payload: Mapping[str, Any]) -> dict[str, Any]:
                result = {**base_envelope, **deepcopy(dict(payload))}
                if len(_canonical_bytes(result)) > FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES:
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_response_budget_exceeded",
                        "The compact navigation response exceeded its bound.",
                    )
                return result

            def require_fields(
                allowed: set[str],
                required: set[str] = set(),
            ) -> None:
                unknown = sorted(set(args) - allowed)
                missing = sorted(required - set(args))
                if unknown or missing:
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_navigation_agent_arguments_invalid",
                        "Navigation tool arguments do not match the closed contract.",
                        details={"unknownFields": unknown, "missingFields": missing},
                    )

            try:
                if tool_name == OBSERVE_NAVIGATION_CONTEXT_TOOL:
                    require_fields({"query", "actorClass", "maximumRecords"})
                    actor_class = args.get("actorClass")
                    if actor_class is not None and actor_class not in {
                        "pedestrian", "vehicle"
                    }:
                        raise FacilityLayoutAgentRuntimeError(
                            "facility_navigation_agent_arguments_invalid",
                            "actorClass must be pedestrian or vehicle.",
                        )
                    maximum = args.get("maximumRecords", 20)
                    if isinstance(maximum, bool) or not isinstance(maximum, int):
                        raise FacilityLayoutAgentRuntimeError(
                            "facility_navigation_agent_arguments_invalid",
                            "maximumRecords must be an integer.",
                        )
                    return navigation_result(navigation_context_summary(
                        bundle.layout_document,
                        query=_clean_text(args.get("query"), 160),
                        actor_class=actor_class,
                        maximum_records=maximum,
                    ))

                if tool_name == COMPILE_NAVIGATION_SNAPSHOT_TOOL:
                    require_fields(
                        {"movementProgramId", "prototypeMode"},
                        {"movementProgramId"},
                    )
                    request = {
                        "movementProgramId": _stable_id(
                            args.get("movementProgramId"), "movementProgramId"
                        ),
                    }
                    if "prototypeMode" in args:
                        if not isinstance(args["prototypeMode"], bool):
                            raise FacilityLayoutAgentRuntimeError(
                                "facility_navigation_agent_arguments_invalid",
                                "prototypeMode must be boolean.",
                            )
                        request["prototypeMode"] = args["prototypeMode"]
                    compiled = self.service.compile_navigation_snapshot(
                        principal,
                        site_id,
                        layout_id,
                        bundle.base_layout_revision,
                        request,
                        _trusted_draft=bundle.layout_document,
                    )
                    return navigation_result(compiled)

                if tool_name == PLAN_ACTOR_JOURNEY_TOOL:
                    require_fields(
                        {
                            "navigationPackageId",
                            "movementProgramId",
                            "prototypeMode",
                            "allowReverse",
                        },
                        {"navigationPackageId", "movementProgramId"},
                    )
                    request = {
                        "navigationPackageId": _stable_id(
                            args.get("navigationPackageId"), "navigationPackageId"
                        ),
                        "movementProgramId": _stable_id(
                            args.get("movementProgramId"), "movementProgramId"
                        ),
                    }
                    for field in ("prototypeMode", "allowReverse"):
                        if field in args:
                            if not isinstance(args[field], bool):
                                raise FacilityLayoutAgentRuntimeError(
                                    "facility_navigation_agent_arguments_invalid",
                                    f"{field} must be boolean.",
                                )
                            request[field] = args[field]
                    planned = self.service.plan_actor_journey(
                        principal,
                        site_id,
                        layout_id,
                        bundle.base_layout_revision,
                        request,
                        _trusted_draft=bundle.layout_document,
                    )
                    return navigation_result(planned)

                if tool_name == VALIDATE_ACTOR_JOURNEY_TOOL:
                    require_fields({"journeySolutionId"}, {"journeySolutionId"})
                    journey_id = _stable_id(
                        args.get("journeySolutionId"), "journeySolutionId"
                    )
                    journey = self.service.get_actor_journey(
                        principal, site_id, layout_id, journey_id
                    )
                    active_revision = layout_revision(bundle.layout_document)
                    return navigation_result({
                        "summary": journey_solution_summary(journey),
                        "activeDraftRevision": active_revision,
                        "generationLayoutRevision": journey[
                            "generationLayoutRevision"
                        ],
                        "stale": (
                            journey["generationLayoutRevision"]
                            != active_revision
                        ),
                        "validationContextFingerprint": journey[
                            "validationContextFingerprint"
                        ],
                        "mutated": False,
                    })

                require_fields(
                    {"journeySolutionIds"}, {"journeySolutionIds"}
                )
                raw_ids = args.get("journeySolutionIds")
                if (
                    not isinstance(raw_ids, list)
                    or not 2 <= len(raw_ids) <= 16
                ):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_navigation_agent_arguments_invalid",
                        "Journey comparison requires 2-16 unique journey IDs.",
                    )
                journey_ids = [
                    _stable_id(value, "journeySolutionId") for value in raw_ids
                ]
                if len(journey_ids) != len(set(journey_ids)):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_navigation_agent_arguments_invalid",
                        "Journey comparison IDs must be unique.",
                    )
                journeys = [
                    self.service.get_actor_journey(
                        principal, site_id, layout_id, journey_id
                    )
                    for journey_id in journey_ids
                ]
                return navigation_result(compare_journey_summaries(journeys))
            except FacilityLayoutAgentRuntimeError:
                raise
            except FacilityLayoutError as error:
                raise FacilityLayoutAgentRuntimeError(
                    getattr(error, "code", "facility_navigation_tool_failed"),
                    str(error),
                    status_code=getattr(error, "status_code", 422),
                    details=getattr(error, "details", {}),
                ) from error

        if tool_name == "search_industrial_assets":
            query = _clean_text(args.get("query"), 120).lower()
            category = _clean_text(args.get("category"), 80).lower()
            capability = _clean_text(
                args.get("capabilityId"),
                128,
            ).lower()
            records = [
                item
                for item in state.get("assets", [])
                if isinstance(item, Mapping)
                and _asset_query_matches(
                    query,
                    " ".join(
                        (
                            str(item.get("assetId") or ""),
                            str(item.get("displayName") or ""),
                            str(item.get("category") or ""),
                            " ".join(item.get("capabilityIds", [])),
                        )
                    ).lower(),
                )
                and (
                    not category
                    or str(item.get("category") or "").lower() == category
                )
                and (
                    not capability
                    or capability
                    in {
                        str(value).lower()
                        for value in item.get("capabilityIds", [])
                    }
                )
            ]
            return self._page(
                records,
                offset=offset,
                page_size=page_size,
                envelope=base_envelope,
                cursor_factory=next_cursor,
            )

        if tool_name == "inspect_facility_entities":
            kind = str(args.get("entityKind") or "")
            if kind not in _ENTITY_COLLECTIONS:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_entity_kind_invalid",
                    "entityKind is unsupported.",
                )
            ids = _bounded_ids(args.get("ids"))
            collection, id_field = _ENTITY_COLLECTIONS[kind]
            index = {
                str(item.get(id_field)): item
                for item in state.get(collection, [])
                if isinstance(item, Mapping) and item.get(id_field)
            }
            return {
                **base_envelope,
                "entityKind": kind,
                "records": [
                    deepcopy(dict(index[item]))
                    for item in ids
                    if item in index
                ],
                "unresolvedIds": [
                    item for item in ids if item not in index
                ],
            }

        if tool_name == "inspect_facility_region":
            kind = str(args.get("regionKind") or "")
            region_id = _stable_id(args.get("regionId"), "regionId")
            records = []
            if kind == "zone":
                records = [
                    deepcopy(dict(item))
                    for item in state.get("zones", [])
                    if isinstance(item, Mapping)
                    and item.get("zoneId") == region_id
                ]
            elif kind == "shell_feature":
                records = [
                    deepcopy(dict(item))
                    for item in bundle.shell_document.get("features", [])
                    if isinstance(item, Mapping)
                    and item.get("featureId") == region_id
                ]
            else:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_region_kind_invalid",
                    "regionKind is unsupported.",
                )
            return {
                **base_envelope,
                "regionKind": kind,
                "records": records,
                "unresolvedIds": [] if records else [region_id],
            }

        if tool_name == "inspect_facility_findings":
            ids = (
                set(_bounded_ids(args.get("ids")))
                if "ids" in args
                else set()
            )
            code = _clean_text(args.get("code"), 128)
            records = [
                item
                for item in state.get("diagnostics", {}).get("findings", [])
                if isinstance(item, Mapping)
                and (
                    not ids
                    or str(item.get("findingId") or "") in ids
                )
                and (not code or str(item.get("code") or "") == code)
            ]
            return self._page(
                records,
                offset=offset,
                page_size=page_size,
                envelope=base_envelope,
                cursor_factory=next_cursor,
            )

        if tool_name in {
            "inspect_facility_semantics",
            "inspect_pattern_provenance",
            "inspect_cell_layout_provenance",
        }:
            semantic_map = build_facility_semantic_map(state)
            view = str(args.get("view") or "")
            if tool_name == "inspect_pattern_provenance":
                view = "layout_patterns"
            elif tool_name == "inspect_cell_layout_provenance":
                view = "layout_patterns"
            ids = (
                set(_bounded_ids(args.get("ids")))
                if "ids" in args else set()
            )
            query = _clean_text(args.get("query"), 120).casefold()
            view_contract = {
                "departments": ("departments", "zoneId"),
                "department_metrics": (
                    "departmentMetricSummaries",
                    "zoneId",
                ),
                "zones": ("zones", "zoneId"),
                "assets": ("assets", "assetId"),
                "placements": ("placements", "placementId"),
                "routes": ("routes", "routeId"),
                "route_crossings": ("routeCrossings", "crossingId"),
                "floor_markings": ("floorMarkings", "markingId"),
                "process_bindings": (
                    "processBindings",
                    "processBindingId",
                ),
                "layout_patterns": (
                    "layoutPatternGroups",
                    "provenanceId",
                ),
                "commands": ("commands", "commandId"),
                "cell_layout_strategies": (
                    "cellLayoutStrategies",
                    "strategyId",
                ),
                "derived_metrics": (
                    "derivedMetricDefinitions",
                    "metricId",
                ),
            }
            if view == "overview":
                if ids or query or cursor:
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_semantic_arguments_invalid",
                        "overview does not accept ids, query, or cursor.",
                    )
                result = {
                    **base_envelope,
                    "semanticContractVersion": semantic_map[
                        "semanticContractVersion"
                    ],
                    "evidenceVocabulary": semantic_map[
                        "evidenceVocabulary"
                    ],
                    "facilitySummary": semantic_map["facilitySummary"],
                    "assetRoleSummary": semantic_map["assetRoleSummary"],
                    "routeRoleSummary": semantic_map["routeRoleSummary"],
                    "routeNetworkSummary": semantic_map[
                        "routeNetworkSummary"
                    ],
                    "floorMarkingRoleSummary": semantic_map[
                        "floorMarkingRoleSummary"
                    ],
                    "analysisCapabilities": semantic_map[
                        "analysisCapabilities"
                    ],
                    "processRelationshipSummary": semantic_map[
                        "processRelationshipSummary"
                    ],
                    "availableViews": ["overview", *view_contract],
                }
                if len(_canonical_bytes(result)) > (
                    FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
                ):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_response_budget_exceeded",
                        "The Facility semantic overview exceeded its bound.",
                    )
                return result
            contract = view_contract.get(view)
            if contract is None:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_semantic_view_invalid",
                    "Facility semantic view is unsupported.",
                )
            collection_name, id_field = contract
            values = semantic_map.get(collection_name, [])
            records = [
                item
                for item in values
                if isinstance(item, Mapping)
                and (
                    tool_name not in {
                        "inspect_pattern_provenance",
                        "inspect_cell_layout_provenance",
                    }
                    or (
                        tool_name == "inspect_pattern_provenance"
                        and str(item.get("command") or "")
                        != "cell_layout"
                        and not bool(item.get("authoredStrategy"))
                    )
                    or (
                        tool_name == "inspect_cell_layout_provenance"
                        and (
                            str(item.get("command") or "")
                            == "cell_layout"
                            or bool(item.get("authoredStrategy"))
                        )
                    )
                )
                and (
                    not ids
                    or str(item.get(id_field) or "") in ids
                )
                and (
                    not query
                    or query in json.dumps(
                        item,
                        ensure_ascii=True,
                        sort_keys=True,
                    ).casefold()
                )
            ]
            result = self._page(
                records,
                offset=offset,
                page_size=page_size,
                envelope={
                    **base_envelope,
                    "semanticContractVersion": semantic_map[
                        "semanticContractVersion"
                    ],
                    "view": view,
                },
                cursor_factory=next_cursor,
            )
            if ids:
                returned_ids = {
                    str(item.get(id_field) or "")
                    for item in result.get("records", [])
                }
                result["unresolvedIds"] = sorted(ids - returned_ids)
            return result

        if tool_name == "analyze_facility_spatial":
            if cursor:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    "Focused Facility spatial analysis does not use cursors.",
                )
            analysis = str(args.get("analysis") or "")
            maximum_results = args.get("maximumResults", 10)
            if isinstance(maximum_results, bool):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    "maximumResults must be an integer.",
                )
            try:
                maximum_results = int(maximum_results)
            except (TypeError, ValueError) as exc:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    "maximumResults must be an integer.",
                ) from exc
            if not 1 <= maximum_results <= 50:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    "maximumResults must be between 1 and 50.",
                )
            scope_ids = args.get("scopeIds") or []
            if not isinstance(scope_ids, list):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    "scopeIds must be an array.",
                )
            scope_ids = _bounded_ids(scope_ids)
            try:
                if analysis == "resolve_entities":
                    kinds = args.get("entityKinds") or []
                    if not isinstance(kinds, list):
                        raise ValueError("entityKinds must be an array")
                    payload = resolve_facility_entities(
                        state,
                        query=_clean_text(args.get("query"), 120),
                        entity_kinds=[str(item) for item in kinds],
                        use_selection=args.get("useCurrentSelection") is True,
                        maximum_results=maximum_results,
                    )
                elif analysis == "clearances":
                    payload = analyze_facility_clearances(
                        state,
                        scope_ids=scope_ids,
                        maximum_results=maximum_results,
                        unit_mode=str(
                            args.get("unitMode") or "operational_units"
                        ),
                    )
                elif analysis == "protected_intrusions":
                    payload = analyze_facility_protected_intrusions(
                        state,
                        scope_ids=scope_ids,
                        maximum_results=maximum_results,
                    )
                elif analysis == "route_crossings":
                    semantic_map = build_facility_semantic_map(state)
                    records = list(semantic_map.get("routeCrossings", []))
                    payload = {
                        "analysis": analysis,
                        "records": records[:maximum_results],
                        "returnedCount": min(len(records), maximum_results),
                        "totalCount": len(records),
                        "routeNetworkSummary": deepcopy(
                            semantic_map.get("routeNetworkSummary") or {}
                        ),
                        "evidenceStatus": "derived",
                    }
                elif analysis == "free_space":
                    payload = analyze_facility_free_space(
                        state,
                        scope_ids=scope_ids,
                        metric=str(
                            args.get("freeSpaceMetric") or "geometric"
                        ),
                        maximum_results=maximum_results,
                    )
                elif analysis == "layout_provenance":
                    payload = analyze_facility_layout_provenance(
                        state,
                        query=_clean_text(args.get("query"), 120),
                        scope_ids=scope_ids,
                        use_selection=(
                            args.get("useCurrentSelection") is True
                        ),
                        maximum_results=maximum_results,
                    )
                elif analysis == "route_access":
                    source_zone_ids = args.get("sourceZoneIds") or []
                    target_zone_ids = args.get("targetZoneIds") or []
                    if not isinstance(source_zone_ids, list):
                        raise ValueError("sourceZoneIds must be an array")
                    if not isinstance(target_zone_ids, list):
                        raise ValueError("targetZoneIds must be an array")
                    payload = analyze_facility_route_access(
                        state,
                        source_query=_clean_text(
                            args.get("sourceQuery"), 120
                        ),
                        target_query=_clean_text(
                            args.get("targetQuery"), 120
                        ),
                        source_zone_ids=_bounded_ids(source_zone_ids),
                        target_zone_ids=_bounded_ids(target_zone_ids),
                        movement_class=str(
                            args.get("movementClass") or "material"
                        ),
                    )
                elif analysis == "route_widths":
                    payload = analyze_facility_route_widths(
                        state,
                        scope_ids=scope_ids,
                        movement_class=str(
                            args.get("movementClass") or "any"
                        ),
                        maximum_results=maximum_results,
                    )
                elif analysis == "cell_alternatives":
                    strategies = args.get("cellStrategies") or list(
                        CELL_FEASIBILITY_STRATEGIES
                    )
                    if not isinstance(strategies, list):
                        raise ValueError("cellStrategies must be an array")
                    payload = analyze_facility_cell_alternatives(
                        state,
                        query=_clean_text(args.get("query"), 120),
                        scope_ids=scope_ids,
                        strategies=[str(item) for item in strategies],
                        preferred_gap_meters=args.get(
                            "preferredGapMeters", 1.0
                        ),
                        invert_u=args.get("invertU") is True,
                    )
                elif analysis == "module_fit":
                    source_zone_ids = args.get("sourceZoneIds") or []
                    target_zone_ids = args.get("targetZoneIds") or []
                    orientations = args.get("orientationsDegrees") or [0, 90]
                    if not isinstance(source_zone_ids, list):
                        raise ValueError("sourceZoneIds must be an array")
                    if not isinstance(target_zone_ids, list):
                        raise ValueError("targetZoneIds must be an array")
                    if not isinstance(orientations, list):
                        raise ValueError("orientationsDegrees must be an array")
                    payload = analyze_facility_module_fit(
                        state,
                        source_query=_clean_text(
                            args.get("sourceQuery"), 120
                        ),
                        target_query=_clean_text(
                            args.get("targetQuery"), 120
                        ),
                        source_zone_ids=_bounded_ids(source_zone_ids),
                        target_zone_ids=_bounded_ids(target_zone_ids),
                        orientations_degrees=orientations,
                        gap_meters=args.get("moduleGapMeters", 1.0),
                        maximum_results=maximum_results,
                    )
                elif analysis == "operator_travel":
                    payload = analyze_facility_operator_travel(
                        state,
                        scope_ids=scope_ids,
                        maximum_results=maximum_results,
                    )
                elif analysis == "asset_access":
                    payload = analyze_facility_asset_access(
                        state,
                        interface_role=str(
                            args.get("interfaceRole") or "service"
                        ),
                        query=_clean_text(args.get("query"), 120),
                        scope_ids=scope_ids,
                        use_selection=(
                            args.get("useCurrentSelection") is True
                        ),
                        maximum_results=maximum_results,
                    )
                elif analysis == "cell_access":
                    payload = analyze_facility_cell_access(
                        state,
                        query=_clean_text(args.get("query"), 120),
                        scope_ids=scope_ids,
                        use_selection=(
                            args.get("useCurrentSelection") is True
                        ),
                        maximum_results=maximum_results,
                    )
                elif analysis == "drone_clearance":
                    payload = analyze_facility_drone_clearance(
                        state,
                        query=_clean_text(args.get("query"), 120),
                        scope_ids=scope_ids,
                        use_selection=(
                            args.get("useCurrentSelection") is True
                        ),
                        altitude_meters=args.get("altitudeMeters"),
                        maximum_results=maximum_results,
                    )
                elif analysis == "render_consistency":
                    payload = analyze_facility_render_consistency(state)
                else:
                    raise ValueError("analysis is unsupported")
            except (TypeError, ValueError) as exc:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_spatial_arguments_invalid",
                    str(exc),
                ) from exc
            response = {**base_envelope, **payload}
            if len(_canonical_bytes(response)) > (
                FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
            ):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_response_budget_exceeded",
                    "The focused Facility spatial response exceeded its limit.",
                )
            return response

        if tool_name == "analyze_facility_fit":
            allowed = {
                "assetId",
                "assetDefinitionRevision",
                "assetQuery",
                "sourcePlacementId",
                "useSelectedPlacement",
                "zoneId",
                "zoneQuery",
                "orientationsDegrees",
                "maximumResults",
            }
            unexpected = sorted(set(args) - allowed)
            if cursor or unexpected:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_fit_arguments_invalid",
                    "Facility fit analysis accepts only asset or placement "
                    "selectors, a target zone selector, orientations, and a "
                    "result limit.",
                    details={"unexpectedFields": unexpected},
                )
            placements_by_id = {
                str(item.get("placementId")): item
                for item in state.get("placements", [])
                if isinstance(item, Mapping) and item.get("placementId")
            }
            zones_by_id = {
                str(item.get("zoneId")): item
                for item in state.get("zones", [])
                if isinstance(item, Mapping) and item.get("zoneId")
            }
            selected_placement_ids = list(
                (state.get("selection") or {}).get("placementIds", [])
            )
            source_placement_id = str(
                args.get("sourcePlacementId") or ""
            ).strip()
            if args.get("useSelectedPlacement") is True:
                if len(selected_placement_ids) != 1:
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_fit_asset_ambiguous",
                        "Select exactly one source placement for this fit analysis.",
                        details={
                            "selectedPlacementIds": selected_placement_ids[:20]
                        },
                    )
                source_placement_id = str(selected_placement_ids[0])
            source_placement = placements_by_id.get(source_placement_id)
            if source_placement_id and source_placement is None:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_fit_asset_unresolved",
                    "The source placement is not present in the current layout revision.",
                )

            asset_id = str(args.get("assetId") or "").strip()
            asset_revision = str(
                args.get("assetDefinitionRevision") or ""
            ).strip()
            if source_placement is not None:
                asset_id = str(source_placement.get("assetId") or "")
                asset_revision = str(
                    source_placement.get("assetDefinitionRevision") or ""
                )
            elif args.get("assetQuery"):
                resolution = resolve_facility_entities(
                    state,
                    query=_clean_text(args.get("assetQuery"), 120),
                    entity_kinds=["placement", "asset"],
                    maximum_results=20,
                )
                resolved = resolution.get("resolved")
                if not isinstance(resolved, Mapping):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_fit_asset_ambiguous"
                        if resolution.get("resolutionStatus") == "ambiguous"
                        else "facility_agent_fit_asset_unresolved",
                        "The asset name did not resolve uniquely in the current revision.",
                        details={"candidates": resolution.get("candidates", [])},
                    )
                if resolved.get("entityKind") == "placement":
                    source_placement = placements_by_id.get(
                        str(resolved.get("entityId") or "")
                    )
                    asset_id = str(source_placement.get("assetId") or "")
                    asset_revision = str(
                        source_placement.get("assetDefinitionRevision") or ""
                    )
                else:
                    asset_id = str(resolved.get("entityId") or "")
                    asset_revision = str(
                        resolved.get("assetDefinitionRevision") or ""
                    )
            if asset_id and not asset_revision:
                # As in inspect_facility_asset: an asset with a single revision in
                # the authorized catalog needs no revision argument. Agents left it
                # out and spent a second call on the retry.
                revisions = {
                    str(item.get("assetDefinitionRevision") or "")
                    for item in state.get("assets", [])
                    if isinstance(item, Mapping) and item.get("assetId") == asset_id
                }
                if len(revisions) == 1:
                    asset_revision = revisions.pop()
            asset_id = _stable_id(asset_id, "assetId")
            asset_revision = _revision(
                asset_revision,
                "assetDefinitionRevision",
            )

            zone_id = str(args.get("zoneId") or "").strip()
            if args.get("zoneQuery"):
                zone_resolution = resolve_facility_entities(
                    state,
                    query=_clean_text(args.get("zoneQuery"), 120),
                    entity_kinds=["zone"],
                    maximum_results=20,
                )
                resolved_zone = zone_resolution.get("resolved")
                if not isinstance(resolved_zone, Mapping):
                    raise FacilityLayoutAgentRuntimeError(
                        "facility_agent_fit_zone_ambiguous"
                        if zone_resolution.get("resolutionStatus") == "ambiguous"
                        else "facility_agent_fit_zone_unresolved",
                        "The target zone name did not resolve uniquely in the current revision.",
                        details={"candidates": zone_resolution.get("candidates", [])},
                    )
                zone_id = str(resolved_zone.get("entityId") or "")
            zone_id = _stable_id(zone_id, "zoneId")
            if zone_id not in zones_by_id:
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_fit_zone_unresolved",
                    "The target zone is not present in the current layout revision.",
                )
            orientations = args.get("orientationsDegrees")
            if orientations is not None and not isinstance(
                orientations,
                list,
            ):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_fit_arguments_invalid",
                    "orientationsDegrees must be an array.",
                )
            maximum_results = args.get("maximumResults", 8)
            if isinstance(maximum_results, bool):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_fit_arguments_invalid",
                    "maximumResults must be an integer.",
                )
            try:
                result = analyze_facility_asset_fit(
                    state,
                    bundle.asset_documents,
                    asset_id=asset_id,
                    asset_definition_revision=asset_revision,
                    zone_id=zone_id,
                    shell=bundle.shell_document,
                    policy_set=bundle.policy_document,
                    evidence_authority=bundle.evidence_authority,
                    orientations_degrees=orientations,
                    maximum_results=int(maximum_results),
                )
            except (FacilityFitAnalysisError, TypeError, ValueError) as exc:
                raise FacilityLayoutAgentRuntimeError(
                    getattr(exc, "code", "facility_agent_fit_failed"),
                    str(exc),
                ) from exc
            response = {**base_envelope, **result}
            if len(_canonical_bytes(response)) > (
                FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
            ):
                raise FacilityLayoutAgentRuntimeError(
                    "facility_agent_response_budget_exceeded",
                    "The bounded Facility fit response exceeded its limit.",
                )
            return response

        ids = (
            set(_bounded_ids(args.get("ids")))
            if "ids" in args
            else set()
        )
        process_map_id = _clean_text(args.get("processMapId"), 128)
        records = [
            item
            for item in state.get("processBindings", [])
            if isinstance(item, Mapping)
            and (
                not ids
                or str(item.get("processBindingId") or "") in ids
            )
            and (
                not process_map_id
                or str(item.get("processMapId") or "") == process_map_id
            )
        ]
        return self._page(
            records,
            offset=offset,
            page_size=page_size,
            envelope=base_envelope,
            cursor_factory=next_cursor,
        )

    def build_preview(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        expected_revision: str,
        semantic_plan: Mapping[str, Any],
        live_facts: Mapping[str, Any] | None = None,
        proposal_id: str | None = None,
        receipt_ids: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        expected_revision = _revision(expected_revision, "expectedRevision")
        source_revisions = semantic_plan.get("sourceRevisions")
        request_identity = {
            "semanticPlan": deepcopy(dict(semantic_plan)),
            "proposalId": proposal_id,
            "receiptIds": sorted(
                str(item) for item in (receipt_ids or []) if item
            ),
        }
        source_binding = {
            "siteId": site_id,
            "layoutId": layout_id,
            "layoutRevision": expected_revision,
            "semanticSourceRevisions": (
                deepcopy(dict(source_revisions))
                if isinstance(source_revisions, Mapping)
                else {}
            ),
        }
        observed_identity: dict[str, Any] = {}

        def observe() -> FacilityAgentContextBundle:
            bundle = self.resolve_context(
                principal,
                site_id=site_id,
                layout_id=layout_id,
                expected_revision=expected_revision,
                live_facts=live_facts,
                proposal_id=proposal_id,
                receipt_ids=receipt_ids,
            )
            observed_identity.update(
                deepcopy(dict(bundle.state.get("identity") or {}))
            )
            return bundle

        def build_plan(bundle: FacilityAgentContextBundle) -> dict[str, Any]:
            source_plan = deepcopy(dict(semantic_plan))
            return {
                "semanticPlan": source_plan,
                "compiled": compile_semantic_facility_plan(
                    source_plan,
                    state=bundle.state,
                    evidence=bundle.evidence,
                ),
            }

        def simulate(
            plan: Mapping[str, Any],
            bundle: FacilityAgentContextBundle,
            _attempt: int,
        ) -> dict[str, Any]:
            return self.service.create_layout_proposals(
                principal,
                str(bundle.state["identity"]["siteId"]),
                str(bundle.state["identity"]["layoutId"]),
                str(bundle.state["identity"]["revision"]),
                plan["compiled"]["plannerRequest"],
            )

        workflow = self.workflow_runtime.run_preview(
            owner_key=self._workflow_owner_key(
                principal,
                site_id,
                layout_id,
            ),
            workflow_id=FACILITY_LAYOUT_VERIFIED_WORKFLOW_ID,
            goal=self._workflow_goal(semantic_plan),
            request_identity=request_identity,
            source_binding=source_binding,
            hard_constraints=self._workflow_hard_constraints(),
            soft_objectives=self._workflow_soft_objectives(semantic_plan),
            observe=observe,
            build_plan=build_plan,
            validate_plan=self._validate_workflow_plan,
            simulate=simulate,
            validate_result=self._validate_workflow_preview,
            repair=self._repair_workflow_plan,
            classify_error=self._classify_workflow_error,
            budget=FACILITY_LAYOUT_VERIFIED_WORKFLOW_BUDGET,
        )
        trace = deepcopy(dict(workflow.trace))
        if trace.get("status") != "preview_ready":
            issues = [
                item for item in trace.get("issues", [])
                if isinstance(item, Mapping)
            ]
            issue = next(
                (
                    item for item in reversed(issues)
                    if item.get("severity") in {"error", "blocked"}
                ),
                {
                    "code": "facility_verified_workflow_blocked",
                    "message": "The verified Facility Layout workflow was blocked.",
                    "details": {},
                },
            )
            issue_details = (
                deepcopy(dict(issue.get("details") or {}))
                if isinstance(issue.get("details"), Mapping)
                else {}
            )
            status_code = int(issue_details.pop("statusCode", 422) or 422)
            raise FacilityLayoutAgentRuntimeError(
                str(issue.get("code") or "facility_verified_workflow_blocked"),
                str(issue.get("message") or "Facility Layout workflow blocked."),
                status_code=status_code,
                details={
                    **issue_details,
                    "workflowRun": trace,
                },
            )
        if not isinstance(workflow.plan, Mapping) or not isinstance(
            workflow.output, Mapping
        ):
            raise FacilityLayoutAgentRuntimeError(
                "facility_verified_workflow_result_invalid",
                "The verified workflow returned no complete preview.",
                details={"workflowRun": trace},
            )
        compiled = workflow.plan["compiled"]
        proposals = workflow.output
        return {
            "ok": True,
            "runtimeVersion": FACILITY_LAYOUT_AGENT_RUNTIME_VERSION,
            "previewOnly": True,
            "saved": False,
            "identity": deepcopy(observed_identity),
            "semanticPlan": {
                "planId": compiled["plan"]["planId"],
                "planHash": compiled["planHash"],
                "bindingHash": compiled["bindingHash"],
                "summary": deepcopy(compiled["semanticSummary"]),
                "assumptions": deepcopy(compiled["assumptions"]),
                "unresolvedItems": deepcopy(compiled["unresolvedItems"]),
                "findings": deepcopy(compiled["findings"]),
            },
            "plannerRequest": deepcopy(compiled["plannerRequest"]),
            "proposal": proposals,
            "selectedProposalId": proposals.get("selectedProposalId"),
            "canonicalReceipt": None,
            "workflowRun": trace,
            "message": (
                "Facility Layout ghost preview created. It is not saved and "
                "requires explicit approval before atomic apply."
            ),
        }

    def get_workflow_run(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        layout_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        site_id = _stable_id(site_id, "siteId")
        layout_id = _stable_id(layout_id, "layoutId")
        run_id = _stable_id(run_id, "runId")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        trace = self.workflow_runtime.get_run(
            self._workflow_owner_key(principal, site_id, layout_id),
            run_id,
        )
        if trace is None:
            raise FacilityLayoutAgentRuntimeError(
                "facility_workflow_run_not_found",
                "The verified Facility Layout workflow run was not found.",
                status_code=404,
            )
        return trace


__all__ = [
    "FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS",
    "FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN",
    "FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES",
    "FACILITY_LAYOUT_AGENT_RUNTIME_VERSION",
    "FACILITY_LAYOUT_VERIFIED_WORKFLOW_BUDGET",
    "FACILITY_LAYOUT_VERIFIED_WORKFLOW_ID",
    "FacilityAgentContextBundle",
    "FacilityLayoutAgentRuntime",
    "FacilityLayoutAgentRuntimeError",
]
