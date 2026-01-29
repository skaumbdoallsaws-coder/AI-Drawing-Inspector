"""Feature extraction modules (OCR, VLM, title block)."""

from .ocr import (
    load_ocr_model,
    run_ocr,
    preprocess_ocr_text,
    parse_ocr_callouts,
    clear_ocr_model,
    PATTERNS as OCR_PATTERNS,
)

from .vlm import (
    load_qwen_model,
    run_qwen_analysis,
    extract_features,
    audit_quality,
    extract_bom,
    extract_manufacturing_notes,
    classify_page,
    full_analysis,
    clear_qwen_model,
    FEATURE_EXTRACTION_PROMPT,
    QUALITY_AUDIT_PROMPT,
    BOM_EXTRACTION_PROMPT,
    MANUFACTURING_NOTES_PROMPT,
    PAGE_CLASSIFICATION_PROMPT,
)

__all__ = [
    # OCR
    "load_ocr_model",
    "run_ocr",
    "preprocess_ocr_text",
    "parse_ocr_callouts",
    "clear_ocr_model",
    "OCR_PATTERNS",
    # VLM (Qwen)
    "load_qwen_model",
    "run_qwen_analysis",
    "extract_features",
    "audit_quality",
    "extract_bom",
    "extract_manufacturing_notes",
    "classify_page",
    "full_analysis",
    "clear_qwen_model",
    "FEATURE_EXTRACTION_PROMPT",
    "QUALITY_AUDIT_PROMPT",
    "BOM_EXTRACTION_PROMPT",
    "MANUFACTURING_NOTES_PROMPT",
    "PAGE_CLASSIFICATION_PROMPT",
]
