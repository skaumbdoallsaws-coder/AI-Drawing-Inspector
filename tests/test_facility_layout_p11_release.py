from __future__ import annotations

from pathlib import Path

from tools.verify_facility_layout_p11 import (
    FEATURE_FLAGS,
    build_accessibility_evidence,
    build_feature_flag_matrix,
    build_licensing_inventory,
    build_performance_evidence,
    build_visual_manifest,
    generate_release_evidence,
    run_feature_flag_matrix,
    run_maker_checker_pilot_gate,
    run_rollback_drill,
)


def test_performance_evidence_passes_observed_slice_without_overclaiming():
    evidence = build_performance_evidence()
    assert evidence["observedChecksPassed"] is True
    assert evidence["status"] == "partial"
    assert evidence["releaseGateMet"] is False
    assert "minimum_reference_hardware_unresolved" in evidence["blockers"]
    assert "benchmark_scope_is_placement_layer_only" in evidence["blockers"]
    assert evidence["protocol"]["measuredSecondsPerRun"] >= 60
    assert (
        "measurement_runs_are_10_seconds_not_required_60_seconds"
        not in evidence["blockers"]
    )
    assert all(
        item["passed"] for item in evidence["observedBudgetChecks"]
    )


def test_static_accessibility_and_visual_manifests_are_source_bound():
    accessibility = build_accessibility_evidence()
    assert accessibility["staticContractPassed"] is True
    assert accessibility["criticalFindings"] == []
    assert accessibility["manualKeyboardAudit"] == "pending"
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
    ] == "pending"
    assert (
        "python_distribution_dependency_review_pending"
        in inventory["blockers"]
    )
    assert inventory["releaseGateMet"] is False


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
):
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
    assert "python_distribution_dependency_review_pending" in result["blockers"]
