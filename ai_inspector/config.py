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

from dataclasses import dataclass


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
    ocr_max_tokens: int = 2048
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
    yolo_model_path: str = "yolo11n-obb.pt"    # Path to YOLO-OBB model weights
    yolo_confidence_threshold: float = 0.25    # YOLO detection confidence threshold

    # === OBB Cropping ===
    crop_pad_ratio: float = 0.15               # Padding ratio around OBB crop
    min_crop_width: int = 64                   # Minimum crop width in pixels
    min_crop_height: int = 32                  # Minimum crop height in pixels

    # === OCR / Rotation ===
    ocr_confidence_threshold: float = 0.4      # Below this, trigger VLM fallback

    # === Evaluation ===
    eval_iou_threshold: float = 0.3            # IoU threshold for detection pairing

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
