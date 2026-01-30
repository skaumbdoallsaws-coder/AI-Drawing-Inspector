"""
AI Engineering Drawing Inspector v4.0

Multi-model QC pipeline for verifying engineering drawings against CAD data.

Models:
- LightOnOCR-2-1B: Text extraction
- Qwen2.5-VL-7B: Visual understanding
- GPT-4o-mini: Report generation

Drawing Types:
- MACHINED_PART: Holes, threads, GD&T (Use OCR)
- SHEET_METAL: Bends, flat patterns (Use OCR)
- ASSEMBLY: BOM, balloons (Skip OCR)
- WELDMENT: Weld symbols, BOM (Skip OCR)
- CASTING: Critical dims (Use OCR)
- PURCHASED_PART: Manufacturer table (Skip OCR)
- GEAR: Gear data table (Use OCR)
"""

__version__ = "4.0.0"

# Classifier exports
from .classifier import (
    DrawingType,
    ClassificationResult,
    DrawingClassifier,
    classify_drawing,
)

# Comparison exports
from .comparison import (
    SwFeatureExtractor,
    SwFeature,
    FeatureMatcher,
    MatchResult,
    DiffResult,
    compare_drawing,
)
