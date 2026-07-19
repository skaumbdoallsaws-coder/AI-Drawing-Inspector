"""Identity, registry, and named-map API tests for process maps."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import repository


def _legacy_map() -> dict:
    return {
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
                "nodeId": "module",
                "level": 1,
                "name": "Fixture Module",
                "parentNodeId": "root",
                "partIds": ["P-001"],
            },
            {
                "nodeId": "part",
                "level": 3,
                "name": "Fixture Part",
                "parentNodeId": "module",
                "partIds": ["P-001"],
            },
        ],
    }


@pytest.fixture
def identity_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "training"
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    legacy_asset = product_dir / "fixture_process_map_working_draft.json"
    legacy_asset.write_text(json.dumps(_legacy_map(), indent=2) + "\n", encoding="utf-8")
    (product_dir / "fixture_unique_items.json").write_text(
        json.dumps({"items": [{"partId": "P-001"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    return {
        "root": root,
        "productDir": product_dir,
        "legacyAsset": legacy_asset,
        "legacyBytes": legacy_asset.read_bytes(),
    }


def _client() -> TestClient:
    return TestClient(server.app)


def _create_map(client: TestClient, name: str = "Machining Plan") -> dict:
    response = client.post(
        "/api/training/process-maps/fixture-product",
        json={"displayName": name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_identity_routes_share_the_existing_feature_flag(
    identity_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    client = _client()
    assert client.get("/api/training/process-maps/fixture-product").status_code == 404
    assert client.post(
        "/api/training/process-maps/fixture-product",
        json={"displayName": "Hidden"},
    ).status_code == 404


def test_legacy_alias_adopts_default_identity_without_rewriting_source(identity_product: dict):
    response = _client().get("/api/training/process-map/fixture-product")
    assert response.status_code == 200
    payload = response.json()

    registry_asset = identity_product["productDir"] / "process_maps" / "registry.json"
    default_asset = identity_product["productDir"] / "process_maps" / "default.json"
    assert registry_asset.is_file()
    assert default_asset.is_file()
    assert identity_product["legacyAsset"].read_bytes() == identity_product["legacyBytes"]

    registry = json.loads(registry_asset.read_text(encoding="ascii"))
    stored = json.loads(default_asset.read_text(encoding="ascii"))
    assert registry["registryVersion"] == 1
    assert registry["defaultMapId"] == "default"
    assert registry["legacyAssetName"] == identity_product["legacyAsset"].name
    assert [item["mapId"] for item in registry["maps"]] == ["default"]
    assert stored["mapId"] == "default"
    assert stored["association"] == {"productId": "fixture-product"}
    assert stored["status"] == "active"
    assert stored["createdAt"].endswith("Z")
    assert stored["updatedAt"].endswith("Z")
    assert "revision" not in stored
    assert payload["assetName"] == identity_product["legacyAsset"].name
    assert payload["canonicalAssetName"] == "default.json"


def test_list_uses_registry_and_returns_current_content_revisions(identity_product: dict):
    response = _client().get("/api/training/process-maps/fixture-product")
    assert response.status_code == 200
    payload = response.json()
    assert payload["defaultMapId"] == "default"
    assert payload["findings"] == []
    assert len(payload["maps"]) == 1
    summary = payload["maps"][0]
    assert summary["mapId"] == "default"
    assert summary["isDefault"] is True
    assert summary["status"] == "active"
    assert len(summary["revision"]) == 64


def test_create_blank_map_stamps_identity_and_server_timestamps(identity_product: dict):
    created = _client().post(
        "/api/training/process-maps/fixture-product",
        json={
            "displayName": "Final Assembly Plan",
            "association": {"productId": "fixture-product", "assemblyId": "ASM-42"},
            "createdAt": "client-owned",
            "updatedAt": "client-owned",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    process_map = payload["map"]
    assert re.fullmatch(r"pm-[0-9a-f]{8}", process_map["mapId"])
    assert process_map["displayName"] == "Final Assembly Plan"
    assert process_map["association"] == {
        "productId": "fixture-product",
        "assemblyId": "ASM-42",
    }
    assert process_map["status"] == "draft"
    assert process_map["createdAt"] != "client-owned"
    assert process_map["updatedAt"] != "client-owned"
    assert process_map["canvasNodes"] == []
    assert process_map["canvasEdges"] == []
    assert process_map["canvasGroups"] == []

    asset = identity_product["productDir"] / "process_maps" / f"{process_map['mapId']}.json"
    stored = json.loads(asset.read_text(encoding="ascii"))
    assert "revision" not in stored
    assert stored == process_map


def test_duplicate_copies_content_but_gets_fresh_identity(identity_product: dict):
    client = _client()
    source = _create_map(client, "Source Plan")
    edited = deepcopy(source["map"])
    edited["canvasNodes"].append(
        {
            "nodeId": "inspect-step",
            "nodeKind": "process_step",
            "processType": "inspection",
            "name": "Inspect assembly",
            "position": {"x": 100, "y": 120},
        }
    )
    saved = client.put(
        f"/api/training/process-maps/fixture-product/{edited['mapId']}",
        json={"map": edited, "baseRevision": source["revision"]},
    ).json()

    duplicate = client.post(
        "/api/training/process-maps/fixture-product",
        json={"displayName": "Source Plan Copy", "duplicateOf": edited["mapId"]},
    )
    assert duplicate.status_code == 200
    copied = duplicate.json()["map"]
    assert copied["mapId"] != saved["map"]["mapId"]
    assert copied["displayName"] == "Source Plan Copy"
    assert copied["status"] == "draft"
    assert copied["canvasNodes"] == saved["map"]["canvasNodes"]
    assert copied["createdAt"] != saved["map"]["createdAt"] or copied["mapId"] != saved["map"]["mapId"]


def test_named_put_owns_timestamps_and_rejects_identity_changes(identity_product: dict):
    client = _client()
    created = _create_map(client)
    original_created_at = created["map"]["createdAt"]
    edited = deepcopy(created["map"])
    edited["displayName"] = "Renamed Plan"
    edited["createdAt"] = "forged-created"
    edited["updatedAt"] = "forged-updated"
    edited["revision"] = "must-not-persist"
    response = client.put(
        f"/api/training/process-maps/fixture-product/{edited['mapId']}",
        json={"map": edited, "baseRevision": created["revision"]},
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["map"]["createdAt"] == original_created_at
    assert saved["map"]["updatedAt"] != "forged-updated"
    assert "revision" not in saved["map"]

    invalid = deepcopy(saved["map"])
    invalid["mapId"] = "default"
    rejected = client.put(
        f"/api/training/process-maps/fixture-product/{created['map']['mapId']}",
        json={"map": invalid, "baseRevision": saved["revision"]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["findings"][0]["code"] == "map_id_immutable"

    wrong_association = deepcopy(saved["map"])
    wrong_association["association"] = {"productId": "another-product"}
    rejected_association = client.put(
        f"/api/training/process-maps/fixture-product/{created['map']['mapId']}",
        json={"map": wrong_association, "baseRevision": saved["revision"]},
    )
    assert rejected_association.status_code == 422
    assert rejected_association.json()["findings"][0]["code"] == "association_product_mismatch"


def test_named_default_save_refreshes_legacy_compatibility_mirror(identity_product: dict):
    client = _client()
    loaded = client.get("/api/training/process-maps/fixture-product/default").json()
    edited = deepcopy(loaded["map"])
    edited["displayName"] = "Updated Default"
    response = client.put(
        "/api/training/process-maps/fixture-product/default",
        json={"map": edited, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 200
    assert response.json().get("legacyMirrorBackupName")
    mirrored = json.loads(identity_product["legacyAsset"].read_text(encoding="ascii"))
    assert mirrored["displayName"] == "Updated Default"
    assert mirrored["mapId"] == "default"


def test_named_put_uses_map_specific_cas(identity_product: dict):
    client = _client()
    first = _create_map(client, "First")
    second = _create_map(client, "Second")
    before_second = client.get(
        f"/api/training/process-maps/fixture-product/{second['map']['mapId']}"
    ).json()["revision"]

    stale = client.put(
        f"/api/training/process-maps/fixture-product/{first['map']['mapId']}",
        json={"map": first["map"], "baseRevision": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["currentRevision"] == first["revision"]
    after_second = client.get(
        f"/api/training/process-maps/fixture-product/{second['map']['mapId']}"
    ).json()["revision"]
    assert after_second == before_second


def test_archive_hides_non_default_map_and_default_is_protected(identity_product: dict):
    client = _client()
    created = _create_map(client)
    archived = client.post(
        f"/api/training/process-maps/fixture-product/{created['map']['mapId']}/archive",
        json={"baseRevision": created["revision"]},
    )
    assert archived.status_code == 200
    assert archived.json()["map"]["status"] == "archived"

    visible = client.get("/api/training/process-maps/fixture-product").json()["maps"]
    all_maps = client.get(
        "/api/training/process-maps/fixture-product?includeArchived=true"
    ).json()["maps"]
    assert created["map"]["mapId"] not in {item["mapId"] for item in visible}
    assert created["map"]["mapId"] in {item["mapId"] for item in all_maps}

    default = client.get("/api/training/process-maps/fixture-product/default").json()
    rejected = client.post(
        "/api/training/process-maps/fixture-product/default/archive",
        json={"baseRevision": default["revision"]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["findings"][0]["code"] == "default_map_cannot_be_archived"

    edited_default = deepcopy(default["map"])
    edited_default["status"] = "archived"
    rejected_put = client.put(
        "/api/training/process-maps/fixture-product/default",
        json={"map": edited_default, "baseRevision": default["revision"]},
    )
    assert rejected_put.status_code == 422
    assert rejected_put.json()["findings"][0]["code"] == "default_map_cannot_be_archived"


def test_registry_pointer_alone_selects_legacy_alias_default(identity_product: dict):
    client = _client()
    created = _create_map(client, "Alternate Default")
    registry_asset = identity_product["productDir"] / "process_maps" / "registry.json"
    registry = json.loads(registry_asset.read_text(encoding="ascii"))
    registry["defaultMapId"] = created["map"]["mapId"]
    registry_asset.write_bytes(repository.canonical_process_map_bytes(registry))

    legacy_alias = client.get("/api/training/process-map/fixture-product")
    assert legacy_alias.status_code == 200
    assert legacy_alias.json()["map"]["mapId"] == created["map"]["mapId"]
    assert legacy_alias.json()["defaultMapId"] == created["map"]["mapId"]


def test_registry_scan_mismatch_is_reported_without_auto_registration(identity_product: dict):
    client = _client()
    created = _create_map(client, "Missing Asset")
    map_dir = identity_product["productDir"] / "process_maps"
    (map_dir / f"{created['map']['mapId']}.json").unlink()
    extra = deepcopy(client.get("/api/training/process-maps/fixture-product/default").json()["map"])
    extra["mapId"] = "pm-deadbeef"
    (map_dir / "pm-deadbeef.json").write_bytes(repository.canonical_process_map_bytes(extra))

    listed = client.get(
        "/api/training/process-maps/fixture-product?includeArchived=true"
    )
    assert listed.status_code == 200
    findings = listed.json()["findings"]
    assert {(item["code"], item.get("mapId")) for item in findings} == {
        ("registered_map_missing", created["map"]["mapId"]),
        ("unregistered_map_asset", "pm-deadbeef"),
    }
    assert "pm-deadbeef" not in {item["mapId"] for item in listed.json()["maps"]}


@pytest.mark.parametrize("map_id", ["../default", "DEFAULT", "pm-nothex", "pm-123"])
def test_invalid_named_map_ids_are_rejected(identity_product: dict, map_id: str):
    response = _client().get(f"/api/training/process-maps/fixture-product/{map_id}")
    assert response.status_code == 404


def test_failed_registry_update_during_create_leaves_no_orphan_map(
    identity_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = _client()
    assert client.get("/api/training/process-maps/fixture-product").status_code == 200
    map_dir = identity_product["productDir"] / "process_maps"

    def fail_registry(_product_dir: Path, _registry: dict) -> None:
        raise repository.ProcessMapWriteError("simulated registry failure")

    monkeypatch.setattr(repository, "_write_registry", fail_registry)
    response = client.post(
        "/api/training/process-maps/fixture-product",
        json={"displayName": "Must Not Persist"},
    )
    assert response.status_code == 500
    assert sorted(path.name for path in map_dir.glob("*.json")) == ["default.json", "registry.json"]


def test_failed_registry_update_during_put_restores_previous_map_bytes(
    identity_product: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = _client()
    created = _create_map(client, "Stable Plan")
    map_id = created["map"]["mapId"]
    asset = identity_product["productDir"] / "process_maps" / f"{map_id}.json"
    before = asset.read_bytes()
    edited = deepcopy(created["map"])
    edited["displayName"] = "Must Roll Back"

    def fail_registry(_product_dir: Path, _registry: dict) -> None:
        raise repository.ProcessMapWriteError("simulated registry failure")

    monkeypatch.setattr(repository, "_write_registry", fail_registry)
    response = client.put(
        f"/api/training/process-maps/fixture-product/{map_id}",
        json={"map": edited, "baseRevision": created["revision"]},
    )
    assert response.status_code == 500
    assert asset.read_bytes() == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
