from __future__ import annotations

import json
from pathlib import Path
import statistics
import hashlib

from ai_inspector.facility_layout.validate import validate_layout
from tools.benchmark_facility_layout_backend_release import (
    DEFAULT_RESULT_PATH,
    DEFAULT_SPEC_PATH,
    REPO_ROOT,
    RESULT_SCHEMA_VERSION,
    SPATIAL_CONTRACT_PATH,
    build_fixture_bundle,
    deterministic_result_manifest,
    run_benchmark,
)


EXPECTED_OPERATION_IDS = [
    "moved_object_spatial_query",
    "candidate_generation",
    "collision_clearance_query",
    "full_diagnostics",
    "forklift_routing",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(
        samples,
        n=100,
        method="inclusive",
    )[94]


def test_spec_pins_contract_scale_protocol_and_release_budgets() -> None:
    spec = _load(DEFAULT_SPEC_PATH)
    contract = _load(SPATIAL_CONTRACT_PATH)
    fixture = spec["primaryFixture"]
    assert fixture["placementCount"] == 500
    assert fixture["zoneCount"] == 100
    assert fixture["routeCount"] == 200
    assert spec["protocol"]["warmupIterations"] == 1
    assert spec["protocol"]["measuredIterations"] == 30
    operations = {
        item["operationId"]: item for item in spec["operations"]
    }
    assert list(operations) == EXPECTED_OPERATION_IDS
    targets = contract["performanceTargets"]
    assert operations["candidate_generation"]["budgetP95Milliseconds"] == (
        targets["backendCandidateGenerationP95Ms"]
    )
    assert operations["collision_clearance_query"][
        "budgetP95Milliseconds"
    ] == targets["backendCollisionQueryP95Ms"]
    assert operations["full_diagnostics"]["budgetP95Milliseconds"] == (
        targets["backendFullDiagnosticsP95Ms"]
    )
    assert operations["moved_object_spatial_query"][
        "budgetP95Milliseconds"
    ] == 20.0
    assert operations["forklift_routing"]["budgetP95Milliseconds"] == 500.0
    assert spec["unavailableOperations"] == [
        {
            "operationId": "browser_advisory_response",
            "required": False,
            "availability": "unavailable",
            "reason": (
                "The advisory implementation is a browser Web Worker API and "
                "is outside this deterministic backend-only harness."
            ),
        }
    ]


def test_generated_primary_fixture_is_canonical_and_hash_stable() -> None:
    spec = _load(DEFAULT_SPEC_PATH)
    first = build_fixture_bundle(spec, smoke=False)
    second = build_fixture_bundle(spec, smoke=False)
    assert first["hashes"] == second["hashes"]
    layout = first["primary"]["layout"]
    assert validate_layout(layout, require_canonical=True) is layout
    assert len(layout["placements"]) == 500
    assert len(layout["zones"]) == 100
    assert len(layout["routes"]) == 200
    assert len(first["forklift"]["traversablePolygons"]) == 2


def test_smoke_runner_schema_and_deterministic_outputs() -> None:
    first = run_benchmark(smoke=True)
    second = run_benchmark(smoke=True)
    assert first["schemaVersion"] == RESULT_SCHEMA_VERSION
    assert first["mode"] == "smoke"
    assert first["releaseEligible"] is False
    assert first["releaseSlicePassed"] is False
    assert first["smokePassed"] is True
    assert first["protocol"]["warmupIterations"] == 1
    assert first["protocol"]["measuredIterations"] == 3
    assert first["requiredOperationsAvailable"] is True
    assert first["determinismPassed"] is True
    assert deterministic_result_manifest(first) == (
        deterministic_result_manifest(second)
    )
    assert first["deterministicEvidenceSha256"] == (
        second["deterministicEvidenceSha256"]
    )
    assert [
        item["operationId"] for item in first["operations"]
    ] == EXPECTED_OPERATION_IDS
    for operation in first["operations"]:
        assert operation["availability"] == "available"
        assert len(operation["rawSamplesMs"]) == 3
        assert len(operation["outputHashes"]) == 3
        assert operation["determinism"]["passed"] is True


def test_committed_release_artifact_schema_budgets_and_determinism() -> None:
    artifact = _load(DEFAULT_RESULT_PATH)
    assert artifact["schemaVersion"] == RESULT_SCHEMA_VERSION
    assert artifact["mode"] == "release"
    assert artifact["releaseEligible"] is True
    assert artifact["protocol"]["warmupIterations"] == 1
    assert artifact["protocol"]["measuredIterations"] == 30
    assert artifact["protocol"]["percentileMethod"] == "inclusive"
    assert artifact["requiredOperationsAvailable"] is True
    assert artifact["determinismPassed"] is True
    assert artifact["provenanceComplete"] is True
    assert len(artifact["source"]["sourceCommit"]) == 40
    assert artifact["environment"]["cpu"]["available"] is True
    assert artifact["environment"]["ram"]["available"] is True
    assert artifact["fixtures"]["primary"]["inputSizes"] == {
        "assetDefinitionCount": 1,
        "placementCount": 500,
        "policyRuleCount": 0,
        "routeCount": 200,
        "routePointCount": 400,
        "shellFeatureCount": 1,
        "zoneCount": 100,
        "zoneVertexCount": 400,
    }
    assert [
        item["operationId"] for item in artifact["operations"]
    ] == EXPECTED_OPERATION_IDS
    observed_budget_results = []
    for operation in artifact["operations"]:
        samples = operation["rawSamplesMs"]
        summary = operation["summaryMilliseconds"]
        assert operation["availability"] == "available"
        assert operation["warmupIterations"] == 1
        assert operation["measuredIterations"] == 30
        assert len(samples) == 30
        assert len(operation["outputHashes"]) == 30
        assert summary["median"] == round(statistics.median(samples), 6)
        assert summary["p95"] == round(_p95(samples), 6)
        assert operation["determinism"]["passed"] is True
        expected_budget_result = (
            summary["p95"] <= operation["budget"]["limit"]
        )
        assert operation["budget"]["passed"] is expected_budget_result
        observed_budget_results.append(expected_budget_result)
    assert artifact["budgetsPassed"] is all(observed_budget_results)
    expected_release_result = (
        artifact["requiredOperationsAvailable"]
        and artifact["determinismPassed"]
        and artifact["budgetsPassed"]
        and artifact["provenanceComplete"]
    )
    assert artifact["releaseSlicePassed"] is expected_release_result


def test_current_release_artifact_fails_closed_on_diagnostics_budget() -> None:
    artifact = _load(DEFAULT_RESULT_PATH)
    operations = {
        item["operationId"]: item for item in artifact["operations"]
    }
    assert operations["moved_object_spatial_query"]["budget"]["passed"] is True
    assert operations["candidate_generation"]["budget"]["passed"] is True
    assert operations["collision_clearance_query"]["budget"]["passed"] is True
    assert operations["forklift_routing"]["budget"]["passed"] is True
    assert operations["full_diagnostics"]["budget"]["passed"] is False
    assert artifact["budgetsPassed"] is False
    assert artifact["releaseSlicePassed"] is False


def test_committed_artifact_is_bound_to_generated_fixtures_and_sources() -> None:
    spec = _load(DEFAULT_SPEC_PATH)
    fixtures = build_fixture_bundle(spec, smoke=False)
    artifact = _load(DEFAULT_RESULT_PATH)
    assert artifact["fixtures"]["primary"]["sha256"] == (
        fixtures["hashes"]["primary"]
    )
    assert artifact["fixtures"]["forklift"]["sha256"] == (
        fixtures["hashes"]["forklift"]
    )
    source_files = {
        item["path"]: item for item in artifact["source"]["files"]
    }
    for relative_path, item in source_files.items():
        payload = (REPO_ROOT / relative_path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
