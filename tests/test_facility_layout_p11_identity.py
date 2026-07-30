from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_inspector.facility_layout.feature_flags import (
    FacilityLayoutFeatureFlags,
)
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.identity import (
    FACILITY_IDENTITY_CONFIG_ENV,
    FACILITY_MAKER_CHECKER_ENV,
    FacilityIdentityConfigurationError,
    FacilityPrincipalResolver,
    maker_checker_required_from_environment,
)
from ai_inspector.facility_layout.transaction_adapter import (
    facility_transaction_principal,
)


MAKER_TOKEN = "maker-p11-token-" + ("m" * 48)
CHECKER_TOKEN = "checker-p11-token-" + ("c" * 48)
ROOT = Path(__file__).resolve().parents[1]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _identity_config(
    *,
    maker_hash: str | None = None,
    checker_hash: str | None = None,
) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "principals": [
                {
                    "tokenSha256": maker_hash or _digest(MAKER_TOKEN),
                    "principalId": "maker-p11",
                    "tenantId": "local",
                    "allowedSiteIds": [LOCAL_SITE_ID],
                    "roles": ["layout_admin"],
                },
                {
                    "tokenSha256": checker_hash or _digest(CHECKER_TOKEN),
                    "principalId": "checker-p11",
                    "tenantId": "local",
                    "allowedSiteIds": [LOCAL_SITE_ID],
                    "roles": ["approver"],
                },
            ],
        },
        separators=(",", ":"),
    )


def _resolver(
    *,
    require_authenticated: bool = True,
) -> FacilityPrincipalResolver:
    return FacilityPrincipalResolver.from_environment(
        site_id=LOCAL_SITE_ID,
        environ={
            FACILITY_IDENTITY_CONFIG_ENV: _identity_config(),
        },
        require_authenticated=require_authenticated,
    )


def _auth(token: str, *, session: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if session is not None:
        headers["X-InspectorPro-Session"] = session
    return headers


def _planner_request(bootstrap: dict) -> dict:
    layout = bootstrap["layout"]["layout"]
    asset = bootstrap["assetCatalog"][0]
    return {
        "schemaVersion": 1,
        "requestId": "p11-product-principal-ingress",
        "objective": "place_asset_set",
        "assetSet": [
            {
                "itemId": "p11-product-principal-ingress-item",
                "assetId": asset["assetId"],
                "assetDefinitionRevision": (
                    asset["assetDefinitionRevision"]
                ),
                "quantity": 1,
                "stage": 0,
            }
        ],
        "strategies": ["compact_rows"],
        "maximumAlternatives": 1,
        "spacingMeters": 1.0,
        "cleanup": {
            "enabled": False,
            "moveAuto": True,
            "movableManualPlacementIds": [],
        },
        "zoneSizing": [],
        "routes": [],
        "sourceRevisions": {
            "shell": layout["sourceShellRef"]["shellRevision"],
            "policy": layout["policySetRef"]["policySetRevision"],
        },
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        (" TRUE ", True),
    ],
)
def test_maker_checker_environment_boolean_is_strict(value, expected):
    assert maker_checker_required_from_environment(
        {FACILITY_MAKER_CHECKER_ENV: value}
    ) is expected


def test_maker_checker_environment_rejects_unknown_value():
    with pytest.raises(
        FacilityIdentityConfigurationError,
        match="boolean value",
    ):
        maker_checker_required_from_environment(
            {FACILITY_MAKER_CHECKER_ENV: "enabled"}
        )


def test_identity_configuration_requires_distinct_pilot_principals():
    with pytest.raises(
        FacilityIdentityConfigurationError,
        match="is required",
    ):
        FacilityPrincipalResolver.from_environment(
            site_id=LOCAL_SITE_ID,
            environ={},
            require_authenticated=True,
        )

    one_identity = json.dumps(
        {
            "schemaVersion": 1,
            "principals": [
                {
                    "tokenSha256": _digest(MAKER_TOKEN),
                    "principalId": "maker-p11",
                    "tenantId": "local",
                    "allowedSiteIds": [LOCAL_SITE_ID],
                    "roles": ["layout_admin"],
                }
            ],
        }
    )
    with pytest.raises(
        FacilityIdentityConfigurationError,
        match="distinct configured",
    ):
        FacilityPrincipalResolver.from_environment(
            site_id=LOCAL_SITE_ID,
            environ={FACILITY_IDENTITY_CONFIG_ENV: one_identity},
            require_authenticated=True,
        )


@pytest.mark.parametrize(
    "config",
    [
        _identity_config(
            checker_hash=_digest(MAKER_TOKEN),
        ),
        _identity_config(
            maker_hash=_digest(MAKER_TOKEN).upper(),
        ),
        json.dumps(
            {
                "schemaVersion": 1,
                "principals": [],
            }
        ),
        json.dumps(
            {
                "schemaVersion": 1,
                "principals": [
                    {
                        "tokenSha256": _digest(MAKER_TOKEN),
                        "principalId": "maker-p11",
                        "tenantId": "other",
                        "allowedSiteIds": [LOCAL_SITE_ID],
                        "roles": ["editor"],
                    }
                ],
            }
        ),
    ],
)
def test_identity_configuration_rejects_ambiguous_or_unsafe_rows(config):
    with pytest.raises(FacilityIdentityConfigurationError):
        FacilityPrincipalResolver.from_environment(
            site_id=LOCAL_SITE_ID,
            environ={FACILITY_IDENTITY_CONFIG_ENV: config},
        )


def test_maker_checker_host_rejects_local_principal_mode(tmp_path):
    with pytest.raises(
        ValueError,
        match="authenticated Facility pilot principal resolver",
    ):
        LocalFacilityLayoutHost(
            tmp_path / "facility",
            require_distinct_approver=True,
        )
    with pytest.raises(
        ValueError,
        match="authenticated Facility pilot principal resolver",
    ):
        LocalFacilityLayoutHost(
            tmp_path / "custom-facility",
            require_distinct_approver=True,
            principal_resolver=lambda _request: None,
        )


def test_product_server_fails_closed_without_pilot_identities():
    environment = os.environ.copy()
    environment[FACILITY_MAKER_CHECKER_ENV] = "1"
    environment[FACILITY_IDENTITY_CONFIG_ENV] = ""
    completed = subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert completed.returncode != 0
    assert FACILITY_IDENTITY_CONFIG_ENV in (
        completed.stdout + completed.stderr
    )


def test_product_server_composes_authenticated_pilot_host():
    environment = os.environ.copy()
    environment[FACILITY_MAKER_CHECKER_ENV] = "1"
    environment[FACILITY_IDENTITY_CONFIG_ENV] = _identity_config()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import server; "
                "host=server._FACILITY_LAYOUT_HOST; "
                "print(host.principal_mode, "
                "host.require_distinct_approver); "
                "host.close()"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, (
        completed.stdout + completed.stderr
    )
    assert "bearer True" in completed.stdout


def test_sage_ingress_preserves_facility_authentication_challenge():
    environment = os.environ.copy()
    environment[FACILITY_MAKER_CHECKER_ENV] = "1"
    environment[FACILITY_IDENTITY_CONFIG_ENV] = _identity_config()
    environment["INSPECTORPRO_SKILLS_SHADOW"] = "1"
    environment["INSPECTORPRO_SAGE_PROVIDER"] = "anthropic"
    environment["ANTHROPIC_API_KEY"] = "test-not-real"
    probe = """
from fastapi.testclient import TestClient
import server

reference = {
    "siteId": "site-local",
    "layoutId": "fl-main",
    "revision": "0" * 64,
}
context = {"attachments": {"facility_layout": reference}}
with TestClient(server.app) as client:
    chat = client.post(
        "/api/agent/chat",
        json={
            "message": "Inspect this layout.",
            "agent_type": "deviation-analyst",
            "inspection_context": context,
        },
    )
    route = client.post(
        "/api/internal/agent-skills/test-route",
        json={
            "message": "Inspect this layout.",
            "agent": "sage",
            "inspection_context": context,
        },
    )
    assert chat.status_code == 401, chat.text
    assert route.status_code == 401, route.text
    assert chat.headers.get("www-authenticate") == "Bearer"
    assert route.headers.get("www-authenticate") == "Bearer"
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, (
        completed.stdout + completed.stderr
    )


def test_product_host_authenticates_and_separates_maker_checker(tmp_path):
    resolver = _resolver()
    host = LocalFacilityLayoutHost(
        tmp_path / "facility",
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        require_distinct_approver=True,
        principal_resolver=resolver,
    )
    app = FastAPI()
    app.include_router(host.create_router())

    with TestClient(app) as client:
        unauthenticated = client.get("/api/facility-layout-bootstrap")
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["www-authenticate"] == "Bearer"
        assert client.get(
            "/api/facility-layout-bootstrap",
            headers=_auth("x" * 48),
        ).status_code == 401

        maker_bootstrap_response = client.get(
            "/api/facility-layout-bootstrap",
            headers=_auth(MAKER_TOKEN),
        )
        assert maker_bootstrap_response.status_code == 200
        bootstrap = maker_bootstrap_response.json()
        assert bootstrap["capabilities"]["principalAuthentication"] == (
            "bearer"
        )
        assert bootstrap["capabilities"]["makerCheckerRequired"] is True
        assert bootstrap["principal"]["principalId"] == "maker-p11"
        assert bootstrap["principalCapabilities"]["semanticPreview"] is True

        layout_url = (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        )
        created = client.post(
            layout_url + "/proposals",
            headers=_auth(MAKER_TOKEN),
            json={
                "baseRevision": bootstrap["layout"]["revision"],
                "request": _planner_request(bootstrap),
            },
        )
        assert created.status_code == 200, created.text
        selected = created.json()["alternatives"][0]
        approval_body = {
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p11-product-principal-apply",
            "explicitApproval": True,
        }

        same_maker = client.post(
            layout_url + "/approvals",
            headers=_auth(MAKER_TOKEN, session="maker-session"),
            json=approval_body,
        )
        assert same_maker.status_code == 403
        assert same_maker.json()["error"]["code"] == (
            "maker_checker_required"
        )

        checker_approval = client.post(
            layout_url + "/approvals",
            headers=_auth(CHECKER_TOKEN, session="checker-session"),
            json=approval_body,
        )
        assert checker_approval.status_code == 200, checker_approval.text
        approval = checker_approval.json()
        applied = client.post(
            layout_url + "/apply",
            headers=_auth(CHECKER_TOKEN, session="checker-session"),
            json={
                "approvalToken": approval["approvalToken"],
                "binding": selected["transactionBinding"],
                "idempotencyKey": "p11-product-principal-apply",
            },
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["receipt"]["principal"]["principalId"] == (
            facility_transaction_principal(
                "local",
                "checker-p11",
                "checker-session",
            ).principal_id
        )
