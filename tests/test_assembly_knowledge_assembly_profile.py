from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import server
from ai_inspector.assembly_knowledge.assembly_profile import (
    build_legacy_assembly_profile,
)


PART_A = "occ-wheel-1"
PART_B = "occ-wheel-2"


def _documents() -> dict:
    root = "occ-root"
    part_a = PART_A
    part_b = PART_B
    return {
        "package.json": {
            "productId": "test-cycle",
            "packageId": "akp-12345678",
            "packageRevision": "1" * 64,
            "sourceRevision": "2" * 64,
            "readiness": "planning_ready",
            "productionEligible": False,
        },
        "product_structure.json": {
            "rootOccurrenceId": root,
            "occurrences": [
                {
                    "occurrenceId": root,
                    "kind": "assembly",
                    "name": "SWPR-Test-Cycle",
                    "sourcePath": "SWPR-Test-Cycle.SLDASM",
                    "state": {"resolved": True},
                },
                {
                    "occurrenceId": part_a,
                    "kind": "part",
                    "name": "SWPR-Test-Cycle_Wheel-1",
                    "sourcePath": "SWPR-Test-Cycle_Wheel.SLDPRT",
                    "configuration": "Default",
                    "transform": {"translation": [0.0, 0.0, 0.0]},
                    "state": {"lightweight": True},
                    "properties": {
                        "referencedFileName": "SWPR-Test-Cycle_Wheel.SLDPRT"
                    },
                },
                {
                    "occurrenceId": part_b,
                    "kind": "part",
                    "name": "SWPR-Test-Cycle_Wheel-2",
                    "sourcePath": "SWPR-Test-Cycle_Wheel.SLDPRT",
                    "configuration": "Default",
                    "transform": {"translation": [1.0, 0.0, 0.0]},
                    "state": {"lightweight": True},
                    "properties": {
                        "referencedFileName": "SWPR-Test-Cycle_Wheel.SLDPRT"
                    },
                },
            ],
        },
        "interface_graph.json": {
            "mates": [
                {
                    "mateId": "mate-1",
                    "displayName": "Concentric1",
                    "type": "Concentric",
                    "occurrenceRefs": [part_a, part_b],
                    "entities": [
                        {"entityType": "Edge"},
                        {"entityType": "Edge"},
                    ],
                }
            ]
        },
        "visual_manifest.json": {
            "views": [
                {
                    "colorLegend": {
                        "#112233": part_a,
                        "#445566": part_b,
                    }
                }
            ]
        },
    }


def test_package_adapter_preserves_occurrences_and_unique_part_identity() -> None:
    profile = build_legacy_assembly_profile(_documents())

    assert profile["identity"]["description"] == "Test Cycle Assembly"
    assert profile["statistics"]["totalComponents"] == 2
    assert profile["statistics"]["uniquePartCount"] == 1
    assert profile["statistics"]["totalMates"] == 1
    assert len(profile["components"]) == 2
    assert len(profile["partDataCache"]) == 1
    assert profile["components"][0]["occurrenceId"] == PART_A
    assert profile["components"][1]["occurrenceId"] == PART_B
    assert profile["components"][0]["itemId"] is None
    assert profile["mates"][0]["entity1"]["componentName"].endswith("Wheel-1")
    assert profile["mates"][0]["entity2"]["componentName"].endswith("Wheel-2")


def test_prepared_package_assets_flow_through_existing_assembly_routes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile = build_legacy_assembly_profile(_documents())
    glb = tmp_path / "assembly.glb"
    glb.write_bytes(b"glTF-test")
    images = {}
    for view in ("front", "top", "right", "isometric"):
        image = tmp_path / f"{view}.png"
        image.write_bytes(f"png-{view}".encode("ascii"))
        images[view] = image

    source = {
        "profile": profile,
        "assets": {"model": glb, **images},
    }
    monkeypatch.setattr(server, "assembly_profiles", {"test-cycle": profile})
    monkeypatch.setattr(server, "assembly_part_lookup", {})
    monkeypatch.setattr(
        server,
        "prepared_assembly_sources",
        {"test-cycle": source},
    )
    monkeypatch.setattr(server, "_ensure_inspector", lambda: None)

    client = TestClient(server.app)
    picker = client.get("/api/profiles")
    assert picker.status_code == 200
    entry = next(
        item
        for item in picker.json()
        if item["part_number"] == "test-cycle"
    )
    assert entry["context_kind"] == "assembly"
    assert entry["component_count"] == 2

    context = client.get("/api/assembly-context/test-cycle")
    assert context.status_code == 200
    assert context.json()["has_glb"] is True
    assert context.json()["has_views"] is True
    assert {
        row["occurrenceId"] for row in context.json()["components"]
    } == {PART_A, PART_B}

    views = client.get("/api/assembly-views/test-cycle")
    assert views.status_code == 200
    assert set(views.json()) == {"front", "top", "right", "isometric"}

    model = client.get("/api/assembly-model/test-cycle")
    assert model.status_code == 200
    assert model.content == b"glTF-test"
