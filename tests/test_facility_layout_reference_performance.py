from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.reference_performance import (
    REFERENCE_PERFORMANCE_SCHEMA,
    FacilityReferencePerformanceError,
    nearest_rank_percentile,
    summarize_timing_samples,
    validate_reference_performance_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "performance-evaluation.json"
)


def _measurement(limit: float = 20.0) -> dict:
    return {
        "scope": "test",
        **summarize_timing_samples(
            [float(value) for value in range(1, 21)],
            limit_milliseconds=limit,
        ),
    }


def test_nearest_rank_and_frozen_twenty_sample_summary() -> None:
    values = [float(value) for value in range(20, 0, -1)]
    assert nearest_rank_percentile(values, 0.50) == 10.0
    assert nearest_rank_percentile(values, 0.95) == 19.0
    summary = summarize_timing_samples(values, limit_milliseconds=19.0)
    assert summary["sampleCount"] == 20
    assert summary["p95Milliseconds"] == 19.0
    assert summary["passed"] is True


def test_reference_performance_artifact_recomputes_every_gate() -> None:
    artifact = {
        "schemaVersion": REFERENCE_PERFORMANCE_SCHEMA,
        "status": "pass",
        "protocol": {
            "discardedWarmupRuns": 1,
            "measuredRuns": 20,
            "percentileMethod": "nearest_rank",
        },
        "machine": {},
        "revisions": {},
        "measurements": {
            "firstMacroPreview": _measurement(),
            "fullReferenceGeneration": _measurement(),
            "localResourceAmendment": _measurement(),
        },
        "browserEvidence": {},
        "providerTiming": {"included": False},
    }
    assert validate_reference_performance_artifact(artifact) == artifact

    artifact["measurements"]["fullReferenceGeneration"][
        "p95Milliseconds"
    ] = 18.0
    with pytest.raises(FacilityReferencePerformanceError):
        validate_reference_performance_artifact(artifact)


def test_frozen_reference_performance_evidence_passes_all_three_gates() -> None:
    artifact = json.loads(PERFORMANCE_PATH.read_text(encoding="utf-8"))
    validated = validate_reference_performance_artifact(artifact)

    assert validated["status"] == "pass"
    assert validated["measurements"]["firstMacroPreview"][
        "p95Milliseconds"
    ] <= 10_000
    assert validated["measurements"]["fullReferenceGeneration"][
        "p95Milliseconds"
    ] <= 90_000
    assert validated["measurements"]["localResourceAmendment"][
        "p95Milliseconds"
    ] <= 10_000
