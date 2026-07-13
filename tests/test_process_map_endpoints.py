"""HTTP and persistence tests for the process-map editor backend."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import repository
from ai_inspector.process_map import validate_process_map


REPO_ROOT = Path(__file__).resolve().parents[1]


def _v1_map() -> dict:
    return {
        "schemaVersion": "fixture-process-map-1",
        "productName": "Fixture Product",
        "nodes": [
            {
                "nodeId": "root",
                "level": 0,
                "name": "Fixture Assembly",
                "parentNodeId": None,
                "partIds": ["P-001"],
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
def process_map_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "training"
    product_dir = root / "fixture-product"
    product_dir.mkdir(parents=True)
    asset = product_dir / "fixture_process_map_working_draft.json"
    asset.write_text(json.dumps(_v1_map(), indent=2) + "\n", encoding="utf-8")
    (product_dir / "fixture_process_map_approved_baseline.json").write_text(
        json.dumps({"schemaVersion": "historical", "nodes": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (product_dir / "fixture_unique_items.json").write_text(
        json.dumps(
            {
                "items": [
                    {"partId": "P-001", "displayName": "Fixture Part"},
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    return {"root": root, "productDir": product_dir, "asset": asset}


def test_flag_off_keeps_editor_routes_unavailable(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    response = TestClient(server.app).get("/api/training/process-map/fixture-product")
    assert response.status_code == 404


def test_get_migrates_v1_in_memory_and_returns_stored_revision(process_map_asset: dict):
    client = TestClient(server.app)
    response = client.get("/api/training/process-map/fixture-product")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["assetName"] == "fixture_process_map_working_draft.json"
    assert len(payload["revision"]) == 64
    assert payload["map"]["schemaVersion"] == 2
    assert payload["map"]["edges"] == []
    assert [node["type"] for node in payload["map"]["nodes"]] == [
        "assembly",
        "subassembly",
        "input",
    ]
    assert {finding["severity"] for finding in payload["findings"]} == {"info"}
    stored = json.loads(process_map_asset["asset"].read_text(encoding="utf-8"))
    assert stored["schemaVersion"] == "fixture-process-map-1"


def test_put_round_trip_creates_backup_and_ascii_v2_asset(process_map_asset: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    edited = loaded["map"]
    edited["nodes"][1]["name"] = "Caf\u00e9 Module"
    edited["nodes"][1]["position"] = {"x": 120, "y": 240}

    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": edited, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["revision"] != loaded["revision"]
    assert not [finding for finding in payload["findings"] if finding["severity"] == "error"]

    raw = process_map_asset["asset"].read_bytes()
    raw.decode("ascii")
    assert b"Caf\\u00e9 Module" in raw
    stored = json.loads(raw.decode("ascii"))
    assert stored["schemaVersion"] == 2
    assert stored["nodes"][1]["position"] == {"x": 120, "y": 240}
    backups = list(process_map_asset["productDir"].glob("*.backup-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["schemaVersion"] == "fixture-process-map-1"

    reloaded = client.get("/api/training/process-map/fixture-product").json()
    assert reloaded["revision"] == payload["revision"]
    assert reloaded["map"]["nodes"][1]["name"] == "Caf\u00e9 Module"


def test_stale_revision_returns_409_without_modifying_asset(process_map_asset: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    before = process_map_asset["asset"].read_bytes()
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": loaded["map"], "baseRevision": "0" * 64},
    )
    assert response.status_code == 409
    assert response.json() == {
        "error": "revision_conflict",
        "currentRevision": loaded["revision"],
    }
    assert process_map_asset["asset"].read_bytes() == before
    assert list(process_map_asset["productDir"].glob("*.backup-*.json")) == []


def test_structural_errors_return_422_but_warnings_can_save(process_map_asset: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    invalid = deepcopy(loaded["map"])
    invalid["nodes"][1]["type"] = "component"
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": invalid, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_failed"
    assert "unknown_node_type" in {
        finding["code"] for finding in response.json()["findings"]
    }

    warning_only = deepcopy(loaded["map"])
    warning_only["nodes"][1]["partIds"] = ["UNKNOWN"]
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": warning_only, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 200
    assert "unknown_part_reference" in {
        finding["code"] for finding in response.json()["findings"]
    }


def test_atomic_replace_failure_leaves_original_and_cleans_temp(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    before = process_map_asset["asset"].read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(repository, "_replace_file", fail_replace)
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": loaded["map"], "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 500
    assert process_map_asset["asset"].read_bytes() == before
    assert list(process_map_asset["productDir"].glob(".*.tmp-*.json")) == []


def test_backup_retention_keeps_only_configured_latest_files(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_BACKUP_LIMIT", "2")
    client = TestClient(server.app)
    for index in range(4):
        loaded = client.get("/api/training/process-map/fixture-product").json()
        edited = deepcopy(loaded["map"])
        edited["nodes"][1]["name"] = f"Fixture Module {index}"
        response = client.put(
            "/api/training/process-map/fixture-product",
            json={"map": edited, "baseRevision": loaded["revision"]},
        )
        assert response.status_code == 200
    backups = sorted(process_map_asset["productDir"].glob("*.backup-*.json"))
    assert len(backups) == 2


def test_real_racing_bike_part_manifest_activates_reference_validation():
    product_dir = REPO_ROOT / "generated" / "training" / "racing-bike"
    known_parts = repository._known_product_part_ids(product_dir)
    assert known_parts is not None
    assert len(known_parts) == 47
    assert {"RB-001", "RB-024", "RB-047"}.issubset(known_parts)

    loaded = repository.load_process_map(product_dir.parent, "racing-bike")
    modified = deepcopy(loaded["map"])
    modified["nodes"][0]["partIds"].append("RB-UNKNOWN")
    findings = validate_process_map(modified, known_parts)
    assert any(
        finding["code"] == "unknown_part_reference"
        and "RB-UNKNOWN" in finding["message"]
        for finding in findings
    )


@pytest.mark.parametrize(
    "product_id",
    ["unknown-product", "INVALID", "bad%21id", "%2E%2E"],
)
def test_unknown_and_invalid_product_ids_return_404(process_map_asset: dict, product_id: str):
    response = TestClient(server.app).get(f"/api/training/process-map/{product_id}")
    assert response.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
