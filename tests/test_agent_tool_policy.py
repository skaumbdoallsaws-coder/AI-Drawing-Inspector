"""Phase 4 typed UI-action policy and browser-receipt checks."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.agent_skills import (  # noqa: E402
    load_ui_action_contract,
    sanitize_execution_receipts,
    tool_policy_metadata,
    validate_ui_action_bundle,
)


def _valid_bundle():
    return {
        "workspace": "assembly",
        "actions": [
            {
                "type": "set_part_highlight",
                "part_numbers": ["SYNTH-P1", "SYNTH-P2"],
                "mode": "replace",
            },
            {
                "type": "play_motion",
                "motion_id": "synthetic-cycle",
                "rpm": 30,
                "loop": True,
            },
        ],
    }


def _receipt(*, receipt_id="receipt:test-1", status="succeeded"):
    return {
        "contract_version": 1,
        "receipt_id": receipt_id,
        "tool_call_id": "tool:test-1",
        "action_id": "a1",
        "tool_id": "play_motion",
        "status": status,
        "requested_args": {"type": "play_motion", "rpm": 30},
        "applied_args": {"type": "play_motion", "rpm": 30},
        "before": {"motion": {"playing": False}},
        "after": {"motion": {"playing": status == "succeeded"}},
        "evidence": ["motion-package:synthetic-cycle"],
        "error": None if status == "succeeded" else "motion_not_playing",
        "duration_ms": 12,
        "timestamp": "2026-07-10T12:00:00Z",
    }


def test_contract_is_ascii_strict_and_covers_existing_actions():
    raw = (REPO_ROOT / "static" / "contracts" / "ui-action-contract-v1.json").read_bytes()
    assert all(byte < 128 for byte in raw)
    contract = load_ui_action_contract()
    assert contract["contract_version"] == 1
    assert len(contract["actions"]) == 25
    assert {
        "set_part_highlight",
        "set_part_display",
        "play_motion",
        "rotate_view",
        "compare_supplier_specs",
        "set_process_map_part_scope",
        "clear_process_map_part_scope",
        "set_process_map_focus",
        "clear_process_map_focus",
    } <= set(contract["actions"])
    assert tool_policy_metadata() == {
        "contract_version": 1,
        "action_count": 25,
        "max_actions": 25,
        "receipt_schema": "execution-receipt.schema.json",
    }


def test_bundle_validation_normalizes_ids_types_and_rejects_conflicts():
    normalized, errors = validate_ui_action_bundle(_valid_bundle())
    assert errors == []
    assert [action["action_id"] for action in normalized["actions"]] == ["a1", "a2"]
    assert normalized["actions"][1]["rpm"] == 30.0

    invalid, errors = validate_ui_action_bundle(
        {"workspace": "assembly", "actions": [{"type": "invented_action"}]}
    )
    assert invalid is None and errors == ["action[0]:unknown_type"]

    conflict = {
        "workspace": "assembly",
        "actions": [{"type": "play_motion"}, {"type": "stop_motion"}],
    }
    invalid, errors = validate_ui_action_bundle(conflict)
    assert invalid is None
    assert errors == ["conflict:play_and_stop_conflict"]


def test_server_tool_guard_applies_the_same_contract():
    guarded = server.sanitize_tool_calls(
        [{"name": "ui_actions", "args": _valid_bundle()}], "deviation-analyst"
    )
    assert len(guarded) == 1
    assert guarded[0]["args"]["actions"][0]["action_id"] == "a1"

    rejected = server.sanitize_tool_calls(
        [{"name": "ui_actions", "args": {"workspace": "assembly", "actions": [
            {"type": "play_motion", "unexpected": True}
        ]}}],
        "deviation-analyst",
    )
    assert rejected == []

    process_map_bundle = {
        "workspace": "process_map",
        "actions": [{
            "type": "set_process_map_part_scope",
            "scope_occurrence_id": "bodywork-1",
            "label": "Bodywork Assembly",
        }],
    }
    guarded = server.sanitize_tool_calls(
        [{"name": "ui_actions", "args": process_map_bundle}],
        "deviation-analyst",
    )
    assert guarded[0]["args"]["actions"][0]["scope_occurrence_id"] == "bodywork-1"

    focus_bundle = {
        "workspace": "process_map",
        "actions": [{
            "type": "set_process_map_focus",
            "target_occurrence_id": "bodywork-1",
            "direction": "upstream",
            "include_routes": True,
            "fit_view": True,
        }],
    }
    guarded = server.sanitize_tool_calls(
        [{"name": "ui_actions", "args": focus_bundle}],
        "deviation-analyst",
    )
    assert guarded[0]["args"]["actions"][0]["target_occurrence_id"] == "bodywork-1"

    multi_focus_bundle = {
        "workspace": "process_map",
        "actions": [{
            "type": "set_process_map_focus",
            "target_node_ids": ["stage-front", "stage-rear"],
            "labels": ["Front Wheel", "Rear Wheel"],
            "direction": "upstream",
            "include_routes": True,
        }],
    }
    guarded = server.sanitize_tool_calls(
        [{"name": "ui_actions", "args": multi_focus_bundle}],
        "deviation-analyst",
    )
    assert guarded[0]["args"]["actions"][0]["target_node_ids"] == [
        "stage-front",
        "stage-rear",
    ]


def test_receipt_sanitizer_is_strict_bounded_and_deduplicated():
    raw = _receipt()
    raw["untrusted_extra"] = "drop me"
    duplicate = dict(raw)
    invalid = dict(raw, receipt_id="bad id with spaces")
    failed = _receipt(receipt_id="receipt:test-2", status="failed")
    cleaned = sanitize_execution_receipts([raw, duplicate, invalid, failed])
    assert [item["receipt_id"] for item in cleaned] == ["receipt:test-1", "receipt:test-2"]
    assert "untrusted_extra" not in cleaned[0]
    assert cleaned[0]["error"] is None
    assert cleaned[1]["error"] == "motion_not_playing"


def test_receipts_flow_into_context_but_current_viewport_stays_separate():
    context = {
        "attachments": {
            "viewport": {
                "state": {
                    "active_tab": "assembly",
                    "motion_playing": False,
                    "highlighted": [],
                    "hidden": [],
                },
                "execution_receipts": [_receipt()],
            }
        }
    }
    flat = server.normalize_agent_context(context)["flat"]
    assert flat["viewport_context"]["state"]["motion_playing"] is False
    assert flat["viewport_context"]["execution_receipts"][0]["status"] == "succeeded"

    assets, contexts, facts = server._skill_route_context(flat)
    assert "viewport.execution_receipts" in contexts
    assert facts["execution_receipts"] == [{
        "receipt_id": "receipt:test-1",
        "tool_id": "play_motion",
        "status": "succeeded",
        "error": None,
    }]
    workflow_state = server._skill_route_workflow_state(flat)
    assert workflow_state["last_execution_receipts"][0]["tool_id"] == "play_motion"
    assert flat["viewport_context"]["state"]["motion_playing"] is False


def test_internal_status_reports_phase4_tool_policy():
    previous_enabled = os.environ.get("INSPECTORPRO_SKILLS_ENABLED")
    previous_shadow = os.environ.get("INSPECTORPRO_SKILLS_SHADOW")
    try:
        os.environ["INSPECTORPRO_SKILLS_ENABLED"] = "0"
        os.environ["INSPECTORPRO_SKILLS_SHADOW"] = "0"
        result = asyncio.run(server.agent_skill_runtime_status())
    finally:
        if previous_enabled is None:
            os.environ.pop("INSPECTORPRO_SKILLS_ENABLED", None)
        else:
            os.environ["INSPECTORPRO_SKILLS_ENABLED"] = previous_enabled
        if previous_shadow is None:
            os.environ.pop("INSPECTORPRO_SKILLS_SHADOW", None)
        else:
            os.environ["INSPECTORPRO_SKILLS_SHADOW"] = previous_shadow
    assert result["phase"] == 5
    assert result["tool_policy"]["contract_version"] == 1
    assert result["tool_policy"]["action_count"] == 25


def test_receipt_schema_is_ascii_and_closed():
    path = REPO_ROOT / "ai_inspector" / "agent_skills" / "schemas" / "execution-receipt.schema.json"
    raw = path.read_bytes()
    assert all(byte < 128 for byte in raw)
    schema = json.loads(raw.decode("ascii"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


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
