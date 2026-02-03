"""Inter-stage data contracts for the YOLO-OBB pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DetectionResult:
    """Output from YOLO-OBB detector."""
    class_name: str
    confidence: float
    obb_points: List[List[float]]  # 4x2 array [[x,y], [x,y], [x,y], [x,y]]
    xywhr: Optional[List[float]] = None
    det_id: str = ""


@dataclass
class CropResult:
    """Output from OBB cropper."""
    image: Any  # PIL.Image (Any to avoid import issues)
    meta: Dict[str, Any] = field(default_factory=dict)
    # meta includes: pad_ratio, crop_w, crop_h, det_id


@dataclass
class OCRResult:
    """Output from OCR adapter."""
    text: str
    confidence: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RotationResult:
    """Output from rotation selector."""
    raw: str
    rotation_used: int  # 0, 90, 180, or 270
    quality_score: float
    ocr_result: Optional[OCRResult] = None


@dataclass
class ReaderResult:
    """Output from crop reader (pre-validation)."""
    callout_type: str
    raw: str
    parsed: Dict[str, Any] = field(default_factory=dict)
    source: str = ""  # "regex" or "vlm"
    ocr_confidence: float = 0.0


@dataclass
class CalloutPacket:
    """Full provenance packet tracking a detection through the pipeline."""
    det_id: str
    detection: Optional[DetectionResult] = None
    crop: Optional[CropResult] = None
    rotation: Optional[RotationResult] = None
    reader: Optional[ReaderResult] = None
    normalized: Optional[Dict[str, Any]] = None
    validated: bool = False
    validation_error: Optional[str] = None
    matched: bool = False
    match_status: Optional[str] = None
