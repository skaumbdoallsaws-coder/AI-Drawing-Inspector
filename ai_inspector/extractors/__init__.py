"""Feature extraction modules for AI Inspector."""

# Legacy v4 pipeline exports
from .ocr import LightOnOCR
from .vlm import QwenVLM
from .identity import resolve_part_identity, extract_pn_candidates
from .ocr_parser import parse_ocr_callouts, preprocess_ocr_text
from .qwen_parser import parse_qwen_features
from .evidence_merger import DrawingEvidence, merge_evidence, build_drawing_evidence
from .drawing_analyzer import DrawingAnalyzer, DrawingAnalysis

# YOLO pipeline exports
from .canonicalize import canonicalize, canonicalize_lines
from .ocr_adapter import OCRAdapter, MockOCRAdapter
from .cropper import crop_obb, crop_detections
from .rotation import select_best_rotation, select_rotations_batch
from .crop_reader import read_crop, read_crops_batch
from .unit_normalizer import normalize_callout, normalize_callouts, detect_drawing_units
from .validator import validate_callout, validate_and_repair_all
from .patterns import PATTERNS_BY_CLASS, parse_by_class

__all__ = [
    # Legacy v4 pipeline
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
    # YOLO pipeline
    "canonicalize",
    "canonicalize_lines",
    "OCRAdapter",
    "MockOCRAdapter",
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
