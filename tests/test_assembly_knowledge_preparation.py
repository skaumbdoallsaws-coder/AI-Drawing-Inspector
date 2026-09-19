from __future__ import annotations

from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgePreparationError,
    AssemblyKnowledgeRepository,
    enrich_published_package,
    prepare_deterministic_package,
    prepare_occurrence_map,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)


def _sources(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    return source, root


def test_preparation_flag_is_required_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, root = _sources(tmp_path)
    monkeypatch.delenv(
        "INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE",
        raising=False,
    )
    with pytest.raises(AssemblyKnowledgePreparationError) as error:
        prepare_deterministic_package(
            training_root=tmp_path / "training",
            product_id="tricycle",
            extracted_package_dir=FIXTURE,
            source_root=source,
            root_assembly=root,
        )
    assert error.value.code == "preparation_disabled"
    assert not (tmp_path / "training").exists()


def test_deterministic_preparation_publishes_no_model_call_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, root = _sources(tmp_path)
    monkeypatch.setenv(
        "INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE",
        "1",
    )
    training_root = tmp_path / "training"
    receipt = prepare_deterministic_package(
        training_root=training_root,
        product_id="tricycle",
        extracted_package_dir=FIXTURE,
        source_root=source,
        root_assembly=root,
    )
    assert receipt["modelCalls"] == 0
    assert receipt["readiness"] == "function_ready"
    assert receipt["sourceStatus"]["current"] is True
    assert receipt["validation"]["valid"] is True
    repository = AssemblyKnowledgeRepository(training_root)
    documents = repository.read("tricycle", receipt["packageId"])
    assert documents["package.json"]["packageRevision"] == receipt[
        "packageRevision"
    ]


def test_occurrence_map_uses_canonical_adapter_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, root = _sources(tmp_path)
    monkeypatch.setenv(
        "INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE",
        "1",
    )
    output = tmp_path / "occurrence-map.tsv"
    receipt = prepare_occurrence_map(
        extracted_package_dir=FIXTURE,
        source_root=source,
        root_assembly=root,
        product_id="tricycle",
        output_path=output,
    )
    rows = [
        line.split("\t")
        for line in output.read_text("ascii").splitlines()
        if line and not line.startswith("#")
    ]
    assert receipt["modelCalls"] == 0
    assert receipt["mappedComponentCount"] == 3
    assert len(rows) == 3
    assert len({row[0] for row in rows}) == 3
    assert len({row[1] for row in rows}) == 3
    assert all(row[1].startswith("occ-") for row in rows)


def test_ai_enrichment_flag_blocks_before_provider_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source, root = _sources(tmp_path)
    monkeypatch.setenv(
        "INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE",
        "1",
    )
    training_root = tmp_path / "training"
    prepared = prepare_deterministic_package(
        training_root=training_root,
        product_id="tricycle",
        extracted_package_dir=FIXTURE,
        source_root=source,
        root_assembly=root,
    )
    monkeypatch.delenv(
        "INSPECTORPRO_ASSEMBLY_KNOWLEDGE_AI_ENRICHMENT",
        raising=False,
    )

    class Provider:
        def invoke(self, request):
            raise AssertionError("provider must not be called")

    with pytest.raises(AssemblyKnowledgePreparationError) as error:
        enrich_published_package(
            training_root=training_root,
            product_id="tricycle",
            package_id=prepared["packageId"],
            provider_name="fixture",
            model="fixture",
            provider=Provider(),
            explicit_approval=True,
            user_id="fixture-user",
            session_id="fixture-session",
            idempotency_key="fixture-disabled-enrichment",
        )
    assert error.value.code == "ai_enrichment_disabled"
