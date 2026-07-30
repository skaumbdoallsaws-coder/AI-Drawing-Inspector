from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.facility_layout.feature_flags import (
    FacilityLayoutFeatureFlags,
)


PROTECTED_PATHS = (
    "/api/facility-layout-bootstrap",
    "/api/facility-layouts/site-local",
    "/api/facility-layout-policy",
    "/api/facility-shell",
    "/api/industrial-assets",
    "/api/industrial-assets/asset-rack",
    "/api/training/facility-layout/semantic",
)


def test_hostile_origin_cannot_read_or_write_product_facility_routes(
    monkeypatch,
):
    monkeypatch.setattr(
        server._FACILITY_LAYOUT_HOST,
        "feature_flags",
        FacilityLayoutFeatureFlags.all_enabled(),
    )
    client = TestClient(server.app, base_url="http://testserver")

    baseline = client.get("/api/facility-layout-bootstrap")
    assert baseline.status_code == 200
    before = baseline.json()["layout"]
    before_revision = before["revision"]
    before_document = before["layout"]

    hostile_headers = {"Origin": "https://attacker.example"}
    blocked_read = client.get(
        "/api/facility-layout-bootstrap",
        headers=hostile_headers,
    )
    assert blocked_read.status_code == 403
    assert blocked_read.json()["error"]["code"] == "facility_origin_forbidden"

    preflight = client.options(
        "/api/facility-layouts/site-local/fl-main",
        headers={
            **hostile_headers,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 403
    assert "access-control-allow-origin" not in {
        key.casefold(): value for key, value in preflight.headers.items()
    }

    blocked_write = client.put(
        "/api/facility-layouts/site-local/fl-main",
        headers=hostile_headers,
        json={
            "baseRevision": before_revision,
            "operations": [
                {
                    "op": "rename_layout",
                    "displayName": "Hostile Rename",
                }
            ],
        },
    )
    assert blocked_write.status_code == 403
    assert blocked_write.json()["error"]["code"] == (
        "facility_origin_forbidden"
    )

    after = client.get("/api/facility-layout-bootstrap").json()["layout"]
    assert after["revision"] == before_revision
    assert after["layout"] == before_document


def test_forged_host_and_matching_origin_are_rejected():
    client = TestClient(server.app, base_url="http://testserver")
    response = client.get(
        "/api/facility-layout-bootstrap",
        headers={
            "Host": "attacker.example",
            "Origin": "http://attacker.example",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "facility_origin_forbidden"


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_every_facility_authority_path_rejects_hostile_origins(path: str):
    client = TestClient(server.app, base_url="http://testserver")
    response = client.get(
        path,
        headers={
            "Host": "attacker.example",
            "Origin": "http://attacker.example",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "facility_origin_forbidden"


def test_no_origin_non_browser_client_remains_available():
    client = TestClient(server.app, base_url="http://testserver")
    response = client.get(
        "/api/facility-layout-bootstrap",
        headers={"Host": "unconfigured-client.example"},
    )
    assert response.status_code == 200


def test_loopback_and_explicit_trust_configuration_remain_available(
    monkeypatch,
):
    loopback_client = TestClient(
        server.app,
        base_url="http://127.0.0.1:8023",
    )
    loopback = loopback_client.get(
        "/api/facility-layout-bootstrap",
        headers={"Origin": "http://127.0.0.1:3000"},
    )
    assert loopback.status_code == 200
    assert loopback.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:3000"
    )

    monkeypatch.setenv(
        "INSPECTORPRO_ALLOWED_ORIGINS",
        "https://trusted.example",
    )
    client = TestClient(server.app, base_url="http://testserver")
    trusted_origin = client.get(
        "/api/facility-layout-bootstrap",
        headers={"Origin": "https://trusted.example"},
    )
    assert trusted_origin.status_code == 200

    monkeypatch.delenv("INSPECTORPRO_ALLOWED_ORIGINS")
    monkeypatch.setenv(
        "INSPECTORPRO_ALLOWED_HOSTS",
        "trusted-host.example:8443",
    )
    trusted_host = client.get(
        "/api/facility-layout-bootstrap",
        headers={
            "Host": "trusted-host.example:8443",
            "Origin": "http://trusted-host.example:8443",
        },
    )
    assert trusted_host.status_code == 200


@pytest.mark.parametrize(
    "origin",
    (
        "null",
        "file://local",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com?query",
        "https://[::1",
    ),
)
def test_malformed_or_non_http_origins_fail_closed(origin: str):
    client = TestClient(server.app, base_url="http://testserver")
    response = client.get(
        "/api/facility-layout-bootstrap",
        headers={"Origin": origin},
    )
    assert response.status_code == 403
