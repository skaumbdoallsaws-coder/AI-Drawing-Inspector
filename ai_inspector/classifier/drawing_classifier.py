"""Drawing type classification for AI Inspector v4.

Classifies engineering drawings into 7 types based on text patterns.
The classification determines OCR strategy and feature extraction focus.

Drawing Types:
    MACHINED_PART (71%): Holes, threads, GD&T, tolerances -> Use OCR
    SHEET_METAL (10%): Bends, flat patterns, slots -> Use OCR
    ASSEMBLY (11%): BOM, balloons, assembly notes -> Skip OCR
    WELDMENT (4%): Weld symbols, BOM, weld callouts -> Skip OCR
    CASTING (2%): Critical dims, reference dims -> Use OCR
    PURCHASED_PART (2%): Manufacturer table -> Skip OCR
    GEAR (<1%): Gear data table -> Use OCR
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any


class DrawingType(Enum):
    """Engineering drawing types supported by v4."""

    MACHINED_PART = "MACHINED_PART"
    SHEET_METAL = "SHEET_METAL"
    ASSEMBLY = "ASSEMBLY"
    WELDMENT = "WELDMENT"
    CASTING = "CASTING"
    PURCHASED_PART = "PURCHASED_PART"
    GEAR = "GEAR"


# Configuration for each drawing type
TYPE_CONFIG: Dict[DrawingType, Dict[str, Any]] = {
    DrawingType.MACHINED_PART: {
        "use_ocr": True,
        "use_qwen": True,
        "features_to_extract": ["holes", "threads", "gdt", "tolerances", "surface_finish"],
        "critical_checks": ["thread_callouts", "hole_dimensions"],
    },
    DrawingType.SHEET_METAL: {
        "use_ocr": True,
        "use_qwen": True,
        "features_to_extract": ["bends", "flat_pattern", "slots", "holes"],
        "critical_checks": ["bend_callouts", "f_dimensions"],
    },
    DrawingType.ASSEMBLY: {
        "use_ocr": False,
        "use_qwen": True,
        "features_to_extract": ["bom", "balloons", "assembly_notes"],
        "critical_checks": ["bom_complete", "balloons_match"],
    },
    DrawingType.WELDMENT: {
        "use_ocr": False,
        "use_qwen": True,
        "features_to_extract": ["weld_symbols", "bom", "weld_callouts"],
        "critical_checks": ["weld_symbols_present"],
    },
    DrawingType.CASTING: {
        "use_ocr": True,
        "use_qwen": True,
        "features_to_extract": ["critical_dims", "reference_dims", "material"],
        "critical_checks": ["critical_features_only"],
    },
    DrawingType.PURCHASED_PART: {
        "use_ocr": False,
        "use_qwen": True,
        "features_to_extract": ["manufacturer_table", "cross_reference"],
        "critical_checks": ["cross_reference_present"],
    },
    DrawingType.GEAR: {
        "use_ocr": True,
        "use_qwen": True,
        "features_to_extract": ["gear_data", "teeth", "pitch", "pressure_angle"],
        "critical_checks": ["gear_data_complete"],
    },
}


@dataclass
class ClassificationResult:
    """Result of drawing type classification.

    Attributes:
        drawing_type: The classified drawing type
        confidence: Confidence score (0.0 to 1.0)
        use_ocr: Whether to run OCR on this drawing
        use_qwen: Whether to run Qwen VLM analysis
        signals_found: List of text patterns that triggered classification
        reason: Human-readable explanation
    """

    drawing_type: DrawingType
    confidence: float
    use_ocr: bool
    use_qwen: bool
    signals_found: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        config = TYPE_CONFIG[self.drawing_type]
        return {
            "drawingType": self.drawing_type.value,
            "confidence": self.confidence,
            "useOCR": self.use_ocr,
            "useQwen": self.use_qwen,
            "signalsFound": self.signals_found,
            "reason": self.reason,
            "featuresToExtract": config["features_to_extract"],
            "criticalChecks": config["critical_checks"],
        }


class DrawingClassifier:
    """Classifies engineering drawings into types based on text patterns.

    The classifier analyzes text extracted from a PDF (via PyMuPDF or OCR)
    and determines the drawing type based on specific text patterns.

    Classification Priority (highest to lowest):
        0. ASSEMBLY - "ASSY" in title + BOM table (prevents misclassifying
           assemblies that contain weldment components)
        1. WELDMENT - "WELDT" in title (without ASSY in title)
        2. GEAR - Gear data keywords (TEETH, PITCH, PRESSURE ANGLE)
        3. PURCHASED_PART - Manufacturer cross-reference table
        4. CASTING - Casting signals (DUCTILE IRON, MFG ITEM #)
        5. SHEET_METAL - Flat pattern, bend callouts
        6. ASSEMBLY - BOM table (fallback if no ASSY in title)
        7. MACHINED_PART - Default (no specific signals)

    Usage:
        classifier = DrawingClassifier()
        result = classifier.classify(pdf_text)

        print(result.drawing_type)  # DrawingType.MACHINED_PART
        print(result.use_ocr)       # True
    """

    # Pattern definitions for classification
    WELDMENT_PATTERNS = [
        r"\bWELDT\b",           # "WELDT" in title
        r"\bWELDMENT\b",        # Full word
        r"\bWELD\s*ASSY\b",     # Weld assembly
    ]

    # Assembly title patterns - indicates drawing IS an assembly (not a component)
    ASSEMBLY_TITLE_PATTERNS = [
        r"\bASSY\b",            # "ASSY" in description
        r"\bASSEMBLY\b",        # Full word
        r"\bASSEM\b",           # Abbreviation
        r"\bSUBASSEM\b",        # Sub-assembly
    ]

    GEAR_PATTERNS = [
        r"\bTEETH\b",
        r"\bPITCH\b",
        r"\bPRESSURE\s*ANGLE\b",
        r"\bDIAMETRAL\s*PITCH\b",
        r"\bMODULE\b",
        r"\bGEAR\s*DATA\b",
    ]

    PURCHASED_PART_PATTERNS = [
        r"\bNSK\b",             # Bearing manufacturer
        r"\bSKF\b",             # Bearing manufacturer
        r"\bAST\b",             # Bearing manufacturer
        r"\bTIMKEN\b",          # Bearing manufacturer
        r"\bFAG\b",             # Bearing manufacturer
        r"\bFOR\s*REFERENCE\s*ONLY\b",
        r"\bMANUFACTURER\s*TABLE\b",
    ]

    CASTING_PATTERNS = [
        r"\bDUCTILE\s*IRON\b",
        r"\bGRAY\s*IRON\b",
        r"\bCAST\s*IRON\b",
        r"\bMFG\s*ITEM\s*#",
        r"\bALL\s*DIMENSIONS\s*ARE\s*REFERENCE\b",
        r"\bCASTING\b",
    ]

    SHEET_METAL_PATTERNS = [
        r"\bFLAT\s*PATTERN\b",
        r"\bBEND\b.*\b(?:UP|DOWN)\b",
        r"\bUP\s*\d+(?:\.\d+)?",       # UP 90 R.03
        r"\bDOWN\s*\d+(?:\.\d+)?",     # DOWN 90 R.03
        r"\(F\)",                       # (F) suffix for flat pattern dims
        r"\bGA(?:UGE)?\s*(?:STEEL|ALUM)",
    ]

    ASSEMBLY_PATTERNS = [
        r"\bITEM\s*NO\.?\b",
        r"\bQTY\.?\b",
        r"\bPART\s*(?:NO\.?|NUMBER)\b",
        r"\bASSEMBLY\b",
        r"\bASSEM\b",
        r"\bSUBASSEM\b",
    ]

    # BOM table detection - needs multiple signals
    BOM_TABLE_PATTERNS = [
        r"\bITEM\s*NO\.?\b",
        r"\bQTY\.?\b",
        r"\bDESCRIPTION\b",
    ]

    def __init__(self):
        """Initialize the classifier with compiled patterns."""
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        self._weldment_re = [re.compile(p, re.IGNORECASE) for p in self.WELDMENT_PATTERNS]
        self._gear_re = [re.compile(p, re.IGNORECASE) for p in self.GEAR_PATTERNS]
        self._purchased_re = [re.compile(p, re.IGNORECASE) for p in self.PURCHASED_PART_PATTERNS]
        self._casting_re = [re.compile(p, re.IGNORECASE) for p in self.CASTING_PATTERNS]
        self._sheet_metal_re = [re.compile(p, re.IGNORECASE) for p in self.SHEET_METAL_PATTERNS]
        self._assembly_re = [re.compile(p, re.IGNORECASE) for p in self.ASSEMBLY_PATTERNS]
        self._assembly_title_re = [re.compile(p, re.IGNORECASE) for p in self.ASSEMBLY_TITLE_PATTERNS]
        self._bom_re = [re.compile(p, re.IGNORECASE) for p in self.BOM_TABLE_PATTERNS]

    def _count_matches(self, text: str, patterns: List[re.Pattern]) -> tuple:
        """Count pattern matches and return (count, signals)."""
        signals = []
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                signals.append(match.group(0))
        return len(signals), signals

    def _has_bom_table(self, text: str) -> bool:
        """Check if text contains a BOM table (needs multiple signals)."""
        count, _ = self._count_matches(text, self._bom_re)
        return count >= 2  # Need at least ITEM NO + QTY or similar

    def _is_assembly_drawing(self, text: str) -> tuple:
        """Check if this is an assembly drawing based on title and BOM.

        Returns (is_assembly, signals) tuple.
        An assembly drawing has "ASSY" in the title AND a BOM table.
        """
        # Check for ASSY in title/description
        title_count, title_signals = self._count_matches(text, self._assembly_title_re)
        has_assy_title = title_count > 0

        # Check for BOM table
        has_bom = self._has_bom_table(text)

        if has_assy_title and has_bom:
            _, bom_signals = self._count_matches(text, self._assembly_re)
            return True, title_signals + bom_signals

        return False, []

    def classify(self, text: str) -> ClassificationResult:
        """Classify a drawing based on its text content.

        Args:
            text: Text extracted from PDF (via PyMuPDF or OCR)

        Returns:
            ClassificationResult with type, confidence, and OCR decision
        """
        if not text or not text.strip():
            return self._make_result(
                DrawingType.MACHINED_PART, 0.3, [],
                "No text available, defaulting to machined part"
            )

        # Priority 0: Check for ASSEMBLY with "ASSY" in title + BOM table
        # This takes priority over WELDMENT because a component in the BOM
        # might have "WELDT" in its description (e.g., "BRKT WELDT")
        is_assembly, assy_signals = self._is_assembly_drawing(text)
        if is_assembly:
            return self._make_result(
                DrawingType.ASSEMBLY, 0.90, assy_signals,
                "Assembly drawing: ASSY in title with BOM table"
            )

        # Priority 1: Check for WELDMENT (only if not an assembly)
        count, signals = self._count_matches(text, self._weldment_re)
        if count > 0:
            return self._make_result(
                DrawingType.WELDMENT, 0.95, signals,
                f"Weldment signal found: {signals[0]}"
            )

        # Priority 2: Check for GEAR
        count, signals = self._count_matches(text, self._gear_re)
        if count >= 2:  # Need multiple gear keywords
            return self._make_result(
                DrawingType.GEAR, 0.90, signals,
                f"Gear data signals found: {', '.join(signals[:3])}"
            )

        # Priority 3: Check for PURCHASED_PART
        count, signals = self._count_matches(text, self._purchased_re)
        if count >= 2:  # Need manufacturer names or reference-only
            return self._make_result(
                DrawingType.PURCHASED_PART, 0.90, signals,
                f"Purchased part signals found: {', '.join(signals[:3])}"
            )

        # Priority 4: Check for CASTING
        count, signals = self._count_matches(text, self._casting_re)
        if count > 0:
            return self._make_result(
                DrawingType.CASTING, 0.85, signals,
                f"Casting signal found: {signals[0]}"
            )

        # Priority 5: Check for SHEET_METAL
        count, signals = self._count_matches(text, self._sheet_metal_re)
        if count > 0:
            confidence = min(0.5 + count * 0.15, 0.95)
            return self._make_result(
                DrawingType.SHEET_METAL, confidence, signals,
                f"Sheet metal signals found: {', '.join(signals[:3])}"
            )

        # Priority 6: Check for ASSEMBLY (BOM table without weldment)
        if self._has_bom_table(text):
            _, bom_signals = self._count_matches(text, self._assembly_re)
            return self._make_result(
                DrawingType.ASSEMBLY, 0.85, bom_signals,
                "BOM table detected"
            )

        # Priority 7: Default to MACHINED_PART
        return self._make_result(
            DrawingType.MACHINED_PART, 0.70, [],
            "No specific signals, defaulting to machined part"
        )

    def _make_result(
        self,
        drawing_type: DrawingType,
        confidence: float,
        signals: List[str],
        reason: str,
    ) -> ClassificationResult:
        """Create ClassificationResult with config lookup."""
        config = TYPE_CONFIG[drawing_type]
        return ClassificationResult(
            drawing_type=drawing_type,
            confidence=confidence,
            use_ocr=config["use_ocr"],
            use_qwen=config["use_qwen"],
            signals_found=signals,
            reason=reason,
        )


def classify_drawing(text: str) -> ClassificationResult:
    """Convenience function to classify a drawing.

    Args:
        text: Text extracted from PDF

    Returns:
        ClassificationResult with type and processing decisions

    Example:
        result = classify_drawing(pdf_text)
        if result.use_ocr:
            ocr_output = run_ocr(image)
    """
    classifier = DrawingClassifier()
    return classifier.classify(text)
