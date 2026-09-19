from __future__ import annotations

import copy
import json
from pathlib import Path

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeRepository,
    adapt_bridge_package,
    build_process_map_evidence_context,
    compile_deterministic_evidence,
    resolve_process_map_evidence_context,
    validate_package_documents,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)


def _documents(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    return adapt_bridge_package(
        FIXTURE,
        source_root=source,
        root_assembly=root,
        product_id="tricycle",
    ).documents


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def test_evidence_compilation_is_deterministic_and_schema_valid(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    first = compile_deterministic_evidence(documents)
    second = compile_deterministic_evidence(documents)
    assert _canonical(first) == _canonical(second)
    assert not [
        item
        for item in validate_package_documents(first)
        if item.get("severity") == "error"
    ]
    assert first["package.json"]["readiness"] == "function_ready"
    assert first["package.json"]["productionEligible"] is False


def test_deterministic_claims_cite_known_evidence_and_never_emit_sequence(
    tmp_path: Path,
) -> None:
    compiled = compile_deterministic_evidence(_documents(tmp_path))
    evidence_ids = {
        item["evidenceId"]
        for item in compiled["evidence_catalog.json"]["sources"]
    }
    claims = compiled["functional_context.json"]["claims"]
    assert claims
    assert all(set(item["evidenceRefs"]).issubset(evidence_ids) for item in claims)
    assert not {
        item["predicate"] for item in claims
    } & {
        "manufacturing_order",
        "precedes",
        "assembly_sequence",
        "operation",
        "operation_family",
    }
    process = compiled["process_candidates.json"]
    assert process["claims"] == []
    assert process["branches"] == []
    assert process["operationFamilies"] == []
    assert any(
        item["code"] == "manufacturing_sequence_not_established"
        for item in compiled["unresolved.json"]["findings"]
    )


def test_evidence_fingerprint_changes_when_source_fact_changes(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    baseline = compile_deterministic_evidence(documents)
    changed = copy.deepcopy(documents)
    changed["product_structure.json"]["occurrences"][1]["transform"]["translation"][0] = 9.0
    revised = compile_deterministic_evidence(changed)
    assert (
        baseline["evidence_catalog.json"]["evidenceFingerprint"]
        != revised["evidence_catalog.json"]["evidenceFingerprint"]
    )


def test_trusted_process_map_evidence_context_is_compact_and_origin_tagged(
    tmp_path: Path,
) -> None:
    compiled = compile_deterministic_evidence(_documents(tmp_path))
    context = build_process_map_evidence_context(
        compiled,
        maximum_characters=8_000,
    )
    assert context["origin"] == {
        "kind": "server",
        "provider": "assembly_knowledge_repository",
    }
    assert context["semanticBoundary"]["cadFactsDoNotEstablish"]
    assert len(_canonical(context)) <= 8_000


def test_repository_resolves_server_owned_process_map_evidence(
    tmp_path: Path,
) -> None:
    compiled = compile_deterministic_evidence(_documents(tmp_path / "input"))
    repository = AssemblyKnowledgeRepository(tmp_path / "training")
    repository.write(compiled)
    context = resolve_process_map_evidence_context(
        tmp_path / "training",
        "tricycle",
    )
    assert context is not None
    assert context["identity"]["packageRevision"] == compiled["package.json"][
        "packageRevision"
    ]
    assert context["origin"]["kind"] == "server"
