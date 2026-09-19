"""HTTP and persistence tests for the process-map editor backend."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.process_map import repository
from ai_inspector.process_map import validate_placement_map


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


def test_auto_routing_status_is_independently_flagged_and_edit_gated(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = TestClient(server.app)
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_AUTO_ROUTING", raising=False)
    assert client.get("/api/training/process-map-auto-routing-status").json() == {
        "success": True,
        "enabled": False,
    }

    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_AUTO_ROUTING", "1")
    assert client.get("/api/training/process-map-auto-routing-status").json() == {
        "success": True,
        "enabled": True,
    }

    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    assert client.get("/api/training/process-map-auto-routing-status").status_code == 404


def test_spatial_analysis_status_is_independently_flagged_and_edit_gated(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = TestClient(server.app)
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_SPATIAL_ANALYSIS", raising=False)
    assert client.get("/api/training/process-map-spatial-analysis-status").json() == {
        "success": True,
        "enabled": False,
    }

    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_SPATIAL_ANALYSIS", "1")
    assert client.get("/api/training/process-map-spatial-analysis-status").json() == {
        "success": True,
        "enabled": True,
    }

    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    assert client.get("/api/training/process-map-spatial-analysis-status").status_code == 404


def test_spatial_telemetry_records_only_bounded_aggregates(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from ai_inspector.telemetry import (
        ENV_VAR,
        get_default_store,
        reset_default_store_for_tests,
    )

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "spatial-telemetry.sqlite"))
    reset_default_store_for_tests()
    client = TestClient(server.app)
    body = {
        "productId": "fixture-product",
        "mapId": "default",
        "revision": "a" * 64,
        "operation": "arrangement",
        "outcome": "previewed",
        "scope": "selection",
        "spatialEngineVersion": 1,
        "policyVersion": 1,
        "nodeCount": 12,
        "edgeCount": 11,
        "scopedNodeCount": 3,
        "scopedEdgeCount": 2,
        "candidatesEvaluated": 24,
        "movedNodeCount": 3,
        "latencyMs": 48.25,
        "rejectionCounts": {"node_overlap": 2, "customer_label": 99},
        "metricsBefore": {"nodeOverlaps": 2, "x": 900.0},
        "metricsAfter": {"nodeOverlaps": 0, "routeLength": 410.5},
    }
    response = client.post("/api/training/process-map-spatial-events", json=body)
    assert response.status_code == 202
    events = [
        event for event in get_default_store().query_recent(20)
        if event.workflow == "process_map_spatial"
    ]
    assert len(events) == 1
    event = events[0]
    assert event.processMapProductId == "fixture-product"
    assert event.processMapId == "default"
    assert event.processMapOperation == "arrangement"
    assert event.processMapOutcome == "previewed"
    assert event.processMapMovedNodeCount == 3
    assert json.loads(event.processMapRejectionCountsJson) == {"node_overlap": 2}
    assert json.loads(event.processMapMetricsBeforeJson) == {"nodeOverlaps": 2.0}
    assert json.loads(event.processMapMetricsAfterJson) == {
        "nodeOverlaps": 0.0,
        "routeLength": 410.5,
    }

    rejected = client.post(
        "/api/training/process-map-spatial-events",
        json={**body, "position": {"x": 10, "y": 20}},
    )
    assert rejected.status_code == 422
    reset_default_store_for_tests()


def test_agent_layout_write_status_is_independently_flagged_and_edit_gated(
    process_map_asset: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client = TestClient(server.app)
    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE", raising=False)
    assert client.get("/api/training/process-map-agent-layout-write-status").json() == {
        "success": True,
        "enabled": False,
    }

    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE", "1")
    assert client.get("/api/training/process-map-agent-layout-write-status").json() == {
        "success": True,
        "enabled": True,
    }

    monkeypatch.delenv("INSPECTORPRO_PROCESS_MAP_EDIT", raising=False)
    assert client.get("/api/training/process-map-agent-layout-write-status").status_code == 404


def test_get_migrates_v1_in_memory_and_returns_stored_revision(process_map_asset: dict):
    client = TestClient(server.app)
    response = client.get("/api/training/process-map/fixture-product")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["assetName"] == "fixture_process_map_working_draft.json"
    assert len(payload["revision"]) == 64
    assert payload["map"]["schemaVersion"] == 3
    assert payload["map"]["layoutVersion"] == 3
    assert payload["map"]["canvasNodes"] == []
    assert payload["map"]["canvasEdges"] == []
    assert payload["map"]["canvasGroups"] == []
    assert payload["map"]["sourceStructureRevision"] == payload["structureRevision"]
    assert [item["kind"] for item in payload["productStructure"]["occurrences"]] == [
        "assembly",
        "subassembly",
        "part",
    ]
    assert {finding["severity"] for finding in payload["findings"]} == {"info"}
    stored = json.loads(process_map_asset["asset"].read_text(encoding="utf-8"))
    assert stored["schemaVersion"] == "fixture-process-map-1"


def test_put_round_trip_creates_backup_source_sidecar_and_ascii_v3_asset(process_map_asset: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    edited = loaded["map"]
    edited["canvasNodes"].append(
        {
            "nodeId": "canvas-module",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "module",
            "nameSnapshot": "Caf\u00e9 Module",
            "itemIdSnapshot": "P-001",
            "labelOverride": "Primary fixture module",
            "note": "Verify alignment before the inspection step.",
            "referenceIds": ["machine-1"],
            "position": {"x": 120, "y": 240},
        }
    )
    edited["canvasNodes"].extend(
        [
            {
                "nodeId": "stage-install",
                "nodeKind": "process_step",
                "processType": "operation",
                "name": "Install fixture module",
                "position": {"x": 420, "y": 240},
                "properties": {
                    "description": "Install and align the fixture module.",
                    "duration": "12 min",
                    "torqueRequirements": "10 N m",
                    "inspectionRequirements": "Verify alignment.",
                },
            },
            {
                "nodeId": "junction-split",
                "nodeKind": "junction",
                "junctionType": "split",
                "position": {"x": 760, "y": 313},
            },
        ]
    )
    edited["canvasEdges"] = [
        {
            "edgeId": "stage-to-split",
            "logicalConnectionId": "stage-to-split",
            "from": {"nodeId": "stage-install", "port": "out"},
            "to": {"nodeId": "junction-split", "port": "in"},
            "kind": "precedence",
        }
    ]
    edited["referenceCatalog"] = [
        {
            "referenceId": "machine-1",
            "kind": "machine",
            "name": "Five-axis machining center",
            "identifier": "MC-01",
        }
    ]
    edited["canvasGroups"] = [
        {
            "groupId": "fixture-cell",
            "label": "Fixture cell",
            "position": {"x": 60, "y": 160},
            "size": {"width": 520, "height": 340},
            "colorKey": "orange",
            "memberNodeIds": ["canvas-module", "stage-install", "junction-split"],
            "collapsed": False,
            "futureGroupField": {"preserve": True},
        }
    ]

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
    assert stored["schemaVersion"] == 3
    assert stored["canvasNodes"][0]["position"] == {"x": 120, "y": 240}
    assert stored["canvasNodes"][0]["labelOverride"] == "Primary fixture module"
    assert stored["canvasNodes"][0]["note"] == "Verify alignment before the inspection step."
    assert stored["canvasNodes"][0]["referenceIds"] == ["machine-1"]
    stored_stage = next(
        node for node in stored["canvasNodes"] if node["nodeId"] == "stage-install"
    )
    stored_junction = next(
        node for node in stored["canvasNodes"] if node["nodeId"] == "junction-split"
    )
    assert stored_stage["properties"]["duration"] == "12 min"
    assert stored_stage["properties"]["torqueRequirements"] == "10 N m"
    assert stored_junction["junctionType"] == "split"
    assert stored["canvasEdges"][0]["to"] == {
        "nodeId": "junction-split",
        "port": "in",
    }
    assert stored["layoutVersion"] == 3
    assert stored["canvasGroups"][0]["memberNodeIds"] == [
        "canvas-module",
        "stage-install",
        "junction-split",
    ]
    assert stored["canvasGroups"][0]["futureGroupField"] == {"preserve": True}
    assert stored["referenceCatalog"][0]["identifier"] == "MC-01"
    structure_asset = process_map_asset["productDir"] / "fixture_product_product_structure.json"
    assert structure_asset.is_file()
    structure_asset.read_bytes().decode("ascii")
    backups = list(process_map_asset["productDir"].glob("*.backup-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["schemaVersion"] == "fixture-process-map-1"

    reloaded = client.get("/api/training/process-map/fixture-product").json()
    assert reloaded["revision"] == payload["revision"]
    assert reloaded["map"]["canvasNodes"][0]["nameSnapshot"] == "Caf\u00e9 Module"
    assert reloaded["map"]["canvasNodes"][0]["labelOverride"] == "Primary fixture module"
    assert reloaded["map"]["canvasNodes"][0]["note"] == "Verify alignment before the inspection step."
    assert reloaded["map"]["canvasNodes"][0]["referenceIds"] == ["machine-1"]
    assert reloaded["map"]["referenceCatalog"][0]["identifier"] == "MC-01"
    reloaded_stage = next(
        node for node in reloaded["map"]["canvasNodes"]
        if node["nodeId"] == "stage-install"
    )
    assert reloaded_stage["properties"] == stored_stage["properties"]
    assert any(
        node.get("junctionType") == "split"
        for node in reloaded["map"]["canvasNodes"]
    )
    assert reloaded["map"]["canvasGroups"] == stored["canvasGroups"]
    assert len(reloaded["productStructure"]["occurrences"]) == 3


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
    invalid["canvasNodes"].append(
        {
            "nodeId": "bad",
            "nodeKind": "component",
            "position": {"x": 0, "y": 0},
        }
    )
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": invalid, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_failed"
    assert "unknown_canvas_node_kind" in {
        finding["code"] for finding in response.json()["findings"]
    }

    warning_only = deepcopy(loaded["map"])
    warning_only["canvasNodes"].append(
        {
            "nodeId": "decision",
            "nodeKind": "process_step",
            "processType": "decision",
            "name": "Review result",
            "position": {"x": 0, "y": 0},
        }
    )
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": warning_only, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 200
    assert "decision_has_fewer_than_two_outputs" in {
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
        edited["productName"] = f"Fixture Product {index}"
        response = client.put(
            "/api/training/process-map/fixture-product",
            json={"map": edited, "baseRevision": loaded["revision"]},
        )
        assert response.status_code == 200
    backups = sorted(process_map_asset["productDir"].glob("*.backup-*.json"))
    assert len(backups) == 2


def test_real_racing_bike_part_manifest_activates_reference_validation(tmp_path: Path):
    source_dir = REPO_ROOT / "generated" / "training" / "racing-bike"
    product_dir = tmp_path / "training" / "racing-bike"
    product_dir.mkdir(parents=True)
    for name in (
        "racing_bike_process_map_working_draft.json",
        "racing_bike_product_structure.json",
        "racing_bike_unique_items.json",
    ):
        shutil.copy2(source_dir / name, product_dir / name)

    known_parts = repository._known_product_part_ids(product_dir)
    assert known_parts is not None
    assert len(known_parts) == 47
    assert {"RB-001", "RB-024", "RB-047"}.issubset(known_parts)

    loaded = repository.load_process_map(product_dir.parent, "racing-bike")
    assert loaded["map"]["schemaVersion"] == 3
    assert isinstance(loaded["map"]["canvasNodes"], list)
    assert len(loaded["productStructure"]["occurrences"]) == 56
    modified = deepcopy(loaded["map"])
    modified["canvasNodes"].append(
        {
            "nodeId": "missing-source",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "RB-UNKNOWN",
            "position": {"x": 0, "y": 0},
        }
    )
    occurrence_ids = {
        item["occurrenceId"] for item in loaded["productStructure"]["occurrences"]
    }
    findings = validate_placement_map(modified, occurrence_ids)
    assert any(
        finding["code"] == "dangling_source_occurrence"
        and "RB-UNKNOWN" in finding["message"]
        for finding in findings
    )


def test_product_structure_endpoint_returns_same_revision(process_map_asset: dict):
    client = TestClient(server.app)
    map_payload = client.get("/api/training/process-map/fixture-product").json()
    response = client.get("/api/training/product-structure/fixture-product")
    assert response.status_code == 200
    payload = response.json()
    assert payload["structureRevision"] == map_payload["structureRevision"]
    assert len(payload["productStructure"]["occurrences"]) == 3


def test_source_structure_revision_conflict_fails_closed(process_map_asset: dict):
    client = TestClient(server.app)
    loaded = client.get("/api/training/process-map/fixture-product").json()
    edited = deepcopy(loaded["map"])
    edited["sourceStructureRevision"] = "0" * 64
    response = client.put(
        "/api/training/process-map/fixture-product",
        json={"map": edited, "baseRevision": loaded["revision"]},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "source_structure_conflict"


def test_color_manifest_only_product_activates_reference_validation(tmp_path: Path):
    product_dir = tmp_path / "color-manifest-product"
    product_dir.mkdir()
    colors = {f"P-{index:03d}": "#4f91ba" for index in range(1, 473)}
    (product_dir / "part_colored_iso_manifest.json").write_text(
        json.dumps({"colors": colors}, indent=2) + "\n",
        encoding="utf-8",
    )

    known_parts = repository._known_product_part_ids(product_dir)
    assert known_parts is not None
    assert len(known_parts) == 472
    assert {"P-001", "P-236", "P-472"}.issubset(known_parts)


@pytest.mark.parametrize(
    "product_id",
    ["unknown-product", "INVALID", "bad%21id", "%2E%2E"],
)
def test_unknown_and_invalid_product_ids_return_404(process_map_asset: dict, product_id: str):
    response = TestClient(server.app).get(f"/api/training/process-map/{product_id}")
    assert response.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
