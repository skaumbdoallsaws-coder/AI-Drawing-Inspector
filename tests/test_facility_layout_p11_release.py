from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import tools.verify_facility_layout_p11 as p11_verifier
from tools.verify_facility_layout_p11 import (
    FEATURE_FLAGS,
    build_accessibility_evidence,
    build_documentation_evidence,
    build_feature_flag_matrix,
    build_licensing_inventory,
    build_performance_evidence,
    build_visual_manifest,
    generate_release_evidence,
    run_feature_flag_matrix,
    run_maker_checker_pilot_gate,
    run_rollback_drill,
)


def test_performance_evidence_derives_observed_slice_without_overclaiming():
    evidence = build_performance_evidence()
    checks_passed = all(
        item["passed"] for item in evidence["observedBudgetChecks"]
    )
    browser_valid = evidence["browserEvidence"]["artifactShapeValid"]
    backend_valid = evidence["backendEvidence"]["artifactShapeValid"]
    assert evidence["observedChecksPassed"] is (
        checks_passed and browser_valid and backend_valid
    )
    assert evidence["standardHardwareSlicePassed"] is (
        evidence["observedChecksPassed"]
        and evidence["browserEvidence"]["hardwareMatch"]["matches"]
    )
    assert evidence["releaseGateMet"] is False
    assert "minimum_reference_hardware_unresolved" in evidence["blockers"]
    assert "minimum_hardware_release_benchmark_not_recorded" in (
        evidence["blockers"]
    )
    assert evidence["protocol"]["browser"]["frame"][
        "measuredSecondsPerRun"
    ] >= 60
    memory = next(
        item for item in evidence["observedBudgetChecks"]
        if item["budgetId"] == "memory-growth-after-20-remounts"
    )
    if memory["passed"] is False:
        assert (
            "browser:budget_failed:memory-growth-after-20-remounts"
            in evidence["blockers"]
        )


def test_performance_hardware_match_is_exact_and_source_derived():
    profile = {
        "measurement": {
            "machine": {"manufacturer": "Acme", "model": "Reference"},
            "cpu": {
                "name": "CPU",
                "physicalCores": 8,
                "logicalProcessors": 16,
            },
            "gpu": {
                "name": "GPU",
                "adapterRamBytesReported": 8_000,
                "driverVersion": "1.2.3",
            },
            "memory": {"ramBytes": 32_000},
            "operatingSystem": {"version": "10.0.1"},
            "browser": {
                "name": "Microsoft Edge",
                "productVersion": "150.0.0.0",
            },
        }
    }
    raw = {
        "environment": {
            "hardwareIdentity": {
                "machine": {
                    "manufacturer": "Acme",
                    "model": "Reference",
                },
                "cpus": [
                    {
                        "name": "CPU",
                        "cores": 8,
                        "logicalProcessors": 16,
                    }
                ],
                "gpus": [
                    {
                        "name": "GPU",
                        "adapterRam": 8_000,
                        "driverVersion": "1.2.3",
                    }
                ],
                "physicalMemoryBytes": 32_000,
                "operatingSystem": {"version": "10.0.1"},
                "browser": {
                    "name": "Microsoft Edge",
                    "version": "150.0.0.0",
                },
            }
        }
    }

    matched = p11_verifier._benchmark_matches_hardware_profile(raw, profile)
    assert matched["matches"] is True
    assert matched["expectedFingerprintSha256"] == (
        matched["observedFingerprintSha256"]
    )

    raw["environment"]["hardwareIdentity"]["machine"]["model"] = (
        "Unrelated"
    )
    mismatched = p11_verifier._benchmark_matches_hardware_profile(
        raw,
        profile,
    )
    assert mismatched["matches"] is False
    assert mismatched["blockers"] == [
        "benchmark_hardware_profile_mismatch"
    ]


def test_performance_benchmark_requires_raw_and_reproducible_summary(
    tmp_path: Path,
):
    missing = p11_verifier._validated_browser_benchmark(
        tmp_path / "minimum-raw.json",
        tmp_path / "minimum-summary.json",
        {},
    )
    assert missing["valid"] is False
    assert missing["validationErrors"] == [
        "benchmark_raw_or_summary_missing"
    ]

    raw_path = tmp_path / "raw.json"
    summary_path = tmp_path / "summary.json"
    raw_path.write_text("{}\n", encoding="ascii")
    summary_path.write_text(
        json.dumps({"releaseGateMet": True}) + "\n",
        encoding="ascii",
    )
    fabricated = p11_verifier._validated_browser_benchmark(
        raw_path,
        summary_path,
        {},
    )
    assert fabricated["valid"] is False
    assert "browser_summary_not_reproducible_from_raw" in (
        fabricated["validationErrors"]
    )


def test_static_accessibility_and_visual_manifests_are_source_bound():
    accessibility = build_accessibility_evidence()
    assert accessibility["staticContractPassed"] is True
    assert accessibility["automatedAuditPassed"] is True
    assert accessibility["criticalFindings"] == []
    assert accessibility["manualKeyboardAudit"] == (
        "covered_by_automated_browser_audit"
    )
    assert accessibility["contrastAudit"] == (
        "covered_by_automated_browser_audit"
    )
    assert accessibility["screenReaderAudit"] == "pending"
    assert accessibility["releaseGateMet"] is False

    visual = build_visual_manifest()
    assert visual["manifestValid"] is True
    assert visual["lightDarkArtifactRequirementMet"] is True
    assert visual["themesRepresented"] == ["dark", "light"]
    assert visual["missingExactCoverage"] == []
    assert visual["unexpectedExactCoverage"] == []
    assert visual["releaseGateMet"] is True
    assert visual["sourceBinding"]["present"] is True
    assert visual["sourceBinding"]["matches"] is True
    assert visual["sourceBinding"]["stalePaths"] == []
    assert visual["sourceBinding"]["inputCount"] == 12
    assert visual["webglContextRecovery"]["verified"] is True
    assert visual["webglContextRecovery"]["lostObserved"] is True
    assert visual["webglContextRecovery"]["restoredObserved"] is True
    assert len(visual["artifacts"]) == 8
    assert all(len(item["sha256"]) == 64 for item in visual["artifacts"])


def test_documentation_contracts_are_specific_and_fail_closed():
    evidence = build_documentation_evidence()
    assert evidence["pilotRunbookContainsSafetyDisclaimer"] is True
    assert evidence["allDocumentContractsPassed"] is True
    assert evidence["releaseGateMet"] is True
    assert all(
        record["contractPassed"]
        and all(record["accuracyChecks"].values())
        for record in evidence["documents"]
    )

    tampered = p11_verifier._documentation_contract_checks(
        "release_gates",
        "Evidence generation does not mean the pilot gate is met.",
    )
    assert tampered["evidenceGenerationIsNotReadiness"] is True
    assert tampered["standardAndMinimumHardwareRequired"] is False
    assert not all(tampered.values())


def test_feature_flag_matrix_exercises_every_runtime_stage(tmp_path: Path):
    evidence = run_feature_flag_matrix(tmp_path / "flags")
    assert [item["flag"] for item in evidence["flags"]] == list(
        FEATURE_FLAGS
    )
    assert all(item["runtimeWired"] is True for item in evidence["flags"])
    assert evidence["releaseGateMet"] is True
    assert evidence["blockers"] == []
    assert all(
        item["executionStatus"] == "passed"
        and item["passed"] is True
        and all(item["checks"].values())
        for item in evidence["matrix"]
    )


def test_licensing_inventory_covers_vendored_javascript_and_blocks_assets():
    inventory = build_licensing_inventory()
    coverage = inventory["vendoredJavaScriptCoverage"]
    assert coverage["complete"] is True
    assert coverage["missing"] == []
    assert coverage["discovered"] == coverage["covered"]
    assert all(
        package["license"] == "MIT"
        and package["licenseTextPresent"] is True
        for package in inventory["vendoredBrowserPackages"]
    )
    assert inventory["industrialAssetReadiness"][
        "notPublicReadyAssetIds"
    ]
    assert inventory["pythonDistributionDependencyReview"][
        "status"
    ] == "blocked"
    assert (
        "python_distribution_machine_assessment_blocked"
        in inventory["blockers"]
    )
    assert (
        "python_distribution_human_legal_review_pending"
        in inventory["blockers"]
    )
    assert inventory["releaseGateMet"] is False


def test_licensing_gate_requires_explicit_human_legal_clearance(
):
    source = deepcopy(
        p11_verifier._read_json(
            p11_verifier.PYTHON_DEPENDENCY_INVENTORY_SOURCE
        )
    )
    source["machineAssessment"]["gateMet"] = True
    source["humanLegalApproval"].update(
        {
            "status": "approved",
            "approved": True,
            "legalClearanceClaimed": False,
        }
    )
    source["releaseGateMet"] = True
    result = p11_verifier._python_distribution_release_gate(
        source,
        {"matches": True},
    )

    assert result["complete"] is False
    assert "python_distribution_legal_clearance_not_recorded" in (
        result["blockers"]
    )


def test_rollback_drill_preserves_all_bytes_and_exercises_flag_control(
    tmp_path: Path,
):
    evidence = run_rollback_drill(tmp_path / "rollback")
    assert evidence["noDataConversion"] is True
    assert evidence["noFileMutation"] is True
    assert evidence["dataFilesBefore"] == evidence["dataFilesAfter"]
    assert evidence["featureFlagControlEffective"] is True
    assert all(
        item["durableReceiptExact"] is True
        for item in evidence["observations"]
    )
    assert evidence["observations"][0]["consumedProposalStatus"] == 403
    assert evidence["observations"][1]["consumedProposalStatus"] == 404
    assert evidence["status"] == "passed"
    assert evidence["releaseGateMet"] is True


def test_maker_checker_pilot_gate_rejects_maker_and_applies_checker(
    tmp_path: Path,
):
    evidence = run_maker_checker_pilot_gate(tmp_path / "maker-checker")
    assert evidence["mode"]["requireDistinctApprover"] is True
    assert evidence["mode"]["principalAuthentication"] == "bearer"
    assert evidence["checks"]["productPrincipalIngress"] is True
    assert evidence["checks"]["bearerAuthenticationRequired"] is True
    assert evidence["checks"]["bootstrapReportsPolicy"] is True
    assert evidence["checks"]["sameMakerRejectedBeforeClaim"] is True
    assert evidence["observations"]["sameMakerErrorCode"] == (
        "maker_checker_required"
    )
    assert evidence["checks"]["distinctCheckerApproved"] is True
    assert evidence["checks"]["distinctCheckerApplied"] is True
    assert evidence["checks"]["canonicalReceiptPersisted"] is True
    assert evidence["releaseGateMet"] is True


def test_consolidated_verdict_is_derived_and_retains_external_gates(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        p11_verifier,
        "REAL_SOAK_EVENT_LEDGER",
        tmp_path / "missing-real-soak-events.json",
    )
    result = generate_release_evidence(
        tmp_path / "evidence",
        run_suites=False,
        skip_soak=True,
    )
    assert result["sectionGates"]["visual"] is True
    assert result["sectionGates"]["featureFlags"] is True
    assert result["sectionGates"]["makerChecker"] is True
    assert result["sectionGates"]["rollback"] is True
    assert result["sectionGates"]["performance"] is False
    assert result["sectionGates"]["accessibility"] is False
    assert result["sectionGates"]["licensing"] is False
    assert result["sectionGates"]["realSoak"] is False
    assert result["releaseGateMet"] is False
    assert result["status"] == "blocked"
    assert "facility_layout_flags_not_runtime_wired" not in result["blockers"]
    assert "visual_viewport_theme_matrix_incomplete" not in result["blockers"]
    assert (
        "python_distribution_machine_assessment_blocked"
        in result["blockers"]
    )
    assert "real_soak_not_started" in result["blockers"]
