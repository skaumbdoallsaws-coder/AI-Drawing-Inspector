"""
Machined Part Analyzer

Specialized analyzer for machined parts (turned/milled).
These parts have holes, threads, GD&T, tolerances, and require OCR.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import BaseAnalyzer, AnalysisResult, ResolvedPartIdentity

if TYPE_CHECKING:
    from ..utils.pdf_render import PageArtifact
    from ..utils.sw_library import SwPartEntry


class MachinedPartAnalyzer(BaseAnalyzer):
    """
    Analyzer for machined parts.

    Features extracted:
    - Holes (through, blind)
    - Tapped holes (threads)
    - Counterbores, countersinks
    - Fillets, chamfers
    - GD&T callouts
    - Surface finish
    - Tolerances
    """

    drawing_type = "machined_part"
    use_ocr = True
    use_qwen = True

    def analyze(
        self,
        artifacts: List['PageArtifact'],
        identity: ResolvedPartIdentity,
        sw_entry: Optional['SwPartEntry'] = None,
    ) -> AnalysisResult:
        """
        Analyze a machined part drawing.

        Args:
            artifacts: Rendered page images
            identity: Resolved part identity
            sw_entry: SolidWorks part data if available

        Returns:
            AnalysisResult with extracted features and comparison
        """
        from ..extractors.ocr import run_ocr, parse_ocr_callouts
        from ..extractors.vlm import (
            extract_features,
            audit_quality,
            extract_bom,
            extract_manufacturing_notes,
        )
        from ..comparison.matcher import (
            extract_sw_requirements,
            generate_diff_result,
            create_stub_diff_result,
        )

        result = AnalysisResult(identity=identity)

        # Run OCR on all pages
        all_ocr_lines = []
        for artifact in artifacts:
            if artifact.needs_ocr:
                try:
                    lines = run_ocr(artifact.image)
                    all_ocr_lines.extend(lines)
                except Exception as e:
                    print(f"  OCR error on page {artifact.page}: {e}")

        # Parse OCR callouts
        if all_ocr_lines:
            result.ocr_callouts = parse_ocr_callouts(all_ocr_lines)

        # Run Qwen analyses on first page (or detail page if multi-page)
        primary_image = artifacts[0].image
        for art in artifacts:
            if art.drawing_type == 'PART_DETAIL':
                primary_image = art.image
                break

        # Feature extraction
        qwen_features = extract_features(primary_image)
        if 'parse_error' not in qwen_features:
            result.features = qwen_features.get('features', [])

        # Quality audit
        result.quality_audit = audit_quality(primary_image)

        # BOM extraction (usually not present for machined parts)
        result.bom_data = extract_bom(primary_image)

        # Manufacturing notes
        result.manufacturing_notes = extract_manufacturing_notes(primary_image)

        # Merge OCR and Qwen evidence
        merged_callouts = self.merge_evidence(
            result.ocr_callouts,
            result.features
        )

        # Extract SW requirements and compare
        if sw_entry and sw_entry.data:
            result.sw_requirements = extract_sw_requirements(sw_entry.data)

            # Generate comparison
            result.comparison = generate_diff_result(
                callouts=merged_callouts,
                requirements=result.sw_requirements,
                part_number=identity.partNumber
            )
        else:
            result.comparison = create_stub_diff_result(
                part_number=identity.partNumber,
                reason="No SolidWorks CAD data found"
            )

        self.result = result
        return result


class MachinedPartAnalyzerLazy(BaseAnalyzer):
    """
    Lazy version of MachinedPartAnalyzer.

    Does not load models at init time - models must be passed in
    or loaded separately. Useful for Colab where model loading
    is handled in separate cells.
    """

    drawing_type = "machined_part"
    use_ocr = True
    use_qwen = True

    def __init__(self, ocr_model=None, ocr_processor=None, qwen_model=None, qwen_processor=None):
        super().__init__()
        self.ocr_model = ocr_model
        self.ocr_processor = ocr_processor
        self.qwen_model = qwen_model
        self.qwen_processor = qwen_processor

    def analyze(
        self,
        artifacts: List['PageArtifact'],
        identity: ResolvedPartIdentity,
        sw_entry: Optional['SwPartEntry'] = None,
        ocr_model=None,
        ocr_processor=None,
        qwen_model=None,
        qwen_processor=None,
    ) -> AnalysisResult:
        """
        Analyze a machined part drawing with explicit model instances.

        Args:
            artifacts: Rendered page images
            identity: Resolved part identity
            sw_entry: SolidWorks part data if available
            ocr_model: LightOnOCR model instance
            ocr_processor: LightOnOCR processor instance
            qwen_model: Qwen VLM model instance
            qwen_processor: Qwen VLM processor instance

        Returns:
            AnalysisResult with extracted features and comparison
        """
        from ..extractors.ocr import run_ocr, parse_ocr_callouts
        from ..extractors.vlm import (
            run_qwen_analysis,
            FEATURE_EXTRACTION_PROMPT,
            QUALITY_AUDIT_PROMPT,
            BOM_EXTRACTION_PROMPT,
            MANUFACTURING_NOTES_PROMPT,
        )
        from ..comparison.matcher import (
            extract_sw_requirements,
            generate_diff_result,
            create_stub_diff_result,
        )

        # Use provided models or instance models
        _ocr_model = ocr_model or self.ocr_model
        _ocr_processor = ocr_processor or self.ocr_processor
        _qwen_model = qwen_model or self.qwen_model
        _qwen_processor = qwen_processor or self.qwen_processor

        result = AnalysisResult(identity=identity)

        # Run OCR on pages that need it
        all_ocr_lines = []
        for artifact in artifacts:
            if artifact.needs_ocr and _ocr_model is not None:
                try:
                    lines = run_ocr(artifact.image, model=_ocr_model, processor=_ocr_processor)
                    all_ocr_lines.extend(lines)
                except Exception as e:
                    print(f"  OCR error on page {artifact.page}: {e}")

        # Parse OCR callouts
        if all_ocr_lines:
            result.ocr_callouts = parse_ocr_callouts(all_ocr_lines)

        # Find primary image for Qwen analysis
        primary_image = artifacts[0].image
        for art in artifacts:
            if art.drawing_type == 'PART_DETAIL':
                primary_image = art.image
                break

        if _qwen_model is not None:
            # Feature extraction
            qwen_features = run_qwen_analysis(
                primary_image, FEATURE_EXTRACTION_PROMPT,
                model=_qwen_model, processor=_qwen_processor
            )
            if 'parse_error' not in qwen_features:
                result.features = qwen_features.get('features', [])

            # Quality audit
            result.quality_audit = run_qwen_analysis(
                primary_image, QUALITY_AUDIT_PROMPT,
                model=_qwen_model, processor=_qwen_processor
            )

            # BOM extraction
            result.bom_data = run_qwen_analysis(
                primary_image, BOM_EXTRACTION_PROMPT,
                model=_qwen_model, processor=_qwen_processor
            )

            # Manufacturing notes
            result.manufacturing_notes = run_qwen_analysis(
                primary_image, MANUFACTURING_NOTES_PROMPT,
                model=_qwen_model, processor=_qwen_processor
            )

        # Merge OCR and Qwen evidence
        merged_callouts = self.merge_evidence(
            result.ocr_callouts,
            result.features
        )

        # Extract SW requirements and compare
        if sw_entry and sw_entry.data:
            result.sw_requirements = extract_sw_requirements(sw_entry.data)

            result.comparison = generate_diff_result(
                callouts=merged_callouts,
                requirements=result.sw_requirements,
                part_number=identity.partNumber
            )
        else:
            result.comparison = create_stub_diff_result(
                part_number=identity.partNumber,
                reason="No SolidWorks CAD data found"
            )

        self.result = result
        return result
