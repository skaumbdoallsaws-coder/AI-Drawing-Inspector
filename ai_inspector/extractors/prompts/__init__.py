"""Prompts for Qwen VLM analysis."""

from .feature_extraction import FEATURE_EXTRACTION_PROMPT
from .quality_audit import QUALITY_AUDIT_PROMPT
from .bom_extraction import BOM_EXTRACTION_PROMPT
from .manufacturing_notes import MANUFACTURING_NOTES_PROMPT
from .page_classification import PAGE_CLASSIFICATION_PROMPT
from .page_understanding import PAGE_UNDERSTANDING_PROMPT

__all__ = [
    "FEATURE_EXTRACTION_PROMPT",
    "QUALITY_AUDIT_PROMPT",
    "BOM_EXTRACTION_PROMPT",
    "MANUFACTURING_NOTES_PROMPT",
    "PAGE_CLASSIFICATION_PROMPT",
    "PAGE_UNDERSTANDING_PROMPT",
]
