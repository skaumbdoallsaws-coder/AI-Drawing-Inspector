"""
Configuration for AI Engineering Drawing Inspector.

All settings centralized here. Override by creating a Config instance
with custom values.

Usage:
    from ai_inspector.config import Config, default_config

    # Use defaults
    print(default_config.render_dpi)  # 300

    # Override for a run
    my_config = Config(render_dpi=150, output_dir="my_output")
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Config:
    """
    Central configuration for the AI Inspector pipeline.

    All settings have sensible defaults matching v3 behavior.
    Create a new instance to override any setting.
    """

    # === Directories ===
    output_dir: str = "qc_output"
    solidworks_json_dir: str = "sw_json_library"

    # === PDF Rendering ===
    render_dpi: int = 300  # Higher = better OCR, but slower

    # === Model IDs ===
    ocr_model_id: str = "lightonai/LightOnOCR-2-1B"
    vlm_model_id: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    report_model_id: str = "gpt-4o-mini"

    # === Model Settings ===
    vlm_max_tokens: int = 4096
    vlm_temperature: float = 0.1
    ocr_max_tokens: int = 128
    report_max_tokens: int = 2500
    report_temperature: float = 0.3

    # === Comparison Tolerances ===
    hole_tolerance_inches: float = 0.015  # ~0.4mm
    thread_tolerance_mm: float = 0.1      # Nominal diameter
    pitch_tolerance: float = 0.01         # Thread pitch
    fillet_tolerance_inches: float = 0.015
    chamfer_tolerance_inches: float = 0.015

    # === Evidence Merging ===
    ocr_qwen_match_tolerance_inches: float = 0.01  # For deduplication

    # === OCR Preprocessing ===
    min_ocr_line_length: int = 1  # Skip empty lines
    min_hole_diameter_inches: float = 0.01  # Filter noise
    max_hole_diameter_inches: float = 3.0   # Filter OCR garbage (>3" unlikely)
    max_fillet_radius_inches: float = 2.0   # Filter OCR garbage (>2" unlikely)

    # === YOLO Detection ===
    yolo_model_path: str = "hf://shadrack20s/ai-inspector-callout-detection/callout_v2_yolo11s-obb_best.pt"
    yolo_confidence_threshold: float = 0.25    # YOLO detection confidence threshold
    # Optional per-class post-filter thresholds. Used after global threshold.
    # Keep Fillet stricter to suppress common false positives.
    yolo_class_confidence_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "Hole": 0.40,
            "TappedHole": 0.40,
            "Chamfer": 0.35,
            "Fillet": 0.88,
        }
    )

    # === OBB Cropping ===
    crop_pad_ratio: float = 0.15               # Padding ratio around OBB crop
    min_crop_width: int = 64                   # Minimum crop width in pixels
    min_crop_height: int = 32                  # Minimum crop height in pixels

    # === OCR / Rotation ===
    ocr_confidence_threshold: float = 0.4      # Below this, trigger VLM fallback
    ocr_max_crop_dimension: int = 384          # Max pixel dimension for crop resizing before OCR
    ocr_retry_enabled: bool = True             # Run second OCR pass on low confidence
    ocr_retry_confidence_threshold: float = 0.55
    ocr_retry_max_tokens: int = 96
    ocr_retry_max_crop_dimension: int = 512
    ocr_crop_max_chars: int = 180              # Trim long hallucinated continuations
    ocr_crop_max_lines: int = 6                # Keep callout-focused content only
    ocr_strip_hallucination_lines: bool = True

    # === Matching heuristics ===
    match_hole_tapped_equivalence: bool = True
    hole_tapped_equivalence_tolerance_inches: float = 0.02
    match_extra_missing_correlation_tolerance_inches: float = 0.02

    # === Evaluation ===
    eval_iou_threshold: float = 0.3            # IoU threshold for detection pairing

    # === Vision Extraction (GPT-4o) ===
    vision_extraction_model: str = "gpt-4o"
    vision_extraction_max_tokens: int = 4096
    vision_extraction_temperature: float = 0.1
    vision_extraction_detail: str = "high"  # OpenAI image detail level ("low", "high", "auto")

    # === VLM (page understanding) ===
    use_vlm: bool = True  # Enable Qwen VLM for holistic page understanding

    # === Classification ===
    classification_confidence_threshold: float = 0.5  # Default to MACHINED_PART if below

    # === Output Files ===
    identity_output_file: str = "ResolvedPartIdentity.json"
    evidence_output_file: str = "DrawingEvidence.json"
    diff_output_file: str = "DiffResult.json"
    report_output_file: str = "QCReport.md"
    qwen_output_file: str = "QwenUnderstanding.json"
    context_output_file: str = "AssemblyContext.json"


# Default configuration instance
default_config = Config()
