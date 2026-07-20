"""Bounded multi-turn workflow state for the Phase 5 skill runtime."""

from __future__ import annotations

import copy
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence


WORKFLOW_STATE_VERSION = 1
WORKFLOW_STATE_STATUSES = frozenset({"active", "completed"})
_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:[a-z0-9_.-]*[a-z0-9])?$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_EFFECT_RECEIPT_TOOLS = {
    "highlight_parts": frozenset({"set_part_highlight"}),
    "play_motion": frozenset({"play_motion"}),
    "pause_motion": frozenset({"pause_motion"}),
    "stop_motion": frozenset({"stop_motion"}),
    "set_motion_rpm": frozenset({"set_motion_rpm"}),
    "hide_parts": frozenset({"set_part_display"}),
    "show_parts": frozenset({"set_part_display", "clear_part_display"}),
    "set_transparency": frozenset({"set_part_display"}),
    "rotate_view": frozenset({"rotate_view", "stop_rotate_view"}),
    "clear_highlight": frozenset({"clear_part_highlight"}),
    "navigate_tab": frozenset({"open_workspace"}),
}
_STAGE_BY_INTENT = {
    "assess_fai_characteristic": "evaluate_result",
    "explain_assembly_impact": "trace_assembly_impact",
    "explain_motion": "trace_assembly_impact",
    "visualize_affected_context": "visualize_affected_context",
    "recommend_disposition": "recommend_disposition",
    "analyze_process_map": "analyze_flow",
}
_OBJECTIVE_BY_WORKFLOW = {
    "supplier-fai-disposition": "Evaluate supplier FAI disposition",
    "process-map-analysis": "Analyze the saved process map",
}


def _unique_affected_motion_group(context_facts: Mapping[str, Any]) -> dict[str, Any] | None:
    tagged: list[dict[str, Any]] = []
    for motion in context_facts.get("motions") or []:
        if not isinstance(motion, Mapping):
            continue
        for group in motion.get("groups") or []:
            if not isinstance(group, Mapping) or not group.get("id"):
                continue
            marker = " ".join(str(group.get(key) or "") for key in ("id", "label", "function"))
            if re.search(r"\b(affected|fai|deviation|discrepant|out of tolerance)\b", marker, re.I):
                tagged.append({
                    "kind": "motion_group",
                    "id": str(group["id"]),
                    "label": _clean_text(group.get("label") or group["id"], 160),
                })
    return tagged[0] if len(tagged) == 1 else None


def resolve_route_referents(
    route: Mapping[str, Any] | None,
    *,
    workflow_state: Mapping[str, Any] | None,
    context_facts: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve omitted continuation targets against validated live IDs.

    This never adds an effect and never authorizes a write. It only supplies
    a target for an effect the semantic router already requested.
    """
    if not route:
        return None
    resolved = copy.deepcopy(dict(route))
    if not resolved.get("continue_existing_workflow") or not workflow_state:
        return resolved
    target_index = context_facts.get("target_index")
    target_index = target_index if isinstance(target_index, Mapping) else {}
    known_groups = {str(value) for value in (target_index.get("motion_group") or [])}
    known_parts = {str(value) for value in (target_index.get("part") or [])}
    referents = workflow_state.get("referents")
    referents = referents if isinstance(referents, Mapping) else {}
    prior_intents = {str(value) for value in (referents.get("last_intent_kinds") or [])}

    def one_valid(key: str, known: set[str]) -> str | None:
        values = [str(value) for value in (referents.get(key) or []) if str(value) in known]
        values = list(dict.fromkeys(values))
        return values[0] if len(values) == 1 else None

    group_id = one_valid("last_motion_group_ids", known_groups)
    part_id = one_valid("last_part_numbers", known_parts)
    for intent in resolved.get("intents") or []:
        if not isinstance(intent, dict):
            continue
        targets = intent.get("targets") if isinstance(intent.get("targets"), list) else []
        effects = {str(value) for value in (intent.get("requested_effects") or [])}
        kinds = {target.get("kind") for target in targets if isinstance(target, Mapping)}
        continuing_motion_visual = (
            intent.get("kind") == "visualize_affected_context"
            and "explain_motion" in prior_intents
            and bool(effects.intersection({"highlight_parts", "highlight_features", "play_motion"}))
        )
        if (
            group_id
            and "motion_group" not in kinds
            and ("play_motion" in effects or continuing_motion_visual)
        ):
            targets.append({"kind": "motion_group", "id": group_id, "label": group_id})
        if (
            part_id
            and "part" not in kinds
            and effects.intersection({"hide_parts", "show_parts", "highlight_parts"})
            and "play_motion" not in effects
        ):
            targets.append({"kind": "part", "id": part_id, "label": part_id})
        intent["targets"] = targets[:6]
    return resolved


def _utc_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clean_token(value: Any, limit: int = 120) -> str:
    token = _clean_text(value, limit)
    return token if token and _TOKEN_RE.fullmatch(token) else ""


def _clean_string_list(value: Any, *, limit: int = 20, item_limit: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value[:limit]:
        token = _clean_text(item, item_limit)
        if token and token not in cleaned:
            cleaned.append(token)
    return cleaned


def _clean_entities(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:20]:
        key = _clean_token(raw_key, 80)
        if not key:
            continue
        if isinstance(raw_value, list):
            items = _clean_string_list(raw_value, limit=20, item_limit=120)
            if items:
                cleaned[key] = items
        elif isinstance(raw_value, (str, int, float)) and not isinstance(raw_value, bool):
            item = _clean_text(raw_value, 120)
            if item:
                cleaned[key] = item
    return cleaned


def _clean_targets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for raw in value[:6]:
        if not isinstance(raw, dict):
            continue
        kind = _clean_token(raw.get("kind"), 40)
        target_id = _clean_text(raw.get("id"), 160)
        label = _clean_text(raw.get("label"), 160)
        if kind:
            cleaned.append({"kind": kind, "id": target_id or None, "label": label})
    return cleaned


def _clean_referents(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    targets = _clean_targets(value.get("last_targets"))
    if targets:
        result["last_targets"] = targets
    for key in (
        "last_characteristic_numbers",
        "last_part_numbers",
        "last_feature_ids",
        "last_motion_group_ids",
        "last_process_map_ids",
        "last_process_node_ids",
        "last_intent_kinds",
        "last_requested_effects",
    ):
        items = _clean_string_list(value.get(key), limit=12, item_limit=120)
        if items:
            result[key] = items
    return result


def _clean_milestones(value: Any) -> dict[str, bool]:
    raw = value if isinstance(value, dict) else {}
    return {
        "failed_characteristic_identified": bool(raw.get("failed_characteristic_identified")),
        "disposition_grounded": bool(raw.get("disposition_grounded")),
        "visualization_requested": bool(raw.get("visualization_requested")),
        "visualization_succeeded": bool(raw.get("visualization_succeeded")),
    }


def compact_execution_receipts(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value[-max(1, min(limit, 12)):]:
        if not isinstance(raw, dict):
            continue
        receipt_id = _clean_text(raw.get("receipt_id"), 120)
        tool_id = _clean_token(raw.get("tool_id"), 80)
        status = _clean_token(raw.get("status"), 20)
        if not receipt_id or not tool_id or status not in {"succeeded", "failed", "rejected"}:
            continue
        if receipt_id in seen:
            continue
        row = {"receipt_id": receipt_id, "tool_id": tool_id, "status": status}
        action_id = _clean_text(raw.get("action_id"), 80)
        if action_id:
            row["action_id"] = action_id
        evidence = _clean_string_list(raw.get("evidence"), limit=8, item_limit=160)
        if evidence:
            row["evidence"] = evidence
        cleaned.append(row)
        seen.add(receipt_id)
    return cleaned


def sanitize_workflow_state(
    value: Any,
    *,
    expected_asset_fingerprint: str | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any] | None:
    """Validate a browser mirror before it is allowed back into server state."""
    if not isinstance(value, dict) or value.get("state_version") != WORKFLOW_STATE_VERSION:
        return None
    workflow_id = _clean_token(value.get("workflow_id"), 80)
    version = _clean_text(value.get("version"), 30)
    stage = _clean_token(value.get("stage"), 80)
    status = _clean_token(value.get("status"), 20)
    asset_fingerprint = _clean_text(value.get("asset_fingerprint"), 100)
    if (
        not workflow_id
        or not _SEMVER_RE.fullmatch(version)
        or not stage
        or status not in WORKFLOW_STATE_STATUSES
        or not asset_fingerprint
    ):
        return None
    if expected_asset_fingerprint and asset_fingerprint != expected_asset_fingerprint:
        return None
    expires_at = _clean_text(value.get("expires_at"), 40)
    if expires_at and now_epoch is not None:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        if expiry <= now_epoch:
            return None
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        revision = 1
    return {
        "state_version": WORKFLOW_STATE_VERSION,
        "workflow_id": workflow_id,
        "version": version,
        "status": status,
        "stage": stage,
        "objective": _clean_text(value.get("objective"), 180),
        "entities": _clean_entities(value.get("entities")),
        "evidence_refs": _clean_string_list(value.get("evidence_refs"), limit=30, item_limit=180),
        "referents": _clean_referents(value.get("referents")),
        "milestones": _clean_milestones(value.get("milestones")),
        "last_execution_receipts": compact_execution_receipts(
            value.get("last_execution_receipts"), limit=8
        ),
        "pending_clarification": _clean_text(value.get("pending_clarification"), 240) or None,
        "asset_fingerprint": asset_fingerprint,
        "revision": revision,
        "created_at": _clean_text(value.get("created_at"), 40),
        "updated_at": _clean_text(value.get("updated_at"), 40),
        "expires_at": expires_at,
    }


def _merge_unique(existing: Sequence[str], additions: Sequence[str], *, limit: int = 30) -> list[str]:
    values: list[str] = []
    for item in [*existing, *additions]:
        token = _clean_text(item, 180)
        if token and token not in values:
            values.append(token)
    return values[-limit:]


def _merge_receipts(state: dict[str, Any], receipts: Sequence[Mapping[str, Any]]) -> bool:
    incoming = compact_execution_receipts(list(receipts), limit=8)
    if not incoming:
        return False
    existing = compact_execution_receipts(state.get("last_execution_receipts"), limit=8)
    by_id = {item["receipt_id"]: item for item in existing}
    changed = False
    for item in incoming:
        if by_id.get(item["receipt_id"]) != item:
            changed = True
        by_id[item["receipt_id"]] = item
    if not changed:
        return False
    state["last_execution_receipts"] = list(by_id.values())[-8:]
    milestones = _clean_milestones(state.get("milestones"))
    required_effects = [
        effect
        for effect in ((state.get("referents") or {}).get("last_requested_effects") or [])
        if effect in _EFFECT_RECEIPT_TOOLS
    ]
    succeeded_tools = {
        item["tool_id"]
        for item in state["last_execution_receipts"]
        if item["status"] == "succeeded"
    }
    if milestones["visualization_requested"] and required_effects:
        milestones["visualization_succeeded"] = all(
            succeeded_tools.intersection(_EFFECT_RECEIPT_TOOLS[effect])
            for effect in required_effects
        )
    state["milestones"] = milestones
    _apply_completion(state)
    return True


def _apply_completion(state: dict[str, Any]) -> None:
    milestones = _clean_milestones(state.get("milestones"))
    visualization_ok = (
        not milestones["visualization_requested"]
        or milestones["visualization_succeeded"]
    )
    complete = (
        milestones["failed_characteristic_identified"]
        and milestones["disposition_grounded"]
        and visualization_ok
        and not state.get("pending_clarification")
    )
    state["status"] = "completed" if complete else "active"


def _route_targets(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for intent in (route.get("intents") or [])[:4]:
        if not isinstance(intent, Mapping):
            continue
        targets.extend(_clean_targets(intent.get("targets")))
    return targets[:12]


def _route_intent_kinds(route: Mapping[str, Any]) -> list[str]:
    return _clean_string_list(
        [item.get("kind") for item in (route.get("intents") or []) if isinstance(item, Mapping)],
        limit=8,
        item_limit=80,
    )


def _route_effects(route: Mapping[str, Any]) -> list[str]:
    effects: list[str] = []
    for intent in (route.get("intents") or [])[:4]:
        if isinstance(intent, Mapping):
            effects = _merge_unique(effects, intent.get("requested_effects") or [], limit=20)
    return effects


def advance_workflow_state(
    prior: Mapping[str, Any] | None,
    *,
    route: Mapping[str, Any],
    context_facts: Mapping[str, Any],
    asset_fingerprint: str,
    workflow_version: str,
    workflow_stages: Sequence[str],
    now_epoch: float,
    ttl_seconds: float,
) -> dict[str, Any] | None:
    """Pure route-to-state transition used by both production and tests."""
    workflow_id = _clean_token(route.get("primary_workflow"), 80)
    if not workflow_id:
        return copy.deepcopy(dict(prior)) if prior else None
    now_iso = _utc_iso(now_epoch)
    prior_state = sanitize_workflow_state(
        dict(prior) if prior else None,
        expected_asset_fingerprint=asset_fingerprint,
        now_epoch=now_epoch,
    )
    if prior_state and prior_state.get("workflow_id") != workflow_id:
        prior_state = None
    if prior_state and route.get("continue_existing_workflow") is False:
        prior_state = None
    state = prior_state or {
        "state_version": WORKFLOW_STATE_VERSION,
        "workflow_id": workflow_id,
        "version": workflow_version,
        "status": "active",
        "stage": workflow_stages[0] if workflow_stages else "identify_characteristic",
        "objective": _OBJECTIVE_BY_WORKFLOW.get(workflow_id, "Complete the selected workflow"),
        "entities": {},
        "evidence_refs": [],
        "referents": {},
        "milestones": _clean_milestones({}),
        "last_execution_receipts": [],
        "pending_clarification": None,
        "asset_fingerprint": asset_fingerprint,
        "revision": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "expires_at": _utc_iso(now_epoch + ttl_seconds),
    }
    state["version"] = workflow_version
    state["asset_fingerprint"] = asset_fingerprint
    state["updated_at"] = now_iso
    state["expires_at"] = _utc_iso(now_epoch + ttl_seconds)
    state["revision"] = int(state.get("revision") or 0) + 1

    targets = _route_targets(route)
    intent_kinds = _route_intent_kinds(route)
    effects = _route_effects(route)
    if "explain_motion" in intent_kinds and not any(
        target.get("kind") == "motion_group" for target in targets
    ):
        affected_group = _unique_affected_motion_group(context_facts)
        if affected_group:
            targets.append(affected_group)
    current_stage = state.get("stage")
    stage_candidates = [_STAGE_BY_INTENT[kind] for kind in intent_kinds if kind in _STAGE_BY_INTENT]
    if stage_candidates and workflow_stages:
        stage_index = {stage: index for index, stage in enumerate(workflow_stages)}
        selected = max(stage_candidates, key=lambda item: stage_index.get(item, -1))
        if stage_index.get(selected, -1) >= stage_index.get(current_stage, -1):
            state["stage"] = selected

    entities = _clean_entities(state.get("entities"))
    part = context_facts.get("part") if isinstance(context_facts.get("part"), Mapping) else {}
    part_number = _clean_text(part.get("part_number"), 120)
    if part_number:
        entities["part_number"] = part_number
    assembly_number = _clean_text(context_facts.get("assembly_number"), 120)
    if assembly_number:
        entities["assembly_number"] = assembly_number
    process_map = (
        context_facts.get("process_map")
        if isinstance(context_facts.get("process_map"), Mapping)
        else {}
    )
    process_map_id = _clean_text(process_map.get("map_id"), 120)
    if process_map_id:
        entities["process_map_id"] = process_map_id
    kind_to_entity = {
        "fai_characteristic": "characteristic_numbers",
        "part": "part_numbers",
        "feature": "feature_ids",
        "motion_group": "motion_group_ids",
        "assembly": "assembly_ids",
        "process_map": "process_map_ids",
        "process_node": "process_node_ids",
    }
    for kind, entity_key in kind_to_entity.items():
        additions = [str(item["id"]) for item in targets if item.get("kind") == kind and item.get("id")]
        existing = entities.get(entity_key) if isinstance(entities.get(entity_key), list) else []
        merged = _merge_unique(existing, additions, limit=20)
        if merged:
            entities[entity_key] = merged
    if not entities.get("characteristic_numbers"):
        fai = context_facts.get("fai") if isinstance(context_facts.get("fai"), Mapping) else {}
        failed = [
            str(row.get("id"))
            for row in (fai.get("rows") or [])
            if isinstance(row, Mapping) and row.get("id") and row.get("status") in {"fail", "failed", "reject"}
        ]
        if failed:
            entities["characteristic_numbers"] = _merge_unique([], failed, limit=20)
    state["entities"] = entities

    evidence = list(state.get("evidence_refs") or [])
    for number in entities.get("characteristic_numbers", []):
        evidence.append(f"fai:{part_number or 'current'}:{number}")
    for feature_id in entities.get("feature_ids", []):
        evidence.append(f"feature:{part_number or 'current'}:{feature_id}")
    for group_id in entities.get("motion_group_ids", []):
        evidence.append(f"motion-group:{group_id}")
    if process_map_id:
        evidence.append(f"process-map:{process_map_id}")
    state["evidence_refs"] = _merge_unique([], evidence, limit=30)

    referents = _clean_referents(state.get("referents"))
    if targets:
        referents["last_targets"] = targets[-6:]
    for entity_key, referent_key in (
        ("characteristic_numbers", "last_characteristic_numbers"),
        ("part_numbers", "last_part_numbers"),
        ("feature_ids", "last_feature_ids"),
        ("motion_group_ids", "last_motion_group_ids"),
        ("process_map_ids", "last_process_map_ids"),
        ("process_node_ids", "last_process_node_ids"),
    ):
        values = entities.get(entity_key)
        if isinstance(values, list) and values:
            referents[referent_key] = values[-12:]
    if intent_kinds:
        referents["last_intent_kinds"] = intent_kinds
    if effects:
        referents["last_requested_effects"] = effects
    state["referents"] = referents

    characteristics = entities.get("characteristic_numbers") or []
    fai = context_facts.get("fai") if isinstance(context_facts.get("fai"), Mapping) else {}
    failed_characteristics = {
        str(row.get("id"))
        for row in (fai.get("rows") or [])
        if isinstance(row, Mapping)
        and row.get("id") is not None
        and str(row.get("status") or "").lower()
            in {"fail", "failed", "reject", "rejected", "out_of_tolerance"}
    }
    selected_failures = [value for value in characteristics if value in failed_characteristics]
    if selected_failures:
        state["objective"] = "Disposition failed characteristic " + ", ".join(selected_failures[:4])
    elif characteristics:
        state["objective"] = "Evaluate characteristic " + ", ".join(characteristics[:4])
    state["pending_clarification"] = (
        _clean_text(route.get("clarification_question"), 240)
        if route.get("needs_clarification")
        else None
    )
    milestones = _clean_milestones(state.get("milestones"))
    if fai.get("rows"):
        milestones["failed_characteristic_identified"] = bool(selected_failures)
    if "recommend_disposition" in intent_kinds:
        milestones["disposition_grounded"] = True
    if any(
        effect in _EFFECT_RECEIPT_TOOLS or effect == "highlight_features"
        for effect in effects
    ):
        milestones["visualization_requested"] = True
        milestones["visualization_succeeded"] = False
    state["milestones"] = milestones
    _apply_completion(state)
    return state


@dataclass(frozen=True)
class WorkflowStateResult:
    state: dict[str, Any] | None
    event: str


@dataclass
class _Entry:
    state: dict[str, Any]
    expires_monotonic: float


class WorkflowStateStore:
    """Thread-safe TTL/LRU store. It never stores or mutates viewport state."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 512,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        if ttl_seconds <= 0 or max_sessions < 1:
            raise ValueError("workflow-state limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._events = {"started": 0, "resumed": 0, "restored": 0, "expired": 0,
                        "invalidated": 0, "abandoned": 0, "completed": 0, "evicted": 0}

    @staticmethod
    def valid_session_id(session_id: Any) -> str:
        token = str(session_id or "").strip()
        return token if _SESSION_RE.fullmatch(token) else ""

    def _touch(self, session_id: str, state: dict[str, Any]) -> None:
        now_mono = self._clock()
        now_epoch = self._wall_clock()
        state["updated_at"] = _utc_iso(now_epoch)
        state["expires_at"] = _utc_iso(now_epoch + self.ttl_seconds)
        self._entries[session_id] = _Entry(copy.deepcopy(state), now_mono + self.ttl_seconds)
        self._entries.move_to_end(session_id)
        while len(self._entries) > self.max_sessions:
            self._entries.popitem(last=False)
            self._events["evicted"] += 1

    def reconcile(
        self,
        session_id: Any,
        *,
        asset_fingerprint: str | None,
        client_state: Any = None,
        receipts: Sequence[Mapping[str, Any]] = (),
    ) -> WorkflowStateResult:
        session_id = self.valid_session_id(session_id)
        asset_fingerprint = _clean_text(asset_fingerprint, 100)
        if not session_id:
            return WorkflowStateResult(None, "invalid_session")
        if not asset_fingerprint:
            return WorkflowStateResult(None, "asset_context_unavailable")
        now_mono = self._clock()
        now_epoch = self._wall_clock()
        with self._lock:
            entry = self._entries.get(session_id)
            prior_event = "empty"
            if entry and entry.expires_monotonic <= now_mono:
                del self._entries[session_id]
                entry = None
                prior_event = "expired"
                self._events["expired"] += 1
            if entry and entry.state.get("asset_fingerprint") != asset_fingerprint:
                del self._entries[session_id]
                entry = None
                prior_event = "invalidated_asset_change"
                self._events["invalidated"] += 1
            if entry:
                state = copy.deepcopy(entry.state)
                changed = _merge_receipts(state, receipts)
                self._touch(session_id, state)
                self._events["resumed"] += 1
                if state.get("status") == "completed":
                    self._events["completed"] += int(changed)
                return WorkflowStateResult(copy.deepcopy(state), "receipts_reconciled" if changed else "resumed")
            if prior_event in {"expired", "invalidated_asset_change"}:
                return WorkflowStateResult(None, prior_event)
            mirror = sanitize_workflow_state(
                client_state,
                expected_asset_fingerprint=asset_fingerprint,
                now_epoch=now_epoch,
            )
            if mirror:
                _merge_receipts(mirror, receipts)
                self._touch(session_id, mirror)
                self._events["restored"] += 1
                return WorkflowStateResult(copy.deepcopy(mirror), "restored_client_mirror")
            return WorkflowStateResult(None, prior_event)

    def advance(
        self,
        session_id: Any,
        *,
        asset_fingerprint: str,
        route: Mapping[str, Any],
        context_facts: Mapping[str, Any],
        workflow_version: str,
        workflow_stages: Sequence[str],
    ) -> WorkflowStateResult:
        session_id = self.valid_session_id(session_id)
        if not session_id or not asset_fingerprint:
            return WorkflowStateResult(None, "invalid_session")
        with self._lock:
            entry = self._entries.get(session_id)
            prior = entry.state if entry and entry.expires_monotonic > self._clock() else None
            restarting = bool(prior and route.get("continue_existing_workflow") is False)
            state = advance_workflow_state(
                prior,
                route=route,
                context_facts=context_facts,
                asset_fingerprint=asset_fingerprint,
                workflow_version=workflow_version,
                workflow_stages=workflow_stages,
                now_epoch=self._wall_clock(),
                ttl_seconds=self.ttl_seconds,
            )
            if state is None:
                return WorkflowStateResult(copy.deepcopy(prior) if prior else None, "unchanged")
            event = "restarted" if restarting else ("started" if prior is None else "continued")
            if prior and not restarting and prior.get("stage") != state.get("stage"):
                event = "advanced"
            if state.get("status") == "completed" and (not prior or prior.get("status") != "completed"):
                event = "completed"
                self._events["completed"] += 1
            if prior is None or restarting:
                self._events["started"] += 1
            self._touch(session_id, state)
            return WorkflowStateResult(copy.deepcopy(state), event)

    def abandon(self, session_id: Any, *, reason: str = "user_requested") -> WorkflowStateResult:
        session_id = self.valid_session_id(session_id)
        if not session_id:
            return WorkflowStateResult(None, "invalid_session")
        with self._lock:
            existed = self._entries.pop(session_id, None) is not None
            if existed:
                self._events["abandoned"] += 1
            return WorkflowStateResult(None, "abandoned:" + _clean_token(reason, 40))

    def get(self, session_id: Any) -> dict[str, Any] | None:
        session_id = self.valid_session_id(session_id)
        if not session_id:
            return None
        with self._lock:
            entry = self._entries.get(session_id)
            if not entry or entry.expires_monotonic <= self._clock():
                return None
            return copy.deepcopy(entry.state)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()
            for key in self._events:
                self._events[key] = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "ttl_seconds": self.ttl_seconds,
                "max_sessions": self.max_sessions,
                "events": dict(self._events),
            }
