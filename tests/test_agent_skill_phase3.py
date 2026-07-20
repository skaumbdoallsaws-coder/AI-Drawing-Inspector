"""Phase 3 selected-skill prompt and registered-executor checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.agent_skills import (  # noqa: E402
    ExactRouteCache,
    classify_production_route,
    merge_executor_tool_calls,
    normalize_route_effect_semantics,
    plan_registered_executor,
)


def _motion_route(*, effects=("highlight_parts", "play_motion"), confidence=0.95):
    return {
        "route_version": 1,
        "speech_act": "command",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": False,
        "workflow_confidence": confidence,
        "intents": [
            {
                "kind": "visualize_affected_context",
                "targets": [
                    {"kind": "motion_group", "id": "synthetic-affected", "label": "Affected joint"}
                ],
                "requested_effects": list(effects),
                "confidence": confidence,
            }
        ],
        "skill_candidates": [
            {"id": "reason-about-motion", "role": "primary", "confidence": confidence},
            {"id": "assess-fai-characteristic", "role": "support", "confidence": confidence},
            {"id": "trace-assembly-impact", "role": "support", "confidence": confidence},
            {"id": "control-cad-viewport", "role": "support", "confidence": confidence},
        ],
        "context_requirements": ["fai.characteristics", "motion.groups"],
        "requested_side_effects": {
            "viewport_write": bool(effects),
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
        "clarification_question": None,
    }


def _facts():
    return {
        "motions": [
            {
                "motion_id": "synthetic-cycle",
                "default_rpm": 90,
                "rpm_range": [10, 600],
                "groups": [
                    {
                        "id": "synthetic-affected",
                        "label": "Affected joint",
                        "function": "Links the inspected interface to the nominal mechanism motion.",
                        "part_numbers": ["SYNTH-P1", "SYNTH-P2", "SYNTH-P3"],
                    }
                ],
            }
        ]
    }


def _part_display_route(effect: str, *, part_id: str | None = "SYNTH-H1"):
    route = _motion_route(effects=(effect,))
    route["intents"][0]["kind"] = "visualize_affected_context"
    route["intents"][0]["targets"] = (
        [{"kind": "part", "id": part_id, "label": "Synthetic lower housing"}]
        if part_id else []
    )
    route["intents"][0]["requested_effects"] = [effect]
    return route


def test_phase3_registry_resolves_dependency_bounded_skill_compositions():
    server._reset_agent_skill_runtime_cache_for_tests()
    workflows, skills = server._get_agent_skill_runtime()
    assert len(skills.ids) == 8
    disposition = skills.resolve_selection(
        primary_id="recommend-fai-disposition",
        supporting_ids=[],
        agent="sage",
        workflow_id="supplier-fai-disposition",
        mode="report_fai",
    )
    assert [package.manifest.id for package in disposition] == [
        "assess-fai-characteristic",
        "recommend-fai-disposition",
    ]
    motion = skills.resolve_selection(
        primary_id="reason-about-motion",
        supporting_ids=["trace-assembly-impact", "control-cad-viewport"],
        agent="sage",
        workflow_id="supplier-fai-disposition",
        mode="report_fai",
    )
    assert len(motion) == 4
    assert {package.manifest.id for package in motion} == {
        "assess-fai-characteristic",
        "trace-assembly-impact",
        "reason-about-motion",
        "control-cad-viewport",
    }
    assert workflows.get("supplier-fai-disposition").manifest.version == "1.0.0"


def test_phase3_prompt_contains_only_selected_skills_and_rejects_unsafe_routes():
    plan, reason = server._compose_production_skill_prompt(_motion_route(), mode="report_fai")
    assert reason == ""
    assert plan is not None
    assert "[SKILL reason-about-motion@1.0.0]" in plan["prompt"]
    assert "[SKILL trace-assembly-impact@1.0.0]" in plan["prompt"]
    assert "[SKILL control-cad-viewport@1.0.0]" in plan["prompt"]
    assert "[SKILL recommend-fai-disposition" not in plan["prompt"]
    assert "If you write more than 3 sentences" not in plan["prompt"]
    assert plan["allowed_tools"] == ["highlight_features", "ui_actions"]

    low_plan, low_reason = server._compose_production_skill_prompt(
        _motion_route(confidence=0.5), mode="report_fai"
    )
    assert low_plan is None and low_reason == "workflow_confidence_below_threshold"

    asset_route = _motion_route(effects=())
    asset_route["speech_act"] = "edit"
    asset_route["requested_side_effects"]["asset_write"] = True
    asset_plan, asset_reason = server._compose_production_skill_prompt(asset_route, mode="report_fai")
    assert asset_plan is None and asset_reason == "write_category_not_in_phase3_slice"


def test_registered_executor_resolves_live_group_and_preserves_unrelated_actions():
    plan = plan_registered_executor(
        _motion_route(),
        context_facts=_facts(),
        message="show the affected motion slowly",
        viewport_authorized=True,
    )
    assert plan is not None
    assert plan.executor_id == "show-resolved-motion-group"
    actions = plan.tool_calls[0]["args"]["actions"]
    assert actions[0] == {
        "type": "set_part_highlight",
        "part_numbers": ["SYNTH-P1", "SYNTH-P2", "SYNTH-P3"],
        "mode": "replace",
    }
    assert actions[1] == {
        "type": "play_motion",
        "motion_id": "synthetic-cycle",
        "rpm": 30.0,
        "loop": True,
    }

    existing = [
        {
            "name": "ui_actions",
            "args": {
                "workspace": "assembly",
                "actions": [
                    {"type": "play_motion", "motion_id": "wrong", "rpm": 500},
                    {"type": "set_part_display", "part_numbers": ["SYNTH-H1"], "hidden": True},
                ],
            },
        }
    ]
    merged = merge_executor_tool_calls(existing, plan)
    assert merged[0]["args"]["actions"] == [
        {"type": "set_part_display", "part_numbers": ["SYNTH-H1"], "hidden": True}
    ]
    assert merged[1] == plan.tool_calls[0]
    assert plan_registered_executor(
        _motion_route(), context_facts=_facts(), message="what is the affected motion?",
        viewport_authorized=False,
    ) is None


def test_registered_executor_owns_hide_reveal_and_restore_followups():
    hide = plan_registered_executor(
        _part_display_route("hide_parts"),
        context_facts=_facts(),
        message="hide the lower housing",
        viewport_authorized=True,
    )
    assert hide.executor_id == "hide-resolved-parts"
    assert hide.tool_calls[0]["args"]["actions"] == [{
        "type": "set_part_display", "part_numbers": ["SYNTH-H1"], "hidden": True,
    }]

    reveal = plan_registered_executor(
        _part_display_route("show_parts"),
        context_facts=_facts(),
        message="bring that back",
        viewport_authorized=True,
    )
    assert reveal.executor_id == "show-resolved-parts"
    assert reveal.tool_calls[0]["args"]["actions"] == [{
        "type": "clear_part_display", "part_numbers": ["SYNTH-H1"],
    }]

    restore_route = _part_display_route("show_parts", part_id=None)
    restore_route["intents"][0]["requested_effects"] = ["show_parts", "clear_highlight"]
    restore = plan_registered_executor(
        restore_route,
        context_facts=_facts(),
        message="bring everything back",
        viewport_authorized=True,
    )
    assert restore.executor_id == "restore-assembly-display"
    assert restore.tool_calls[0]["args"]["actions"] == [
        {"type": "clear_part_display", "all": True},
        {"type": "clear_part_highlight", "all": True},
    ]

    merged = merge_executor_tool_calls([
        {"name": "ui_actions", "args": {"workspace": "assembly", "actions": [
            {"type": "set_part_display", "part_numbers": ["SYNTH-P1"], "hidden": True},
            {"type": "play_motion", "motion_id": "synthetic-cycle", "rpm": 30},
        ]}},
    ], reveal)
    assert merged[0]["args"]["actions"] == [
        {"type": "play_motion", "motion_id": "synthetic-cycle", "rpm": 30}
    ]
    assert merged[1] == reveal.tool_calls[0]


def test_add_named_part_normalizes_selection_without_changing_restore_semantics():
    pronoun_motion = normalize_route_effect_semantics(
        _motion_route(effects=("highlight_features",)),
        message="show it",
        workflow_state={"referents": {"last_intent_kinds": ["explain_motion"]}},
    )
    assert pronoun_motion["intents"][0]["requested_effects"] == [
        "highlight_parts", "play_motion",
    ]

    focused_motion = normalize_route_effect_semantics(
        _motion_route(effects=("highlight_features", "play_motion")),
        message="show it",
    )
    assert focused_motion["intents"][0]["requested_effects"] == [
        "highlight_parts", "play_motion",
    ]

    additive = normalize_route_effect_semantics(
        _part_display_route("show_parts", part_id="SYNTH-P3"),
        message="also add the synthetic link",
    )
    assert additive["intents"][0]["requested_effects"] == ["highlight_parts"]
    plan = plan_registered_executor(
        additive,
        context_facts=_facts(),
        message="also add the synthetic link",
        viewport_authorized=True,
    )
    assert plan.executor_id == "highlight-resolved-parts"
    assert plan.tool_calls[0]["args"]["actions"][0]["mode"] == "add"

    restore = normalize_route_effect_semantics(
        _part_display_route("show_parts", part_id="SYNTH-H1"),
        message="add the lower housing back",
    )
    assert restore["intents"][0]["requested_effects"] == ["show_parts"]


def test_production_classifier_metadata_is_distinct_from_shadow():
    catalog, facts = server._build_skill_route_catalog(
        {
            "active_mode": "report_fai",
            "part_number": "SYNTH-P1",
            "fai_characteristics": [
                {"char_number": "5", "description": "Synthetic bore", "status": "FAIL", "measured": 12.0}
            ],
            "profile_features": [{"id": "synthetic-bore", "semantic_name": "Synthetic bore"}],
            "viewport_context": {
                "part_legend": [
                    {"part_number": "SYNTH-P1", "description": "Inspected part"},
                    {"part_number": "SYNTH-P2", "description": "Mating part"},
                ],
                "motion": {"available": True, **_facts()},
                "state": {"active_tab": "report", "motion_playing": False, "highlighted": [], "hidden": []},
            },
        },
        "sage",
    )
    route = _motion_route()
    with patch("ai_inspector.agent_skills.shadow.record_workflow_stage"):
        classified = classify_production_route(
            "show the affected motion",
            catalog=catalog,
            context_facts=facts,
            recent_turns=[],
            workflow_state={},
            cache=ExactRouteCache(max_entries=2, ttl_seconds=60),
            model="test-model",
            timeout_seconds=4.75,
            max_tokens=700,
            complete=lambda *_args: json.dumps(route),
            authorize=lambda *_args: {
                "viewport_write": True,
                "asset_write": False,
                "system_write": False,
            },
        )
    assert classified is not None
    assert "_shadow" not in classified
    assert classified["_runtime"]["mode"] == "production"
    assert classified["_runtime"]["used_for_prompt"] is True
    assert classified["_runtime"]["used_for_execution"] is False


def _run_without_pytest() -> int:
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return failures


if __name__ == "__main__":
    raise SystemExit(_run_without_pytest())
