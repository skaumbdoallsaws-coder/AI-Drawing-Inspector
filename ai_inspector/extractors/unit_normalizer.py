"""Unit normalization: detect units and convert to inches for SW matching.

Three-level detection:
1. Drawing-level: parse title block for unit declaration
2. Callout-level: look for mm/in suffixes or inch marks
3. Dual-hypothesis: when unknown, try both and pick plausible one

All dimensions are normalized to inches for comparison with SolidWorks data.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# Conversion factor
MM_TO_INCH = 1.0 / 25.4
INCH_TO_INCH = 1.0

# Drawing-level unit detection patterns
INCH_PATTERNS = [
    re.compile(r'DIMENSIONS?\s+(?:ARE\s+)?IN\s+INCHES', re.IGNORECASE),
    re.compile(r'UNLESS\s+OTHERWISE\s+(?:SPECIFIED|NOTED).*INCHES', re.IGNORECASE),
    re.compile(r'ALL\s+DIMENSIONS?\s+(?:IN\s+)?INCHES', re.IGNORECASE),
    re.compile(r'UNIT[S]?\s*:\s*INCH', re.IGNORECASE),
    re.compile(r'INCH(?:ES)?(?:\s*\(IN\))?', re.IGNORECASE),
]

METRIC_PATTERNS = [
    re.compile(r'DIMENSIONS?\s+(?:ARE\s+)?IN\s+(?:MILLI)?MET(?:ER|RE)S?', re.IGNORECASE),
    re.compile(r'UNLESS\s+OTHERWISE\s+(?:SPECIFIED|NOTED).*(?:MILLI)?MET(?:ER|RE)S?', re.IGNORECASE),
    re.compile(r'ALL\s+DIMENSIONS?\s+(?:IN\s+)?(?:MILLI)?MET(?:ER|RE)S?', re.IGNORECASE),
    re.compile(r'UNIT[S]?\s*:\s*MM', re.IGNORECASE),
    re.compile(r'MILLIMETERS?\s*\(MM\)', re.IGNORECASE),
]

# Callout-level unit hints
METRIC_THREAD_PATTERN = re.compile(r'\bM\d+(?:[xX]\d+(?:\.\d+)?)?\b')
IMPERIAL_THREAD_PATTERN = re.compile(r'(?:\d+/\d+|#\d+)-\d+\s*(?:UNC|UNF|UN)\b', re.IGNORECASE)
CALLOUT_MM_HINT = re.compile(r'(\d+\.?\d*)\s*mm\b', re.IGNORECASE)
CALLOUT_INCH_HINT = re.compile(r'(\d+\.?\d*)\s*(?:"|in\.?)\b')

# Plausible dimension ranges (in inches) for common engineering features
# Used for dual-hypothesis disambiguation
PLAUSIBLE_RANGES = {
    "diameter": (0.010, 12.0),      # 0.01" to 12"
    "radius": (0.005, 6.0),         # 0.005" to 6"
    "size": (0.005, 2.0),           # chamfer size
    "depth": (0.010, 12.0),
    "cboreDiameter": (0.050, 6.0),
    "cboreDepth": (0.010, 4.0),
    "csinkDiameter": (0.050, 4.0),
    "roughness": (1.0, 500.0),      # Ra microinch (not converted)
    "toleranceValue": (0.0001, 0.1),
}

# Fields that hold numeric dimension values needing conversion
DIMENSION_FIELDS = {
    "diameter", "radius", "size", "depth",
    "cboreDiameter", "cboreDepth", "csinkDiameter",
    "nominal", "tolerance", "bilateral", "plus", "minus",
    "threadSize",
}

# Fields that should NOT be converted (angles, counts, etc.)
SKIP_FIELDS = {
    "quantity", "calloutType", "pitch",
    "threadClass", "csinkAngle", "angle", "roughness",
    "gdtType", "toleranceValue",
}


def detect_drawing_units(title_block_text: str) -> Optional[str]:
    """
    Detect drawing-level units from title block text.

    Args:
        title_block_text: OCR text from the title block area

    Returns:
        "inch", "mm", or None if undetermined
    """
    if not title_block_text:
        return None

    for pattern in INCH_PATTERNS:
        if pattern.search(title_block_text):
            return "inch"

    for pattern in METRIC_PATTERNS:
        if pattern.search(title_block_text):
            return "mm"

    return None


def detect_callout_units(raw_text: str) -> Optional[str]:
    """
    Detect unit hints from a single callout's text.

    Args:
        raw_text: Canonicalized OCR text of the callout

    Returns:
        "inch", "mm", or None
    """
    if not raw_text:
        return None

    # Metric thread specs (M10, M10x1.5, etc.) are always metric
    if METRIC_THREAD_PATTERN.search(raw_text):
        return "mm"
    # Imperial thread specs (1/4-20 UNC, #10-32 UNF, etc.) are always imperial
    if IMPERIAL_THREAD_PATTERN.search(raw_text):
        return "inch"

    if CALLOUT_MM_HINT.search(raw_text):
        return "mm"
    if CALLOUT_INCH_HINT.search(raw_text):
        return "inch"

    return None


def _parse_numeric(value: str) -> Optional[float]:
    """Parse a numeric string, handling fractions like '3/8'."""
    if not value:
        return None

    value = value.strip().strip('"')

    # Handle fractions: 3/8, 1/4, etc.
    frac_match = re.match(r'^(\d+)/(\d+)$', value)
    if frac_match:
        num, den = int(frac_match.group(1)), int(frac_match.group(2))
        if den != 0:
            return num / den
        return None

    # Handle mixed fractions: 1-3/8
    mixed_match = re.match(r'^(\d+)-(\d+)/(\d+)$', value)
    if mixed_match:
        whole = int(mixed_match.group(1))
        num = int(mixed_match.group(2))
        den = int(mixed_match.group(3))
        if den != 0:
            return whole + num / den
        return None

    # Strip depth keywords
    value = re.sub(r'(?:THRU|DEEP)\s*', '', value, flags=re.IGNORECASE).strip()

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _is_plausible_inch(value: float, field_name: str) -> bool:
    """Check if a value in inches falls within plausible range."""
    lo, hi = PLAUSIBLE_RANGES.get(field_name, (0.001, 50.0))
    return lo <= value <= hi


def _convert_value(value: str, factor: float) -> Optional[float]:
    """Parse and convert a dimension value."""
    numeric = _parse_numeric(value)
    if numeric is None:
        return None
    return numeric * factor


def normalize_callout(
    parsed: Dict[str, Any],
    raw_text: str = "",
    drawing_units: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalize a single parsed callout's dimensions to inches.

    Priority:
    1. Callout-level unit hint (from raw text)
    2. Drawing-level units (from title block)
    3. Dual-hypothesis: try both, pick plausible

    Args:
        parsed: Parsed callout dict from regex/VLM
        raw_text: Original canonicalized OCR text
        drawing_units: Drawing-level units ("inch", "mm", or None)

    Returns:
        New dict with normalized values and provenance fields:
        - _detected_units: what was detected
        - _drawing_units: drawing-level setting
        - _normalization_method: "callout_hint", "drawing_hint", "dual_hypothesis", or "dual_hypothesis_ambiguous"
    """
    if not parsed:
        return {
            "_detected_units": None,
            "_drawing_units": drawing_units,
            "_normalization_method": None,
        }

    result = dict(parsed)  # shallow copy

    # Detect callout-level units
    callout_units = detect_callout_units(raw_text)

    # Determine effective units and method
    if callout_units:
        effective_units = callout_units
        method = "callout_hint"
    elif drawing_units:
        effective_units = drawing_units
        method = "drawing_hint"
    else:
        # Dual hypothesis: try both, pick plausible
        effective_units, method = _dual_hypothesis(parsed)

    # Apply conversion
    factor = MM_TO_INCH if effective_units == "mm" else INCH_TO_INCH

    for field_name, value in parsed.items():
        if field_name in SKIP_FIELDS:
            continue
        if field_name not in DIMENSION_FIELDS:
            continue
        if not isinstance(value, str):
            continue

        converted = _convert_value(value, factor)
        if converted is not None:
            result[field_name] = round(converted, 6)

    # Add provenance
    result["_detected_units"] = effective_units
    result["_drawing_units"] = drawing_units
    result["_normalization_method"] = method

    return result


def _dual_hypothesis(parsed: Dict[str, Any]) -> Tuple[str, str]:
    """
    Try both inch and mm interpretations, pick the more plausible one.

    Returns:
        (effective_units, method) tuple
    """
    inch_plausible = 0
    mm_plausible = 0
    total_checked = 0

    for field_name, value in parsed.items():
        if field_name in SKIP_FIELDS or field_name not in DIMENSION_FIELDS:
            continue
        if not isinstance(value, str):
            continue

        numeric = _parse_numeric(value)
        if numeric is None:
            continue

        total_checked += 1

        # As inches
        if _is_plausible_inch(numeric, field_name):
            inch_plausible += 1

        # As mm -> converted to inches
        converted = numeric * MM_TO_INCH
        if _is_plausible_inch(converted, field_name):
            mm_plausible += 1

    if total_checked == 0:
        return "inch", "dual_hypothesis_ambiguous"

    if mm_plausible > inch_plausible:
        return "mm", "dual_hypothesis"
    elif inch_plausible > mm_plausible:
        return "inch", "dual_hypothesis"
    else:
        # Both equally plausible (or neither plausible); prefer inches (SW native)
        return "inch", "dual_hypothesis_ambiguous"


def normalize_callouts(
    callouts: List[Dict[str, Any]],
    raw_texts: Optional[List[str]] = None,
    title_block_text: str = "",
) -> List[Dict[str, Any]]:
    """
    Normalize a list of callouts.

    Args:
        callouts: List of parsed callout dicts
        raw_texts: Optional list of raw OCR texts per callout
        title_block_text: Title block text for drawing-level unit detection

    Returns:
        List of normalized callout dicts
    """
    drawing_units = detect_drawing_units(title_block_text)

    if raw_texts is None:
        raw_texts = [""] * len(callouts)

    return [
        normalize_callout(parsed, raw, drawing_units)
        for parsed, raw in zip(callouts, raw_texts)
    ]
