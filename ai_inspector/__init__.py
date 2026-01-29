"""
AI Drawing Inspector - v4.0

A modular package for automated engineering drawing inspection.
Classifies drawing types and applies type-specific analysis.

Drawing Types Supported:
- Machined Parts (71% of typical library)
- Sheet Metal
- Weldments
- Assemblies
- Castings
- Purchased Parts
- Gears

Usage (Colab):
    from ai_inspector import classify_drawing, DrawingType
    from ai_inspector.utils import render_pdf, SwJsonLibrary
    from ai_inspector.analyzers import MachinedPartAnalyzer, resolve_part_identity
    from ai_inspector.report import generate_qc_report
"""

__version__ = "4.0.0"

# Classifier
from .classifier.drawing_classifier import (
    classify_drawing,
    DrawingType,
    ClassificationResult,
    TypeConfig,
    TYPE_CONFIGS,
)

# Re-export key items for convenience
__all__ = [
    # Version
    "__version__",
    # Classifier
    "classify_drawing",
    "DrawingType",
    "ClassificationResult",
    "TypeConfig",
    "TYPE_CONFIGS",
]
