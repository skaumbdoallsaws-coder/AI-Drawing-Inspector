"""Deterministic performance evidence contracts for RQ8."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence


REFERENCE_PERFORMANCE_SCHEMA = "facility-reference-quality-performance-v1"


class FacilityReferencePerformanceError(ValueError):
    pass


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    """Return the nearest-rank percentile used by the frozen RQ protocol."""

    if not values:
        raise FacilityReferencePerformanceError("Timing samples cannot be empty.")
    if not 0 < percentile <= 1:
        raise FacilityReferencePerformanceError(
            "Percentile must be greater than zero and no greater than one."
        )
    samples = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in samples):
        raise FacilityReferencePerformanceError(
            "Timing samples must be finite non-negative numbers."
        )
    rank = max(1, math.ceil(percentile * len(samples)))
    return samples[rank - 1]


def summarize_timing_samples(
    values: Sequence[float],
    *,
    limit_milliseconds: float,
) -> dict[str, Any]:
    samples = [round(float(value), 6) for value in values]
    if len(samples) != 20:
        raise FacilityReferencePerformanceError(
            "The frozen RQ protocol requires exactly 20 measured samples."
        )
    p50 = nearest_rank_percentile(samples, 0.50)
    p95 = nearest_rank_percentile(samples, 0.95)
    return {
        "sampleCount": len(samples),
        "rawMilliseconds": samples,
        "minimumMilliseconds": min(samples),
        "medianMilliseconds": round(p50, 6),
        "p95Milliseconds": round(p95, 6),
        "maximumMilliseconds": max(samples),
        "limitMilliseconds": float(limit_milliseconds),
        "passed": p95 <= float(limit_milliseconds),
    }


def validate_reference_performance_artifact(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityReferencePerformanceError(
            "Reference performance evidence must be an object."
        )
    required = {
        "schemaVersion",
        "status",
        "protocol",
        "machine",
        "revisions",
        "measurements",
        "browserEvidence",
        "providerTiming",
    }
    if set(value) != required:
        raise FacilityReferencePerformanceError(
            "Reference performance evidence fields are invalid."
        )
    if value.get("schemaVersion") != REFERENCE_PERFORMANCE_SCHEMA:
        raise FacilityReferencePerformanceError(
            "Reference performance evidence schema is unsupported."
        )
    protocol = value.get("protocol")
    if not isinstance(protocol, Mapping) or (
        protocol.get("discardedWarmupRuns") != 1
        or protocol.get("measuredRuns") != 20
        or protocol.get("percentileMethod") != "nearest_rank"
    ):
        raise FacilityReferencePerformanceError(
            "Reference performance measurement protocol is invalid."
        )
    measurements = value.get("measurements")
    if not isinstance(measurements, Mapping) or set(measurements) != {
        "firstMacroPreview",
        "fullReferenceGeneration",
        "localResourceAmendment",
    }:
        raise FacilityReferencePerformanceError(
            "Reference performance measurements are incomplete."
        )
    for measurement in measurements.values():
        if not isinstance(measurement, Mapping):
            raise FacilityReferencePerformanceError(
                "Reference performance measurement is invalid."
            )
        samples = measurement.get("rawMilliseconds")
        if not isinstance(samples, list) or len(samples) != 20:
            raise FacilityReferencePerformanceError(
                "Every measurement must retain 20 raw timings."
            )
        observed = nearest_rank_percentile(samples, 0.95)
        if abs(observed - float(measurement.get("p95Milliseconds"))) > 1e-6:
            raise FacilityReferencePerformanceError(
                "A recorded p95 does not match its raw timings."
            )
        expected_passed = observed <= float(measurement.get("limitMilliseconds"))
        if measurement.get("passed") is not expected_passed:
            raise FacilityReferencePerformanceError(
                "A performance gate result does not match its measured value."
            )
    expected_status = (
        "pass"
        if all(item.get("passed") is True for item in measurements.values())
        else "fail"
    )
    if value.get("status") != expected_status:
        raise FacilityReferencePerformanceError(
            "Reference performance status does not match its gates."
        )
    return deepcopy(dict(value))


__all__ = [
    "REFERENCE_PERFORMANCE_SCHEMA",
    "FacilityReferencePerformanceError",
    "nearest_rank_percentile",
    "summarize_timing_samples",
    "validate_reference_performance_artifact",
]
