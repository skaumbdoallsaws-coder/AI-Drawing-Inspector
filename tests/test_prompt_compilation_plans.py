"""Compilation-plan tests independent from router and answer quality."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "prompt_compilation_cases.json"


def _route(case: dict) -> dict:
    candidates = [{
        "id": case["primary"],
        "role": "primary",
        "confidence": 0.99,
    }]
    candidates.extend({
        "id": skill_id,
        "role": "support",
        "confidence": 0.98,
    } for skill_id in case["supports"])
    return {
        "route_version": 2,
        "speech_act": case["speech_act"],
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": False,
        "workflow_confidence": 0.99,
        "intents": [{
            "kind": case["id"].replace("-", "_"),
            "targets": [],
            "requested_effects": ["viewport_write"] if case["viewport_write"] else [],
        }],
        "skill_candidates": candidates,
        "requested_side_effects": {
            "viewport_write": case["viewport_write"],
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
    }


def test_compilation_plan_fixture_is_ascii_and_unique():
    raw = FIXTURE.read_bytes()
    assert all(byte < 128 for byte in raw)
    fixture = json.loads(raw.decode("ascii"))
    assert fixture["schema_version"] == 1
    ids = [case["id"] for case in fixture["cases"]]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 5


def test_expected_compilation_plans():
    fixture = json.loads(FIXTURE.read_text(encoding="ascii"))
    for case in fixture["cases"]:
        plan, reason = server._compose_production_skill_prompt(
            _route(case), mode=case["mode"]
        )
        assert reason == "", (case["id"], reason)
        assert plan is not None
        assert [item["id"] for item in plan["selection"]] == case["expected_skills"]
        assert plan["allowed_tools"] == case["allowed_tools"]
        assert set(case["required_context"]) <= set(plan["context_requirements"])
        assert len(plan["contracts"]) == len(plan["selection"])
        assert all(
            re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", item["version"])
            for item in plan["contracts"]
        )
        assert plan["resolved_policy"]["primary_skill"] == case["primary"]
        assert plan["resolved_policy"]["side_effect_default"] == "prohibited"
        assert plan["accounting"]["total_chars"] < 20_000
        assert plan["prompt"].count(
            "SUPPLIER FAI INVERTED-PYRAMID RESPONSE FORMAT"
        ) == 1
        assert plan["prompt"].count("[FORMAT EXAMPLE - SYNTHETIC DATA]") == 8
        for banned in (
            "HIGHLIGHT_PARTS:",
            "HIGHLIGHT_FEATURES:",
            "[UI_ACTIONS]",
            "<tool_calls>",
        ):
            assert banned not in plan["prompt"], (case["id"], banned)
        if case["viewport_write"]:
            control = next(
                item for item in plan["contracts"]
                if item["skill_id"] == "control-cad-viewport"
            )
            assert control["side_effect_default"] == "prohibited"
            assert set(control["explicit_request_tools"]) == set(case["allowed_tools"])
            assert plan["resolved_policy"]["output"] == {
                "format": "concise_action_confirmation",
                "maximum_sentences": 3,
            }
            assert plan["resolved_policy"]["contradictory_context"] == "refuse_side_effect"
        else:
            assert plan["allowed_tools"] == []


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
