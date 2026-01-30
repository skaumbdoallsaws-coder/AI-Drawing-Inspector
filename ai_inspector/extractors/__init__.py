"""Feature extraction modules for AI Inspector."""

from .patterns import PATTERNS
from .ocr import LightOnOCR
from .vlm import QwenVLM
from .identity import resolve_part_identity, extract_pn_candidates
from .ocr_parser import parse_ocr_callouts, preprocess_ocr_text
from .qwen_parser import parse_qwen_features
from .evidence_merger import DrawingEvidence, merge_evidence, build_drawing_evidence
from .drawing_analyzer import DrawingAnalyzer, DrawingAnalysis

__all__ = [
    "PATTERNS",
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
]
