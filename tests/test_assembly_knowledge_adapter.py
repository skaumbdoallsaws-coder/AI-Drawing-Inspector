from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeConflict,
    AssemblyKnowledgeRepository,
    ExtractionAdapterError,
    adapt_bridge_package,
    canonical_json_bytes,
    verify_sources_unchanged,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)


def _source_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "source"
    root.mkdir()
    assembly = root / "SWPR-Tricycle.SLDASM"
    assembly.write_bytes(b"assembly-fixture")
    (root / "Wheel.SLDPRT").write_bytes(b"wheel-fixture")
    (root / "Axle.SLDPRT").write_bytes(b"axle-fixture")
    return root, assembly


def _adapt(tmp_path: Path):
    root, assembly = _source_tree(tmp_path)
    return adapt_bridge_package(
        FIXTURE,
        source_root=root,
        root_assembly=assembly,
        product_id="tricycle",
    )


def test_adapter_creates_distinct_repeated_occurrences_and_stable_mates(
    tmp_path: Path,
) -> None:
    adapted = _adapt(tmp_path)
    structure = adapted.documents["product_structure.json"]
    wheels = [
        item
        for item in structure["occurrences"]
        if item["properties"].get("referencedFileName") == "Wheel.SLDPRT"
    ]
    assert len(wheels) == 2
    assert wheels[0]["itemId"] == wheels[1]["itemId"]
    assert wheels[0]["occurrenceId"] != wheels[1]["occurrenceId"]
    graph = adapted.documents["interface_graph.json"]
    assert len(graph["mates"]) == 2
    assert len({item["mateId"] for item in graph["mates"]}) == 2
    assert {item["identityStrength"] for item in graph["mates"]} == {"weak"}
    assert adapted.documents["package.json"]["readiness"] == "structure_ready"


def test_adapter_is_deterministic_and_does_not_rewrite_legacy_ids(
    tmp_path: Path,
) -> None:
    first = _adapt(tmp_path)
    first_bytes = {
        name: canonical_json_bytes(document)
        for name, document in first.documents.items()
    }
    second = adapt_bridge_package(
        FIXTURE,
        source_root=tmp_path / "source",
        root_assembly=tmp_path / "source" / "SWPR-Tricycle.SLDASM",
        product_id="tricycle",
    )
    assert first_bytes == {
        name: canonical_json_bytes(document)
        for name, document in second.documents.items()
    }
    assert not any("nodeId" in document for document in second.documents.values())


def test_adapter_rejects_unknown_bridge_major_and_missing_sources(
    tmp_path: Path,
) -> None:
    root, assembly = _source_tree(tmp_path)
    modified = tmp_path / "bridge"
    (modified / "assembly").mkdir(parents=True)
    manifest = json.loads((FIXTURE / "manifest.json").read_text("utf-8"))
    manifest["schemaVersion"] = "2.0"
    (modified / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    (modified / "assembly" / "assembly.json").write_bytes(
        (FIXTURE / "assembly" / "assembly.json").read_bytes()
    )
    with pytest.raises(ExtractionAdapterError, match="Unsupported bridge"):
        adapt_bridge_package(
            modified,
            source_root=root,
            root_assembly=assembly,
            product_id="tricycle",
        )
    (root / "Wheel.SLDPRT").unlink()
    with pytest.raises(ExtractionAdapterError, match="missing"):
        adapt_bridge_package(
            FIXTURE,
            source_root=root,
            root_assembly=assembly,
            product_id="tricycle",
        )


def test_stale_source_detection_is_fail_closed(tmp_path: Path) -> None:
    adapted = _adapt(tmp_path)
    assert verify_sources_unchanged(adapted) == []
    (tmp_path / "source" / "Wheel.SLDPRT").write_bytes(b"changed")
    findings = verify_sources_unchanged(adapted)
    assert [item["code"] for item in findings] == [
        "source_changed_during_preparation"
    ]


def test_adapter_maps_root_assembly_mate_endpoint(tmp_path: Path) -> None:
    root, assembly = _source_tree(tmp_path)
    modified = tmp_path / "bridge-root-mate"
    (modified / "assembly").mkdir(parents=True)
    manifest = json.loads((FIXTURE / "manifest.json").read_text("utf-8"))
    bridge_assembly = json.loads(
        (FIXTURE / "assembly" / "assembly.json").read_text("utf-8")
    )
    bridge_assembly["mates"][0]["entity2"]["componentName"] = "SWPR-Tricycle"
    (modified / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    (modified / "assembly" / "assembly.json").write_text(
        json.dumps(bridge_assembly), "utf-8"
    )
    adapted = adapt_bridge_package(
        modified,
        source_root=root,
        root_assembly=assembly,
        product_id="tricycle",
    )
    root_id = adapted.documents["product_structure.json"]["rootOccurrenceId"]
    assert root_id in adapted.documents["interface_graph.json"]["mates"][0][
        "occurrenceRefs"
    ]


def test_repository_round_trip_and_cas(tmp_path: Path) -> None:
    adapted = _adapt(tmp_path)
    repository = AssemblyKnowledgeRepository(tmp_path / "generated" / "training")
    revision = repository.write(adapted.documents)
    assert revision == adapted.package_revision
    loaded = repository.read("tricycle", adapted.package_id)
    assert canonical_json_bytes(loaded) == canonical_json_bytes(adapted.documents)
    with pytest.raises(AssemblyKnowledgeConflict):
        repository.write(adapted.documents)
    assert (
        repository.write(adapted.documents, base_revision=adapted.package_revision)
        == adapted.package_revision
    )


def test_repository_rejects_tampered_document(tmp_path: Path) -> None:
    adapted = _adapt(tmp_path)
    repository = AssemblyKnowledgeRepository(tmp_path / "generated" / "training")
    repository.write(adapted.documents)
    package_dir = repository.package_dir("tricycle", adapted.package_id)
    structure_path = package_dir / "product_structure.json"
    structure = json.loads(structure_path.read_text("ascii"))
    structure["occurrences"][0]["name"] = "tampered"
    structure_path.write_text(json.dumps(structure), "ascii")
    with pytest.raises(Exception, match="hash mismatch"):
        repository.read("tricycle", adapted.package_id)
