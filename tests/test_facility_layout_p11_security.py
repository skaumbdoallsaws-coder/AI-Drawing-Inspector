from __future__ import annotations

from pathlib import Path

from ai_inspector.facility_layout.authorization import (
    FacilityPrincipal,
    ROLE_ACTIONS,
    authorize_facility_action,
)
from tools.verify_facility_layout_p11 import ROOT, build_suite_matrix


def test_security_orchestration_covers_every_p11_authority_boundary():
    matrix = build_suite_matrix()
    coverage = {
        item
        for suite in matrix["suites"]
        for item in suite["coverage"]
    }
    assert set(matrix["requiredCoverage"]) <= coverage
    assert {
        "rbac",
        "principal_authentication",
        "idor",
        "tool_authorization",
        "explicit_approval",
        "stale_revision",
        "exact_diff",
        "replay",
        "receipt",
    } <= coverage
    for suite in matrix["suites"]:
        command_paths = [
            ROOT / item
            for item in suite["command"]
            if isinstance(item, str)
            and (
                item.startswith("tests/")
                or item.startswith("tests\\")
            )
        ]
        assert command_paths
        assert all(path.exists() for path in command_paths)


def test_required_stale_idor_replay_and_tool_tests_remain_named():
    required = {
        "tests/test_facility_layout_authorization.py": [
            "test_cross_tenant_cross_site_and_malformed_scope_are_indistinguishable",
            "test_admin_wildcard_does_not_bypass_scope",
        ],
        "tests/test_facility_layout_p11_identity.py": [
            "test_product_host_authenticates_and_separates_maker_checker",
            "test_maker_checker_host_rejects_local_principal_mode",
        ],
        "tests/test_facility_layout_proposals.py": [
            "test_product_proposal_preview_is_pure_and_apply_is_exact",
            "test_proposal_owner_and_tenant_site_target_fail_closed",
            "test_stale_layout_and_wrong_session_fail_closed",
            "test_proposal_binding_and_consent_are_exact",
            "test_editor_and_approver_authority_remain_separate",
            "test_unapproved_proposal_authority_fails_closed_after_restart",
        ],
        "tests/test_facility_layout_agent_runtime.py": [
            "test_context_reloads_authorities_and_discards_browser_geometry",
            "test_stale_revision_rejects_before_observation",
            "test_per_turn_read_budget_fails_closed",
            "test_model_authored_coordinates_are_rejected_before_p8",
        ],
    }
    for relative, names in required.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        for name in names:
            assert f"def {name}" in source


def test_read_only_principal_has_no_write_or_proposal_capability():
    principal = FacilityPrincipal(
        principal_id="p11-viewer",
        tenant_id="tenant-a",
        allowed_site_ids=("site-a",),
        roles=("viewer",),
    )
    assert principal.action_set == ROLE_ACTIONS["viewer"]
    assert not any(
        principal.permits(action)
        for action in (
            "layout.create",
            "layout.edit",
            "proposal.create",
            "proposal.approve",
            "proposal.apply",
        )
    )
    cross_scope = authorize_facility_action(
        principal,
        tenant_id="tenant-b",
        site_id="site-b",
        action="layout.read",
    )
    assert cross_scope.authorized is False
    assert cross_scope.reason == "not_found"
