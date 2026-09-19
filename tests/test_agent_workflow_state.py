"""Durable v2 workflow-state lifecycle and revision reconciliation checks."""

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
    advance_workflow_state_v2,
    migrate_workflow_state_v1_to_v2,
    reconcile_workflow_state_v2,
    resolve_route_referents,
    sanitize_workflow_state,
)
from ai_inspector.memory import revision_vector_sha256  # noqa: E402
from ai_inspector.memory.invalidation import (  # noqa: E402
    AUTHORIZATION_KINDS,
    WORKFLOW_STAGE_POLICIES,
)


STAGES = (
    "identify_characteristic",
    "evaluate_result",
    "explain_part_function",
    "trace_assembly_impact",
    "visualize_affected_context",
    "recommend_disposition",
)
SCOPE = "scope-v1:" + "1" * 64
OTHER_SCOPE = "scope-v1:" + "2" * 64
REVISIONS = {
    "partRevision": "part-a",
    "drawingRevision": "drawing-a",
    "faiRevision": "fai-a",
    "assemblyKnowledgeRevision": "assembly-a",
    "motionAssetPin": "motion-a",
}
TARGET_INDEX = {
    "fai_characteristic": ["5", "6"],
    "part": ["SYNTH-P1", "SYNTH-P2", "SYNTH-H1"],
    "assembly": ["SYNTH-A1"],
    "feature": [],
    "motion_group": ["synthetic-affected", "synthetic-full"],
    "process_map": [],
    "process_node": [],
}


def _route(
    intent_kind: str,
    *,
    target_kind: str = "fai_characteristic",
    target_id: str = "5",
    effects=(),
    continue_existing: bool = True,
):
    return {
        "route_version": 1,
        "speech_act": "command" if effects else "question",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": continue_existing,
        "workflow_confidence": 0.95,
        "intents": [{
            "kind": intent_kind,
            "targets": [{
                "kind": target_kind,
                "id": target_id,
                "label": "Synthetic target",
            }],
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
        "target_index": dict(TARGET_INDEX),
        "fai": {
            "count": 2,
            "rows": [
                {
                    "id": "5",
                    "description": "Synthetic bore",
                    "status": "fail",
                    "has_measured_value": True,
                },
                {
                    "id": "6",
                    "description": "Synthetic length",
                    "status": "pending",
                    "has_measured_value": False,
                },
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
    }


def _receipt(
    receipt_id: str = "receipt:one",
    *,
    status: str = "succeeded",
    tool_id: str = "play_motion",
):
    return {
        "receipt_id": receipt_id,
        "tool_id": tool_id,
        "status": status,
        "action_id": "a1",
        "evidence": ["motion-package:synthetic-cycle"],
    }


def _advance(
    prior,
    route,
    facts,
    *,
    now: float = 1000.0,
    scope: str = SCOPE,
    revisions=None,
):
    return advance_workflow_state_v2(
        prior,
        route=route,
        context_facts=facts,
        scope_fingerprint=scope,
        revision_vector=revisions or REVISIONS,
        workflow_version="1.0.0",
        workflow_stages=STAGES,
        now_epoch=now,
        ttl_seconds=600.0,
    )


def test_pure_transition_tracks_stage_entities_evidence_and_referents():
    state = _advance(
        None,
        _route("explain_assembly_impact", continue_existing=False),
        _facts(),
    )
    assert state["state_version"] == 2
    assert state["stage"] == "trace_assembly_impact"
    assert state["entities"]["part_number"] == "SYNTH-P1"
    assert state["entities"]["assembly_number"] == "SYNTH-A1"
    assert state["entities"]["characteristic_numbers"] == ["5"]
    assert state["referents"]["last_characteristic_numbers"] == ["5"]
    assert "fai:SYNTH-P1:5" in state["evidence_refs"]
    assert state["objective"] == "Disposition failed characteristic 5"
    assert state["scope_fingerprint"] == SCOPE
    assert state["revision_vector"] == REVISIONS
    assert state["revision_vector_sha256"] == revision_vector_sha256(REVISIONS)
    assert state["revision"] == 1


def test_selected_pending_characteristic_is_not_promoted_to_failure():
    facts = _facts()
    facts["fai"]["rows"][0]["status"] = "pending"
    state = _advance(
        None,
        _route("assess_fai_characteristic", continue_existing=False),
        facts,
    )
    assert state["objective"] == "Evaluate characteristic 5"
    assert state["milestones"]["failed_characteristic_identified"] is False
    assert state["status"] == "active"


def test_motion_referent_is_data_grounded_and_followup_resolves_it():
    state = _advance(
        None,
        _route("explain_motion", continue_existing=False),
        _facts_with_motion(),
    )
    assert state["entities"]["motion_group_ids"] == ["synthetic-affected"]
    followup = _route(
        "visualize_affected_context",
        effects=("highlight_parts", "play_motion"),
    )
    resolved = resolve_route_referents(
        followup,
        workflow_state=state,
        context_facts=_facts_with_motion(),
    )
    targets = resolved["intents"][0]["targets"]
    assert {target["kind"]: target["id"] for target in targets}["motion_group"] == (
        "synthetic-affected"
    )

    stale = json.loads(json.dumps(state))
    stale["referents"]["last_motion_group_ids"] = ["removed-group"]
    unresolved = resolve_route_referents(
        followup,
        workflow_state=stale,
        context_facts=_facts_with_motion(),
    )
    assert not any(
        target["kind"] == "motion_group"
        for target in unresolved["intents"][0]["targets"]
    )


def test_continuation_advances_and_explicit_restart_drops_old_referents():
    first = _advance(
        None,
        _route("explain_assembly_impact", continue_existing=False),
        _facts(),
    )
    continued = _advance(
        first,
        _route(
            "visualize_affected_context",
            target_kind="motion_group",
            target_id="synthetic-affected",
            effects=("highlight_parts", "play_motion"),
        ),
        _facts_with_motion(),
        now=1010.0,
    )
    assert continued["stage"] == "visualize_affected_context"
    assert continued["entities"]["motion_group_ids"] == ["synthetic-affected"]
    assert continued["milestones"]["visualization_requested"] is True

    restarted_facts = _facts()
    restarted_facts["fai"] = {
        "count": 1,
        "rows": [{"id": "6", "status": "fail", "has_measured_value": True}],
    }
    restarted = _advance(
        continued,
        _route("assess_fai_characteristic", target_id="6", continue_existing=False),
        restarted_facts,
        now=1020.0,
    )
    assert restarted["stage"] == "evaluate_result"
    assert restarted["entities"]["characteristic_numbers"] == ["6"]
    assert "motion_group_ids" not in restarted["entities"]
    assert restarted["revision"] == 1


def test_receipts_complete_only_the_effects_requested_in_current_state():
    mono = [10.0]
    wall = [1000.0]
    store = WorkflowStateStore(
        ttl_seconds=300,
        max_sessions=8,
        clock=lambda: mono[0],
        wall_clock=lambda: wall[0],
    )
    store.advance(
        "session:one",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    store.advance(
        "session:one",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route(
            "visualize_affected_context",
            target_kind="motion_group",
            target_id="synthetic-affected",
            effects=("highlight_parts", "play_motion"),
        ),
        context_facts=_facts_with_motion(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    store.advance(
        "session:one",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("recommend_disposition"),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    partial = store.reconcile(
        "session:one",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
        receipts=[_receipt("receipt:highlight", tool_id="set_part_highlight")],
    )
    assert partial.event == "receipts_reconciled"
    assert partial.state["status"] == "active"
    reconciled = store.reconcile(
        "session:one",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
        receipts=[_receipt("receipt:motion", tool_id="play_motion")],
    )
    assert reconciled.state["status"] == "completed"
    assert reconciled.state["milestones"]["visualization_succeeded"] is True


def test_revision_change_preserves_scope_but_revalidates_stage_and_targets():
    state = _advance(
        None,
        _route("explain_assembly_impact", continue_existing=False),
        _facts(),
    )
    changed_revisions = dict(REVISIONS, faiRevision="fai-b")
    result = reconcile_workflow_state_v2(
        state,
        current_scope_fingerprint=SCOPE,
        current_revision_vector=changed_revisions,
        target_index={**TARGET_INDEX, "fai_characteristic": ["6"]},
        workflow_stages=STAGES,
        now_epoch=1010.0,
    )
    assert result.event == "same_scope_revision_advanced"
    assert result.state["objective"] == state["objective"]
    assert result.state["stage"] == "explain_part_function"
    assert "characteristic_numbers" not in result.state["entities"]
    assert not result.state["evidence_refs"]
    assert result.state["revision_vector"] == changed_revisions


def test_authorization_stage_receipts_become_audit_only_after_revision_change():
    state = _advance(
        None,
        _route(
            "visualize_affected_context",
            target_kind="motion_group",
            target_id="synthetic-affected",
            effects=("play_motion",),
            continue_existing=False,
        ),
        _facts_with_motion(),
    )
    state["last_execution_receipts"] = [_receipt()]
    changed = dict(REVISIONS, motionAssetPin="motion-b")
    result = reconcile_workflow_state_v2(
        state,
        current_scope_fingerprint=SCOPE,
        current_revision_vector=changed,
        target_index=TARGET_INDEX,
        workflow_stages=STAGES,
    )
    assert result.state["stage"] == "trace_assembly_impact"
    assert result.state["last_execution_receipts"] == []
    assert result.state["audit_receipts"][0]["receipt_id"] == "receipt:one"


def test_scope_change_and_expiry_drop_active_state():
    mono = [10.0]
    wall = [1000.0]
    store = WorkflowStateStore(
        ttl_seconds=60,
        max_sessions=8,
        clock=lambda: mono[0],
        wall_clock=lambda: wall[0],
    )
    store.advance(
        "session:scope",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    changed = store.reconcile(
        "session:scope",
        scope_fingerprint=OTHER_SCOPE,
        revision_vector=REVISIONS,
    )
    assert changed.state is None and changed.event == "scope_changed"

    store.advance(
        "session:expiry",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    mono[0] = 71.0
    wall[0] = 1061.0
    expired = store.reconcile(
        "session:expiry",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
    )
    assert expired.state is None and expired.event == "memory_expired"


def test_v2_browser_mirror_restores_only_for_matching_scope():
    source = WorkflowStateStore(
        ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1000.0
    )
    created = source.advance(
        "session:mirror",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    ).state
    restored = WorkflowStateStore(
        ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1001.0
    ).reconcile(
        "session:mirror",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        target_index=TARGET_INDEX,
        client_state=created,
    )
    assert restored.event == "restored_client_mirror"
    rejected = WorkflowStateStore(
        ttl_seconds=300, max_sessions=8, wall_clock=lambda: 1001.0
    ).reconcile(
        "session:mirror",
        scope_fingerprint=OTHER_SCOPE,
        revision_vector=REVISIONS,
        client_state=created,
    )
    assert rejected.state is None and rejected.event == "empty"


def test_v1_migration_rebuilds_trusted_identity_and_drops_authority():
    path = REPO_ROOT / "tests" / "fixtures" / "memory" / "workflow-state-v1-state.json"
    legacy = json.loads(path.read_text(encoding="ascii"))
    migrated = migrate_workflow_state_v1_to_v2(
        legacy,
        SCOPE,
        REVISIONS,
        TARGET_INDEX,
    )
    assert migrated["state_version"] == 2
    assert migrated["scope_fingerprint"] == SCOPE
    assert migrated["revision_vector"] == REVISIONS
    assert migrated["evidence_refs"] == []
    assert migrated["last_execution_receipts"] == []
    assert migrated["audit_receipts"]
    assert migrated["stage"] == "explain_part_function"
    assert migrate_workflow_state_v1_to_v2(legacy, None, REVISIONS, TARGET_INDEX) is None


def test_store_is_bounded_and_explicit_abandonment_is_narrow():
    store = WorkflowStateStore(ttl_seconds=300, max_sessions=2)
    for index in range(3):
        store.advance(
            f"session:{index}",
            scope_fingerprint=f"scope-v1:{index:064x}",
            revision_vector=REVISIONS,
            route=_route("assess_fai_characteristic", continue_existing=False),
            context_facts=_facts(),
            workflow_version="1.0.0",
            workflow_stages=STAGES,
        )
    assert store.stats()["entries"] == 2
    assert store.get("session:0") is None
    assert store.abandon("session:2").event == "abandoned:user_requested"
    assert server._workflow_abandonment_requested("cancel this workflow") is True
    assert server._workflow_abandonment_requested("start over") is True
    assert server._workflow_abandonment_requested("stop the motion") is False


def test_server_scope_ignores_viewport_and_revision_changes_do_not_change_scope():
    base = {
        "part_number": "SYNTH-P1",
        "revision": "A",
        "assembly_number": "SYNTH-A1",
        "active_assembly_config": "Default",
        "asset_identity": {"fai_revision": "A", "motion_asset_pin": "abc"},
        "viewport_context": {
            "motion": {"motions": [{"motion_id": "synthetic-cycle"}]},
            "state": {"active_tab": "report", "motion_playing": False},
        },
    }
    changed_view = json.loads(json.dumps(base))
    changed_view["viewport_context"]["state"] = {
        "active_tab": "assembly",
        "motion_playing": True,
        "highlighted": ["SYNTH-P1"],
    }
    base_scope, base_revisions = server._workflow_scope_and_revision(base)
    view_scope, view_revisions = server._workflow_scope_and_revision(changed_view)
    assert (base_scope, base_revisions) == (view_scope, view_revisions)
    changed_revision = json.loads(json.dumps(base))
    changed_revision["revision"] = "B"
    next_scope, next_revisions = server._workflow_scope_and_revision(changed_revision)
    assert next_scope == base_scope
    assert next_revisions != base_revisions


def test_server_normalization_prompt_and_mirror_use_validated_v2_state():
    state = _advance(
        None,
        _route("explain_assembly_impact", continue_existing=False),
        _facts(),
        now=time.time(),
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
    assert normalized["skill_workflow_state"]["stage"] == "trace_assembly_impact"
    plan, reason = server._compose_production_skill_prompt(
        {
            **_route(
                "explain_motion",
                target_kind="motion_group",
                target_id="synthetic-affected",
            ),
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
    assert server._validated_workflow_state_mirror(
        state, SCOPE, REVISIONS, TARGET_INDEX
    ) is not None
    unknown = dict(state, workflow_id="invented-workflow")
    assert sanitize_workflow_state(
        unknown,
        expected_scope_fingerprint=SCOPE,
        now_epoch=1001.0,
    )
    assert server._validated_workflow_state_mirror(
        unknown, SCOPE, REVISIONS, TARGET_INDEX
    ) is None


def test_shadow_and_production_state_are_isolated_and_status_remains_visible():
    assert server._SKILL_WORKFLOW_STATE_STORE is not (
        server._SKILL_WORKFLOW_STATE_SHADOW_STORE
    )
    server._SKILL_WORKFLOW_STATE_STORE.reset()
    server._SKILL_WORKFLOW_STATE_SHADOW_STORE.reset()
    server._SKILL_WORKFLOW_STATE_SHADOW_STORE.advance(
        "session:isolated",
        scope_fingerprint=SCOPE,
        revision_vector=REVISIONS,
        route=_route("assess_fai_characteristic", continue_existing=False),
        context_facts=_facts(),
        workflow_version="1.0.0",
        workflow_stages=STAGES,
    )
    assert server._SKILL_WORKFLOW_STATE_SHADOW_STORE.get("session:isolated") is not None
    assert server._SKILL_WORKFLOW_STATE_STORE.get("session:isolated") is None

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


def test_workflow_state_schema_is_ascii_closed_and_v2_only():
    path = (
        REPO_ROOT
        / "ai_inspector"
        / "agent_skills"
        / "schemas"
        / "workflow-state.schema.json"
    )
    raw = path.read_bytes()
    assert all(byte < 128 for byte in raw)
    schema = json.loads(raw.decode("ascii"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["state_version"]["const"] == 2
    assert "scope_fingerprint" in schema["required"]
    assert "revision_vector" in schema["required"]


def test_every_registered_workflow_stage_has_revision_policy() -> None:
    server._reset_agent_skill_runtime_cache_for_tests()
    workflows, _skills = server._get_agent_skill_runtime()
    assert set(workflows.ids) == set(WORKFLOW_STAGE_POLICIES)
    for workflow_id in workflows.ids:
        package = workflows.get(workflow_id)
        policy = WORKFLOW_STAGE_POLICIES[workflow_id]
        assert package.manifest.version == policy.version
        assert tuple(package.manifest.stages) == tuple(policy.stages)
        for stage_name, stage in policy.stages.items():
            assert stage.dependencies
            if stage.authorization_kind in AUTHORIZATION_KINDS:
                assert stage.safe_predecessor in policy.stages, stage_name


def _run_without_pytest() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
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
