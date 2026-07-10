"""Tests for the server-side viewport intent classifier (hybrid intent layer).

The classifier itself is an LLM call, so these tests cover the deterministic
shell around it: the context digest the model grounds against, the strict
validation of its output, and the graceful-fallback contract (any failure
returns None so the frontend's regex resolvers take over).

The fixture context is deliberately NOT the engine demo -- a generic gearbox
with different ids/part numbers -- to prove nothing is hard-coded.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


def _ctx():
    """Generic gearbox context (not the engine demo)."""
    return {
        "active_mode": "report_fai",
        "viewport_context": {
            "active_tab": "report",
            "motion": {
                "available": True,
                "motions": [{
                    "motion_id": "gearbox_input_cycle",
                    "name": "Gearbox input cycle",
                    "default_rpm": 55,
                    "rpm_range": [5, 300],
                    "groups": [
                        {
                            "id": "input_shaft_drive",
                            "label": "Input shaft drive",
                            "function": "Rotary input that drives the gear train.",
                            "part_numbers": ["200001"],
                        },
                        {
                            "id": "bore_fai_affected",
                            "label": "Bore affected motion group",
                            "function": "Components whose fit is affected by bore alignment.",
                            "part_numbers": ["200002", "200003"],
                        },
                    ],
                }],
            },
            "part_legend": [
                {"part_number": "200001", "description": "Input Shaft"},
                {"part_number": "200002", "description": "Idler Gear"},
                {"part_number": "200003", "description": "Output Gear"},
                {"part_number": "200004", "description": "Housing"},
            ],
            "state": {
                "motion_playing": False,
                "motion_rpm": None,
                "highlighted": ["200002"],
                "hidden": ["200004"],
            },
        },
    }


def _intent(**overrides):
    base = {
        "intent_kind": "highlight_motion",
        "workflow": "assembly",
        "targets": [{
            "kind": "motion_group",
            "label": "the affected motion",
            "part_numbers": [],
            "feature_ids": [],
            "motion_group_id": "bore_fai_affected",
        }],
        "motion": {"requested": True, "speed": "slow", "rpm": None},
        "display": {"hidden": None, "opacity": None},
        "mode": "replace",
        "confidence": 0.9,
        "needs_clarification": False,
        "clarification_question": None,
    }
    base.update(overrides)
    return base


def test_digest_contains_groups_legend_and_state():
    digest = server._viewport_intent_context_digest(_ctx())
    assert "motion_package: available" in digest
    assert "group input_shaft_drive" in digest
    assert "group bore_fai_affected" in digest
    assert "rpm_range=[5, 300]" in digest
    assert "200004: Housing" in digest
    assert "motion_playing=False" in digest
    assert "hidden=['200004']" in digest


def test_action_capable_agents_use_viewport_intent_layer():
    assert "deviation-analyst" in server.VIEWPORT_INTENT_AGENT_TYPES
    assert "inspector" in server.VIEWPORT_INTENT_AGENT_TYPES


def test_digest_without_motion_package():
    digest = server._viewport_intent_context_digest({"active_mode": "assembly"})
    assert "motion_package: none" in digest


def test_validate_accepts_good_intent():
    out = server._validate_viewport_intent(_intent(), _ctx())
    assert out is not None
    assert out["intent_kind"] == "highlight_motion"
    assert out["targets"][0]["motion_group_id"] == "bore_fai_affected"
    assert out["motion"]["requested"] is True
    assert out["motion"]["speed"] == "slow"
    assert out["confidence"] == 0.9


def test_validate_rejects_unknown_intent_kind():
    assert server._validate_viewport_intent(_intent(intent_kind="explode_everything"), _ctx()) is None
    assert server._validate_viewport_intent("not a dict", _ctx()) is None
    assert server._validate_viewport_intent(None, _ctx()) is None


def test_validate_filters_unknown_part_numbers_and_groups():
    intent = _intent(targets=[{
        "kind": "part",
        "label": "made up parts",
        "part_numbers": ["200001", "999999"],
        "feature_ids": [],
        "motion_group_id": "no_such_group",
    }])
    out = server._validate_viewport_intent(intent, _ctx())
    assert out["targets"][0]["part_numbers"] == ["200001"]
    assert out["targets"][0]["motion_group_id"] is None


def test_validate_clamps_numbers_and_enums():
    intent = _intent(
        motion={"requested": True, "speed": "warp", "rpm": 999999},
        display={"hidden": "yes", "opacity": 7},
        mode="sideways",
        confidence=3.5,
    )
    out = server._validate_viewport_intent(intent, _ctx())
    assert out["motion"]["speed"] is None
    assert out["motion"]["rpm"] is None
    assert out["display"]["hidden"] is None
    assert out["display"]["opacity"] is None
    assert out["mode"] is None
    assert out["confidence"] == 1.0


def test_classify_with_injected_completion_parses_fenced_json():
    raw = "Here you go:\n```json\n" + json.dumps(_intent()) + "\n```"
    out = server.classify_viewport_intent(
        "can you the show the affected motion?", _ctx(),
        _complete=lambda system, user: raw,
    )
    assert out is not None
    assert out["intent_kind"] == "highlight_motion"
    assert out["targets"][0]["motion_group_id"] == "bore_fai_affected"


def test_classify_grounds_prompt_in_context():
    captured = {}

    def fake_complete(system, user):
        captured["system"] = system
        captured["user"] = user
        return json.dumps(_intent())

    server.classify_viewport_intent("show the affected motion", _ctx(), _complete=fake_complete)
    assert "group bore_fai_affected" in captured["user"]
    assert "USER MESSAGE:\nshow the affected motion" in captured["user"]
    # The rules the evaluation depends on must be in the system prompt.
    assert "highlight only" in captured["system"]
    assert "plain target request like \"show the pin joint\"" in captured["system"]
    assert "Whole-assembly motion requests" in captured["system"]
    assert "Never clear highlights, never stop motion" in captured["system"]
    assert "camera" in captured["system"]


def test_classify_returns_none_on_garbage_or_failure():
    assert server.classify_viewport_intent("show it", _ctx(), _complete=lambda s, u: "not json") is None
    assert server.classify_viewport_intent("", _ctx(), _complete=lambda s, u: "{}") is None

    def boom(system, user):
        raise RuntimeError("model down")

    assert server.classify_viewport_intent("show it", _ctx(), _complete=boom) is None


def test_classify_returns_none_without_api_key():
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert server.classify_viewport_intent("show the affected motion", _ctx()) is None
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_normalize_preserves_viewport_attachment():
    ctx = {"attachments": {"viewport": {"active_tab": "report", "motion": {"available": False}}}}
    normalized = server.normalize_agent_context(ctx)
    assert normalized["flat"]["viewport_context"]["active_tab"] == "report"


def test_explanation_questions_rule_in_system_prompt():
    # Explanation/impact questions must classify as "none" even when they
    # mention assembly/motion/affected -- the rule is spelled out for the
    # classifier, and the frontend verb gate enforces it deterministically.
    prompt = server._VIEWPORT_INTENT_SYSTEM
    assert "what is the affected motion?" in prompt
    assert "what is the impact on" in prompt
    assert "Explanation/analysis/impact questions" in prompt


if __name__ == "__main__":
    import traceback

    _tests = sorted(
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    )
    _passed = _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            _passed += 1
            print(f"PASS {_name}")
        except Exception:  # noqa: BLE001
            _failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)
