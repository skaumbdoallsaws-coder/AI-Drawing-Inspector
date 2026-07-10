"""Registered, data-driven executor recipes for the Phase 3 FAI slice."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_RPM_RE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*rpm\b")
_ADD_RE = re.compile(r"(?i)\b(also|add|include|plus|as well|keep)\b")
_SLOW_RE = re.compile(r"(?i)\b(slow|slowly|detail|carefully)\b")


@dataclass(frozen=True)
class ExecutorPlan:
    executor_id: str
    target_ids: tuple[str, ...]
    requested_effects: tuple[str, ...]
    tool_calls: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "executor": self.executor_id,
            "target_ids": list(self.target_ids),
            "requested_effects": list(self.requested_effects),
            "tool_calls": copy.deepcopy(list(self.tool_calls)),
        }


EXECUTOR_RECIPES: dict[str, dict[str, Any]] = {
    "show-resolved-motion-group": {
        "effects": ("highlight_parts", "play_motion"),
        "preserves": ("viewport.hidden_parts", "viewport.rotation"),
    },
    "highlight-resolved-motion-group": {
        "effects": ("highlight_parts",),
        "preserves": ("viewport.motion", "viewport.hidden_parts", "viewport.rotation"),
    },
    "highlight-resolved-parts": {
        "effects": ("highlight_parts",),
        "preserves": ("viewport.motion", "viewport.hidden_parts", "viewport.rotation"),
    },
    "highlight-resolved-features": {
        "effects": ("highlight_features",),
        "preserves": ("viewport.motion", "viewport.hidden_parts", "viewport.rotation"),
    },
}


def _intent_effects(route: Mapping[str, Any]) -> set[str]:
    effects: set[str] = set()
    for intent in route.get("intents") or []:
        if isinstance(intent, Mapping):
            effects.update(str(value) for value in (intent.get("requested_effects") or []))
    return effects


def _target_ids(route: Mapping[str, Any], kind: str) -> list[str]:
    values: list[str] = []
    for intent in route.get("intents") or []:
        if not isinstance(intent, Mapping):
            continue
        for target in intent.get("targets") or []:
            if not isinstance(target, Mapping) or target.get("kind") != kind or target.get("id") is None:
                continue
            value = str(target["id"]).strip()
            if value and value not in values:
                values.append(value)
    return values


def _motion_groups(context_facts: Mapping[str, Any]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    groups: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for motion in context_facts.get("motions") or []:
        if not isinstance(motion, dict):
            continue
        for group in motion.get("groups") or []:
            if not isinstance(group, dict) or not group.get("id"):
                continue
            groups[str(group["id"])] = (motion, group)
    return groups


def _clamp_rpm(message: str, motion: Mapping[str, Any]) -> float:
    raw_range = motion.get("rpm_range")
    if isinstance(raw_range, Sequence) and not isinstance(raw_range, (str, bytes)) and len(raw_range) >= 2:
        try:
            low, high = sorted((float(raw_range[0]), float(raw_range[1])))
        except (TypeError, ValueError):
            low, high = 10.0, 600.0
    else:
        low, high = 10.0, 600.0
    explicit = _RPM_RE.search(message or "")
    if explicit:
        requested = float(explicit.group(1))
    elif _SLOW_RE.search(message or ""):
        requested = 30.0
    else:
        requested = 30.0
    return max(low, min(high, requested))


def plan_registered_executor(
    route: Mapping[str, Any] | None,
    *,
    context_facts: Mapping[str, Any],
    message: str,
    viewport_authorized: bool,
) -> ExecutorPlan | None:
    """Resolve a validated route into one registered recipe without side effects."""
    if not route or route.get("primary_workflow") != "supplier-fai-disposition":
        return None
    if route.get("needs_clarification") or not viewport_authorized:
        return None
    requested = route.get("requested_side_effects") or {}
    if not requested.get("viewport_write"):
        return None

    effects = _intent_effects(route)
    groups = _motion_groups(context_facts)
    motion_group_ids = _target_ids(route, "motion_group")
    if len(motion_group_ids) == 1 and motion_group_ids[0] in groups:
        group_id = motion_group_ids[0]
        motion, group = groups[group_id]
        part_numbers = tuple(dict.fromkeys(str(value) for value in (group.get("part_numbers") or []) if str(value)))
        highlight_mode = "add" if _ADD_RE.search(message or "") else "replace"
        if "play_motion" in effects:
            motion_id = str(motion.get("motion_id") or "").strip()
            if not motion_id or not part_numbers:
                return None
            rpm = _clamp_rpm(message, motion)
            actions = (
                {"type": "set_part_highlight", "part_numbers": list(part_numbers), "mode": highlight_mode},
                {"type": "play_motion", "motion_id": motion_id, "rpm": rpm, "loop": True},
            )
            return ExecutorPlan(
                executor_id="show-resolved-motion-group",
                target_ids=(group_id,),
                requested_effects=("highlight_parts", "play_motion"),
                tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": list(actions)}},),
            )
        if "highlight_parts" in effects and part_numbers:
            action = {"type": "set_part_highlight", "part_numbers": list(part_numbers), "mode": highlight_mode}
            return ExecutorPlan(
                executor_id="highlight-resolved-motion-group",
                target_ids=(group_id,),
                requested_effects=("highlight_parts",),
                tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": [action]}},),
            )

    part_ids = _target_ids(route, "part")
    if "highlight_parts" in effects and part_ids:
        action = {
            "type": "set_part_highlight",
            "part_numbers": part_ids,
            "mode": "add" if _ADD_RE.search(message or "") else "replace",
        }
        return ExecutorPlan(
            executor_id="highlight-resolved-parts",
            target_ids=tuple(part_ids),
            requested_effects=("highlight_parts",),
            tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": [action]}},),
        )

    feature_ids = _target_ids(route, "feature")
    if "highlight_features" in effects and feature_ids:
        return ExecutorPlan(
            executor_id="highlight-resolved-features",
            target_ids=tuple(feature_ids),
            requested_effects=("highlight_features",),
            tool_calls=({"name": "highlight_features", "args": {"feature_ids": feature_ids}},),
        )
    return None


def merge_executor_tool_calls(
    existing_calls: Sequence[Mapping[str, Any]],
    plan: ExecutorPlan,
) -> list[dict[str, Any]]:
    """Let a validated executor own only the action types it resolves."""
    executor_calls = copy.deepcopy(list(plan.tool_calls))
    managed_action_types = {
        str(action.get("type"))
        for call in executor_calls
        if call.get("name") == "ui_actions"
        for action in ((call.get("args") or {}).get("actions") or [])
        if isinstance(action, dict) and action.get("type")
    }
    manages_features = any(call.get("name") == "highlight_features" for call in executor_calls)
    merged: list[dict[str, Any]] = []
    for original in existing_calls:
        call = copy.deepcopy(dict(original))
        if manages_features and call.get("name") == "highlight_features":
            continue
        if call.get("name") == "ui_actions" and managed_action_types:
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            actions = [
                action
                for action in (args.get("actions") or [])
                if isinstance(action, dict) and action.get("type") not in managed_action_types
            ]
            if not actions:
                continue
            args["actions"] = actions
            call["args"] = args
        merged.append(call)
    merged.extend(executor_calls)
    return merged
