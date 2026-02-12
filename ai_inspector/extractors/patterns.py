"""Regex patterns per YOLO class for parsing canonicalized OCR text.

Diameter symbols handled (after canonicalize):
- \u2300 (diameter sign) - canonical form after canonicalize()

Usage:
    from ai_inspector.extractors.patterns import parse_by_class, PATTERNS_BY_CLASS

    result = parse_by_class("\u2300.500 THRU", "Hole")
    # result == {"calloutType": "Hole", "diameter": ".500", "depth": "THRU"}
"""

import re
from typing import Any, Dict, List, Optional


# Diameter symbol classes
_DIA_LEGACY = r"[oO\u00d8\u2205\u03c6\u2300]"  # broad set for v4 ocr_parser
_DIA = r"[\u2300]"  # canonical only (after canonicalize)


# ===========================================================================
# YOLO-class-aware pattern groups
# ===========================================================================

# --- Hole patterns ---
# Examples: "\u2300.500 THRU", "\u230012.7 DEEP 25.4", "2X \u2300.250 THRU", "\u23003/8 THRU"
HOLE_PATTERNS = [
    # Quantity + diameter symbol + diameter + depth
    re.compile(
        r'(?:(\d+)X\s+)?'           # optional quantity (2X)
        r'[\u2300]\s*'               # diameter symbol
        r'(\d*\.?\d+|\d+/\d+)'      # diameter value (decimal or fraction)
        r'(?:\s*")?'                 # optional inch mark
        r'(?:\s+(THRU(?:\s+ALL)?|DEEP\s+\d*\.?\d+|DEEP))?',  # depth
        re.IGNORECASE
    ),
    # Drill callouts without explicit diameter symbol: "33/64 DRILL", ".500 DRILL THRU"
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(\d+/\d+|\d*\.?\d+)'
        r'\s*DRILL'
        r'(?:\s+(THRU(?:\s+ALL)?|DEEP\s+\d*\.?\d+|DEEP))?',
        re.IGNORECASE
    ),
    # Without diameter symbol: ".500 DIA", "12.7 DIA"
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(\d*\.?\d+)'
        r'\s*(?:DIA\.?|DIAMETER)',
        re.IGNORECASE
    ),
]

# --- Tapped Hole patterns ---
# Examples: "M6x1.0 THRU", "M8x1.25 DEEP 15", "1/4-20 UNC THRU", "3/8-16 UNC-2B"
TAPPED_HOLE_PATTERNS = [
    # Metric: M{d}x{pitch}, tolerant to OCR noise such as "M10 - 55"
    re.compile(
        r'(?:(\d+)X\s+)?'           # optional quantity
        r'(M\d+\.?\d*)'             # thread size (M6, M8, M10)
        r'(?:\s*[xX\u00d7\-]\s*'    # separator (x or OCR-noisy dash)
        r'(\d+\.?\d*))?'            # optional pitch
        r'(?:\s*-\s*(\w+))?'        # optional class (6H, 6g)
        r'(?:\s+(THRU(?:\s+ALL)?|DEEP\s+\d+\.?\d*|DEEP))?',
        re.IGNORECASE
    ),
    # Unified: d-tpi UNC/UNF
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(\d+/?\d*-\d+)'           # size-tpi (1/4-20, 3/8-16)
        r'\s*(UNC|UNF|UNEF|UN)'      # thread series
        r'(?:\s*-\s*(\w+))?'         # optional class (2B)
        r'(?:\s+(THRU(?:\s+ALL)?|DEEP\s+\d+\.?\d*|DEEP))?',
        re.IGNORECASE
    ),
]

# --- Counterbore patterns ---
# Examples: "\u2334 \u2300.750 DEEP .500", "CBORE \u2300.750 X .500 DEEP"
COUNTERBORE_PATTERNS = [
    re.compile(
        r'(?:[\u2334]|C\'?BORE|CBORE)\s*'
        r'[\u2300]?\s*(\d*\.?\d+)'   # cbore diameter
        r'(?:\s*[xX\u00d7]\s*|\s+DEEP\s+|\s+)'
        r'(\d*\.?\d+)',              # cbore depth
        re.IGNORECASE
    ),
]

# --- Countersink patterns ---
# Examples: "\u2335 \u2300.500 X 82\u00b0", "CSINK \u2300.500 82 DEG"
COUNTERSINK_PATTERNS = [
    re.compile(
        r'(?:[\u2335]|C\'?SINK|CSINK)\s*'
        r'[\u2300]?\s*(\d*\.?\d+)'   # csink diameter
        r'(?:\s*[xX\u00d7]\s*|\s+)'
        r'(\d+\.?\d*)\s*[\u00b0]?',  # csink angle
        re.IGNORECASE
    ),
]

# --- Fillet/Radius patterns ---
# Examples: "R.125", "R 3.0", "2X R.250", "FILLET R.125"
FILLET_PATTERNS = [
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(?:FILLET\s+)?'
        r'(?<![A-Za-z])'             # negative lookbehind
        r'R\s*(\.?\d+\.?\d*)'        # radius value
        r'(?:\s*")?',                # optional inch mark
        re.IGNORECASE
    ),
]

# --- Chamfer patterns ---
# Examples: ".030 X 45\u00b0", "1.0 X 45 DEG", "2X .060 X 45\u00b0", "CHAMFER .030 X 45\u00b0"
CHAMFER_PATTERNS = [
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(?:CHAM(?:FER)?\s+)?'
        r'(\d*\.?\d+)'              # chamfer size
        r'\s*[xX\u00d7]\s*'
        r'(\d+\.?\d*)\s*[\u00b0]?',  # chamfer angle
        re.IGNORECASE
    ),
]

# --- Thread patterns (standalone, not tapped hole) ---
THREAD_PATTERNS = [
    # Metric with optional qty
    re.compile(
        r'(?:(\d+)X\s+)?'
        r'(M\d+\.?\d*)[xX\u00d7](\d+\.?\d*)',
        re.IGNORECASE
    ),
    # ACME
    re.compile(
        r'(\d+\.?\d*)\s*-\s*(\d+)\s*ACME',
        re.IGNORECASE
    ),
]

# --- GD&T patterns ---
GDT_PATTERNS = [
    re.compile(
        r'(TRUE\s*POS(?:ITION)?|PERPENDICULARITY|PARALLELISM|CONCENTRICITY|'
        r'CIRCULARITY|CYLINDRICITY|FLATNESS|STRAIGHTNESS|'
        r'TOTAL\s*RUNOUT|CIRCULAR\s*RUNOUT|PROFILE\s*(?:OF\s*)?(?:LINE|SURFACE))'
        r'\s*[\u2300]?\s*(\d*\.?\d+)',
        re.IGNORECASE
    ),
]

# --- Surface Finish patterns ---
# Examples: "63 Ra", "125 Ra \u03bcin", "Ra 32"
SURFACE_FINISH_PATTERNS = [
    re.compile(
        r'(?:Ra\s*)?(\d+\.?\d*)\s*(?:Ra|(?:\u03bc|u)in|microinch)',
        re.IGNORECASE
    ),
    re.compile(
        r'Ra\s*(\d+\.?\d*)',
        re.IGNORECASE
    ),
]

# --- Dimension patterns ---
DIMENSION_PATTERNS = [
    # Basic dimension with tolerance: "1.500 \u00b1.005"
    re.compile(
        r'(\d*\.?\d+)\s*[\u00b1]\s*(\d*\.?\d+)',
    ),
    # Dimension with limits: "1.500 / 1.495"
    re.compile(
        r'(\d+\.?\d+)\s*/\s*(\d+\.?\d+)',
    ),
]

# --- Tolerance patterns ---
TOLERANCE_PATTERNS = [
    re.compile(
        r'[\u00b1]\s*(\d*\.?\d+)',
    ),
    # Bilateral: +.005 / -.003
    re.compile(
        r'\+\s*(\d*\.?\d+)\s*/?\s*-\s*(\d*\.?\d+)',
    ),
]

# ===========================================================================
# Master lookup: YOLO class name -> list of compiled patterns
# ===========================================================================
PATTERNS_BY_CLASS: Dict[str, list] = {
    "Hole": HOLE_PATTERNS,
    "TappedHole": TAPPED_HOLE_PATTERNS,
    "CounterboreHole": COUNTERBORE_PATTERNS,
    "CountersinkHole": COUNTERSINK_PATTERNS,
    "Fillet": FILLET_PATTERNS,
    "Chamfer": CHAMFER_PATTERNS,
    "Thread": THREAD_PATTERNS,
    "GDT": GDT_PATTERNS,
    "SurfaceFinish": SURFACE_FINISH_PATTERNS,
    "Dimension": DIMENSION_PATTERNS,
    "Tolerance": TOLERANCE_PATTERNS,
}


# ===========================================================================
# YOLO-class-aware parsing
# ===========================================================================

def parse_by_class(text: str, yolo_class: str) -> Optional[Dict[str, Any]]:
    """
    Try to parse canonicalized text using patterns for the given YOLO class.

    Args:
        text: Canonicalized OCR text
        yolo_class: YOLO class name (e.g., "Hole", "TappedHole")

    Returns:
        Dict of parsed fields if a pattern matched, None otherwise.
        Always includes 'calloutType' and matched groups.
    """
    patterns = PATTERNS_BY_CLASS.get(yolo_class, [])

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            return _extract_fields(yolo_class, groups, text)

    return None


def _extract_fields(yolo_class: str, groups: tuple, text: str) -> Dict[str, Any]:
    """Extract structured fields from regex match groups based on class type."""

    result: Dict[str, Any] = {"calloutType": yolo_class}

    if yolo_class == "Hole":
        qty, diameter, depth = (groups + (None, None, None))[:3]
        if qty:
            result["quantity"] = int(qty)
        if diameter:
            result["diameter"] = diameter
        if depth:
            result["depth"] = depth.strip()

    elif yolo_class == "TappedHole":
        qty, size, pitch_or_tpi, thread_class, depth = (groups + (None,) * 5)[:5]
        if qty:
            result["quantity"] = int(qty)
        if size:
            result["threadSize"] = size
        if pitch_or_tpi:
            result["pitch"] = pitch_or_tpi
        if thread_class:
            result["threadClass"] = thread_class
        if depth:
            result["depth"] = depth.strip()

    elif yolo_class == "CounterboreHole":
        diameter, depth = (groups + (None, None))[:2]
        if diameter:
            result["cboreDiameter"] = diameter
        if depth:
            result["cboreDepth"] = depth

    elif yolo_class == "CountersinkHole":
        diameter, angle = (groups + (None, None))[:2]
        if diameter:
            result["csinkDiameter"] = diameter
        if angle:
            result["csinkAngle"] = angle

    elif yolo_class == "Fillet":
        qty, radius = (groups + (None, None))[:2]
        if qty:
            result["quantity"] = int(qty)
        if radius:
            result["radius"] = radius

    elif yolo_class == "Chamfer":
        qty, size, angle = (groups + (None, None, None))[:3]
        if qty:
            result["quantity"] = int(qty)
        if size:
            result["size"] = size
        if angle:
            result["angle"] = angle

    elif yolo_class == "Thread":
        # First pattern: metric with optional qty
        if len(groups) >= 3 and groups[1] is not None:
            if groups[0]:
                result["quantity"] = int(groups[0])
            if groups[1].upper().startswith('M'):
                result["threadSize"] = groups[1]
                result["pitch"] = groups[2]
            else:
                result["threadSize"] = groups[0]
                result["pitch"] = groups[1]
        elif len(groups) >= 2:
            # ACME pattern
            result["threadSize"] = groups[0]
            result["tpi"] = groups[1]

    elif yolo_class == "GDT":
        gdt_type, tolerance_value = (groups + (None, None))[:2]
        if gdt_type:
            result["gdtType"] = gdt_type.strip().upper()
        if tolerance_value:
            result["toleranceValue"] = tolerance_value

    elif yolo_class == "SurfaceFinish":
        value = groups[0] if groups else None
        if value:
            result["roughness"] = value

    elif yolo_class == "Dimension":
        if len(groups) >= 2:
            result["nominal"] = groups[0]
            result["tolerance"] = groups[1]

    elif yolo_class == "Tolerance":
        if len(groups) >= 2 and groups[1] is not None:
            result["plus"] = groups[0]
            result["minus"] = groups[1]
        elif len(groups) >= 1:
            result["bilateral"] = groups[0]

    return result


# ===========================================================================
# Legacy PATTERNS dict (used by v4 ocr_parser.py — do not remove)
# ===========================================================================
PATTERNS = {
    "metric_thread": r"M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)",
    "imperial_thread": r"(\d+/\d+)\s*[-]\s*(\d+)",
    "unified_thread": r"(\.?\d+\.?\d*)\s*-\s*(\d+)\s*(UNC|UNF)",
    "thru_hole": rf"{_DIA_LEGACY}?\s*(\.?\d+\.?\d*)\s*(?:THRU|THR)",
    "blind_hole": rf"{_DIA_LEGACY}?\s*(\.?\d+\.?\d*)\s*[xX]\s*(\.?\d+\.?\d*)\s*(?:DEEP|DP)",
    "counterbore": rf"(?:CBORE|C'BORE|C-BORE)\s*{_DIA_LEGACY}?\s*(\.?\d+\.?\d*)",
    "countersink": rf"(?:CSK|CSINK|C-SINK)\s*{_DIA_LEGACY}?\s*(\.?\d+\.?\d*)",
    "diameter": rf"{_DIA_LEGACY}\s*(\.?\d+\.?\d*)",
    "major_minor_dia": rf"(?:MAJOR|MINOR|MAJ|MIN)\s*{_DIA_LEGACY}?\s*(\.?\d+\.?\d+)(?:\s*/\s*(\.?\d+\.?\d+))?",
    "fillet": r"(?<![A-Za-z])R\s*(\.?\d+\.?\d*)(?!\w)",
    "chamfer": r"(\.?\d+\.?\d*)\s*[xX]\s*45\s*[\u00b0]?",
    "quantity_prefix": r"[\(]?(\d+)\s*[xX][\)]?\s*",
    "quantity_suffix": r"\((\d+)\s*[xX]?\s*(?:PLACES?)?\)",
    "position_tolerance": rf"[\u2316]?\s*{_DIA_LEGACY}?\s*(\.?\d+\.?\d*)\s*\(?[MLSmls\u24c2\u24c1\u24c8]?\)?",
    "surface_finish": r"(\d+)\s*(?:[\u25bd\u25b3]|Ra|RMS|rms)",
}
