"""Classification models for drawing pages."""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class PageType(Enum):
    """Classification types for individual drawing pages."""

    ASSEMBLY_BOM = "ASSEMBLY_BOM"  # Exploded view, BOM table, no dimensions
    PART_DETAIL = "PART_DETAIL"    # Single part with dimensions/tolerances
    MIXED = "MIXED"                 # Both BOM and dimensioned views


@dataclass
class PageClassification:
    """
    Classification result for a single page.

    Created by classifier/page_classifier.py using Qwen VLM.

    Attributes:
        page_type: The classified page type
        needs_ocr: Whether OCR should be run on this page
        has_bom: Whether a Bill of Materials is present
        has_dimensioned_views: Whether dimensioned views are present
        has_detail_views: Whether detail views are present
        confidence: Classification confidence (0.0-1.0)
        reason: Explanation from the classifier
    """

    page_type: PageType
    needs_ocr: bool
    has_bom: bool
    has_dimensioned_views: bool
    has_detail_views: bool
    confidence: float
    reason: str


@dataclass
class DrawingClassification:
    """
    Overall classification for an entire drawing (all pages).

    Aggregates page-level classifications into drawing-level summary.

    Attributes:
        overall_type: Drawing type (PART_DETAIL, ASSEMBLY_BOM, MULTI_PAGE_ASSEMBLY)
        pages_needing_ocr: List of page numbers that need OCR
        pages_with_bom: List of page numbers with BOM tables
        pages_with_details: List of page numbers with detail views
        has_bom: Whether any page has a BOM
    """

    overall_type: str
    pages_needing_ocr: List[int] = field(default_factory=list)
    pages_with_bom: List[int] = field(default_factory=list)
    pages_with_details: List[int] = field(default_factory=list)
    has_bom: bool = False
