"""Main orchestrator for AI Inspector v4 pipeline.

This module ties all components together into a single inspection workflow:
1. Render PDF to images
2. Classify drawing type (determines OCR strategy)
3. Extract features (OCR + VLM based on type)
4. Compare against SolidWorks CAD data
5. Generate QC report

Usage:
    from ai_inspector.pipeline import run_inspection

    result = run_inspection(
        pdf_path="drawing.pdf",
        sw_library_path="sw_json_library",
        hf_token="your_hf_token",
        openai_api_key="your_openai_key",  # Optional, for GPT reports
    )

    print(result.status)  # "PASS" or "FAIL"
    print(result.report.to_markdown())
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
import json
import os

from ..config import Config, default_config
from ..models.page import PageArtifact
from ..models.identity import ResolvedPartIdentity
from ..classifier import DrawingClassifier, ClassificationResult, DrawingType
from ..utils.pdf_render import render_pdf
from ..utils.sw_library import SwJsonLibrary
from ..utils.context_db import ContextDatabase
from ..extractors.identity import resolve_part_identity
from ..extractors.evidence_merger import DrawingEvidence, build_drawing_evidence
from ..comparison.diff_result import DiffResult, compare_drawing
from ..report.qc_report import QCReport, generate_report, generate_report_without_llm


@dataclass
class InspectionResult:
    """
    Complete result of an inspection run.

    Attributes:
        part_number: Resolved part number
        drawing_type: Classified drawing type
        classification: Full classification result
        status: PASS or FAIL
        match_rate: Feature match rate (0.0-1.0)
        evidence: Extracted drawing evidence
        diff: Comparison result
        report: Generated QC report
        has_sw_data: Whether SW CAD data was available
        timing: Timing information for each stage
        errors: Any errors encountered
    """
    part_number: str = ""
    drawing_type: str = ""
    classification: Optional[ClassificationResult] = None
    status: str = "UNKNOWN"
    match_rate: float = 0.0
    evidence: Optional[DrawingEvidence] = None
    diff: Optional[DiffResult] = None
    report: Optional[QCReport] = None
    has_sw_data: bool = False
    timing: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "partNumber": self.part_number,
            "drawingType": self.drawing_type,
            "status": self.status,
            "matchRate": self.match_rate,
            "hasSwData": self.has_sw_data,
            "timing": self.timing,
            "errors": self.errors,
            "classification": self.classification.to_dict() if self.classification else None,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "diff": self.diff.to_dict() if self.diff else None,
            "report": self.report.to_dict() if self.report else None,
        }

    def save(self, output_dir: str) -> None:
        """Save all outputs to directory."""
        os.makedirs(output_dir, exist_ok=True)

        # Save full result
        with open(os.path.join(output_dir, "InspectionResult.json"), "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        # Save report markdown
        if self.report:
            with open(os.path.join(output_dir, "QCReport.md"), "w") as f:
                f.write(self.report.to_markdown())

        # Save evidence
        if self.evidence:
            with open(os.path.join(output_dir, "DrawingEvidence.json"), "w") as f:
                json.dump(self.evidence.to_dict(), f, indent=2)

        # Save diff
        if self.diff:
            with open(os.path.join(output_dir, "DiffResult.json"), "w") as f:
                json.dump(self.diff.to_dict(), f, indent=2)


class InspectorPipeline:
    """
    Main pipeline orchestrator for AI Inspector v4.

    Coordinates all stages of the inspection process:
    - PDF rendering
    - Drawing classification
    - OCR extraction (conditional on type)
    - VLM analysis
    - Evidence merging
    - SW comparison
    - Report generation

    Usage:
        pipeline = InspectorPipeline(
            hf_token="your_token",
            openai_api_key="your_key",
        )

        # Load models (GPU required)
        pipeline.load_models()

        # Run inspection
        result = pipeline.inspect("drawing.pdf", sw_library)

        # Cleanup
        pipeline.unload_models()
    """

    def __init__(
        self,
        config: Config = None,
        hf_token: str = None,
        openai_api_key: str = None,
    ):
        """
        Initialize pipeline.

        Args:
            config: Configuration (uses default if None)
            hf_token: HuggingFace token for model access
            openai_api_key: OpenAI API key for report generation
        """
        self.config = config or default_config
        self.hf_token = hf_token
        self.openai_api_key = openai_api_key

        # Components (lazy-loaded)
        self.classifier = DrawingClassifier()
        self.ocr = None
        self.vlm = None
        self._models_loaded = False

    def load_models(self) -> None:
        """
        Load OCR and VLM models into GPU memory.

        Call this before running inspections. Models require ~7GB GPU memory.
        """
        from ..extractors.ocr import LightOnOCR
        from ..extractors.vlm import QwenVLM

        print("Loading OCR model...")
        self.ocr = LightOnOCR(hf_token=self.hf_token)
        self.ocr.load()
        print(f"  OCR loaded: {self.ocr.memory_gb:.1f} GB")

        print("Loading VLM model...")
        self.vlm = QwenVLM()
        self.vlm.load()
        print(f"  VLM loaded: {self.vlm.memory_gb:.1f} GB")

        self._models_loaded = True
        print("Models ready.")

    def unload_models(self) -> None:
        """Release models from GPU memory."""
        if self.ocr:
            self.ocr.unload()
            self.ocr = None
        if self.vlm:
            self.vlm.unload()
            self.vlm = None
        self._models_loaded = False
        print("Models unloaded.")

    @property
    def models_loaded(self) -> bool:
        """Check if models are loaded."""
        return self._models_loaded

    def inspect(
        self,
        pdf_path: str,
        sw_library: SwJsonLibrary,
        context_db: ContextDatabase = None,
        skip_ocr: bool = False,
        skip_vlm: bool = False,
        use_llm_report: bool = True,
    ) -> InspectionResult:
        """
        Run complete inspection on a PDF drawing.

        Args:
            pdf_path: Path to PDF file
            sw_library: Loaded SolidWorks JSON library
            context_db: Optional context database for assembly info
            skip_ocr: Force skip OCR (for testing)
            skip_vlm: Force skip VLM (for testing)
            use_llm_report: Use GPT-4o-mini for report (requires API key)

        Returns:
            InspectionResult with all outputs
        """
        import time

        result = InspectionResult()
        timing = {}

        try:
            # Stage 1: Render PDF
            t0 = time.time()
            artifacts = render_pdf(pdf_path, dpi=self.config.render_dpi)
            timing["render"] = time.time() - t0

            if not artifacts:
                result.errors.append("Failed to render PDF")
                return result

            # Stage 2: Classify drawing type
            t0 = time.time()
            combined_text = "\n".join(
                art.direct_text or "" for art in artifacts
            )
            classification = self.classifier.classify(combined_text)
            result.classification = classification
            result.drawing_type = classification.drawing_type.value
            timing["classify"] = time.time() - t0

            # Stage 3: Resolve part identity
            t0 = time.time()
            identity = resolve_part_identity(pdf_path, artifacts, sw_library)
            result.part_number = identity.part_number
            timing["identity"] = time.time() - t0

            # Stage 4: Extract features (OCR + VLM)
            t0 = time.time()
            ocr_lines = []
            qwen_output = {}

            # OCR (conditional on drawing type)
            use_ocr = classification.use_ocr and not skip_ocr
            if use_ocr and self._models_loaded and self.ocr:
                ocr_lines = self.ocr.extract_from_pages(artifacts)

            # VLM analysis
            use_vlm = classification.use_qwen and not skip_vlm
            if use_vlm and self._models_loaded and self.vlm:
                from ..extractors.drawing_analyzer import DrawingAnalyzer
                analyzer = DrawingAnalyzer(self.vlm)
                analysis = analyzer.full_analysis(artifacts)
                qwen_output = analysis.feature_analysis

            timing["extract"] = time.time() - t0

            # Stage 5: Build evidence
            t0 = time.time()
            evidence = build_drawing_evidence(
                result.part_number,
                ocr_lines,
                qwen_output,
            )
            result.evidence = evidence
            timing["evidence"] = time.time() - t0

            # Stage 6: Compare against SW data
            t0 = time.time()
            sw_entry = sw_library.lookup(result.part_number)
            sw_data = sw_entry.data if sw_entry else None
            result.has_sw_data = sw_data is not None

            diff = compare_drawing(evidence, sw_data)
            result.diff = diff
            result.match_rate = diff.match_rate
            timing["compare"] = time.time() - t0

            # Stage 7: Generate report
            t0 = time.time()
            if use_llm_report and self.openai_api_key:
                report = generate_report(
                    diff,
                    classification.drawing_type,
                    api_key=self.openai_api_key,
                )
            else:
                report = generate_report_without_llm(
                    diff,
                    classification.drawing_type,
                )
            result.report = report
            result.status = report.status
            timing["report"] = time.time() - t0

            result.timing = timing

        except Exception as e:
            result.errors.append(f"Pipeline error: {str(e)}")
            result.status = "ERROR"

        return result


def run_inspection(
    pdf_path: str,
    sw_library_path: str = None,
    sw_library: SwJsonLibrary = None,
    hf_token: str = None,
    openai_api_key: str = None,
    load_models: bool = True,
    use_llm_report: bool = True,
) -> InspectionResult:
    """
    Convenience function to run a complete inspection.

    Args:
        pdf_path: Path to PDF file
        sw_library_path: Path to SW JSON library directory
        sw_library: Pre-loaded SW library (alternative to path)
        hf_token: HuggingFace token for models
        openai_api_key: OpenAI API key for reports
        load_models: Whether to load OCR/VLM models
        use_llm_report: Use GPT-4o-mini for report

    Returns:
        InspectionResult with all outputs

    Example:
        result = run_inspection(
            "drawing.pdf",
            sw_library_path="sw_json_library",
            hf_token="hf_...",
        )
        print(result.status)
    """
    # Load SW library if path provided
    if sw_library is None:
        sw_library = SwJsonLibrary()
        if sw_library_path and os.path.exists(sw_library_path):
            sw_library.load_from_directory(sw_library_path)

    # Create and run pipeline
    pipeline = InspectorPipeline(
        hf_token=hf_token,
        openai_api_key=openai_api_key,
    )

    if load_models:
        pipeline.load_models()

    try:
        result = pipeline.inspect(
            pdf_path,
            sw_library,
            use_llm_report=use_llm_report,
        )
    finally:
        if load_models:
            pipeline.unload_models()

    return result
