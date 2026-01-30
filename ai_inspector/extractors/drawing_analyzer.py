"""Drawing analysis using Qwen VLM."""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from PIL import Image

from .vlm import QwenVLM
from .prompts import (
    FEATURE_EXTRACTION_PROMPT,
    QUALITY_AUDIT_PROMPT,
    BOM_EXTRACTION_PROMPT,
    MANUFACTURING_NOTES_PROMPT,
)
from ..models.page import PageArtifact


@dataclass
class DrawingAnalysis:
    """
    Complete Qwen analysis results.

    Contains results from all 4 analysis passes:
    - feature_analysis: Holes, threads, GD&T, etc.
    - quality_audit: Title block, drawing quality
    - bom_extraction: Bill of Materials
    - manufacturing_notes: Heat treat, finish, coating
    """

    feature_analysis: Dict[str, Any]
    quality_audit: Dict[str, Any]
    bom_extraction: Dict[str, Any]
    manufacturing_notes: Dict[str, Any]


class DrawingAnalyzer:
    """
    Analyzes engineering drawings using Qwen VLM.

    Runs 4 analysis passes: features, quality, BOM, manufacturing notes.
    Each pass uses a specialized prompt to extract different information.

    Usage:
        vlm = QwenVLM()
        vlm.load()

        analyzer = DrawingAnalyzer(vlm)
        analysis = analyzer.full_analysis(artifacts)

        print(analysis.feature_analysis["features"])
        print(analysis.quality_audit["titleBlockCompleteness"])

    Attributes:
        vlm: QwenVLM instance (must be loaded)
    """

    def __init__(self, vlm: QwenVLM):
        """
        Initialize analyzer with VLM instance.

        Args:
            vlm: Loaded QwenVLM instance
        """
        self.vlm = vlm

    def analyze_features(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract features (holes, threads, GD&T, etc.).

        Args:
            image: PIL Image of drawing page

        Returns:
            Dict with features, views, material, titleBlockInfo, notes
        """
        return self.vlm.analyze(image, FEATURE_EXTRACTION_PROMPT)

    def analyze_quality(self, image: Image.Image) -> Dict[str, Any]:
        """
        Audit drawing quality and title block.

        Args:
            image: PIL Image of drawing page

        Returns:
            Dict with titleBlockCompleteness, drawingQuality, overallAssessment
        """
        return self.vlm.analyze(image, QUALITY_AUDIT_PROMPT)

    def extract_bom(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract Bill of Materials if present.

        Args:
            image: PIL Image of drawing page

        Returns:
            Dict with hasBOM, bomItems, totalItems, bomNotes
        """
        return self.vlm.analyze(image, BOM_EXTRACTION_PROMPT)

    def extract_manufacturing_notes(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract manufacturing specifications.

        Args:
            image: PIL Image of drawing page

        Returns:
            Dict with heatTreatment, surfaceFinish, platingOrCoating, etc.
        """
        return self.vlm.analyze(image, MANUFACTURING_NOTES_PROMPT)

    def full_analysis(
        self,
        artifacts: List[PageArtifact],
        pages_with_details: Optional[List[PageArtifact]] = None,
        pages_with_bom: Optional[List[PageArtifact]] = None,
    ) -> DrawingAnalysis:
        """
        Run all 4 analyses on appropriate pages.

        Selects appropriate pages for each analysis:
        - Features: First detail page (or first page)
        - Quality: First page
        - BOM: First BOM page (or first page)
        - Manufacturing notes: First page

        Args:
            artifacts: All page artifacts
            pages_with_details: Pages with dimensioned views (for features)
            pages_with_bom: Pages with BOM table

        Returns:
            DrawingAnalysis with all 4 results
        """
        # Select appropriate pages
        detail_page = (
            pages_with_details[0] if pages_with_details else artifacts[0]
        )
        bom_page = pages_with_bom[0] if pages_with_bom else artifacts[0]
        first_page = artifacts[0]

        return DrawingAnalysis(
            feature_analysis=self.analyze_features(detail_page.image),
            quality_audit=self.analyze_quality(first_page.image),
            bom_extraction=self.extract_bom(bom_page.image),
            manufacturing_notes=self.extract_manufacturing_notes(first_page.image),
        )
