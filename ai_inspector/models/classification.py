"""Classification models for v4 drawing type classification.

v4 classifies at the DRAWING level (not page level) into 7 types:
- MACHINED_PART: Holes, threads, GD&T (Use OCR)
- SHEET_METAL: Bends, flat patterns (Use OCR)
- ASSEMBLY: BOM, balloons (Skip OCR)
- WELDMENT: Weld symbols, BOM (Skip OCR)
- CASTING: Critical dims (Use OCR)
- PURCHASED_PART: Manufacturer table (Skip OCR)
- GEAR: Gear data table (Use OCR)

The main classification is done by classifier/drawing_classifier.py.
This module re-exports those types for convenience.
"""

# Re-export from classifier module for backwards compatibility
from ..classifier import DrawingType, ClassificationResult

__all__ = ["DrawingType", "ClassificationResult"]
