"""Dedicated packaging permissions keep every role's access exactly as before (P5 permission gap).

Synthetic principals and a throwaway store only; no carrier or network access.
"""
from __future__ import annotations

from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from ai_inspector.facility_layout.authorization import KNOWN_ROLES, FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.permissions import ACCOUNT, DERIVED_FROM, EDIT, QUOTE, READ, granted, permits
from ai_inspector.packaging_shipping.service import PackagingService

ALL = {READ, EDIT, QUOTE, ACCOUNT}
# What each frozen Facility Layout role could do in packaging before the dedicated names existed.
EXPECTED = {"viewer": {READ}, "editor": ALL, "approver": {READ}, "catalog_curator": set(), "authority_curator": set(),
            "admin": ALL, "layout_admin": ALL, "facility_authority_admin": set()}
QUOTE_ROUTES = {("POST", "/api/packaging/documents/{doc_id}/quotes"), ("POST", "/api/packaging/documents/{doc_id}/alternatives/{alt_id}/quotes"),
                ("POST", "/api/packaging/documents/{doc_id}/scenarios"), ("DELETE", "/api/packaging/documents/{doc_id}/scenarios/{scenario_id}")}
ACCOUNT_ROUTES = {("PUT", "/api/packaging/account"), ("DELETE", "/api/packaging/account"), ("POST", "/api/packaging/account/carrier-accounts")}


def principal(*roles):
    return FacilityPrincipal(principal_id="test-user", tenant_id="test-tenant", allowed_site_ids=("test",), roles=roles)


def test_every_role_keeps_its_previous_packaging_access():
    assert set(EXPECTED) == set(KNOWN_ROLES)
    for role in sorted(KNOWN_ROLES):
        p = principal(role)
        assert set(granted(p)) == EXPECTED[role], role
        for action, legacy in DERIVED_FROM.items():
            assert permits(p, action) == p.permits(legacy), (role, action)
    assert set(granted(principal("viewer", "editor"))) == ALL


def test_unknown_actions_and_foreign_principals_are_refused():
    with pytest.raises(ValueError):
        permits(principal("admin"), "packaging.purchase")
    for foreign in (None, object(), {"roles": ["admin"]}):
        assert not permits(foreign, READ) and granted(foreign) == []


def routes(tmp_path):
    app = FastAPI()
    current = {"principal": principal("admin")}
    app.include_router(create_router(PackagingService(tmp_path / "store"), principal_resolver=lambda _request: current["principal"],
                                     static_root=Path("static")))
    found = [(method, route.path) for route in app.routes if isinstance(route, APIRoute)
             and (route.path.startswith("/api/packaging") or route.path == "/packaging") for method in sorted(route.methods)]
    return app, current, found


def concrete(path):
    return re.sub(r"\{[a-z_]+\}", "test_x", path)


ROLE_DENIED = "Your application role does not permit this operation."


def refused(client, method, path):
    """True only for the permission refusal; other 403s (such as no carrier store on this host) are business rules."""
    response = client.request(method, concrete(path), json={}, headers={"X-InspectorPro-Request": "packaging"})
    return response.status_code == 403 and response.json().get("detail") == ROLE_DENIED


def test_routes_require_the_dedicated_action_for_each_method(tmp_path):
    app, current, found = routes(tmp_path)
    assert QUOTE_ROUTES | ACCOUNT_ROUTES <= set(found)
    assert any(method == "GET" for method, _ in found) and any(method != "GET" for method, _ in found)
    with TestClient(app) as client:
        for role, expected in EXPECTED.items():
            current["principal"] = principal(role)
            for method, path in found:
                needed = QUOTE if (method, path) in QUOTE_ROUTES else ACCOUNT if (method, path) in ACCOUNT_ROUTES \
                    else READ if method in {"GET", "HEAD"} else EDIT
                allowed = READ in expected and needed in expected
                assert refused(client, method, path) != allowed, (role, method, path)


def test_status_reports_the_principal_permissions(tmp_path):
    app, current, _ = routes(tmp_path)
    with TestClient(app) as client:
        current["principal"] = principal("viewer")
        assert client.get("/api/packaging/status").json()["permissions"] == [READ]
        current["principal"] = principal("editor")
        assert client.get("/api/packaging/status").json()["permissions"] == [READ, EDIT, QUOTE, ACCOUNT]


def test_quote_and_account_routes_ask_for_their_own_action(tmp_path, monkeypatch):
    # Remap the derivations so the three write actions differ; each route must follow its own.
    monkeypatch.setitem(DERIVED_FROM, QUOTE, "proposal.approve")  # approver: read and quote only
    monkeypatch.setitem(DERIVED_FROM, ACCOUNT, "proposal.create")  # editor: read, edit and account, no quote
    app, current, found = routes(tmp_path)
    with TestClient(app) as client:
        current["principal"] = principal("approver")
        assert set(granted(current["principal"])) == {READ, QUOTE}
        for method, path in found:
            assert refused(client, method, path) == (method != "GET" and (method, path) not in QUOTE_ROUTES), (method, path)
        current["principal"] = principal("editor")
        assert set(granted(current["principal"])) == {READ, EDIT, ACCOUNT}
        for method, path in found:
            assert refused(client, method, path) == ((method, path) in QUOTE_ROUTES), (method, path)
