"""Comparison module for matching drawing evidence against SolidWorks CAD data."""

from .sw_extractor import SwFeatureExtractor, SwFeature
from .matcher import FeatureMatcher, MatchResult, MatchStatus
from .diff_result import DiffResult, DiffEntry, compare_drawing

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
