"""Crop reader: OCR + canonicalize + regex parse with VLM fallback.

Pipeline per crop:
1. OCR the cropped image -> raw text + confidence
2. Canonicalize the text (normalize symbols, whitespace)
3. Regex parse based on YOLO class
4. If regex fails OR OCR confidence is too low -> VLM fallback (if available)
5. Always return a ReaderResult with at minimum the raw text
"""

from typing import Any, Callable, List, Optional, Tuple

from PIL import Image

from ..config import default_config
from ..contracts import ReaderResult
from .canonicalize import canonicalize
from .patterns import parse_by_class
from ..detection.classes import CLASS_TO_CALLOUT_TYPE


# OCR confidence threshold below which VLM fallback triggers
# Derived from config for backward compatibility.
OCR_CONFIDENCE_THRESHOLD = default_config.ocr_confidence_threshold


def _strip_hallucinated_tail(text: str) -> str:
    """
    Remove common OCR continuation noise from callout crops.

    The OCR model occasionally appends explanatory prose or markdown after
    the first valid callout line. This keeps the callout-focused prefix.
    """
    if not text:
        return ""

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""

    cleaned: List[str] = []
    for ln in lines:
        low = ln.lower()
        if (
            low.startswith("note:")
            or "the image contains" in low
            or low.startswith("**")
            or low.startswith("---")
            or low.startswith("solution")
        ):
            break
        cleaned.append(ln)
        if len(cleaned) >= default_config.ocr_crop_max_lines:
            break

    if not cleaned:
        cleaned = lines[:1]

    out = "\n".join(cleaned).strip()
    if len(out) > default_config.ocr_crop_max_chars:
        out = out[: default_config.ocr_crop_max_chars].rstrip()
    return out


def read_crop(
    image: Image.Image,
    ocr_fn: Callable[[Image.Image], Tuple[str, float]],
    yolo_class: str,
    ocr_confidence_threshold: float = OCR_CONFIDENCE_THRESHOLD,
    vlm_fn: Optional[Callable] = None,
    pre_ocr: Optional[Tuple[str, float]] = None,
) -> ReaderResult:
    """
    Read a cropped callout image through the parsing pipeline.

    Pipeline:
    1. OCR the crop -> raw text + confidence (or use pre_ocr if provided)
    2. Canonicalize the text
    3. Regex parse based on YOLO class
    4. If regex fails OR OCR confidence too low -> VLM fallback (if available)
    5. Always return a result with 'raw' field

    Args:
        image: Cropped PIL Image (already rotation-corrected)
        ocr_fn: Callable returning (text, confidence)
        yolo_class: YOLO detection class name
        ocr_confidence_threshold: Below this, trigger VLM fallback
        vlm_fn: Optional VLM fallback callable
        pre_ocr: Optional (text, confidence) tuple from a prior stage
                 (e.g., rotation selector). If provided, skips OCR step.

    Returns:
        ReaderResult with callout_type, raw text, and parsed fields
    """
    # Step 1: OCR (use pre_ocr if the rotation selector already ran OCR)
    if pre_ocr is not None:
        raw_text, confidence = pre_ocr
    else:
        raw_text, confidence = ocr_fn(image)

    # Step 2: Canonicalize + strip long hallucinated continuations
    canon_text = canonicalize(raw_text)
    if default_config.ocr_strip_hallucination_lines:
        canon_text = _strip_hallucinated_tail(canon_text)

    # Step 3: Map YOLO class to callout type
    callout_type = CLASS_TO_CALLOUT_TYPE.get(yolo_class, "Unknown")

    # Step 4: Try regex parse
    parsed = None
    source = "regex"

    if confidence >= ocr_confidence_threshold and canon_text:
        parsed = parse_by_class(canon_text, yolo_class)

    # Step 5: VLM fallback if regex failed or confidence too low
    if parsed is None and vlm_fn is not None:
        try:
            vlm_result = vlm_fn(image, yolo_class)
            if vlm_result and isinstance(vlm_result, dict):
                parsed = vlm_result
                source = "vlm"
                callout_type = vlm_result.get("calloutType", callout_type)
        except Exception:
            pass  # VLM failure is non-fatal

    # Step 6: If still no parse, mark as Unknown
    if parsed is None:
        parsed = {"calloutType": "Unknown"}
        if confidence < ocr_confidence_threshold:
            callout_type = "Unknown"
    else:
        callout_type = parsed.get("calloutType", callout_type)

    return ReaderResult(
        callout_type=callout_type,
        raw=canon_text or raw_text,
        parsed=parsed,
        source=source,
        ocr_confidence=confidence,
    )


def read_crops_batch(
    images: List[Image.Image],
    ocr_fn: Callable[[Image.Image], Tuple[str, float]],
    yolo_classes: List[str],
    **kwargs: Any,
) -> List[ReaderResult]:
    """
    Read a batch of cropped images.

    Args:
        images: List of PIL Images
        ocr_fn: OCR callable
        yolo_classes: List of YOLO class names per image

    Returns:
        List of ReaderResult
    """
    return [
        read_crop(img, ocr_fn, cls, **kwargs)
        for img, cls in zip(images, yolo_classes)
    ]
