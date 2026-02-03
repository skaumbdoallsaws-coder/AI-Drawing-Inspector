"""Comparison module for matching drawing evidence against SolidWorks CAD data."""

# Lightweight imports (no heavy deps)
from .sw_extractor import SwFeatureExtractor, SwFeature
from .matcher import FeatureMatcher, MatchResult, MatchStatus


def __getattr__(name):
    """Lazy import for diff_result to avoid pulling in evidence_merger -> fitz chain."""
    _diff_names = {"DiffResult", "DiffEntry", "compare_drawing"}
    if name in _diff_names:
        from . import diff_result
        return getattr(diff_result, name)
    raise AttributeError(f"module 'ai_inspector.comparison' has no attribute {name!r}")


__all__ = [
    "SwFeatureExtractor",
    "SwFeature",
    "FeatureMatcher",
    "MatchResult",
    "MatchStatus",
    "DiffResult",
    "DiffEntry",
    "compare_drawing",
]
