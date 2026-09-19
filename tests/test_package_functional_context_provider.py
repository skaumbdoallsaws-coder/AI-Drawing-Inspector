from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge.runtime_provider import (
    PackageFunctionalContextProvider,
)
from ai_inspector.product_intelligence.functional_relationships import (
    FunctionalRelationshipError,
    FunctionalRelationshipRegistry,
    build_functional_context,
)


ROOT = Path(__file__).resolve().parents[1]


def _provider() -> PackageFunctionalContextProvider:
    return PackageFunctionalContextProvider(ROOT / "generated" / "training")


def test_catalog_adapter_preserves_all_eight_runtime_contexts() -> None:
    provider = _provider()
    registry = FunctionalRelationshipRegistry()
    graph, _ = registry.load("100001")
    for component in graph["component_types"]:
        part_number = component["part_number"]
        expected = build_functional_context(graph, part_number=part_number)
        actual, diagnostics = provider.context_for_asset(
            assembly_number="100001",
            part_number=part_number,
            prototype_mode=True,
        )
        assert actual == expected
        assert diagnostics["provider"] == "assembly_knowledge_package_catalog_adapter"
        assert diagnostics["fallbackUsed"] is False


def test_catalog_remains_read_only_fallback_when_prototype_mode_is_off() -> None:
    provider = _provider()
    graph, _ = FunctionalRelationshipRegistry().load("100001")
    expected = build_functional_context(graph, part_number="100006")
    actual, diagnostics = provider.context_for_asset(
        assembly_number="100001",
        part_number="100006",
        prototype_mode=False,
    )
    assert actual == expected
    assert diagnostics["provider"] == "functional_catalog_fallback"
    assert diagnostics["fallbackUsed"] is True
    assert diagnostics["eligibility"]["code"] == "prototype_mode_required"


def test_mmle_native_retrieval_is_explicit_bounded_and_nonproduction() -> None:
    context, diagnostics = _provider().context_for_asset(
        assembly_number="MMLE-50D",
        part_number="1030097",
        include_available_parts=True,
        prototype_mode=True,
    )
    retrieval = diagnostics["retrieval"]
    assert diagnostics["provider"] == "assembly_knowledge_package_native"
    assert diagnostics["productionEligible"] is False
    assert diagnostics["eligibility"]["code"] == "prototype_eligible"
    assert retrieval["returnedCount"] <= 12
    assert retrieval["renderedCharacters"] <= 6000
    assert len(context["available_parts"]) == 70
    assert all(
        claim["subjectRef"].startswith(("occ-", "interface-"))
        for claim in context["assembly_semantic_claims"]
    )
    assert len(
        json.dumps(context["assembly_semantic_claims"], separators=(",", ":"))
    ) <= 6000


def test_controlled_or_stale_mmle_package_fails_closed(monkeypatch) -> None:
    provider = _provider()
    with pytest.raises(FunctionalRelationshipError):
        provider.context_for_asset(
            assembly_number="MMLE-50D",
            part_number="1030097",
            prototype_mode=True,
            controlled_use=True,
        )

    monkeypatch.setattr(
        provider.repository,
        "source_status",
        lambda product_id, package_id: {
            "bound": True,
            "current": False,
            "checkedSourceCount": 1,
            "findings": [{"code": "source_file_changed"}],
        },
    )
    provider.clear_cache()
    with pytest.raises(FunctionalRelationshipError):
        provider.context_for_asset(
            assembly_number="MMLE-50D",
            part_number="1030097",
            prototype_mode=True,
        )


def test_package_provider_warm_retrieval_p95_is_under_50_ms() -> None:
    provider = _provider()
    provider.context_for_asset(
        assembly_number="MMLE-50D",
        part_number="1030097",
        prototype_mode=True,
    )
    samples = []
    for _ in range(25):
        started = time.perf_counter()
        provider.context_for_asset(
            assembly_number="MMLE-50D",
            part_number="1030097",
            prototype_mode=True,
        )
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
    assert p95 <= 50.0
