"""Rotation selection with text quality scoring for cropped callouts."""

import re
from typing import Callable, List, Optional, Tuple

from PIL import Image

from ..contracts import CropResult, OCRResult, RotationResult


# Rotations to try
ROTATIONS = [0, 90, 180, 270]

# Engineering patterns that indicate good OCR quality
ENGINEERING_PATTERNS = [
    r'\d+\.?\d*',                    # Numbers (dimensions)
    r'[⌀Øø∅]\s*\.?\d',              # Diameter symbols
    r'M\d+',                         # Metric thread (M6, M8, etc.)
    r'\d+/\d+-\d+\s*(UNC|UNF)',     # Unified thread
    r'R\.?\d',                       # Radius
    r'THRU|DEEP|MIN|MAX',           # Depth keywords
    r'X\s*\d',                       # Quantity (2X, 4X)
    r'[±]\s*\.?\d',                  # Tolerances
    r'\d+°',                         # Angles
    r'TYP\.?',                       # Typical
    r'REF\.?',                       # Reference
    r'GD&T|TRUE\s*POS',            # GD&T indicators
    r'Ra\s*\d',                      # Surface finish
]

# Characters that indicate garbage OCR
GARBAGE_INDICATORS = [
    r'[■□▪▫●◆◇★☆♦♣♠♥]',  # Symbols that shouldn't appear
    r'(.)\1{4,}',                     # Same char repeated 5+ times
]


def _compute_text_quality(text: str, yolo_class: str = "") -> float:
    """
    Score OCR text quality for engineering drawing callouts.

    Higher score = more likely to be correct orientation.

    Scoring:
    - Base: length of text (longer usually means more content recognized)
    - Bonus: engineering patterns found
    - Penalty: garbage indicators
    - Bonus: class-specific patterns (e.g., diameter for Hole class)

    Args:
        text: OCR output text
        yolo_class: YOLO detection class name (for class-specific bonuses)

    Returns:
        Quality score (float, higher is better)
    """
    if not text or not text.strip():
        return 0.0

    score = 0.0

    # Base score: text length (normalized)
    score += min(len(text.strip()) / 20.0, 3.0)

    # Bonus for engineering patterns
    for pattern in ENGINEERING_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 1.0

    # Penalty for garbage
    for pattern in GARBAGE_INDICATORS:
        matches = re.findall(pattern, text)
        score -= len(matches) * 2.0

    # Class-specific bonuses
    class_patterns = {
        "Hole": [r'[⌀Øø∅]', r'THRU|DEEP', r'\d+X'],
        "TappedHole": [r'M\d+', r'UNC|UNF', r'TAP|THREAD'],
        "CounterboreHole": [r'[⌴]|C\'?BORE|CBORE', r'[⌀Øø∅]'],
        "CountersinkHole": [r'[⌵]|C\'?SINK|CSINK', r'\d+°'],
        "Fillet": [r'R\.?\d', r'RADIUS|RAD'],
        "Chamfer": [r'\d+\s*[Xx×]\s*\d+', r'\d+°', r'CHAM'],
        "Thread": [r'M\d+', r'UNC|UNF|ACME', r'THREAD'],
        "GDT": [r'TRUE\s*POS|PERP|PARALLEL|CONC|RUNOUT'],
        "SurfaceFinish": [r'Ra\s*\d', r'\d+\s*μ'],
        "Dimension": [r'\d+\.?\d*\s*[±]?\s*\.?\d*'],
    }

    if yolo_class in class_patterns:
        for pattern in class_patterns[yolo_class]:
            if re.search(pattern, text, re.IGNORECASE):
                score += 1.5

    # Penalty for very short text (likely garbage)
    if len(text.strip()) < 3:
        score -= 2.0

    return max(score, 0.0)


def select_best_rotation(
    crop_image: Image.Image,
    ocr_fn: Callable[[Image.Image], Tuple[str, float]],
    yolo_class: str = "",
    rotations: Optional[List[int]] = None,
) -> RotationResult:
    """
    Try multiple rotations and select the one with best text quality.

    Args:
        crop_image: Cropped PIL Image to test
        ocr_fn: Callable that takes PIL Image and returns (text, confidence)
        yolo_class: YOLO class name for class-specific scoring
        rotations: List of rotation angles to try (default: [0, 90, 180, 270])

    Returns:
        RotationResult with best rotation's text, angle, and quality score
    """
    if rotations is None:
        rotations = ROTATIONS

    best_result = None
    best_score = -1.0

    for angle in rotations:
        # Rotate the crop
        if angle == 0:
            rotated = crop_image
        else:
            rotated = crop_image.rotate(-angle, resample=Image.BICUBIC, expand=True)

        # Run OCR
        text, confidence = ocr_fn(rotated)

        # Score quality
        quality = _compute_text_quality(text, yolo_class)

        # Factor in OCR confidence
        combined_score = quality + (confidence * 2.0)

        ocr_result = OCRResult(
            text=text,
            confidence=confidence,
            meta={"rotation": angle},
        )

        if combined_score > best_score:
            best_score = combined_score
            best_result = RotationResult(
                raw=text,
                rotation_used=angle,
                quality_score=quality,
                ocr_result=ocr_result,
            )

    # If nothing worked at all, return empty result at 0 degrees
    if best_result is None:
        best_result = RotationResult(
            raw="",
            rotation_used=0,
            quality_score=0.0,
            ocr_result=OCRResult(text="", confidence=0.0, meta={"rotation": 0}),
        )

    return best_result


def select_rotations_batch(
    crops: List[CropResult],
    ocr_fn: Callable[[Image.Image], Tuple[str, float]],
    yolo_classes: Optional[List[str]] = None,
) -> List[RotationResult]:
    """
    Select best rotation for a batch of crops.

    Args:
        crops: List of CropResult from the cropper
        ocr_fn: OCR callable
        yolo_classes: Optional list of YOLO class names per crop

    Returns:
        List of RotationResult, one per crop
    """
    if yolo_classes is None:
        yolo_classes = [""] * len(crops)

    results = []
    for crop, cls_name in zip(crops, yolo_classes):
        result = select_best_rotation(
            crop_image=crop.image,
            ocr_fn=ocr_fn,
            yolo_class=cls_name,
        )
        results.append(result)

    return results
