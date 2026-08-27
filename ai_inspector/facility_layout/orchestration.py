"""Intent-driven orchestration contracts for Facility Layout chat.

The language model may choose how to explain a result. This module decides
which deterministic capabilities exist for one operation, what evidence is
required, and whether any candidate state may be produced. It deliberately
contains no geometry implementation and no commit path.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Iterable, Mapping, Sequence


FACILITY_ORCHESTRATION_VERSION = "1.1.0"

_READ_TOOL_NAMES = frozenset({
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
})

_INTENT_READ_TOOLS: dict[str, frozenset[str]] = {
    "inspect": frozenset({
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "inspect_pattern_provenance",
        "inspect_cell_layout_provenance",
    }),
    "measure": frozenset({
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_semantics",
        "analyze_facility_spatial",
        "analyze_facility_fit",
    }),
    "compare": frozenset({
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "inspect_pattern_provenance",
        "inspect_cell_layout_provenance",
        "analyze_facility_spatial",
        "analyze_facility_fit",
    }),
    "recommend": frozenset({
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "analyze_facility_spatial",
        "analyze_facility_fit",
    }),
    "simulate": _READ_TOOL_NAMES,
    "exact_transform": frozenset({
        "inspect_facility_entities",
        "inspect_facility_semantics",
        "analyze_facility_spatial",
    }),
    "modify": _READ_TOOL_NAMES,
    "navigate": frozenset({
        "inspect_facility_entities",
        "inspect_facility_semantics",
    }),
    "render": frozenset({
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_semantics",
        "analyze_facility_spatial",
        "analyze_facility_fit",
    }),
}

_TOOL_CONTRACTS: dict[str, dict[str, Any]] = {
    "search_industrial_assets": {
        "mutates": False,
        "requires": ["authorized_asset_catalog"],
        "returns": ["bounded_asset_candidates", "stable_asset_ids"],
    },
    "inspect_facility_entities": {
        "mutates": False,
        "requires": ["active_layout_revision", "stable_entity_ids"],
        "returns": ["revision_bound_entity_records"],
    },
    "inspect_facility_region": {
        "mutates": False,
        "requires": ["active_layout_revision", "authored_region_id"],
        "returns": ["revision_bound_region_record"],
    },
    "inspect_facility_findings": {
        "mutates": False,
        "requires": ["active_layout_revision"],
        "returns": ["deterministic_findings"],
    },
    "inspect_process_bindings": {
        "mutates": False,
        "requires": ["active_layout_revision"],
        "returns": ["revision_bound_process_relationships"],
    },
    "inspect_facility_semantics": {
        "mutates": False,
        "requires": ["active_layout_revision"],
        "returns": ["semantic_records", "evidence_classification"],
    },
    "inspect_pattern_provenance": {
        "mutates": False,
        "requires": ["active_layout_revision"],
        "returns": ["authored_pattern_parameters", "pattern_drift"],
    },
    "inspect_cell_layout_provenance": {
        "mutates": False,
        "requires": ["active_layout_revision"],
        "returns": ["authored_cell_strategy", "current_conformance"],
    },
    "analyze_facility_spatial": {
        "mutates": False,
        "requires": ["active_layout_revision", "bounded_analysis_scope"],
        "returns": ["deterministic_spatial_observation", "evidence_status"],
    },
    "analyze_facility_fit": {
        "mutates": False,
        "requires": ["resolved_asset", "authored_target_zone"],
        "returns": ["validated_candidate_fits", "limiting_constraints"],
    },
    "present_chat_table": {
        "mutates": False,
        "requires": ["grounded_rows"],
        "returns": ["sanitized_table_block"],
    },
    "present_chat_visualization": {
        "mutates": False,
        "requires": ["requested_metric", "grounded_series"],
        "returns": ["validated_visualization_block"],
    },
    "build_facility_layout_preview": {
        "mutates": False,
        "requires": ["explicit_simulation_or_modify_intent", "semantic_plan"],
        "returns": ["validated_candidate_state", "ghost_preview"],
        "guarantees": ["saved_layout_unchanged", "approval_required"],
    },
    "generate_facility_departments_draft": {
        "mutates": True,
        "requires": [
            "explicit_generation_intent",
            "complete_facility_envelope_and_department_intent",
            "coordinate_free_facility_intent",
        ],
        "returns": [
            "resumable_generation_run",
            "validated_unsaved_draft",
            "cumulative_review_proposal",
        ],
        "guarantees": [
            "deterministic_geometry",
            "saved_layout_unchanged",
            "explicit_save_required",
        ],
    },
    "preview_facility_move": {
        "mutates": True,
        "requires": ["explicit_exact_transform", "resolved_placement"],
        "returns": ["validated_unsaved_draft", "undo_transaction"],
        "guarantees": ["rotation_preserved", "rollback_on_validation_failure"],
    },
}

_OPERATION_STEPS: dict[str, tuple[str, ...]] = {
    "inspect": ("resolve_scope", "observe_current_state", "synthesize"),
    "measure": (
        "resolve_scope",
        "collect_required_geometry",
        "compute_requested_metric",
        "verify_evidence",
        "synthesize",
    ),
    "compare": (
        "resolve_comparison_scope",
        "measure_with_shared_definitions",
        "verify_evidence",
        "synthesize",
    ),
    "recommend": (
        "understand_operational_context",
        "measure_relevant_conditions",
        "rank_recommendations",
        "synthesize_without_preview",
    ),
    "simulate": (
        "understand_current_state",
        "generate_candidate",
        "validate_candidate",
        "preview_without_commit",
    ),
    "exact_transform": (
        "resolve_target",
        "derive_exact_delta",
        "validate_candidate",
        "create_atomic_unsaved_draft",
    ),
    "modify": (
        "understand_current_state",
        "build_semantic_plan",
        "validate_candidate",
        "preview_without_commit",
    ),
    "navigate": (
        "resolve_target",
        "resolve_safe_viewpoint",
        "execute_dedicated_navigation_action",
    ),
    "render": (
        "resolve_requested_metric",
        "collect_exact_values",
        "verify_evidence",
        "render_requested_presentation",
    ),
}


def _presentation_tool(
    names: Iterable[str],
    *,
    table_requested: bool,
    chart_requested: bool,
) -> set[str]:
    allowed: set[str] = set()
    for raw in names:
        name = str(raw or "")
        if table_requested and "table" in name:
            allowed.add(name)
        if chart_requested and (
            "visualization" in name or "chart" in name
        ):
            allowed.add(name)
    return allowed


def _observation_tool(
    operation_intent: str,
    spatial_analyses: Sequence[str],
) -> str | None:
    analyses = {str(value) for value in spatial_analyses}
    if operation_intent == "navigate":
        return "inspect_facility_entities"
    if operation_intent == "exact_transform":
        return "analyze_facility_spatial"
    if "pattern_provenance" in analyses:
        return "inspect_pattern_provenance"
    if "cell_layout_provenance" in analyses:
        return "inspect_cell_layout_provenance"
    if "layout_provenance" in analyses:
        return "inspect_facility_semantics"
    if analyses:
        return "analyze_facility_spatial"
    if operation_intent in {
        "inspect",
        "measure",
        "compare",
        "recommend",
        "simulate",
        "modify",
        "render",
    }:
        return "inspect_facility_semantics"
    return None


def facility_orchestration_trace(
    plan: Mapping[str, Any],
    *,
    resolved_entity_ids: Sequence[str] = (),
    tool_calls: Sequence[Mapping[str, Any]] = (),
    evidence_completeness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact user-safe trace of one orchestration decision."""

    allowed = {
        str(value) for value in plan.get("allowedToolNames", ()) if str(value)
    }
    calls = []
    for item in tool_calls:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        calls.append({
            "name": name,
            "allowed": name in allowed,
        })
    return {
        "version": str(plan.get("version") or ""),
        "operationIntent": str(plan.get("operationIntent") or "inspect"),
        "actionMode": str(plan.get("actionMode") or "READ_ONLY"),
        "permission": str(plan.get("permission") or "read_only"),
        "resolvedEntityIds": [
            str(value) for value in resolved_entity_ids if str(value)
        ][:50],
        "steps": [str(value) for value in plan.get("steps", ())],
        "allowedToolNames": sorted(allowed),
        "toolCalls": calls,
        "evidenceCompleteness": (
            copy.deepcopy(dict(evidence_completeness))
            if isinstance(evidence_completeness, Mapping)
            else None
        ),
    }


def _evidence_requirements(
    operation_intent: str,
    *,
    requested_metric: str | None,
    required_observation_tool: str | None,
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = [{
        "id": "revision_bound_context",
        "satisfiedBy": "trusted_facility_context",
    }]
    if required_observation_tool:
        requirements.append({
            "id": (
                "requested_metric_evidence"
                if requested_metric
                else "operation_evidence"
            ),
            "satisfiedByAnyTool": [required_observation_tool],
            "metricId": requested_metric,
        })
    if operation_intent in {"simulate", "modify", "exact_transform"}:
        requirements.append({
            "id": "candidate_validation",
            "satisfiedBy": "candidate_runtime_validation",
        })
    return requirements


def build_facility_orchestration_plan(
    *,
    operation_intent: str,
    action_mode: str,
    available_read_tools: Iterable[str],
    presentation_tools: Iterable[str],
    preview_tool_name: str,
    move_tool_name: str,
    requested_metric: str | None = None,
    spatial_analyses: Sequence[str] = (),
    table_requested: bool = False,
    chart_requested: bool = False,
    pending_operation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the closed tool policy and operational plan for one turn."""

    operation = str(operation_intent or "inspect")
    if operation not in _INTENT_READ_TOOLS:
        operation = "inspect"
    available = {
        str(name) for name in available_read_tools if str(name)
    }
    allowed = set(_INTENT_READ_TOOLS[operation] & available)
    allowed.update(_presentation_tool(
        presentation_tools,
        table_requested=table_requested,
        chart_requested=chart_requested,
    ))

    permission = "read_only"
    if action_mode == "COMMIT":
        # Chat has no commit capability. Approval is handled by the existing
        # authoritative proposal transaction surface, never by model tools.
        allowed.clear()
        permission = "commit_request"
    elif operation == "exact_transform" and action_mode == "PREVIEW":
        allowed.add(move_tool_name)
        permission = "draft_write"
    elif operation in {"simulate", "modify"} and action_mode == "PREVIEW":
        allowed.add(preview_tool_name)
        permission = "simulate"
    elif operation == "navigate":
        # A dedicated Facility navigation tool is not registered yet. Generic
        # CAD/viewport actions remain unavailable to avoid action confusion.
        permission = "navigation_readiness"

    required_observation = _observation_tool(operation, spatial_analyses)
    if required_observation not in allowed:
        required_observation = None
    requirements = _evidence_requirements(
        operation,
        requested_metric=requested_metric,
        required_observation_tool=required_observation,
    )
    contracts = {
        name: copy.deepcopy(_TOOL_CONTRACTS.get(name, {
            "mutates": False,
            "requires": [],
            "returns": [],
        }))
        for name in sorted(allowed)
    }
    return {
        "version": FACILITY_ORCHESTRATION_VERSION,
        "operationIntent": operation,
        "actionMode": action_mode,
        "permission": permission,
        "steps": list(_OPERATION_STEPS[operation]),
        "allowedToolNames": frozenset(allowed),
        "requiredObservationTool": required_observation,
        "requiredEvidence": requirements,
        "toolContracts": contracts,
        "pendingOperation": (
            copy.deepcopy(dict(pending_operation))
            if isinstance(pending_operation, Mapping)
            else None
        ),
        "chatCommitToolAvailable": False,
        "viewportNavigationAuthorized": False,
    }


class FacilityPendingOperationStore:
    """Small server-authoritative TTL store for Facility follow-ups."""

    _SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 512,
        clock: Any = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_sessions < 1:
            raise ValueError("pending-operation limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, tuple[dict[str, Any], float]] = (
            OrderedDict()
        )

    @classmethod
    def _session(cls, value: Any) -> str:
        token = str(value or "").strip()
        return token if cls._SESSION.fullmatch(token) else ""

    def put(self, session_id: Any, operation: Mapping[str, Any]) -> bool:
        session = self._session(session_id)
        if not session or not isinstance(operation, Mapping):
            return False
        goal = " ".join(str(operation.get("goal") or "").split())[:800]
        intent = str(operation.get("operationIntent") or "inspect")
        awaiting = str(operation.get("awaiting") or "clarification")
        if not goal or intent not in _INTENT_READ_TOOLS:
            return False
        record = {
            "goal": goal,
            "operationIntent": intent,
            "actionMode": "READ_ONLY",
            "referencedEntityIds": [
                str(value)[:128]
                for value in operation.get("referencedEntityIds", [])
                if str(value)
            ][:50],
            "requiredEvidence": copy.deepcopy(
                list(operation.get("requiredEvidence") or [])[:12]
            ),
            "awaiting": awaiting,
        }
        with self._lock:
            self._entries[session] = (
                record,
                self._clock() + self.ttl_seconds,
            )
            self._entries.move_to_end(session)
            while len(self._entries) > self.max_sessions:
                self._entries.popitem(last=False)
        return True

    def get(self, session_id: Any) -> dict[str, Any] | None:
        session = self._session(session_id)
        if not session:
            return None
        with self._lock:
            entry = self._entries.get(session)
            if entry is None:
                return None
            record, expires = entry
            if expires <= self._clock():
                self._entries.pop(session, None)
                return None
            self._entries.move_to_end(session)
            return copy.deepcopy(record)

    def clear(self, session_id: Any) -> None:
        session = self._session(session_id)
        if not session:
            return
        with self._lock:
            self._entries.pop(session, None)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            expired = [
                key for key, (_record, expiry) in self._entries.items()
                if expiry <= now
            ]
            for key in expired:
                self._entries.pop(key, None)
            return {
                "entries": len(self._entries),
                "ttlSeconds": self.ttl_seconds,
                "maxSessions": self.max_sessions,
            }


__all__ = [
    "FACILITY_ORCHESTRATION_VERSION",
    "FacilityPendingOperationStore",
    "build_facility_orchestration_plan",
    "facility_orchestration_trace",
]
