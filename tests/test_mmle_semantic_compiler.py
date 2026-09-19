from __future__ import annotations

import json
from pathlib import Path

from ai_inspector.assembly_knowledge.manifest import sha256_file
from ai_inspector.assembly_knowledge.mmle_compiler import (
    MMLE_EXTRACT_PATH,
    compile_deterministic_mmle,
    deterministic_probe,
)
from ai_inspector.assembly_knowledge.repository import AssemblyKnowledgeRepository
from ai_inspector.assembly_knowledge.semantic_rollout import (
    MMLE_PACKAGE_ID,
    MMLE_PRODUCT_ID,
)
from ai_inspector.assembly_knowledge.validation import (
    validate_assembly_knowledge_package,
)


ROOT = Path(__file__).resolve().parents[1]


def _documents() -> dict:
    repository = AssemblyKnowledgeRepository(ROOT / "generated" / "training")
    return repository.read(MMLE_PRODUCT_ID, MMLE_PACKAGE_ID)


def _compiled() -> dict:
    extract_path = ROOT / MMLE_EXTRACT_PATH
    raw = json.loads(extract_path.read_text(encoding="utf-8-sig"))
    return compile_deterministic_mmle(
        _documents(),
        raw,
        raw_extract_sha256=sha256_file(extract_path),
    )


def test_mmle_cad_mates_compile_without_inference_or_schema_errors() -> None:
    compiled = _compiled()
    assert len(compiled["interface_graph.json"]["mates"]) == 206
    assert len(compiled["interface_graph.json"]["interfaces"]) == 130
    claims = compiled["functional_context.json"]["claims"]
    assert len(claims) == 130
    assert {item["predicate"] for item in claims} == {
        "cad_interface_relationship"
    }
    assert {item["knowledgeStatus"] for item in claims} == {"derived"}
    assert {item["authority"] for item in claims} == {"supporting"}
    assert {item["reviewStatus"] for item in claims} == {"confirmed"}
    assert compiled["package.json"]["productionEligible"] is False
    assert compiled["package.json"]["readiness"] == "function_ready"
    assert not [
        item
        for item in validate_assembly_knowledge_package(compiled)
        if item["severity"] == "error"
    ]


def test_mmle_compilation_is_byte_stable_and_idempotent() -> None:
    extract_path = ROOT / MMLE_EXTRACT_PATH
    raw = json.loads(extract_path.read_text(encoding="utf-8-sig"))
    digest = sha256_file(extract_path)
    first = compile_deterministic_mmle(
        _documents(), raw, raw_extract_sha256=digest
    )
    second = compile_deterministic_mmle(first, raw, raw_extract_sha256=digest)
    assert second == first


def test_deterministic_probe_resolves_all_crosswalk_rows_and_ambiguities() -> None:
    crosswalk = json.loads(
        (ROOT / "docs" / "semantic-knowledge" / "mmle-entity-crosswalk.json").read_text(
            encoding="ascii"
        )
    )
    probe = deterministic_probe(_compiled(), crosswalk)
    assert probe["passed"] is True
    assert probe["failedQueryIds"] == []
    assert probe["caseKindCounts"]["identity"] == 70
    assert probe["caseKindCounts"]["relationship"] == 20
    assert probe["caseKindCounts"]["operation"] == 10
    assert probe["caseKindCounts"]["ambiguous_identity"] > 0
    assert all(
        item["actual"]["selectedBinding"] is None
        for item in probe["cases"]
        if item["kind"] == "ambiguous_identity"
    )

