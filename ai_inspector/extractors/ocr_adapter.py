"""OCR adapter wrapping LightOnOCR-2 with confidence estimation.

Provides a consistent interface for the YOLO pipeline:
    adapter.read(image) -> OCRResult(text, confidence, meta)

The adapter wraps the existing LightOnOCR class and adds:
- Confidence estimation (heuristic-based since LightOnOCR doesn't return token scores)
- Canonicalization of output text
- Consistent (text, confidence, meta) return format
"""

import re
from typing import Dict, Optional, Tuple

from PIL import Image

from ..config import default_config
from ..contracts import OCRResult
from .canonicalize import canonicalize


def _estimate_confidence(raw_text: str, canonicalized_text: str) -> float:
    """
    Estimate OCR confidence heuristically.

    Since LightOnOCR-2 doesn't expose token-level confidence scores,
    we estimate based on text characteristics:

    - Presence of recognizable engineering patterns -> higher confidence
    - Very short or empty text -> lower confidence
    - High ratio of special/garbage characters -> lower confidence
    - Balanced alphanumeric content -> higher confidence

    Returns:
        Confidence score between 0.0 and 1.0
    """
    if not canonicalized_text or not canonicalized_text.strip():
        return 0.0

    text = canonicalized_text.strip()
    score = 0.5  # Start at midpoint

    # Length factor (very short text is suspicious)
    if len(text) < 3:
        score -= 0.2
    elif len(text) >= 5:
        score += 0.1

    # Alphanumeric ratio
    alnum_count = sum(1 for c in text if c.isalnum())
    total_count = len(text)
    alnum_ratio = alnum_count / total_count if total_count > 0 else 0

    if alnum_ratio > 0.6:
        score += 0.15
    elif alnum_ratio < 0.3:
        score -= 0.15

    # Engineering pattern bonuses
    eng_patterns = [
        r'\d+\.?\d*',              # Numbers
        r'[\u2300]',               # Diameter symbol
        r'M\d+',                   # Metric thread
        r'R\.?\d',                 # Radius
        r'THRU|DEEP',             # Keywords
        r'[\u00B1]',              # Tolerance
        r'\d+\u00B0',             # Angle
    ]

    pattern_hits = sum(
        1 for p in eng_patterns
        if re.search(p, text, re.IGNORECASE)
    )
    score += min(pattern_hits * 0.05, 0.2)

    # Garbage penalties
    garbage_chars = sum(1 for c in text if ord(c) > 0x2600)  # Emoji/symbol block
    if garbage_chars > 0:
        score -= garbage_chars * 0.1

    # Repeated character penalty
    if re.search(r'(.)\1{4,}', text):
        score -= 0.2

    return max(0.0, min(1.0, score))


class OCRAdapter:
    """
    Adapter wrapping LightOnOCR-2 for the YOLO pipeline.

    Provides consistent (text, confidence, meta) output with
    automatic canonicalization.

    Usage:
        adapter = OCRAdapter(hf_token="your_token")
        adapter.load()

        result = adapter.read(image)
        print(result.text, result.confidence)

        # Or use the simple callable interface for rotation selector:
        text, conf = adapter.read_simple(image)
    """

    def __init__(self, hf_token: Optional[str] = None):
        """
        Initialize adapter.

        Args:
            hf_token: HuggingFace token for LightOnOCR-2 (gated model)
        """
        self.hf_token = hf_token
        self._ocr = None

    def load(self) -> None:
        """Load the underlying LightOnOCR model."""
        from .ocr import LightOnOCR
        self._ocr = LightOnOCR(hf_token=self.hf_token)
        self._ocr.load()

    def unload(self) -> None:
        """Release model from memory."""
        if self._ocr is not None:
            self._ocr.unload()
            self._ocr = None

    @property
    def is_loaded(self) -> bool:
        return self._ocr is not None and self._ocr.is_loaded

    def _run_ocr_pass(
        self,
        image: Image.Image,
        max_tokens: int,
        max_crop_dimension: int,
    ) -> Dict[str, object]:
        """Run one OCR pass and return text + confidence bundle."""
        raw_lines = self._ocr.extract(
            image,
            max_tokens=max_tokens,
            max_crop_dimension=max_crop_dimension,
        )
        raw_text = "\n".join(raw_lines)
        canon_text = canonicalize(raw_text)
        confidence = _estimate_confidence(raw_text, canon_text)
        return {
            "raw_lines": raw_lines,
            "raw_text": raw_text,
            "canon_text": canon_text,
            "confidence": confidence,
            "max_tokens": max_tokens,
            "max_crop_dimension": max_crop_dimension,
        }

    def read(self, image: Image.Image) -> OCRResult:
        """
        Read text from image with confidence estimation.

        Args:
            image: PIL Image to OCR

        Returns:
            OCRResult with canonicalized text, confidence, and metadata
        """
        if not self.is_loaded:
            raise RuntimeError("OCR model not loaded. Call load() first.")

        # First pass: fast crop OCR tuned for short engineering callouts
        first = self._run_ocr_pass(
            image=image,
            max_tokens=64,
            max_crop_dimension=default_config.ocr_max_crop_dimension,
        )
        best = first
        retry = None

        # Second pass on weak reads: slightly larger crop and token budget
        if (
            default_config.ocr_retry_enabled
            and float(first["confidence"]) < default_config.ocr_retry_confidence_threshold
        ):
            retry = self._run_ocr_pass(
                image=image,
                max_tokens=default_config.ocr_retry_max_tokens,
                max_crop_dimension=default_config.ocr_retry_max_crop_dimension,
            )

            first_conf = float(first["confidence"])
            retry_conf = float(retry["confidence"])
            if retry_conf > first_conf:
                best = retry
            elif retry_conf == first_conf:
                # Tie-breaker: prefer richer canonical text
                if len(str(retry["canon_text"])) > len(str(first["canon_text"])):
                    best = retry

        return OCRResult(
            text=str(best["canon_text"]),
            confidence=float(best["confidence"]),
            meta={
                "raw_text": str(best["raw_text"]),
                "raw_lines": list(best["raw_lines"]),
                "line_count": len(best["raw_lines"]),
                "engine": "LightOnOCR-2",
                "ocr_retry_enabled": default_config.ocr_retry_enabled,
                "ocr_retry_triggered": retry is not None,
                "ocr_passes": {
                    "first": {
                        "confidence": float(first["confidence"]),
                        "max_tokens": int(first["max_tokens"]),
                        "max_crop_dimension": int(first["max_crop_dimension"]),
                    },
                    "retry": None if retry is None else {
                        "confidence": float(retry["confidence"]),
                        "max_tokens": int(retry["max_tokens"]),
                        "max_crop_dimension": int(retry["max_crop_dimension"]),
                    },
                },
            },
        )

    def read_simple(self, image: Image.Image) -> Tuple[str, float]:
        """
        Simple interface returning (text, confidence) tuple.

        Compatible with the rotation selector's ocr_fn parameter.
        """
        result = self.read(image)
        return result.text, result.confidence


class MockOCRAdapter:
    """
    Mock OCR adapter for testing without GPU.

    Returns configurable fixed text and confidence.
    """

    def __init__(self, default_text: str = "", default_confidence: float = 0.5):
        self.default_text = default_text
        self.default_confidence = default_confidence
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def read(self, image: Image.Image) -> OCRResult:
        return OCRResult(
            text=self.default_text,
            confidence=self.default_confidence,
            meta={"engine": "MockOCR"},
        )

    def read_simple(self, image: Image.Image) -> Tuple[str, float]:
        return self.default_text, self.default_confidence
