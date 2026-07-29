from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.authorization import (
    KNOWN_ROLES,
    ROLE_ACTIONS,
    AuthorizationDecision,
    FacilityNotFoundError,
    FacilityPrincipal,
    FacilityPrincipalValidationError,
    FacilityRoleNotAuthorizedError,
    authorize_facility_action,
    local_facility_principal,
    require_facility_action,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "static" / "contracts" / "facility-layout-authorization-v1.json"
)


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="ascii"))


def _principal(
    *,
    tenant: str = "tenant-a",
    sites: tuple[str, ...] = ("site-a",),
    roles: tuple[str, ...] = ("viewer",),
) -> FacilityPrincipal:
    return FacilityPrincipal(
        principal_id="principal-a",
        tenant_id=tenant,
        allowed_site_ids=sites,
        roles=roles,
    )


def test_frozen_role_matrix_is_exact_and_aliases_are_additive():
    expected = {
        role: frozenset(actions)
        for role, actions in _contract()["roles"].items()
    }
    assert ROLE_ACTIONS == expected
    assert {
        "viewer",
        "editor",
        "approver",
        "catalog_curator",
        "authority_curator",
        "admin",
        "layout_admin",
        "facility_authority_admin",
    } == KNOWN_ROLES


@pytest.mark.parametrize("case", _contract()["cases"], ids=lambda item: item["caseId"])
def test_frozen_authorization_cases(case):
    raw = case["principal"]
    principal = FacilityPrincipal(
        principal_id=f"principal-{case['caseId']}",
        tenant_id=raw["tenantId"],
        allowed_site_ids=tuple(raw["siteIds"]),
        roles=tuple(raw["roles"]),
    )
    request = case["request"]
    decision = authorize_facility_action(
        principal,
        tenant_id=request["tenantId"],
        site_id=request["siteId"],
        action=request["action"],
    )
    if case["reason"] in {"not_found", "role_not_authorized"}:
        expected = AuthorizationDecision(False, case["reason"])
    else:
        # Exact approval payload validation belongs to the transaction gate.
        expected = AuthorizationDecision(True, "authorized")
    assert decision == expected


def test_authorization_layer_owns_scope_and_role_but_not_approval_payload():
    approver = _principal(roles=("approver",))
    decision = authorize_facility_action(
        approver,
        tenant_id="tenant-a",
        site_id="site-a",
        action="proposal.apply",
    )
    assert decision == AuthorizationDecision(True, "authorized")


def test_cross_tenant_cross_site_and_malformed_scope_are_indistinguishable():
    principal = _principal(sites=("site-a", "site-c"))
    failures = (
        {"tenant_id": "tenant-b", "site_id": "site-a"},
        {"tenant_id": "tenant-a", "site_id": "site-b"},
        {"tenant_id": "../tenant-a", "site_id": "site-a"},
        {"tenant_id": "tenant-a", "site_id": "../site-a"},
    )
    messages = set()
    for values in failures:
        with pytest.raises(FacilityNotFoundError) as captured:
            require_facility_action(
                principal,
                action="authority.read",
                **values,
            )
        assert captured.value.code == "not_found"
        messages.add(str(captured.value))
    assert messages == {"Facility resource was not found."}


def test_role_failure_remains_distinct_after_valid_scope():
    principal = _principal(roles=("viewer",))
    with pytest.raises(FacilityRoleNotAuthorizedError) as captured:
        require_facility_action(
            principal,
            tenant_id="tenant-a",
            site_id="site-a",
            action="authority.publish",
        )
    assert captured.value.code == "role_not_authorized"


def test_layout_admin_is_exact_editor_plus_approver_alias():
    principal = _principal(roles=("layout_admin",))
    expected = ROLE_ACTIONS["editor"] | ROLE_ACTIONS["approver"]
    assert principal.action_set == expected
    assert principal.permits("layout.edit")
    assert principal.permits("proposal.apply")
    assert not principal.permits("authority.publish")
    assert not principal.permits("catalog.publish")


def test_facility_authority_admin_is_exact_curator_alias():
    principal = _principal(roles=("facility_authority_admin",))
    assert principal.action_set == ROLE_ACTIONS["authority_curator"]
    assert principal.permits("authority.create")
    assert principal.permits("authority.publish")
    assert not principal.permits("catalog.publish")
    assert not principal.permits("proposal.apply")


def test_admin_wildcard_does_not_bypass_scope():
    principal = _principal(roles=("admin",))
    assert principal.permits("future.action")
    with pytest.raises(FacilityNotFoundError):
        require_facility_action(
            principal,
            tenant_id="tenant-b",
            site_id="site-b",
            action="future.action",
        )


def test_principal_mapping_accepts_contract_site_spelling():
    principal = FacilityPrincipal.from_mapping(
        {
            "principalId": "principal-a",
            "tenantId": "tenant-a",
            "siteIds": ["site-b", "site-a"],
            "roles": ["viewer"],
        }
    )
    assert principal.allowed_site_ids == ("site-a", "site-b")
    assert principal.site_ids == ("site-a", "site-b")


@pytest.mark.parametrize(
    "kwargs",
    (
        {
            "principal_id": "../principal",
            "tenant_id": "tenant-a",
            "allowed_site_ids": ("site-a",),
            "roles": ("viewer",),
        },
        {
            "principal_id": "principal-a",
            "tenant_id": "tenant-a",
            "allowed_site_ids": ("site-a", "site-a"),
            "roles": ("viewer",),
        },
        {
            "principal_id": "principal-a",
            "tenant_id": "tenant-a",
            "allowed_site_ids": ("site-a",),
            "roles": ("unknown-role",),
        },
    ),
)
def test_invalid_principal_is_rejected(kwargs):
    with pytest.raises(FacilityPrincipalValidationError) as captured:
        FacilityPrincipal(**kwargs)
    assert captured.value.code == "invalid_principal"


def test_local_mode_uses_an_explicit_principal_and_normal_checks():
    principal = local_facility_principal(site_id="local-site")
    assert principal.principal_id == "local-user"
    assert principal.tenant_id == "local"
    require_facility_action(
        principal,
        tenant_id="local",
        site_id="local-site",
        action="authority.publish",
    )
    with pytest.raises(FacilityNotFoundError):
        require_facility_action(
            principal,
            tenant_id="local",
            site_id="other-site",
            action="authority.publish",
        )
