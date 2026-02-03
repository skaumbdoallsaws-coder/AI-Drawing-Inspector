"""Feature extraction modules for AI Inspector."""

# YOLO pipeline exports (lightweight, no fitz/torch at import time)
from .canonicalize import canonicalize, canonicalize_lines
from .cropper import crop_obb, crop_detections
from .rotation import select_best_rotation, select_rotations_batch
from .crop_reader import read_crop, read_crops_batch
from .unit_normalizer import normalize_callout, normalize_callouts, detect_drawing_units
from .validator import validate_callout, validate_and_repair_all
from .patterns import PATTERNS_BY_CLASS, parse_by_class

# Legacy v4 names that require heavy deps (fitz, torch, transformers)
_LEGACY_NAMES = {
    "LightOnOCR": ("ocr", "LightOnOCR"),
    "QwenVLM": ("vlm", "QwenVLM"),
    "resolve_part_identity": ("identity", "resolve_part_identity"),
    "extract_pn_candidates": ("identity", "extract_pn_candidates"),
    "parse_ocr_callouts": ("ocr_parser", "parse_ocr_callouts"),
    "preprocess_ocr_text": ("ocr_parser", "preprocess_ocr_text"),
    "parse_qwen_features": ("qwen_parser", "parse_qwen_features"),
    "DrawingEvidence": ("evidence_merger", "DrawingEvidence"),
    "merge_evidence": ("evidence_merger", "merge_evidence"),
    "build_drawing_evidence": ("evidence_merger", "build_drawing_evidence"),
    "DrawingAnalyzer": ("drawing_analyzer", "DrawingAnalyzer"),
    "DrawingAnalysis": ("drawing_analyzer", "DrawingAnalysis"),
    "OCRAdapter": ("ocr_adapter", "OCRAdapter"),
    "MockOCRAdapter": ("ocr_adapter", "MockOCRAdapter"),
}


def __getattr__(name):
    """Lazy import for v4 modules to avoid pulling in fitz/torch eagerly."""
    if name in _LEGACY_NAMES:
        module_name, attr_name = _LEGACY_NAMES[name]
        import importlib
        mod = importlib.import_module(f".{module_name}", __package__)
        return getattr(mod, attr_name)
    raise AttributeError(f"module 'ai_inspector.extractors' has no attribute {name!r}")


__all__ = [
    # Legacy v4 pipeline (lazy)
    "LightOnOCR",
    "QwenVLM",
    "resolve_part_identity",
    "extract_pn_candidates",
    "parse_ocr_callouts",
    "preprocess_ocr_text",
    "parse_qwen_features",
    "DrawingEvidence",
    "merge_evidence",
    "build_drawing_evidence",
    "DrawingAnalyzer",
    "DrawingAnalysis",
    "OCRAdapter",
    "MockOCRAdapter",
    # YOLO pipeline (eager)
    "canonicalize",
    "canonicalize_lines",
    "crop_obb",
    "crop_detections",
    "select_best_rotation",
    "select_rotations_batch",
    "read_crop",
    "read_crops_batch",
    "normalize_callout",
    "normalize_callouts",
    "detect_drawing_units",
    "validate_callout",
    "validate_and_repair_all",
    "PATTERNS_BY_CLASS",
    "parse_by_class",
]
