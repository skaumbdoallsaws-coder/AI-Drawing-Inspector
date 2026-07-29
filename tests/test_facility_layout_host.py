from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)


def _client(root: Path) -> tuple[TestClient, LocalFacilityLayoutHost]:
    host = LocalFacilityLayoutHost(root)
    app = FastAPI()
    app.include_router(host.create_router())
    return TestClient(app), host


def test_local_host_bootstraps_persistent_authority_and_empty_layout(tmp_path):
    client, _ = _client(tmp_path / "facility")
    response = client.get("/api/facility-layout-bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["siteId"] == LOCAL_SITE_ID
    assert body["layoutId"] == LOCAL_LAYOUT_ID
    assert len(body["assetCatalog"]) == 4
    assert body["layout"]["layout"]["placements"] == []
    first_revision = body["layout"]["revision"]

    reopened, _ = _client(tmp_path / "facility")
    repeated = reopened.get("/api/facility-layout-bootstrap")
    assert repeated.status_code == 200
    assert repeated.json()["layout"]["revision"] == first_revision


def test_local_host_uses_revision_bound_preview_and_apply(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    asset = bootstrap["assetCatalog"][0]
    revision = bootstrap["layout"]["revision"]
    operation = {
        "op": "place_asset",
        "placement": {
            "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {
                "position": {"x": 5, "y": 0, "z": 4},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
    }
    preview = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview",
        json={"baseRevision": revision, "operations": [operation]},
    )
    assert preview.status_code == 200
    assert preview.json()["baseRevision"] == revision
    assert preview.json()["changed"] is True

    before = client.get(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    ).json()
    assert before["layout"]["placements"] == []

    applied = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={"baseRevision": revision, "operations": [operation]},
    )
    assert applied.status_code == 200
    assert len(applied.json()["layout"]["placements"]) == 1
    assert applied.json()["revision"] != revision


def test_local_host_rejects_unknown_asset_and_cross_site_scope(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    operation = {
        "op": "place_asset",
        "placement": {
            "assetId": "asset-unknown",
            "assetDefinitionRevision": "f" * 64,
            "transform": {
                "position": {"x": 1, "y": 0, "z": 1},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
    }
    rejected = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview",
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [operation],
        },
    )
    assert rejected.status_code == 404
    hidden = client.get("/api/facility-layouts/site-other")
    assert hidden.status_code == 404
    hidden_assets = client.get(
        "/api/industrial-assets",
        params={"siteId": "site-other"},
    )
    assert hidden_assets.status_code == 404


def test_local_host_resolves_revision_bound_named_process_maps(tmp_path):
    process_root = tmp_path / "training"
    product_dir = process_root / "fixture-product"
    product_dir.mkdir(parents=True)
    legacy_asset = product_dir / "fixture_process_map_working_draft.json"
    legacy_asset.write_text(
        json.dumps(
            {
                "schemaVersion": "fixture-process-map-1",
                "productId": "fixture-product",
                "productName": "Fixture Product",
                "nodes": [
                    {
                        "nodeId": "root",
                        "level": 0,
                        "name": "Fixture Product",
                        "parentNodeId": None,
                        "partIds": [],
                    },
                    {
                        "nodeId": "part",
                        "level": 1,
                        "name": "Fixture Part",
                        "parentNodeId": "root",
                        "partIds": ["P-001"],
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    host = LocalFacilityLayoutHost(
        tmp_path / "facility",
        process_map_root=process_root,
    )
    try:
        resolved = host._resolve_process_map(
            host.principal(),
            LOCAL_SITE_ID,
            "fixture-product",
            "default",
            "ignored-by-resolver",
        )
    finally:
        host.close()
    assert resolved is not None
    assert len(resolved["revision"]) == 64
    assert resolved["document"]["mapId"] == "default"
    assert resolved["document"]["association"]["productId"] == "fixture-product"
