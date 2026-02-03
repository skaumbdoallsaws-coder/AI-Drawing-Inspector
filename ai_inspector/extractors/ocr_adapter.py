"""OCR adapter wrapping LightOnOCR-2 with confidence estimation.

Provides a consistent interface for the YOLO pipeline:
    adapter.read(image) -> OCRResult(text, confidence, meta)

The adapter wraps the existing LightOnOCR class and adds:
- Confidence estimation (heuristic-based since LightOnOCR doesn't return token scores)
- Canonicalization of output text
- Consistent (text, confidence, meta) return format
"""

import re
from typing import Optional, Tuple

from PIL import Image

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

        # Get raw lines from LightOnOCR
        raw_lines = self._ocr.extract(image)
        raw_text = "\n".join(raw_lines)

        # Canonicalize
        canon_text = canonicalize(raw_text)

        # Estimate confidence
        confidence = _estimate_confidence(raw_text, canon_text)

        return OCRResult(
            text=canon_text,
            confidence=confidence,
            meta={
                "raw_text": raw_text,
                "raw_lines": raw_lines,
                "line_count": len(raw_lines),
                "engine": "LightOnOCR-2",
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
