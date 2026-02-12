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


def __getattr__(name):
    """Lazy imports to avoid pulling in heavy dependencies (fitz, torch, etc.)
    when only a submodule like comparison or extractors is needed."""

    _classifier_names = {
        "DrawingType", "ClassificationResult", "DrawingClassifier", "classify_drawing",
    }
    _comparison_names = {
        "SwFeatureExtractor", "SwFeature", "FeatureMatcher", "MatchResult",
        "DiffResult", "compare_drawing",
    }
    _report_names = {
        "QCReportGenerator", "QCReport", "generate_report",
    }
    _pipeline_names = {
        "InspectorPipeline", "InspectionResult", "run_inspection",
        "YOLOPipeline", "VisionPipeline", "PipelineResult",
    }

    if name in _classifier_names:
        from . import classifier
        return getattr(classifier, name)
    elif name in _comparison_names:
        from . import comparison
        return getattr(comparison, name)
    elif name in _report_names:
        from . import report
        return getattr(report, name)
    elif name in _pipeline_names:
        from . import pipeline
        return getattr(pipeline, name)

    raise AttributeError(f"module 'ai_inspector' has no attribute {name!r}")
