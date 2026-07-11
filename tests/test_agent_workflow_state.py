"""Phase 5 multi-turn workflow-state lifecycle and reconciliation checks."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.agent_skills import (  # noqa: E402
    WorkflowStateStore,
    advance_workflow_state,
    resolve_route_referents,
    sanitize_workflow_state,
)


STAGES = (
    "identify_characteristic",
    "evaluate_result",
    "explain_part_function",
    "trace_assembly_impact",
    "visualize_affected_context",
    "recommend_disposition",
)


def _route(
    intent_kind: str,
    *,
    target_kind="fai_characteristic",
    target_id="5",
    effects=(),
    continue_existing=True,
):
    return {
        "route_version": 1,
        "speech_act": "command" if effects else "question",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": continue_existing,
        "workflow_confidence": 0.95,
        "intents": [{
            "kind": intent_kind,
            "targets": [{"kind": target_kind, "id": target_id, "label": "Synthetic target"}],
            "requested_effects": list(effects),
            "confidence": 0.95,
        }],
        "skill_candidates": [],
        "context_requirements": [],
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
        "part": {"part_number": "SYNTH-P1", "part_name": "Synthetic part"},
        "assembly_number": "SYNTH-A1",
        "fai": {
            "count": 2,
            "rows": [
                {"id": "5", "description": "Synthetic bore", "status": "fail", "has_measured_value": True},
                {"id": "6", "description": "Synthetic length", "status": "pending", "has_measured_value": False},
            ],
        },
    }


def _facts_with_motion():
    return {
        **_facts(),
        "motions": [{
            "motion_id": "synthetic-cycle",
            "groups": [
                {
                    "id": "synthetic-affected",
                    "label": "Synthetic FAI affected joint",
                    "function": "Shows the motion affected by the inspected interface.",
                    "part_numbers": ["SYNTH-P1", "SYNTH-P2"],
                },
                {
                    "id": "synthetic-full",
                    "label": "Full mechanism",
                    "function": "Shows the complete mechanism.",
                    "part_numbers": ["SYNTH-P1", "SYNTH-P2", "SYNTH-H1"],
                },
            ],
        }],
        "target_index": {
            "motion_group": ["synthetic-affected", "synthetic-full"],
            "part": ["SYNTH-P1", "SYNTH-P2", "SYNTH-H1"],
        },
    }


def _receipt(receipt_id="receipt:one", *, status="succeeded", tool_id="play_motion"):
    return {
        "receipt_id": receipt_id,
        "tool_id": tool_id,
        "status": status,
        "action_id": "a1",
        "evidence": ["motion-package:synthetic-cycle"],
    }


def test_pure_transition_tracks_stage_entities_evidence_and_referents():
    state = advance_workflow_state(
        None,
        route=_route("explain_assembly_impact", continue_existing=False),
        context_facts=_facts(),
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=time.time(),
        ttl_seconds=600.0,
    )
    assert state["stage"] == "trace_assembly_impact"
    assert state["entities"]["part_number"] == "SYNTH-P1"
    assert state["entities"]["assembly_number"] == "SYNTH-A1"
    assert state["entities"]["characteristic_numbers"] == ["5"]
    assert state["referents"]["last_characteristic_numbers"] == ["5"]
    assert "fai:SYNTH-P1:5" in state["evidence_refs"]
    assert state["objective"] == "Disposition failed characteristic 5"
    assert state["revision"] == 1


def test_selected_pending_characteristic_is_not_promoted_to_failure():
    facts = _facts()
    facts["fai"]["rows"][0]["status"] = "pending"
    state = advance_workflow_state(
        None,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=facts,
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1000.0,
        ttl_seconds=600.0,
    )
    assert state["objective"] == "Evaluate characteristic 5"
    assert state["milestones"]["failed_characteristic_identified"] is False
    assert state["status"] == "active"


def test_motion_explanation_persists_unique_data_tagged_group_and_resolves_followup():
    state = advance_workflow_state(
        None,
        route=_route("explain_motion", continue_existing=False),
        context_facts=_facts_with_motion(),
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1000.0,
        ttl_seconds=600.0,
    )
    assert state["entities"]["motion_group_ids"] == ["synthetic-affected"]
    assert state["referents"]["last_motion_group_ids"] == ["synthetic-affected"]

    followup = _route(
        "visualize_affected_context",
        target_kind="fai_characteristic",
        target_id="5",
        effects=("highlight_parts", "play_motion"),
    )
    resolved = resolve_route_referents(
        followup,
        workflow_state=state,
        context_facts=_facts_with_motion(),
    )
    targets = resolved["intents"][0]["targets"]
    assert {target["kind"]: target["id"] for target in targets}["motion_group"] == "synthetic-affected"

    stale = json.loads(json.dumps(state))
    stale["referents"]["last_motion_group_ids"] = ["removed-group"]
    unresolved = resolve_route_referents(
        followup,
        workflow_state=stale,
        context_facts=_facts_with_motion(),
    )
    assert not any(target["kind"] == "motion_group" for target in unresolved["intents"][0]["targets"])


def test_continuation_advances_without_regression_and_restart_drops_old_referents():
    first = advance_workflow_state(
        None,
        route=_route("explain_assembly_impact", continue_existing=False),
        context_facts=_facts(),
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1000.0,
        ttl_seconds=600.0,
    )
    continued = advance_workflow_state(
        first,
        route=_route(
            "visualize_affected_context",
            target_kind="motion_group",
            target_id="synthetic-affected",
            effects=("highlight_parts", "play_motion"),
            continue_existing=True,
        ),
        context_facts=_facts(),
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1010.0,
        ttl_seconds=600.0,
    )
    assert continued["stage"] == "visualize_affected_context"
    assert continued["entities"]["characteristic_numbers"] == ["5"]
    assert continued["entities"]["motion_group_ids"] == ["synthetic-affected"]
    assert continued["milestones"]["visualization_requested"] is True
    assert continued["milestones"]["visualization_succeeded"] is False

    restarted = advance_workflow_state(
        continued,
        route=_route("assess_fai_characteristic", target_id="6", continue_existing=False),
        context_facts={
            **_facts(),
            "fai": {"count": 1, "rows": [{"id": "6", "status": "fail", "has_measured_value": True}]},
        },
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1020.0,
        ttl_seconds=600.0,
    )
    assert restarted["stage"] == "evaluate_result"
    assert restarted["entities"]["characteristic_numbers"] == ["6"]
    assert "motion_group_ids" not in restarted["entities"]
    assert restarted["revision"] == 1


def test_receipt_reconciliation_completes_only_after_requested_visualization_succeeds():
    mono = [10.0]
    wall = [1000.0]
    store = WorkflowStateStore(
        ttl_seconds=300,
        max_sessions=8,
        clock=lambda: mono[0],
        wall_clock=lambda: wall[0],
    )
    asset = "asset-v1:test"
    store.advance(
        "session:one",
        asset_fingerprint=asset,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    store.advance(
        "session:one",
        asset_fingerprint=asset,
        route=_route(
            "visualize_affected_context",
            target_kind="motion_group",
            target_id="synthetic-affected",
            effects=("highlight_parts", "play_motion"),
        ),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    before_receipt = store.advance(
        "session:one",
        asset_fingerprint=asset,
        route=_route("recommend_disposition"),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert before_receipt.state["status"] == "active"
    partial = store.reconcile(
        "session:one",
        asset_fingerprint=asset,
        receipts=[_receipt("receipt:highlight", tool_id="set_part_highlight")],
    )
    assert partial.event == "receipts_reconciled"
    assert partial.state["status"] == "active"
    assert partial.state["milestones"]["visualization_succeeded"] is False

    duplicate = store.reconcile(
        "session:one",
        asset_fingerprint=asset,
        receipts=[_receipt("receipt:highlight", tool_id="set_part_highlight")],
    )
    assert duplicate.event == "resumed"

    reconciled = store.reconcile(
        "session:one",
        asset_fingerprint=asset,
        receipts=[_receipt("receipt:motion", tool_id="play_motion")],
    )
    assert reconciled.event == "receipts_reconciled"
    assert reconciled.state["status"] == "completed"
    assert reconciled.state["milestones"]["visualization_succeeded"] is True


def test_asset_change_and_expiry_invalidate_without_carrying_state():
    mono = [10.0]
    wall = [1000.0]
    store = WorkflowStateStore(
        ttl_seconds=60,
        max_sessions=8,
        clock=lambda: mono[0],
        wall_clock=lambda: wall[0],
    )
    store.advance(
        "session:asset",
        asset_fingerprint="asset-v1:a",
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    changed = store.reconcile("session:asset", asset_fingerprint="asset-v1:b")
    assert changed.state is None and changed.event == "invalidated_asset_change"

    store.advance(
        "session:expiry",
        asset_fingerprint="asset-v1:a",
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    mono[0] = 71.0
    wall[0] = 1061.0
    expired = store.reconcile("session:expiry", asset_fingerprint="asset-v1:a")
    assert expired.state is None and expired.event == "expired"


def test_matching_unexpired_browser_mirror_restores_after_server_restart():
    source = WorkflowStateStore(ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1000.0)
    created = source.advance(
        "session:mirror",
        asset_fingerprint="asset-v1:a",
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    ).state
    restored_store = WorkflowStateStore(ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1001.0)
    restored = restored_store.reconcile(
        "session:mirror", asset_fingerprint="asset-v1:a", client_state=created
    )
    assert restored.event == "restored_client_mirror"
    assert restored.state["entities"]["characteristic_numbers"] == ["5"]
    rejected = WorkflowStateStore(ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1001.0).reconcile(
        "session:mirror", asset_fingerprint="asset-v1:b", client_state=created
    )
    assert rejected.state is None and rejected.event == "empty"


def test_store_is_bounded_and_explicit_abandonment_is_narrow():
    store = WorkflowStateStore(ttl_seconds=300, max_sessions=2)
    for index in range(3):
        store.advance(
            f"session:{index}",
            asset_fingerprint=f"asset-v1:{index}",
            route=_route("assess_fai_characteristic", continue_existing=False),
            context_facts=_facts(),
            workflow_version="1.0.0",
            workflow_stages=STAGES,
        )
    assert store.stats()["entries"] == 2
    assert store.get("session:0") is None
    abandoned = store.abandon("session:2")
    assert abandoned.event == "abandoned:user_requested"
    assert store.get("session:2") is None
    assert server._workflow_abandonment_requested("cancel this workflow") is True
    assert server._workflow_abandonment_requested("start over") is True
    assert server._workflow_abandonment_requested("stop the motion") is False


def test_server_asset_fingerprint_ignores_tab_and_live_viewport_state():
    base = {
        "part_number": "SYNTH-P1",
        "revision": "A",
        "assembly_number": "SYNTH-A1",
        "active_assembly_config": "Default",
        "asset_identity": {"fai_revision": "A", "motion_asset_pin": "abc"},
        "viewport_context": {
            "motion": {"motions": [{"motion_id": "synthetic-cycle"}]},
            "state": {"active_tab": "report", "motion_playing": False, "highlighted": []},
        },
    }
    changed_view = json.loads(json.dumps(base))
    changed_view["viewport_context"]["state"] = {
        "active_tab": "assembly", "motion_playing": True, "highlighted": ["SYNTH-P1"]
    }
    assert server._workflow_asset_fingerprint(base) == server._workflow_asset_fingerprint(changed_view)
    changed_asset = json.loads(json.dumps(base))
    changed_asset["revision"] = "B"
    assert server._workflow_asset_fingerprint(base) != server._workflow_asset_fingerprint(changed_asset)


def test_server_normalization_and_prompt_include_validated_state_only():
    state = advance_workflow_state(
        None,
        route=_route("explain_assembly_impact", continue_existing=False),
        context_facts=_facts(),
        asset_fingerprint="asset-v1:test",
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=1000.0,
        ttl_seconds=600.0,
    )
    normalized = server.normalize_agent_context({
        "attachments": {
            "session": {
                "active_mode": "report_fai",
                "asset_identity": {"part_number": "SYNTH-P1"},
                "skill_workflow_state": state,
            },
            "assembly": {"assembly_number": "SYNTH-A1"},
        }
    })["flat"]
    assert normalized["asset_identity"]["part_number"] == "SYNTH-P1"
    assert normalized["assembly_number"] == "SYNTH-A1"
    assert normalized["skill_workflow_state"]["stage"] == "trace_assembly_impact"

    plan, reason = server._compose_production_skill_prompt(
        {
            **_route("explain_motion", target_kind="motion_group", target_id="synthetic-affected"),
            "skill_candidates": [
                {"id": "reason-about-motion", "role": "primary", "confidence": 0.95},
                {"id": "assess-fai-characteristic", "role": "support", "confidence": 0.95},
                {"id": "trace-assembly-impact", "role": "support", "confidence": 0.95},
            ],
        },
        mode="report_fai",
        workflow_state=state,
    )
    assert reason == ""
    assert "Current stage: trace_assembly_impact" in plan["prompt"]
    assert "last_characteristic_numbers" in plan["prompt"]


def test_server_rejects_unknown_workflow_mirror_and_reports_phase5():
    asset = "asset-v1:test"
    now = time.time()
    state = advance_workflow_state(
        None,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        asset_fingerprint=asset,
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=now,
        ttl_seconds=600.0,
    )
    assert server._validated_workflow_state_mirror(state, asset) is not None
    unknown = dict(state, workflow_id="invented-workflow")
    assert sanitize_workflow_state(unknown, expected_asset_fingerprint=asset, now_epoch=now + 1)
    assert server._validated_workflow_state_mirror(unknown, asset) is None

    previous_enabled = os.environ.get("INSPECTORPRO_SKILLS_ENABLED")
    previous_shadow = os.environ.get("INSPECTORPRO_SKILLS_SHADOW")
    try:
        os.environ["INSPECTORPRO_SKILLS_ENABLED"] = "0"
        os.environ["INSPECTORPRO_SKILLS_SHADOW"] = "0"
        status = asyncio.run(server.agent_skill_runtime_status())
    finally:
        if previous_enabled is None:
            os.environ.pop("INSPECTORPRO_SKILLS_ENABLED", None)
        else:
            os.environ["INSPECTORPRO_SKILLS_ENABLED"] = previous_enabled
        if previous_shadow is None:
            os.environ.pop("INSPECTORPRO_SKILLS_SHADOW", None)
        else:
            os.environ["INSPECTORPRO_SKILLS_SHADOW"] = previous_shadow
    assert status["phase"] == 5
    assert status["workflow_state"]["production"]["ttl_seconds"] == 1800.0
    assert status["workflow_state"]["shadow"]["ttl_seconds"] == 1800.0


def test_shadow_and_production_workflow_state_are_strictly_isolated():
    assert server._SKILL_WORKFLOW_STATE_STORE is not server._SKILL_WORKFLOW_STATE_SHADOW_STORE
    server._SKILL_WORKFLOW_STATE_STORE.reset()
    server._SKILL_WORKFLOW_STATE_SHADOW_STORE.reset()
    server._SKILL_WORKFLOW_STATE_SHADOW_STORE.advance(
        "session:isolated",
        asset_fingerprint="asset-v1:test",
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert server._SKILL_WORKFLOW_STATE_SHADOW_STORE.get("session:isolated") is not None
    assert server._SKILL_WORKFLOW_STATE_STORE.get("session:isolated") is None


def test_workflow_state_schema_is_ascii_and_closed():
    path = REPO_ROOT / "ai_inspector" / "agent_skills" / "schemas" / "workflow-state.schema.json"
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
