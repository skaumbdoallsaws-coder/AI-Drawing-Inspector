from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import server
from ai_inspector.process_map.assembly_catalog import (
    ensure_assembly_process_map_product,
    process_map_product_id_for_assembly,
    product_structure_from_assembly_profile,
)


def _assembly_profile() -> dict:
    return {
        "identity": {
            "assemblyNumber": "Customer_Assembly_01",
            "description": "Customer Fixture Assembly",
        },
        "statistics": {
            "totalComponents": 3,
            "uniquePartCount": 2,
            "totalMates": 0,
        },
        "components": [
            {
                "name": "Customer Fixture Assembly",
                "type": "Assembly",
                "level": 0,
                "parentName": None,
                "referencedFileName": "Customer_Assembly_01.SLDASM",
            },
            {
                "name": "Repeated Clamp-1",
                "type": "Part",
                "level": 1,
                "parentName": "Customer Fixture Assembly",
                "referencedFileName": "Repeated Clamp.SLDPRT",
                "partDataKey": "repeated clamp.sldprt",
                "properties": {"PartNo": "CLAMP-01"},
            },
            {
                "name": "Repeated Clamp-2",
                "type": "Part",
                "level": 1,
                "parentName": "Customer Fixture Assembly",
                "referencedFileName": "Repeated Clamp.SLDPRT",
                "partDataKey": "repeated clamp.sldprt",
                "properties": {"PartNo": "CLAMP-01"},
            },
        ],
        "partDataCache": {},
        "mates": [],
    }


def test_loaded_assembly_profile_becomes_a_distinct_occurrence_catalog() -> None:
    product_id = process_map_product_id_for_assembly("Customer_Assembly_01")
    assert product_id.startswith("customer-assembly-01-")
    assert product_id == process_map_product_id_for_assembly("Customer_Assembly_01")
    assert product_id != process_map_product_id_for_assembly("customer-assembly-01")

    structure = product_structure_from_assembly_profile(
        _assembly_profile(),
        assembly_number="Customer_Assembly_01",
        product_id=product_id,
    )
    assert structure["productId"] == product_id
    assert structure["productName"] == "Customer Fixture Assembly"
    assert len(structure["occurrences"]) == 3
    parts = [
        item for item in structure["occurrences"]
        if item["kind"] == "part"
    ]
    assert len(parts) == 2
    assert {item["itemId"] for item in parts} == {"CLAMP-01"}
    assert len({item["occurrenceId"] for item in parts}) == 2
    assert {item["parentOccurrenceId"] for item in parts} == {
        structure["occurrences"][0]["occurrenceId"]
    }


def test_bootstrap_preserves_existing_assets_and_starts_new_maps_empty(
    tmp_path: Path,
) -> None:
    first = ensure_assembly_process_map_product(
        tmp_path,
        assembly_number="Customer_Assembly_01",
        profile=_assembly_profile(),
    )
    product_dir = tmp_path / first["productId"]
    structure_path = product_dir / first["assets"]["productStructure"]
    original = structure_path.read_bytes()

    second = ensure_assembly_process_map_product(
        tmp_path,
        assembly_number="Customer_Assembly_01",
        profile={
            **_assembly_profile(),
            "identity": {"description": "A changed display name"},
        },
    )
    assert second["productId"] == first["productId"]
    assert structure_path.read_bytes() == original
    legacy = product_dir / first["assets"]["legacyMap"]
    assert json.loads(legacy.read_text(encoding="utf-8"))["canvasNodes"] == []


def test_loaded_assembly_endpoint_provisions_and_returns_its_own_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    training_root = tmp_path / "training"
    profile = _assembly_profile()
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", training_root)
    monkeypatch.setattr(
        server,
        "assembly_profiles",
        {"Customer_Assembly_01": profile},
    )
    monkeypatch.setattr(server, "assembly_part_lookup", {})
    monkeypatch.setattr(server, "prepared_assembly_sources", {})
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")

    client = TestClient(server.app)
    response = client.get(
        "/api/training/process-map-for-assembly/Customer_Assembly_01"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["assemblyNumber"] == "Customer_Assembly_01"
    assert payload["map"]["productId"] == payload["productStructure"]["productId"]
    assert payload["productStructure"]["productName"] == "Customer Fixture Assembly"
    assert len(payload["productStructure"]["occurrences"]) == 3
    assert payload["map"]["canvasNodes"] == []
    assert payload["map"]["canvasEdges"] == []

    normal = client.get(
        f"/api/training/process-map/{payload['map']['productId']}"
    )
    assert normal.status_code == 200
    assert normal.json()["revision"] == payload["revision"]
