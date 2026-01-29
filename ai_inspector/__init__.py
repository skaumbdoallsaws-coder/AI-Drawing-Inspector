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
"""

__version__ = "4.0.0"

from .classifier.drawing_classifier import classify_drawing, DrawingType

__all__ = [
    "classify_drawing",
    "DrawingType",
    "__version__",
]
