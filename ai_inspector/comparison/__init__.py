"""CAD vs Drawing comparison logic."""

from .matcher import (
    extract_sw_requirements,
    extract_mate_requirements,
    compare_callout_to_requirement,
    generate_diff_result,
    create_stub_diff_result,
    DEFAULT_TOLERANCE_INCHES,
    STANDARD_METRIC_PITCHES,
)

__all__ = [
    "extract_sw_requirements",
    "extract_mate_requirements",
    "compare_callout_to_requirement",
    "generate_diff_result",
    "create_stub_diff_result",
    "DEFAULT_TOLERANCE_INCHES",
    "STANDARD_METRIC_PITCHES",
]
