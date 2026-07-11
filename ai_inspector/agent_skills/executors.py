"""Registered, data-driven executor recipes for the Phase 3 FAI slice."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_RPM_RE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*rpm\b")
_ADD_RE = re.compile(r"(?i)\b(also|add|include|plus|as well|keep)\b")
_RESTORE_RE = re.compile(r"(?i)\b(back|again|restore|reveal|visible|unhide)\b")
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
    "hide-resolved-parts": {
        "effects": ("hide_parts",),
        "preserves": ("viewport.highlight", "viewport.motion", "viewport.rotation"),
    },
    "show-resolved-parts": {
        "effects": ("show_parts",),
        "preserves": ("viewport.highlight", "viewport.motion", "viewport.rotation"),
    },
    "restore-assembly-display": {
        "effects": ("show_parts", "clear_highlight"),
        "preserves": ("viewport.motion", "viewport.rotation"),
    },
    "clear-assembly-highlight": {
        "effects": ("clear_highlight",),
        "preserves": ("viewport.hidden_parts", "viewport.motion", "viewport.rotation"),
    },
}


def normalize_route_effect_semantics(
    route: Mapping[str, Any] | None,
    *,
    message: str,
    workflow_state: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize ambiguous display vocabulary into the app's tool semantics.

    The semantic router still decides the target and requested write. This
    deterministic layer only distinguishes additive selection from restoring
    a hidden part, which are separate viewport state domains.
    """
    if not route:
        return None
    normalized = copy.deepcopy(dict(route))
    additive = bool(_ADD_RE.search(message or "")) and not bool(_RESTORE_RE.search(message or ""))
    compact_message = re.sub(r"[^a-z]+", " ", str(message or "").lower()).strip()
    pronoun_show = bool(re.fullmatch(
        r"(?:please )?(?:show|display|visualize)(?: me)? (?:it|that|them)(?: please)?",
        compact_message,
    ))
    referents = workflow_state.get("referents") if isinstance(workflow_state, Mapping) else {}
    referents = referents if isinstance(referents, Mapping) else {}
    prior_intents = {str(value) for value in (referents.get("last_intent_kinds") or [])}
    for intent in normalized.get("intents") or []:
        if not isinstance(intent, dict):
            continue
        targets = intent.get("targets") or []
        has_part = any(
            isinstance(target, Mapping) and target.get("kind") == "part" and target.get("id")
            for target in targets
        )
        has_motion_group = any(
            isinstance(target, Mapping) and target.get("kind") == "motion_group" and target.get("id")
            for target in targets
        )
        effects = list(intent.get("requested_effects") or [])
        if (
            pronoun_show
            and has_motion_group
            and "explain_motion" in prior_intents
            and "play_motion" not in effects
        ):
            effects.append("play_motion")
        if has_motion_group and "play_motion" in effects and "highlight_parts" not in effects:
            effects = [effect for effect in effects if effect != "highlight_features"]
            effects.insert(0, "highlight_parts")
            intent["requested_effects"] = list(dict.fromkeys(effects))
        elif additive and has_part and "show_parts" in effects and "highlight_parts" not in effects:
            effects = [
                "highlight_parts" if effect == "show_parts" else effect for effect in effects
            ]
        intent["requested_effects"] = list(dict.fromkeys(effects))
    return normalized


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
    if "hide_parts" in effects and part_ids:
        action = {"type": "set_part_display", "part_numbers": part_ids, "hidden": True}
        return ExecutorPlan(
            executor_id="hide-resolved-parts",
            target_ids=tuple(part_ids),
            requested_effects=("hide_parts",),
            tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": [action]}},),
        )
    if "show_parts" in effects and part_ids:
        action = {"type": "clear_part_display", "part_numbers": part_ids}
        return ExecutorPlan(
            executor_id="show-resolved-parts",
            target_ids=tuple(part_ids),
            requested_effects=("show_parts",),
            tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": [action]}},),
        )
    if "show_parts" in effects and not part_ids:
        actions = [{"type": "clear_part_display", "all": True}]
        requested_effects = ["show_parts"]
        if "clear_highlight" in effects:
            actions.append({"type": "clear_part_highlight", "all": True})
            requested_effects.append("clear_highlight")
        return ExecutorPlan(
            executor_id="restore-assembly-display",
            target_ids=("all",),
            requested_effects=tuple(requested_effects),
            tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": actions}},),
        )
    if "clear_highlight" in effects:
        action = {"type": "clear_part_highlight", "all": True}
        return ExecutorPlan(
            executor_id="clear-assembly-highlight",
            target_ids=("all",),
            requested_effects=("clear_highlight",),
            tool_calls=({"name": "ui_actions", "args": {"workspace": "assembly", "actions": [action]}},),
        )
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
    for family in (
        {"set_part_highlight", "clear_part_highlight"},
        {"set_part_display", "clear_part_display"},
        {"play_motion", "pause_motion", "stop_motion", "set_motion_rpm", "seek_motion"},
        {"rotate_view", "stop_rotate_view"},
    ):
        if managed_action_types.intersection(family):
            managed_action_types.update(family)
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
