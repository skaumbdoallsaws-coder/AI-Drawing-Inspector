from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.synthetic_planning_corpus import (
    build_synthetic_facility_corpus,
    build_synthetic_facility_planning_package,
    compile_synthetic_facility_example,
    evaluate_synthetic_facility_negative_cases,
    synthetic_facility_archetypes,
    synthetic_facility_intent_cases,
    synthetic_facility_variants,
)
from tools.build_facility_planning_synthetic_corpus import _validated_output_root


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = (
    ROOT / "generated" / "facility_planning" / "synthetic-corpus" / "v1"
)
BROWSER_EVIDENCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "synthetic_corpus"
    / "browser-evidence.json"
)
EXPECTED_AUTHORITY = {
    "knowledgeStatus": "inferred",
    "authority": "illustrative",
    "reviewStatus": "pending",
    "productionEligible": False,
    "planningClaim": "illustrative_prototype",
    "reviewReceiptId": None,
}


def _catalog() -> list[dict]:
    return build_private_local_asset_catalog(ROOT)


def test_corpus_has_12_unique_archetypes_and_4_variants() -> None:
    archetypes = synthetic_facility_archetypes()
    variants = synthetic_facility_variants()

    assert len(archetypes) == 12
    assert len({item["archetype_id"] for item in archetypes}) == 12
    assert len(variants) == 4
    assert [item["variant_id"] for item in variants] == [
        "pilot",
        "balanced",
        "expanded",
        "high-throughput",
    ]


def test_all_package_contracts_are_illustrative_and_split_without_leakage() -> None:
    corpus = build_synthetic_facility_corpus(_catalog())

    assert len(corpus) == 48
    assert Counter(item["metadata"]["split"] for item in corpus) == {
        "development": 24,
        "evaluation": 8,
        "heldout": 16,
    }
    assert len({item["package"]["packageId"] for item in corpus}) == 48

    splits_by_archetype: dict[str, set[str]] = defaultdict(set)
    for item in corpus:
        package = item["package"]
        metadata = item["metadata"]
        splits_by_archetype[metadata["archetypeId"]].add(metadata["split"])
        assert package["authority"] == EXPECTED_AUTHORITY
        assert all(
            evidence["authority"] != "controlled"
            and evidence["reviewStatus"] != "confirmed"
            for evidence in package["evidenceRegister"]
        )
        assert all(
            not evidence["synthetic"]
            or (
                evidence["authority"] == "illustrative"
                and evidence["reviewStatus"] == "pending"
            )
            for evidence in package["evidenceRegister"]
        )

    heldout_archetypes = {
        item["metadata"]["archetypeId"]
        for item in corpus
        if item["metadata"]["split"] == "heldout"
    }
    assert len(heldout_archetypes) == 4
    assert all(splits_by_archetype[item] == {"heldout"} for item in heldout_archetypes)
    assert all(
        "heldout" not in splits
        for archetype, splits in splits_by_archetype.items()
        if archetype not in heldout_archetypes
    )


def test_representative_packages_compile_to_unsaved_deterministic_layouts() -> None:
    catalog = _catalog()
    cases = (
        ("linear-discrete-assembly", "pilot"),
        ("distribution-center", "high-throughput"),
        ("compact-urban-factory", "balanced"),
    )

    for archetype_id, variant_id in cases:
        package = build_synthetic_facility_planning_package(
            archetype_id, variant_id, catalog
        )
        first = compile_synthetic_facility_example(package, catalog)
        second = compile_synthetic_facility_example(package, catalog)

        assert first["execution"]["saved"] is False
        assert first["execution"]["authority"]["production_eligible"] is False
        assert first["execution"]["draftLayoutRevision"] == second["execution"][
            "draftLayoutRevision"
        ]
        assert first["execution"]["draftLayout"] == second["execution"][
            "draftLayout"
        ]
        assert first["execution"]["counts"]["zones"] > 0
        assert first["execution"]["counts"]["placements"] > 0


def test_negative_cases_fail_closed_without_mutating_the_base() -> None:
    catalog = _catalog()
    package = build_synthetic_facility_planning_package(
        "linear-discrete-assembly", "pilot", catalog
    )
    report = evaluate_synthetic_facility_negative_cases(package, catalog)

    assert report["caseCount"] == report["passedCount"] == 12
    assert all(item["status"] == "expected_refusal" for item in report["cases"])
    assert all(item["baseRevisionUnchanged"] for item in report["cases"])
    assert all(
        item["actualCode"] == item["expectedCode"] for item in report["cases"]
    )


def test_intent_cases_are_revision_bound_and_never_request_save() -> None:
    catalog = _catalog()
    corpus = build_synthetic_facility_corpus(catalog)
    cases = [
        case
        for item in corpus
        for case in synthetic_facility_intent_cases(item["package"], item["metadata"])
    ]

    assert len(cases) == 144
    assert len({item["caseId"] for item in cases}) == 144
    assert all(item["expectedSaved"] is False for item in cases)
    assert all(item["expectedAuthority"] == "illustrative" for item in cases)
    assert all(
        item["expectedExecutionMode"] == "authorized_draft_run" for item in cases
    )


def test_generated_manifest_records_a_complete_passing_local_build() -> None:
    manifest_path = GENERATED_ROOT / "manifest.json"
    report_path = GENERATED_ROOT / "evaluation-report.json"
    assert manifest_path.is_file()
    assert report_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = manifest["summary"]

    assert summary["archetypeCount"] == 12
    assert summary["variantCount"] == 4
    assert summary["packageCount"] == summary["layoutCount"] == 48
    assert summary["positivePassedCount"] == 48
    assert summary["negativePassedCount"] == summary["negativeCaseCount"] == 12
    assert summary["intentCaseCount"] == 144
    assert summary["splitCounts"] == {
        "development": 24,
        "evaluation": 8,
        "heldout": 16,
    }
    assert manifest["corpusRevision"] == report["corpusRevision"]
    assert len({item["packageId"] for item in manifest["examples"]}) == 48
    assert len({item["packageRevision"] for item in manifest["examples"]}) == 48
    assert len(
        {item["facilityProgramRevision"] for item in manifest["examples"]}
    ) == 48
    assert len(
        {item["operationPlanRevision"] for item in manifest["examples"]}
    ) == 48
    assert len({item["layoutRevision"] for item in manifest["examples"]}) == 48
    assert all(item["saved"] is False for item in manifest["examples"])
    assert all(item["productionEligible"] is False for item in manifest["examples"])
    assert all((GENERATED_ROOT / item["packagePath"]).is_file() for item in manifest["examples"])
    assert all((GENERATED_ROOT / item["layoutPath"]).is_file() for item in manifest["examples"])


def test_generator_rejects_destructive_output_outside_its_owned_root() -> None:
    assert _validated_output_root(GENERATED_ROOT) == GENERATED_ROOT.resolve()
    with pytest.raises(ValueError):
        _validated_output_root(ROOT)
    with pytest.raises(ValueError):
        _validated_output_root(ROOT / "generated" / "facility_planning")


def test_representative_browser_captures_are_nonblank_and_nonmutating() -> None:
    assert BROWSER_EVIDENCE.is_file()

    evidence = json.loads(BROWSER_EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["captureCount"] == 6
    assert evidence["savedLayoutUnchanged"] is True
    assert evidence["pageErrors"] == []
    assert evidence["consoleErrors"] == []
    assert evidence["failedRequests"] == []
    assert evidence["serverErrors"] == []
    assert all(item["planImage"]["nonBlank"] for item in evidence["captures"])
    three_d = [
        item for item in evidence["captures"] if item.get("threeDImage")
    ]
    assert len(three_d) >= 1
    assert all(item["threeDImage"]["nonBlank"] for item in three_d)
    assert all(item["threeDCanvas"]["nonBlank"] for item in three_d)
