from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from tools.benchmark_facility_layout_release_browser import (
    RAW_SCHEMA,
    REQUIRED_PROGRESSIVE_STAGES,
    SUMMARY_SCHEMA,
    build_summary,
    protocol_for,
    validate_raw_artifact,
    validate_required_inputs,
)


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "performance"
)
RAW = PERFORMANCE / "facility-layout-release-performance-smoke-raw.json"
SUMMARY = (
    PERFORMANCE
    / "facility-layout-release-performance-smoke-summary.json"
)


def _raw() -> dict:
    return json.loads(RAW.read_text(encoding="ascii"))


def _summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="ascii"))


def test_smoke_artifacts_are_source_bound_and_cover_real_adapters():
    raw = _raw()
    summary = _summary()

    assert raw["schemaVersion"] == RAW_SCHEMA
    assert validate_raw_artifact(raw) == []
    assert summary["schemaVersion"] == SUMMARY_SCHEMA
    assert summary["artifactShapeValid"] is True
    assert summary["validationErrors"] == []
    assert summary["status"] == "smoke_passed"
    assert summary["releaseEligible"] is False
    assert summary["releaseGateMet"] is False
    assert summary["blockers"] == [
        "smoke_profile_not_release_eligible"
    ]
    assert all(
        item["applicable"] is False and item["passed"] is None
        for item in summary["budgetChecks"]
    )

    proof = raw["samples"]["core"]["mount"]["snapshot"]["moduleProof"]
    assert proof["actualWorkspace"] is True
    assert proof["actualTopPlanAdapter"] is True
    assert proof["actualThreeAdapter"] is True
    assert proof["workspaceConstructor"] == "Workspace"
    assert proof["topAdapterType"] == "top-plan"
    assert proof["threeAdapterStatus"] == "ready"

    source_ids = {
        item["sourceId"] for item in raw["source"]["files"]
    }
    assert {
        "facility_layout_workspace",
        "facility_layout_editor",
        "facility_layout_session",
        "facility_layout_three_adapter",
        "p4_layout",
        "p4_asset_catalog",
        "p5_authoring_script",
        "rack_overview_glb",
        "rack_detail_glb",
    } <= source_ids
    assert "renderer_benchmark_html" not in source_ids


def test_artifact_has_every_required_raw_measurement_family():
    raw = _raw()
    samples = raw["samples"]

    facts = samples["planRender"]["layerFacts"]
    assert facts["layoutCounts"] == {
        "placements": 6,
        "routes": 1,
        "zones": 1,
    }
    assert facts["renderedCounts"] == facts["layoutCounts"]
    assert facts["layerOrder"] == ["zones", "routes", "placements"]
    assert facts["labels"]["accessibilityLabelCount"] == 7
    assert facts["labels"]["visibleTextLabelsSupported"] is False
    assert facts["labels"]["unavailableReason"]
    assert facts["clearances"]["routeCorridorCount"] == 1
    assert (
        facts["clearances"]["placementClearanceVolumesSupported"]
        is False
    )
    assert facts["clearances"]["unavailableReason"]

    assert samples["planFrames"][0]["frameIntervalsMs"]
    assert samples["threeFrames"][0]["frameIntervalsMs"]
    interactions = {
        item["interaction"]
        for item in samples["threeFrames"][0]["interaction"][
            "operations"
        ]
    }
    assert interactions == {"orbit", "pan"}
    assert samples["threeFrames"][0]["selection"]["synchronized"] is True
    assert samples["picking"]["samples"][0]["placementId"]
    assert (
        samples["idleRenderStop"]["samples"][0]["activeAdapterFrames"]
        == 0
    )

    loading = samples["assetLoading"][0]
    assert loading["networkProfile"] == "local"
    assert loading["cacheState"] == "cold"
    assert [
        item["stage"] for item in loading["load"]["stages"]
    ] == list(REQUIRED_PROGRESSIVE_STAGES)
    assert all(
        item["status"] == "resolved"
        and isinstance(item["durationMs"], (int, float))
        for item in loading["load"]["stages"]
    )
    assert any(
        item["name"].endswith(".glb")
        and item["encodedBodySize"] > 0
        for item in loading["load"]["resources"]
    )

    sequence = samples["remountMemory"][0]
    assert sequence["freshBrowserContext"] is True
    assert sequence["preciseMemoryInfo"] is True
    assert sequence["cycleCount"] == 2
    assert len(sequence["cycles"]) == 2
    assert sequence["initialMount"]["snapshot"]["rendererPool"] == {
        "availableCount": 0,
        "createdCount": 1,
        "disposed": False,
        "leasedCount": 1,
        "maximumSize": 1,
        "reusedCount": 0,
    }
    final_pool = sequence["cycles"][-1]["lifecycle"]["mounted"][
        "rendererPool"
    ]
    assert final_pool["createdCount"] == 1
    assert final_pool["leasedCount"] == 1
    assert final_pool["availableCount"] == 0
    assert final_pool["reusedCount"] == 2
    assert isinstance(
        sequence["before"]["performanceMemory"]["usedJSHeapSize"],
        int,
    )
    assert isinstance(
        sequence["after"]["cdpRuntimeHeapUsage"][
            "backingStorageSize"
        ],
        int,
    )


def test_release_protocol_matches_section_18_3_counts():
    protocol = protocol_for(False)

    assert protocol["profile"] == "release"
    assert protocol["releaseEligible"] is True
    assert protocol["discrete"] == {
        "discardedWarmups": 1,
        "measuredIterations": 30,
    }
    assert protocol["frame"] == {
        "runsPerScenario": 5,
        "warmupSecondsPerRun": 10.0,
        "measuredSecondsPerRun": 60.0,
        "minimumMeasuredFramesTotal": 3_000,
    }
    assert protocol["assetLoading"] == {
        "discardedWarmupsPerCondition": 1,
        "measuredIterationsPerCondition": 30,
        "networkProfiles": ["local", "50mbps"],
        "cacheStates": ["cold", "warm"],
    }
    assert protocol["remount"] == {
        "discardedWarmupsPerSequence": 0,
        "independentSequences": 5,
        "cyclesPerSequence": 20,
        "freshBrowserContextPerSequence": True,
        "explicitInitialMountBeforeBaseline": True,
        "quiescenceMsBeforeMemorySample": 1_000,
    }


def test_validator_fails_closed_for_missing_or_fabricated_evidence():
    original = _raw()

    no_route = deepcopy(original)
    no_route["samples"]["planRender"]["layerFacts"][
        "renderedCounts"
    ]["routes"] = 0
    assert "plan_rendered_count_mismatch:routes" in (
        validate_raw_artifact(no_route)
    )

    external = deepcopy(original)
    external["network"]["attemptedExternalRequests"] = [
        {"method": "GET", "url": "https://example.invalid/asset.glb"}
    ]
    assert "external_request_attempted" in validate_raw_artifact(
        external
    )

    no_memory = deepcopy(original)
    del no_memory["samples"]["remountMemory"][0]["after"][
        "performanceMemory"
    ]["usedJSHeapSize"]
    no_memory["unavailableRequiredMeasurements"] = ["precise_memory"]
    memory_errors = validate_raw_artifact(no_memory)
    assert "precise_js_heap_value_missing" in memory_errors
    assert "required_measurement_unavailable" in memory_errors

    duplicate_context = deepcopy(original)
    duplicate_context["protocol"]["remount"]["independentSequences"] = 2
    duplicate_context["samples"]["remountMemory"].append(
        deepcopy(duplicate_context["samples"]["remountMemory"][0])
    )
    duplicate_errors = validate_raw_artifact(duplicate_context)
    assert "remount_contexts_not_independent" in duplicate_errors

    bad_hash = deepcopy(original)
    bad_hash["source"]["files"][0]["sha256"] = "0" * 64
    assert any(
        error.startswith("source_hash_mismatch:")
        for error in validate_raw_artifact(bad_hash)
    )

    substituted_source = deepcopy(original)
    first, second = substituted_source["source"]["files"][:2]
    first.update(
        {
            "path": second["path"],
            "role": second["role"],
            "byteLength": second["byteLength"],
            "sha256": second["sha256"],
        }
    )
    substitution_errors = validate_raw_artifact(substituted_source)
    assert "source_path_mismatch:benchmark_runner" in substitution_errors
    assert "source_role_mismatch:benchmark_runner" in substitution_errors

    unexpected_source = deepcopy(original)
    unexpected_source["source"]["files"].append(
        {
            "sourceId": "attacker_controlled",
            "path": "../outside.json",
            "role": "governing_contract",
            "byteLength": 1,
            "sha256": "0" * 64,
        }
    )
    assert "unexpected_source_id:attacker_controlled" in (
        validate_raw_artifact(unexpected_source)
    )

    fabricated_growth = deepcopy(original)
    fabricated_growth["samples"]["remountMemory"][0][
        "growthPercent"
    ] = -99.0
    assert "remount_heap_growth_mismatch" in validate_raw_artifact(
        fabricated_growth
    )

    fabricated_pool = deepcopy(original)
    fabricated_pool["samples"]["remountMemory"][0]["cycles"][-1][
        "lifecycle"
    ]["mounted"]["rendererPool"]["createdCount"] = 2
    assert "remount_renderer_pool_reuse_invalid" in validate_raw_artifact(
        fabricated_pool
    )

    fabricated_hardware = deepcopy(original)
    fabricated_hardware["environment"]["hostHardware"][
        "physicalMemoryBytes"
    ] += 1
    hardware_errors = validate_raw_artifact(fabricated_hardware)
    assert "hardware_identity_mismatch" in hardware_errors
    assert "hardware_fingerprint_mismatch" in hardware_errors


def test_summary_never_promotes_invalid_or_smoke_evidence():
    raw = _raw()
    raw["unavailableRequiredMeasurements"] = ["picking"]
    raw["samples"]["picking"] = {}

    summary = build_summary(raw)

    assert summary["artifactShapeValid"] is False
    assert summary["releaseGateMet"] is False
    assert summary["status"] == "failed"
    assert "required_measurement_unavailable" in (
        summary["validationErrors"]
    )
    assert "picking_samples_missing" in summary["validationErrors"]


def test_missing_browser_or_inputs_fail_before_measurement(tmp_path: Path):
    errors = validate_required_inputs(
        tmp_path / "missing-edge-executable.exe"
    )

    assert any(error.startswith("missing_browser:") for error in errors)
