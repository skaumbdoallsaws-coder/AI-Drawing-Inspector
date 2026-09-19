"""Contract checks for Sage's hierarchical Facility Layout skill."""

from __future__ import annotations

from pathlib import Path

from ai_inspector.agent_skills import SkillRegistry, WorkflowRegistry
from ai_inspector.prompts import compile_skill_context


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "ai_inspector" / "agent_skills"
WORKFLOW_ROOT = ROOT / "ai_inspector" / "agent_workflows"

FACILITY_TOOLS = {
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
    "preview_facility_move",
    "build_facility_layout_preview",
    "generate_full_factory_draft",
    "generate_facility_planning_prototype_draft",
    "amend_facility_program_resource_batch_draft",
    "observe_navigation_context",
    "compile_navigation_snapshot",
    "plan_actor_journey",
    "validate_actor_journey",
    "compare_journey_alternatives",
    "propose_navigation_intent",
    "build_activity_scenario",
}


def _package():
    workflows = WorkflowRegistry.from_roots(
        [WORKFLOW_ROOT],
        known_agents={"sage", "iris", "scout"},
    )
    registry = SkillRegistry.from_roots(
        [SKILL_ROOT],
        workflow_ids=set(workflows.ids),
        known_agents={"sage", "iris", "scout"},
        known_modes={
            "report_fai",
            "report",
            "drawing",
            "assembly",
            "training",
            "facility_layout",
        },
    )
    return registry.get("generate-facility-layout")


def test_factory_playbook_loads_as_the_authoritative_facility_skill() -> None:
    package = _package()

    assert package.manifest.version == "1.10.0"
    assert package.contract is not None
    assert package.contract.version == package.manifest.version
    assert set(package.manifest.allowed_tools) == FACILITY_TOOLS
    assert package.manifest.side_effects == ()
    assert package.contract.explicit_request_tools == (
        "preview_facility_move",
        "build_facility_layout_preview",
        "generate_full_factory_draft",
        "generate_facility_planning_prototype_draft",
        "amend_facility_program_resource_batch_draft",
        "propose_navigation_intent",
        "build_activity_scenario",
    )
    assert package.manifest.requires_context == ("facility_layout.digest",)
    assert set(package.manifest.optional_context) == {
        "facility_layout.state",
        "facility_layout.evidence",
    }
    assert package.contract.required_evidence == (
        "facility_layout_digest",
    )


def test_factory_playbook_encodes_macro_to_micro_planning_in_order() -> None:
    body = _package().body.lower()
    headings = [
        "establish the design basis",
        "build the macro zone hierarchy",
        "establish flow and access",
        "populate departments and cells",
        "choose deterministic layout alternatives",
        "check completeness before preview",
        "bounded verification and correction",
    ]

    positions = [body.index(heading) for heading in headings]
    assert positions == sorted(positions)
    for phrase in (
        "greenfield, brownfield",
        "workcell",
        "floor markings",
        "manual or locked",
        "exact quantities",
        "at most two repairs",
        "one complete ghost preview",
    ):
        assert phrase in body


def test_factory_playbook_names_limits_instead_of_simulating_ui_actions() -> None:
    body = _package().body.lower()
    prose = " ".join(body.split())

    assert "do not imitate the user's manual clicks" in prose
    assert "semantic plan v1 does not author arbitrary marking geometry" in prose
    assert "stack or named support surface attachments" in prose
    assert "do not silently relax a rule" in prose
    for forbidden_tool in (
        "place_asset",
        "add_floor_marking",
        "move_placement",
        "add_zone",
    ):
        assert f"`{forbidden_tool}`" not in body


def test_large_layout_uses_digest_and_omits_full_optional_providers() -> None:
    package = _package()
    compiled = compile_skill_context(
        {
            "_user_message": "Review the current large factory layout.",
            "active_mode": "training",
            "facility_layout_digest": {
                "identity": {
                    "siteId": "site-large",
                    "layoutId": "layout-large",
                    "revision": "a" * 64,
                },
                "counts": {"placements": 2000, "zones": 40},
                "readDescriptors": [
                    {
                        "tool": "inspect_facility_entities",
                        "entityKind": "placements",
                    }
                ],
            },
            "facility_layout_state": {
                "placements": [
                    {
                        "placementId": f"placement-{index}",
                        "notes": "x" * 200,
                    }
                    for index in range(2000)
                ]
            },
            "facility_layout_evidence": {
                "records": [
                    {
                        "evidenceId": f"evidence-{index}",
                        "detail": "y" * 200,
                    }
                    for index in range(1000)
                ]
            },
        },
        [package],
        mode="training",
    )

    assert "facility_layout_digest" in compiled.context
    assert "facility_layout_state" not in compiled.context
    assert "facility_layout_evidence" not in compiled.context
    assert compiled.accounting["budget"]["budget_exceeded"] is False
    providers = {
        item["contextKey"]: item
        for item in compiled.accounting["providers"]
    }
    assert providers["facility_layout.digest"]["required"] is True
    assert providers["facility_layout.digest"]["included"] is True
    assert providers["facility_layout.state"]["required"] is False
    assert providers["facility_layout.state"]["included"] is False
    assert providers["facility_layout.evidence"]["required"] is False
    assert providers["facility_layout.evidence"]["included"] is False
