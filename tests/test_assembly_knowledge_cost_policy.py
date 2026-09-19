from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeEnrichmentCache,
    EnrichmentBudgetError,
    adapt_bridge_package,
    assert_authorization_matches_plan,
    authorize_enrichment_plan,
    build_enrichment_cache_key,
    build_enrichment_semantic_input,
    changed_occurrence_ids,
    compile_deterministic_evidence,
    enrichment_process_reference_map,
    occurrence_dependency_fingerprints,
    plan_enrichment_request,
    required_process_input_occurrence_ids,
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
    documents = compile_deterministic_evidence(
        adapt_bridge_package(
            FIXTURE,
            source_root=source,
            root_assembly=root,
            product_id="tricycle",
        ).documents
    )
    documents["package.json"]["assetHashes"] = {
        "visuals/presentation/contact-sheet.png": "1" * 64,
        "visuals/presentation/front.png": "2" * 64,
    }
    documents["visual_manifest.json"]["contactSheets"] = [
        {
            "contactSheetId": "sheet-1",
            "assetPath": "visuals/presentation/contact-sheet.png",
            "assetHash": "1" * 64,
            "width": 1800,
            "height": 1300,
            "viewIds": ["view-1"],
        }
    ]
    documents["visual_manifest.json"]["views"] = [
        {
            "viewId": "view-1",
            "kind": "presentation",
            "projection": "orthographic",
            "assetPath": "visuals/presentation/front.png",
            "assetHash": "2" * 64,
            "width": 1518,
            "height": 683,
            "camera": {},
            "visibleOccurrenceIds": [],
            "mateIds": [],
            "featureIds": [],
            "maskAssetPath": None,
            "maskAssetHash": None,
            "colorLegend": {},
        }
    ]
    return documents


def test_semantic_input_names_the_exact_process_contract(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    structure = documents["product_structure.json"]
    required_ids = required_process_input_occurrence_ids(structure)
    assert required_ids == sorted(
        item["occurrenceId"]
        for item in structure["occurrences"]
        if item["occurrenceId"] != structure["rootOccurrenceId"]
    )
    semantic_input = build_enrichment_semantic_input(documents)
    assert semantic_input["rootOccurrenceId"] == structure["rootOccurrenceId"]
    process_refs = enrichment_process_reference_map(structure)
    assert semantic_input["rootProcessRef"] == "occRef-root"
    assert semantic_input["requiredProcessInputRefs"] == [
        process_refs[occurrence_id] for occurrence_id in required_ids
    ]

    structure["occurrences"][1]["state"]["suppressed"] = True
    assert structure["occurrences"][1]["occurrenceId"] not in (
        required_process_input_occurrence_ids(structure)
    )


@pytest.mark.parametrize("occurrence_count", [1, 25, 250])
def test_economy_call_count_is_constant(
    tmp_path: Path,
    occurrence_count: int,
) -> None:
    documents = _documents(tmp_path)
    prototype = documents["product_structure.json"]["occurrences"][0]
    documents["product_structure.json"]["occurrences"] = [
        {
            **copy.deepcopy(prototype),
            "occurrenceId": f"occ-{index:08x}",
            "sourceOccurrenceId": f"occ-{index:08x}",
        }
        for index in range(occurrence_count)
    ]
    # Keep the payload estimate stable to isolate the call-count invariant.
    plan = plan_enrichment_request(
        documents,
        provider="openai",
        model="gpt-4o-mini",
        prompt_version="fixture-v1",
        prompt_characters=0,
    )
    assert plan["uncachedPlannedCalls"] == 1
    assert plan["maximumProviderAttempts"] == 2
    assert plan["maximumRetries"] == 1
    assert plan["perOccurrenceCalls"] == 0
    assert plan["perInterfaceCalls"] == 0


def test_oversized_catalog_fails_before_any_paid_call(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    prototype = documents["product_structure.json"]["occurrences"][0]
    documents["product_structure.json"]["occurrences"] = [
        {
            **copy.deepcopy(prototype),
            "occurrenceId": f"occ-{index:08x}",
            "sourceOccurrenceId": f"occ-{index:08x}",
        }
        for index in range(10_000)
    ]
    with pytest.raises(EnrichmentBudgetError) as exc:
        plan_enrichment_request(
            documents,
            provider="openai",
            model="gpt-4o-mini",
            prompt_version="fixture-v1",
            prompt_characters=0,
        )
    assert exc.value.code == "input_token_budget_exceeded"


def test_schema_correction_is_the_only_second_call(tmp_path: Path) -> None:
    plan = plan_enrichment_request(
        _documents(tmp_path),
        provider="openai",
        model="gpt-4o-mini",
        prompt_version="fixture-v1",
        schema_correction_required=True,
    )
    assert plan["uncachedPlannedCalls"] == 2
    assert plan["maximumProviderAttempts"] == 2
    assert plan["maximumRetries"] == 0
    assert plan["schemaCorrectionOnly"] is True


def test_unknown_pricing_is_not_reported_as_zero_cost(tmp_path: Path) -> None:
    plan = plan_enrichment_request(
        _documents(tmp_path),
        provider="fixture-provider",
        model="unknown-model",
        prompt_version="fixture-v1",
    )
    assert plan["pricingKnown"] is False
    assert plan["pricingConfidence"] == "unknown"
    assert plan["estimatedMaximumCostUsd"] is None
    denied = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-enrichment-0001",
    )
    assert denied == {
        "authorized": False,
        "reason": "unknown_pricing_acknowledgement_required",
    }


def test_authorization_is_explicit_and_bound_to_plan(tmp_path: Path) -> None:
    plan = plan_enrichment_request(
        _documents(tmp_path),
        provider="openai",
        model="gpt-4o-mini",
        prompt_version="fixture-v1",
    )
    assert authorize_enrichment_plan(
        plan,
        explicit_approval=False,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-enrichment-0002",
    )["reason"] == "explicit_approval_required"
    authorized = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-enrichment-0002",
    )
    assert authorized["authorized"] is True
    assert_authorization_matches_plan(plan, authorized)
    changed = dict(plan)
    changed["requestFingerprint"] = "f" * 64
    with pytest.raises(EnrichmentBudgetError) as exc:
        assert_authorization_matches_plan(changed, authorized)
    assert exc.value.code == "authorization_fingerprint_mismatch"


def test_cache_key_binds_every_required_revision_axis() -> None:
    base = {
        "source_revision": "1" * 64,
        "evidence_fingerprint": "2" * 64,
        "image_hashes": ["3" * 64],
        "enrichment_policy_version": "economy-v1",
        "prompt_version": "prompt-v1",
        "provider": "openai",
        "model": "gpt-4o-mini",
    }
    baseline = build_enrichment_cache_key(**base)
    for field, replacement in (
        ("source_revision", "4" * 64),
        ("evidence_fingerprint", "5" * 64),
        ("image_hashes", ["6" * 64]),
        ("enrichment_policy_version", "economy-v2"),
        ("prompt_version", "prompt-v2"),
        ("provider", "anthropic"),
        ("model", "other-model"),
    ):
        changed = dict(base)
        changed[field] = replacement
        assert build_enrichment_cache_key(**changed) != baseline


def test_occurrence_delta_and_atomic_cache_round_trip(tmp_path: Path) -> None:
    documents = _documents(tmp_path / "input")
    first = occurrence_dependency_fingerprints(documents)
    changed_documents = copy.deepcopy(documents)
    changed_documents["product_structure.json"]["occurrences"][0]["name"] = "Changed"
    second = occurrence_dependency_fingerprints(changed_documents)
    changed = changed_occurrence_ids(first, second)
    assert changed == [
        changed_documents["product_structure.json"]["occurrences"][0][
            "occurrenceId"
        ]
    ]

    cache = AssemblyKnowledgeEnrichmentCache(tmp_path / "cache")
    cache_key = "a" * 64
    assert cache.read(cache_key) is None
    written = cache.write(
        cache_key,
        request_fingerprint="b" * 64,
        response={"roles": []},
        usage={"inputTokens": 10, "outputTokens": 2},
        provider="fixture",
        model="fixture-v1",
        occurrence_fingerprints=second,
    )
    assert cache.read(cache_key) == written


def test_budget_rejects_excessive_output_tokens(tmp_path: Path) -> None:
    with pytest.raises(EnrichmentBudgetError) as exc:
        plan_enrichment_request(
            _documents(tmp_path),
            provider="openai",
            model="gpt-4o-mini",
            prompt_version="fixture-v1",
            maximum_output_tokens=100_000,
        )
    assert exc.value.code == "output_token_budget_exceeded"
