from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "production_hardening"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_source_binding(binding: dict[str, Any]) -> None:
    records = binding["files"]
    assert records
    for record in records:
        path = ROOT / record["path"]
        assert path.is_file()
        assert path.stat().st_size == record["byteLength"]
        assert _sha256(path) == record["sha256"]
    aggregate = hashlib.sha256(
        canonical_facility_knowledge_bytes(records)
    ).hexdigest()
    assert binding["aggregateSha256"] == aggregate


def test_fli030_parity_artifact_is_current_and_complete() -> None:
    evidence = _read_json(EVIDENCE_ROOT / "fli030-parity-evidence.json")

    assert evidence["schemaVersion"] == "facility-layout-fli030-parity-v1"
    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    _assert_source_binding(evidence["sourceBinding"])

    records = evidence["records"]
    assert len(records) == 8
    assert {record["view"] for record in records} == {"plan", "3d"}
    assert {record["theme"] for record in records} == {"light", "dark"}
    assert {
        (record["viewport"]["width"], record["viewport"]["height"])
        for record in records
    } == {(1440, 960), (390, 844)}
    assert {record["layoutRevision"] for record in records} == {
        evidence["draftRevision"]
    }
    assert all(record["entityIds"] == evidence["entityIds"] for record in records)

    for record in records:
        assert record["passed"] is True
        assert all(record["checks"].values())
        assert record["surfacePixels"]["nonblank"] is True
        assert record["surfacePixels"]["changedPixelCount"] > 0
        assert record["diagnostics"]["topPlan"]["placementTransformAudit"][
            "status"
        ] == "match"
        assert record["diagnostics"]["three"]["placementTransformAudit"][
            "status"
        ] == "match"
        screenshot = ROOT / record["screenshot"]["path"]
        assert screenshot.is_file()
        assert screenshot.stat().st_size == record["screenshot"]["byteLength"]
        assert _sha256(screenshot) == record["screenshot"]["sha256"]


def test_fli031_performance_artifact_is_current_and_within_budget() -> None:
    evidence = _read_json(EVIDENCE_ROOT / "fli031-performance-evidence.json")

    assert evidence["schemaVersion"] == "facility-layout-fli031-performance-v1"
    assert evidence["passed"] is True
    assert all(evidence["checks"].values())
    assert all(evidence["budgetChecks"].values())
    assert all(evidence["cycleChecks"].values())
    _assert_source_binding(evidence["sourceBinding"])

    assert evidence["protocol"]["discardedWarmupCycles"] == 1
    assert evidence["protocol"]["measuredCycles"] == 20
    assert evidence["protocol"]["javascriptGrowthWindowSize"] == 5
    assert len(evidence["samples"]["cycles"]) == 20
    for metric, limit in evidence["budgets"].items():
        assert evidence["observed"][metric] <= limit

    assert evidence["controlledReleaseGateMet"] is False
    assert "literal_fourteen_day_elapsed_soak_not_completed" in evidence[
        "controlledReleaseBlockers"
    ]
    assert evidence["controlledReleaseBlockers"]

    soak = _read_json(ROOT / evidence["acceleratedSoakArtifact"])
    accelerated = soak["acceleratedDeterministicSoak"]
    assert accelerated["status"] == "passed"
    assert all(accelerated["checks"].values())
    assert accelerated["counts"]["layouts"] >= 10
    assert accelerated["counts"]["proposalPreviews"] >= 20
    assert accelerated["counts"]["approvedReceiptBackedApplies"] >= 10
    assert accelerated["counts"]["reopenCyclesPerLayout"] >= 5
    assert soak["releaseGateMet"] is False
