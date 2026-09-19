from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from ai_inspector.assembly_knowledge import (
    ROLLOUT_FIXTURE_IDS,
    adapt_bridge_package,
    compile_deterministic_evidence,
    evaluate_assembly_knowledge_package,
    evaluate_assembly_knowledge_rollout,
    refresh_package_revision,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)
RUNTIME_GUARDS = {
    "stalePackageProposalBlocked": True,
    "unapprovedWriteBlocked": True,
    "stalePackageProposalEvidence": (
        "test_package_revision_change_invalidates_builder_approval"
    ),
    "unapprovedWriteEvidence": "Builder explicit-approval suite",
}
ROLLOUT_MATRIX = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "rollout_matrix.json"
)


def _documents(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    return compile_deterministic_evidence(
        adapt_bridge_package(
            FIXTURE,
            source_root=source,
            root_assembly=root,
            product_id="tricycle",
        ).documents
    )


def _evaluate(documents, *, current=True, guards=RUNTIME_GUARDS):
    return evaluate_assembly_knowledge_package(
        documents,
        source_status={
            "bound": True,
            "current": current,
            "findings": [],
        },
        runtime_guards=guards,
    )


def test_hard_metrics_pass_for_deterministic_fixture(tmp_path: Path):
    report = _evaluate(_documents(tmp_path))
    assert report["summary"]["hardMetricsPassed"] is True
    assert report["summary"]["rolloutReady"] is False
    assert report["hardMetrics"][
        "repeatedOccurrenceIdentityCorrectness"
    ]["observed"]["repeatedItemGroups"] >= 1
    assert report["qualityMetrics"]["modelCalls"] == 0
    assert report["qualityMetrics"]["submittedImages"] == 0


def test_planning_readiness_and_runtime_guards_are_both_required(
    tmp_path: Path,
):
    documents = refresh_package_revision(
        _documents(tmp_path),
        package_updates={
            "readiness": "planning_ready",
            "productionEligible": False,
        },
    )
    ready = _evaluate(documents)
    assert ready["summary"]["rolloutReady"] is True
    missing_guards = _evaluate(documents, guards={})
    assert missing_guards["summary"]["hardMetricsPassed"] is False
    assert missing_guards["hardMetrics"]["stalePackageProposals"][
        "passed"
    ] is False
    assert missing_guards["hardMetrics"]["unapprovedProcessMapWrites"][
        "passed"
    ] is False


def test_changed_source_and_false_subassembly_fail_closed(tmp_path: Path):
    documents = _documents(tmp_path)
    changed_source = _evaluate(documents, current=False)
    assert changed_source["hardMetrics"]["sourceReferenceResolution"][
        "passed"
    ] is False

    false_subassembly = copy.deepcopy(documents)
    part = next(
        item
        for item in false_subassembly["product_structure.json"][
            "occurrences"
        ]
        if item["kind"] == "part"
    )
    part["kind"] = "subassembly"
    report = _evaluate(false_subassembly)
    assert report["hardMetrics"]["falseNativeSubassemblies"][
        "passed"
    ] is False


def test_unsupported_authority_and_numeric_values_are_hard_failures(
    tmp_path: Path,
):
    documents = _documents(tmp_path)
    template = copy.deepcopy(
        documents["functional_context.json"]["claims"][0]
    )
    unsupported = copy.deepcopy(template)
    unsupported.update(
        {
            "claimId": "claim-unsupported-authority",
            "authority": "authored",
            "knowledgeStatus": "derived",
            "reviewStatus": "confirmed",
        }
    )
    numeric = copy.deepcopy(template)
    numeric.update(
        {
            "claimId": "claim-invented-torque",
            "predicate": "torque_requirement",
            "value": {"torque": 8},
            "authority": "supporting",
            "knowledgeStatus": "derived",
            "reviewStatus": "confirmed",
        }
    )
    documents["functional_context.json"]["claims"].extend(
        [unsupported, numeric]
    )
    report = _evaluate(documents)
    assert report["hardMetrics"]["unsupportedAuthoritativeClaims"][
        "passed"
    ] is False
    assert report["hardMetrics"]["inventedNumericManufacturingValues"][
        "passed"
    ] is False
    assert report["summary"]["rolloutReady"] is False


def test_suppressed_missing_properties_and_large_repeated_fixture_scale(
    tmp_path: Path,
):
    documents = _documents(tmp_path)
    occurrences = documents["product_structure.json"]["occurrences"]
    part_template = copy.deepcopy(
        next(item for item in occurrences if item["kind"] == "part")
    )
    part_template["state"]["suppressed"] = True
    part_template["properties"] = {}
    root_id = documents["product_structure.json"]["rootOccurrenceId"]
    for index in range(400):
        item = copy.deepcopy(part_template)
        item["occurrenceId"] = f"occ-scale-{index:04d}"
        item["sourceOccurrenceId"] = item["occurrenceId"]
        item["parentOccurrenceId"] = root_id
        item["name"] = f"Repeated Part-{index + 1}"
        item["properties"] = {
            "sourceOccurrencePath": f"Root/Repeated Part-{index + 1}"
        }
        occurrences.append(item)
    started = time.perf_counter()
    report = _evaluate(documents)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert report["hardMetrics"]["occurrenceIdentityCorrectness"][
        "passed"
    ] is True
    assert report["hardMetrics"][
        "repeatedOccurrenceIdentityCorrectness"
    ]["passed"] is True


def _rollout_rows(tmp_path: Path):
    matrix = json.loads(ROLLOUT_MATRIX.read_text(encoding="ascii"))
    base_documents = _documents(tmp_path)
    base_report = _evaluate(base_documents)
    changed_report = _evaluate(base_documents, current=False)
    conflicting_documents = copy.deepcopy(base_documents)
    unsupported = copy.deepcopy(
        conflicting_documents["functional_context.json"]["claims"][0]
    )
    unsupported.update(
        {
            "claimId": "claim-rollout-unsupported-authority",
            "authority": "authored",
            "knowledgeStatus": "inferred",
            "reviewStatus": "pending",
        }
    )
    conflicting_documents["functional_context.json"]["claims"].append(
        unsupported
    )
    conflicting_report = _evaluate(conflicting_documents)
    reports = {
        "changed-part-revision": changed_report,
        "conflicting-authored-inferred-claims": conflicting_report,
    }
    rows = []
    for fixture in matrix["fixtures"]:
        report = copy.deepcopy(
            reports.get(fixture["fixtureId"], base_report)
        )
        if fixture["fixtureId"] == "four-cylinder-engine-functional":
            report["qualityMetrics"].update(
                {
                    "modelCalls": 1,
                    "submittedImages": 1,
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "totalTokens": 150,
                    "estimatedMaximumCostUsd": 0.02,
                    "pricingConfidence": "exact",
                }
            )
        if fixture["fixtureId"] == "large-assembly-scaling":
            report["identity"]["occurrenceCount"] = 404
        rows.append(
            {
                "fixtureId": fixture["fixtureId"],
                "expectedBlockedMetrics": fixture[
                    "expectedBlockedMetrics"
                ],
                "report": report,
            }
        )
    return matrix, rows


def test_rollout_matrix_covers_every_approved_scenario(tmp_path: Path):
    matrix, rows = _rollout_rows(tmp_path)
    assert matrix["schemaVersion"] == 1
    assert tuple(item["fixtureId"] for item in rows) == ROLLOUT_FIXTURE_IDS
    assert all(item["covers"] for item in matrix["fixtures"])
    assert all(item["evidence"] for item in matrix["fixtures"])


def test_rollout_gate_aggregates_expected_blocks_usage_and_review_burden(
    tmp_path: Path,
):
    _, rows = _rollout_rows(tmp_path)
    report = evaluate_assembly_knowledge_rollout(
        rows,
        feature_flag_guards={
            "preparationFlagRequired": True,
            "aiEnrichmentFlagRequired": True,
            "evidence": "tests/test_assembly_knowledge_preparation.py",
        },
    )
    assert report["summary"] == {
        "rolloutGatePassed": True,
        "fixtureCoveragePassed": True,
        "scenarioExpectationsPassed": True,
        "reviewBurdenGatePassed": True,
        "usageReportingPassed": True,
        "featureFlagGatePassed": True,
    }
    assert report["aggregateQuality"]["modelCalls"] == 1
    assert report["aggregateQuality"]["submittedImages"] == 1
    assert report["aggregateQuality"]["totalTokens"] == 150
    assert report["aggregateQuality"]["estimatedMaximumCostUsd"] == 0.02
    assert report["aggregateQuality"]["reviewActionsPerOccurrence"] == 0


def test_rollout_gate_fails_on_missing_fixture_unknown_cost_or_flag_gap(
    tmp_path: Path,
):
    _, rows = _rollout_rows(tmp_path)
    rows = rows[:-1]
    model_row = next(
        item
        for item in rows
        if item["fixtureId"] == "four-cylinder-engine-functional"
    )
    model_row["report"]["qualityMetrics"][
        "estimatedMaximumCostUsd"
    ] = None
    report = evaluate_assembly_knowledge_rollout(
        rows,
        feature_flag_guards={
            "preparationFlagRequired": True,
            "aiEnrichmentFlagRequired": False,
        },
    )
    assert report["summary"]["rolloutGatePassed"] is False
    assert report["fixtureCoverage"]["missing"] == [
        "large-assembly-scaling"
    ]
    assert report["summary"]["usageReportingPassed"] is False
    assert report["summary"]["featureFlagGatePassed"] is False
