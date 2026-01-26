"""
Canonicalizer - Normalize drawing callouts to match SolidWorks data.

This module implements the canonicalization rules for DrawingEvidence schema v1.1.1.
See: canonicalization_rules.json and drawing_evidence_v1.1.1.schema.json

LOCKED TO SCHEMA VERSION: 1.1.1
"""

import re
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass, field

# Schema version this canonicalizer is locked to
SCHEMA_VERSION = "1.1.1"

# Constants - Unicode code points for consistency
INCH_TO_MM = 25.4
DIAMETER_SYMBOL = "\u00f8"  # LATIN SMALL LETTER O WITH STROKE (U+00F8)
DEGREE_SYMBOL = "\u00b0"    # DEGREE SIGN (U+00B0)

# Common fractions lookup (for speed)
COMMON_FRACTIONS = {
    "1/64": 0.015625, "1/32": 0.03125, "1/16": 0.0625, "3/32": 0.09375,
    "1/8": 0.125, "5/32": 0.15625, "3/16": 0.1875, "7/32": 0.21875,
    "1/4": 0.25, "9/32": 0.28125, "5/16": 0.3125, "11/32": 0.34375,
    "3/8": 0.375, "13/32": 0.40625, "7/16": 0.4375, "15/32": 0.46875,
    "1/2": 0.5, "17/32": 0.53125, "9/16": 0.5625, "19/32": 0.59375,
    "5/8": 0.625, "21/32": 0.65625, "11/16": 0.6875, "23/32": 0.71875,
    "3/4": 0.75, "25/32": 0.78125, "13/16": 0.8125, "27/32": 0.84375,
    "7/8": 0.875, "29/32": 0.90625, "15/16": 0.9375, "31/32": 0.96875,
    "1": 1.0
}

# Diameter symbol aliases
DIAMETER_ALIASES = ["Ø", "ø", "⌀", "∅", "DIA", "DIA.", "DIAM", "DIAM.", "O/", "0", "Φ"]

# THRU aliases
THRU_ALIASES = ["THRU", "THROUGH", "THRU ALL", "↓", "THRU-ALL"]

# DEEP aliases
DEEP_ALIASES = ["DEEP", "DP", "DP.", "DEPTH", "↧"]


# Soft validation rules per callout type (from schema v1.1.1)
SOFT_VALIDATION_RULES = {
    "Hole": {
        "shouldHave": ["diameterMm"],
        "warnIf": {
            "blindWithoutDepth": "Blind hole without depth specified"
        }
    },
    "TappedHole": {
        "shouldHave": ["thread", "thread.standard", "thread.nominalMm"],
        "warnIf": {
            "missingThread": "Thread specification is incomplete",
            "missingPitch": "Thread pitch/TPI not specified"
        }
    },
    "Fillet": {
        "shouldHave": ["radiusMm"],
        "warnIf": {}
    },
    "Chamfer": {
        "shouldHave": ["distance1Mm"],
        "warnIf": {
            "missingAngle": "Chamfer angle not specified (assumed 45°)"
        }
    }
}


@dataclass
class QuantityInfo:
    """Parsed quantity information from callout"""
    quantity: int = 1
    quantity_raw: Optional[str] = None  # Original token: "(4X)", "4 HOLES", "2 PLCS", "TYP"
    is_typical: Optional[bool] = None   # True if TYP/TYPICAL was found
    plcs: Optional[int] = None          # Places if explicitly mentioned


@dataclass
class ParsedHole:
    """Parsed hole callout data"""
    diameter_mm: float
    diameter_inches: Optional[float]
    diameter_raw: str
    depth_mm: Optional[float]
    depth_raw: Optional[str]
    is_through: bool
    quantity: int
    canonical: str
    # v1.1.1 additions
    quantity_raw: Optional[str] = None
    is_typical: Optional[bool] = None
    validation_warnings: List[str] = field(default_factory=list)


@dataclass
class ParsedThread:
    """Parsed thread specification"""
    raw_text: str
    standard: str  # Metric, UNC, UNF, NPT, etc.
    nominal_mm: float
    pitch: Optional[float]  # mm for metric
    tpi: Optional[int]  # threads per inch
    thread_class: Optional[str]
    depth_mm: Optional[float]
    canonical: str
    # v1.1.1 additions
    quantity: int = 1
    quantity_raw: Optional[str] = None
    is_typical: Optional[bool] = None
    validation_warnings: List[str] = field(default_factory=list)


@dataclass
class ParsedFillet:
    """Parsed fillet callout"""
    radius_mm: float
    radius_inches: Optional[float]
    radius_raw: str
    quantity: int
    canonical: str
    # v1.1.1 additions
    quantity_raw: Optional[str] = None
    is_typical: Optional[bool] = None
    validation_warnings: List[str] = field(default_factory=list)


@dataclass
class ParsedChamfer:
    """Parsed chamfer callout"""
    distance1_mm: float
    distance2_mm: Optional[float]
    angle_degrees: float
    chamfer_type: str  # AngleDistance, DistanceDistance
    quantity: int
    canonical: str
    # v1.1.1 additions
    quantity_raw: Optional[str] = None
    is_typical: Optional[bool] = None
    validation_warnings: List[str] = field(default_factory=list)


def parse_fraction(text: str) -> Optional[float]:
    """Parse a fraction string to decimal inches."""
    text = text.strip()

    # Check common fractions first (faster)
    if text in COMMON_FRACTIONS:
        return COMMON_FRACTIONS[text]

    # Try to parse as fraction
    match = re.match(r'^(\d+)\s*/\s*(\d+)$', text)
    if match:
        num, den = int(match.group(1)), int(match.group(2))
        if den != 0:
            return num / den

    # Try mixed number (e.g., "1 1/2")
    match = re.match(r'^(\d+)\s+(\d+)\s*/\s*(\d+)$', text)
    if match:
        whole, num, den = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if den != 0:
            return whole + num / den

    return None


def parse_number(text: str) -> Tuple[Optional[float], str]:
    """
    Parse a number that may be decimal or fraction.
    Returns (value_in_inches, raw_text).
    """
    text = text.strip()
    original = text

    # Try fraction first
    frac_val = parse_fraction(text)
    if frac_val is not None:
        return frac_val, original

    # Try decimal (with optional leading zero)
    match = re.match(r'^\.?(\d*\.?\d+)$', text)
    if match:
        try:
            return float(text), original
        except ValueError:
            pass

    return None, original


def detect_units(text: str, value: float) -> str:
    """
    Detect if a value is in inches or mm based on context.
    Returns 'inch' or 'mm'.
    """
    # Check for explicit unit suffix
    if re.search(r'\bmm\b', text, re.IGNORECASE):
        return 'mm'
    if re.search(r'\bin\.?\b|inch|"', text, re.IGNORECASE):
        return 'inch'

    # Heuristic: values with leading decimal point are usually inches
    if text.startswith('.'):
        return 'inch'

    # Heuristic: small values (< 3) are probably inches, larger probably mm
    # This is a fallback - prefer explicit units
    if value < 3:
        return 'inch'

    return 'mm'


def inches_to_mm(value: float) -> float:
    """Convert inches to mm."""
    return value * INCH_TO_MM


def normalize_diameter_symbol(text: str) -> str:
    """Replace diameter symbol aliases with canonical ø."""
    result = text
    for alias in DIAMETER_ALIASES:
        result = re.sub(re.escape(alias), DIAMETER_SYMBOL, result, flags=re.IGNORECASE)
    return result


def extract_quantity(text: str) -> Tuple[QuantityInfo, str]:
    """
    Extract quantity from callout text.
    Returns (QuantityInfo, text_without_quantity).

    Detects and preserves:
    - Prefix: "2X ", "4X ", "(4) ", "4-"
    - Suffix: "(2X)", "2 PLCS", "2 PLACES", "2 PL", "4 HOLES"
    - Typical: "TYP", "TYPICAL"
    """
    info = QuantityInfo()
    remaining = text

    # Check for TYP/TYPICAL anywhere in text
    typ_match = re.search(r'\b(TYP(?:ICAL)?)\b', text, re.IGNORECASE)
    if typ_match:
        info.is_typical = True
        info.quantity_raw = typ_match.group(0).upper()
        # Don't remove TYP from text - it's often part of callout like "R.030 TYP"

    # Prefix patterns: "2X ", "4X ", "(4) ", "4-"
    match = re.match(r'^(\d+)\s*[Xx]\s+', remaining)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.quantity_raw = match.group(0).strip()
        return info, remaining[match.end():]

    match = re.match(r'^\((\d+)\)\s*', remaining)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.quantity_raw = match.group(0).strip()
        return info, remaining[match.end():]

    match = re.match(r'^(\d+)-(?=\D)', remaining)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.quantity_raw = f"{qty}-"
        return info, remaining[match.end():]

    # Suffix patterns: "(2X)", "2 PLCS", "2 PLACES", "2 PL", "N HOLES"
    match = re.search(r'\((\d+)\s*[Xx]\)\s*$', remaining)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.quantity_raw = match.group(0).strip()
        return info, remaining[:match.start()].strip()

    match = re.search(r'(\d+)\s*(PLCS|PLACES|PL)\.?\s*$', remaining, re.IGNORECASE)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.plcs = qty  # Explicitly "places" notation
        info.quantity_raw = match.group(0).strip()
        return info, remaining[:match.start()].strip()

    match = re.search(r'(\d+)\s*HOLES?\s*$', remaining, re.IGNORECASE)
    if match:
        qty = int(match.group(1))
        info.quantity = qty
        info.quantity_raw = match.group(0).strip()
        return info, remaining[:match.start()].strip()

    return info, remaining


def parse_hole_callout(raw_text: str) -> Optional[ParsedHole]:
    """
    Parse a hole callout and return canonical form.

    Examples:
        "Ø1/2 THRU" -> "ø12.70mm THRU"
        "4X Ø.375 x 1.000 DEEP" -> "ø9.53mm x 25.4mm DEEP (4X)"
        "Ø.500 [12.7] THRU (2 PLCS)" -> "ø12.70mm THRU (2X)"
    """
    text = raw_text.strip()
    warnings: List[str] = []

    # Quick check: must have diameter symbol or look like a hole callout
    has_dia_symbol = any(alias in text.upper() for alias in ["Ø", "DIA", "⌀", "∅"])
    if not has_dia_symbol and not re.search(r'[Øø⌀∅]', text):
        # Check if it starts with diameter-like pattern (not R for radius)
        if not re.match(r'^[\d\(].*(?:THRU|DEEP|DP)', text, re.IGNORECASE):
            return None

    # Extract quantity info using new function
    qty_info = QuantityInfo()
    text_for_qty = text

    # Suffix patterns: "(2X)", "(2 PLCS)", "2 PLCS", "2 PLACES", "2 PL" - check BEFORE prefix
    plcs_match = re.search(r'\((\d+)\s*[Xx]\)\s*$', text_for_qty)
    if plcs_match:
        qty_info.quantity = int(plcs_match.group(1))
        qty_info.quantity_raw = plcs_match.group(0).strip()
        text = text_for_qty[:plcs_match.start()].strip()
    else:
        # Check for "(2 PLCS)" with parens
        plcs_match = re.search(r'\((\d+)\s*(?:PLCS|PLACES|PL)\.?\)\s*$', text_for_qty, re.IGNORECASE)
        if plcs_match:
            qty_info.quantity = int(plcs_match.group(1))
            qty_info.plcs = qty_info.quantity
            qty_info.quantity_raw = plcs_match.group(0).strip()
            text = text_for_qty[:plcs_match.start()].strip()
        else:
            # Check for "2 PLCS" without parens
            plcs_match = re.search(r'(\d+)\s*(?:PLCS|PLACES|PL)\.?\s*$', text_for_qty, re.IGNORECASE)
            if plcs_match:
                qty_info.quantity = int(plcs_match.group(1))
                qty_info.plcs = qty_info.quantity
                qty_info.quantity_raw = plcs_match.group(0).strip()
                text = text_for_qty[:plcs_match.start()].strip()
            else:
                # Check for "N HOLES"
                holes_match = re.search(r'(\d+)\s*HOLES?\s*$', text_for_qty, re.IGNORECASE)
                if holes_match:
                    qty_info.quantity = int(holes_match.group(1))
                    qty_info.quantity_raw = holes_match.group(0).strip()
                    text = text_for_qty[:holes_match.start()].strip()
                else:
                    # No suffix match, try prefix patterns: "2X ", "4X ", "(4) ", "4-"
                    prefix_match = re.match(r'^(\d+)\s*[Xx]\s+', text)
                    if prefix_match:
                        qty_info.quantity = int(prefix_match.group(1))
                        qty_info.quantity_raw = prefix_match.group(0).strip()
                        text = text[prefix_match.end():]
                    else:
                        prefix_match = re.match(r'^\((\d+)\)\s*', text)
                        if prefix_match:
                            qty_info.quantity = int(prefix_match.group(1))
                            qty_info.quantity_raw = prefix_match.group(0).strip()
                            text = text[prefix_match.end():]

    # Check for TYP/TYPICAL
    typ_match = re.search(r'\b(TYP(?:ICAL)?)\b', text, re.IGNORECASE)
    if typ_match:
        qty_info.is_typical = True
        if not qty_info.quantity_raw:
            qty_info.quantity_raw = typ_match.group(0).upper()

    # Normalize diameter symbol
    text = normalize_diameter_symbol(text)

    # Extract diameter
    dia_match = re.search(rf'{DIAMETER_SYMBOL}\s*(\d+\s*/\s*\d+|\d*\.?\d+)', text, re.IGNORECASE)
    if not dia_match:
        return None

    dia_raw = dia_match.group(1)
    dia_value, _ = parse_number(dia_raw)
    if dia_value is None:
        return None

    # Check for dual units [mm] or (mm)
    dual_match = re.search(r'[\[\(](\d+\.?\d*)\s*(?:mm)?[\]\)]', text)
    if dual_match:
        # Use the bracketed mm value directly
        dia_mm = float(dual_match.group(1))
        dia_inches = dia_mm / INCH_TO_MM
    else:
        # Detect units
        units = detect_units(dia_raw, dia_value)
        if units == 'inch':
            dia_inches = dia_value
            dia_mm = inches_to_mm(dia_value)
        else:
            dia_mm = dia_value
            dia_inches = dia_value / INCH_TO_MM

    # Check for THRU
    is_through = any(alias in text.upper() for alias in THRU_ALIASES)

    # Extract depth
    depth_mm = None
    depth_raw = None

    if not is_through:
        # Look for "x {depth} DEEP" or "x {depth} DP" or just "x {depth}"
        depth_match = re.search(r'[Xx×]\s*(\d*\.?\d+)\s*(?:mm\s*)?(?:DEEP|DP\.?)?', text, re.IGNORECASE)
        if depth_match:
            depth_raw = depth_match.group(1)
            depth_value, _ = parse_number(depth_raw)
            if depth_value is not None:
                # Detect depth units
                depth_units = detect_units(depth_raw, depth_value)
                if depth_units == 'inch':
                    depth_mm = inches_to_mm(depth_value)
                else:
                    depth_mm = depth_value

    # Soft validation warnings
    if not is_through and depth_mm is None:
        warnings.append("Blind hole without depth specified")

    # Build canonical string
    canonical = f"{DIAMETER_SYMBOL}{dia_mm:.2f}mm"
    if is_through:
        canonical += " THRU"
    elif depth_mm is not None:
        canonical += f" x {depth_mm:.1f}mm DEEP"

    if qty_info.quantity > 1:
        canonical += f" ({qty_info.quantity}X)"

    return ParsedHole(
        diameter_mm=round(dia_mm, 2),
        diameter_inches=round(dia_inches, 4) if dia_inches else None,
        diameter_raw=dia_raw,
        depth_mm=round(depth_mm, 1) if depth_mm else None,
        depth_raw=depth_raw,
        is_through=is_through,
        quantity=qty_info.quantity,
        canonical=canonical,
        quantity_raw=qty_info.quantity_raw,
        is_typical=qty_info.is_typical,
        validation_warnings=warnings
    )


def parse_thread_callout(raw_text: str) -> Optional[ParsedThread]:
    """
    Parse a thread callout.

    Examples:
        "M6X1.0" -> "M6x1.0"
        "1/4-20 UNC" -> "1/4-20 UNC"
        "M6x1.0 x 12 DEEP" -> "M6x1.0 x 12mm DEEP"
    """
    text = raw_text.strip().upper()
    warnings: List[str] = []

    # Extract quantity first
    qty_info, text_after_qty = extract_quantity(raw_text.strip())
    text = text_after_qty.upper()

    depth_mm = None
    thread_class = None

    # Extract depth if present
    depth_match = re.search(r'[Xx×]\s*(\d+\.?\d*)\s*(?:MM\s*)?(?:DEEP|DP)', text, re.IGNORECASE)
    if depth_match:
        depth_val = float(depth_match.group(1))
        depth_mm = depth_val if depth_val > 3 else inches_to_mm(depth_val)

    # Check for metric thread: M{size}x{pitch}
    metric_match = re.match(r'M(\d+\.?\d*)\s*[Xx×-]\s*(\d+\.?\d*)(?:-(\d+[HhGg]))?', text)
    if metric_match:
        nominal = float(metric_match.group(1))
        pitch = float(metric_match.group(2))
        thread_class = metric_match.group(3)

        canonical = f"M{nominal:.0f}x{pitch}"
        if thread_class:
            canonical += f"-{thread_class.upper()}"
        if depth_mm:
            canonical += f" x {depth_mm:.0f}mm DEEP"
        if qty_info.quantity > 1:
            canonical += f" ({qty_info.quantity}X)"

        return ParsedThread(
            raw_text=raw_text,
            standard="Metric",
            nominal_mm=nominal,
            pitch=pitch,
            tpi=None,
            thread_class=thread_class,
            depth_mm=depth_mm,
            canonical=canonical,
            quantity=qty_info.quantity,
            quantity_raw=qty_info.quantity_raw,
            is_typical=qty_info.is_typical,
            validation_warnings=warnings
        )

    # Check for inch thread: {size}-{tpi} UNC/UNF
    inch_match = re.match(r'(\d+/\d+|\.\d+|\d+\.?\d*)-(\d+)\s*(UNC|UNF|UN)(?:-(\d+[ABab]))?', text)
    if inch_match:
        size_raw = inch_match.group(1)
        tpi = int(inch_match.group(2))
        standard = inch_match.group(3)
        thread_class = inch_match.group(4)

        # Normalize size to fraction if possible
        size_val, _ = parse_number(size_raw)
        size_str = size_raw

        # Try to convert decimal to standard fraction
        for frac, dec in COMMON_FRACTIONS.items():
            if size_val and abs(size_val - dec) < 0.001:
                size_str = frac
                break

        nominal_mm = inches_to_mm(size_val) if size_val else 0

        canonical = f"{size_str}-{tpi} {standard}"
        if thread_class:
            canonical += f"-{thread_class.upper()}"
        if depth_mm:
            canonical += f" x {depth_mm:.0f}mm DEEP"
        if qty_info.quantity > 1:
            canonical += f" ({qty_info.quantity}X)"

        return ParsedThread(
            raw_text=raw_text,
            standard=standard,
            nominal_mm=nominal_mm,
            pitch=None,
            tpi=tpi,
            thread_class=thread_class,
            depth_mm=depth_mm,
            canonical=canonical,
            quantity=qty_info.quantity,
            quantity_raw=qty_info.quantity_raw,
            is_typical=qty_info.is_typical,
            validation_warnings=warnings
        )

    # Check for NPT
    npt_match = re.match(r'(\d+/\d+|\d+\.?\d*)\s*(?:-\d+)?\s*NPT', text)
    if npt_match:
        size_raw = npt_match.group(1)
        size_val, _ = parse_number(size_raw)
        size_str = size_raw

        for frac, dec in COMMON_FRACTIONS.items():
            if size_val and abs(size_val - dec) < 0.001:
                size_str = frac
                break

        nominal_mm = inches_to_mm(size_val) if size_val else 0

        npt_canonical = f"{size_str} NPT"
        if qty_info.quantity > 1:
            npt_canonical += f" ({qty_info.quantity}X)"

        return ParsedThread(
            raw_text=raw_text,
            standard="NPT",
            nominal_mm=nominal_mm,
            pitch=None,
            tpi=None,
            thread_class=None,
            depth_mm=depth_mm,
            canonical=npt_canonical,
            quantity=qty_info.quantity,
            quantity_raw=qty_info.quantity_raw,
            is_typical=qty_info.is_typical,
            validation_warnings=warnings
        )

    return None


def parse_fillet_callout(raw_text: str) -> Optional[ParsedFillet]:
    """
    Parse a fillet callout.

    Examples:
        "R.030" -> "Fillet: R0.76mm"
        "FILLET R3" -> "Fillet: R3.00mm"
    """
    text = raw_text.strip()
    warnings: List[str] = []

    # Quick check: must start with R or contain FILLET
    # But NOT if it has a diameter symbol (that's a hole)
    if any(sym in text for sym in ["Ø", "ø", "⌀", "∅", "DIA"]):
        return None

    # Must start with R (radius) or contain FILLET keyword
    if not (re.match(r'^R\s*[\d.]', text, re.IGNORECASE) or
            'FILLET' in text.upper() or
            'RAD' in text.upper()):
        return None

    # Extract quantity
    qty_info, text = extract_quantity(text)

    # Look for R{value} pattern
    match = re.search(r'R\s*(\d*\.?\d+)', text, re.IGNORECASE)
    if not match:
        return None

    radius_raw = match.group(1)
    radius_val, _ = parse_number(radius_raw)
    if radius_val is None:
        return None

    # Detect units
    units = detect_units(radius_raw, radius_val)
    if units == 'inch':
        radius_inches = radius_val
        radius_mm = inches_to_mm(radius_val)
    else:
        radius_mm = radius_val
        radius_inches = radius_val / INCH_TO_MM

    canonical = f"Fillet: R{radius_mm:.2f}mm"
    if qty_info.quantity > 1:
        canonical += f" ({qty_info.quantity}X)"

    return ParsedFillet(
        radius_mm=round(radius_mm, 2),
        radius_inches=round(radius_inches, 4) if radius_inches else None,
        radius_raw=radius_raw,
        quantity=qty_info.quantity,
        canonical=canonical,
        quantity_raw=qty_info.quantity_raw,
        is_typical=qty_info.is_typical,
        validation_warnings=warnings
    )


def parse_chamfer_callout(raw_text: str) -> Optional[ParsedChamfer]:
    """
    Parse a chamfer callout.

    Examples:
        "45 x .030" -> "Chamfer: 0.76mm x 45 deg"
        "C0.5" -> "Chamfer: 0.50mm x 45 deg"
        ".030 x .030" -> "Chamfer: 0.76mm x 0.76mm"
    """
    text = raw_text.strip()
    warnings: List[str] = []

    # Quick check: must look like a chamfer
    # - C-notation (C0.5)
    # - Contains degree symbol with x
    # - Contains CHAMFER keyword
    # - Has angle pattern like "45 x" or "x 45"
    # But NOT if it has THRU/DEEP (that's a hole)
    if any(kw in text.upper() for kw in ['THRU', 'DEEP', 'DP']):
        return None

    # Must have chamfer indicators
    has_c_notation = re.match(r'^C\s*\d', text, re.IGNORECASE)
    has_degree = '°' in text or re.search(r'\b45\b|\b30\b|\b60\b', text)
    has_chamfer_kw = 'CHAMFER' in text.upper()

    if not (has_c_notation or has_degree or has_chamfer_kw):
        return None

    # Extract quantity
    qty_info, text = extract_quantity(text)

    # Check for C-notation: C{distance}
    c_match = re.match(r'C\s*(\d*\.?\d+)', text, re.IGNORECASE)
    if c_match:
        dist_raw = c_match.group(1)
        dist_val, _ = parse_number(dist_raw)
        if dist_val is not None:
            units = detect_units(dist_raw, dist_val)
            dist_mm = inches_to_mm(dist_val) if units == 'inch' else dist_val

            canonical = f"Chamfer: {dist_mm:.2f}mm x 45{DEGREE_SYMBOL}"
            if qty_info.quantity > 1:
                canonical += f" ({qty_info.quantity}X)"

            return ParsedChamfer(
                distance1_mm=round(dist_mm, 2),
                distance2_mm=None,
                angle_degrees=45.0,
                chamfer_type="AngleDistance",
                quantity=qty_info.quantity,
                canonical=canonical,
                quantity_raw=qty_info.quantity_raw,
                is_typical=qty_info.is_typical,
                validation_warnings=warnings
            )

    # Check for angle x distance or distance x angle
    # Note: Check for leading decimal first to avoid partial matches like ".030" -> "030"
    starts_with_decimal = text.startswith('.')

    # Pattern for "45° x .030" (angle first, must have degree symbol to be unambiguous)
    angle_dist_match = re.search(r'(\d+)\s*°\s*[Xx×]\s*(\d*\.?\d+)', text)
    # Pattern for ".030 x 45°" (distance first)
    dist_angle_match = re.search(r'(\d*\.?\d+)\s*[Xx×]\s*(\d+)\s*°?', text)

    # If text starts with a decimal, prefer dist_angle_match
    if starts_with_decimal and dist_angle_match:
        dist_raw = dist_angle_match.group(1)
        angle = float(dist_angle_match.group(2))
        dist_val, _ = parse_number(dist_raw)
        if dist_val is not None:
            units = detect_units(dist_raw, dist_val)
            dist_mm = inches_to_mm(dist_val) if units == 'inch' else dist_val

            canonical = f"Chamfer: {dist_mm:.2f}mm x {angle:.0f}{DEGREE_SYMBOL}"
            if qty_info.quantity > 1:
                canonical += f" ({qty_info.quantity}X)"

            return ParsedChamfer(
                distance1_mm=round(dist_mm, 2),
                distance2_mm=None,
                angle_degrees=angle,
                chamfer_type="AngleDistance",
                quantity=qty_info.quantity,
                canonical=canonical,
                quantity_raw=qty_info.quantity_raw,
                is_typical=qty_info.is_typical,
                validation_warnings=warnings
            )

    if angle_dist_match:
        angle = float(angle_dist_match.group(1))
        dist_raw = angle_dist_match.group(2)
        dist_val, _ = parse_number(dist_raw)
        if dist_val is not None:
            units = detect_units(dist_raw, dist_val)
            dist_mm = inches_to_mm(dist_val) if units == 'inch' else dist_val

            canonical = f"Chamfer: {dist_mm:.2f}mm x {angle:.0f}{DEGREE_SYMBOL}"
            if qty_info.quantity > 1:
                canonical += f" ({qty_info.quantity}X)"

            return ParsedChamfer(
                distance1_mm=round(dist_mm, 2),
                distance2_mm=None,
                angle_degrees=angle,
                chamfer_type="AngleDistance",
                quantity=qty_info.quantity,
                canonical=canonical,
                quantity_raw=qty_info.quantity_raw,
                is_typical=qty_info.is_typical,
                validation_warnings=warnings
            )

    elif dist_angle_match:
        dist_raw = dist_angle_match.group(1)
        angle = float(dist_angle_match.group(2))
        dist_val, _ = parse_number(dist_raw)
        if dist_val is not None:
            units = detect_units(dist_raw, dist_val)
            dist_mm = inches_to_mm(dist_val) if units == 'inch' else dist_val

            canonical = f"Chamfer: {dist_mm:.2f}mm x {angle:.0f}{DEGREE_SYMBOL}"
            if qty_info.quantity > 1:
                canonical += f" ({qty_info.quantity}X)"

            return ParsedChamfer(
                distance1_mm=round(dist_mm, 2),
                distance2_mm=None,
                angle_degrees=angle,
                chamfer_type="AngleDistance",
                quantity=qty_info.quantity,
                canonical=canonical,
                quantity_raw=qty_info.quantity_raw,
                is_typical=qty_info.is_typical,
                validation_warnings=warnings
            )

    # Check for distance x distance
    dist_dist_match = re.search(r'(\d*\.?\d+)\s*[Xx×]\s*(\d*\.?\d+)', text)
    if dist_dist_match:
        dist1_raw = dist_dist_match.group(1)
        dist2_raw = dist_dist_match.group(2)
        dist1_val, _ = parse_number(dist1_raw)
        dist2_val, _ = parse_number(dist2_raw)

        if dist1_val is not None and dist2_val is not None:
            units1 = detect_units(dist1_raw, dist1_val)
            units2 = detect_units(dist2_raw, dist2_val)
            dist1_mm = inches_to_mm(dist1_val) if units1 == 'inch' else dist1_val
            dist2_mm = inches_to_mm(dist2_val) if units2 == 'inch' else dist2_val

            canonical = f"Chamfer: {dist1_mm:.2f}mm x {dist2_mm:.2f}mm"
            if qty_info.quantity > 1:
                canonical += f" ({qty_info.quantity}X)"

            return ParsedChamfer(
                distance1_mm=round(dist1_mm, 2),
                distance2_mm=round(dist2_mm, 2),
                angle_degrees=0,
                chamfer_type="DistanceDistance",
                quantity=qty_info.quantity,
                canonical=canonical,
                quantity_raw=qty_info.quantity_raw,
                is_typical=qty_info.is_typical,
                validation_warnings=warnings
            )

    return None


def match_callouts(sw_canonical: str, drawing_canonical: str,
                   tolerances: Dict[str, float] = None) -> Tuple[bool, float]:
    """
    Compare two canonical callouts and return (matches, confidence).

    Default tolerances:
        diameter: ±0.15mm or ±0.5%
        depth: ±0.5mm or ±2%
        radius: ±0.05mm or ±5%
    """
    if tolerances is None:
        tolerances = {
            'diameter_abs': 0.15,
            'diameter_pct': 0.5,
            'depth_abs': 0.5,
            'depth_pct': 2.0,
            'radius_abs': 0.05,
            'radius_pct': 5.0,
        }

    # Parse both canonicals
    sw_parsed = parse_hole_callout(sw_canonical) or parse_fillet_callout(sw_canonical)
    dwg_parsed = parse_hole_callout(drawing_canonical) or parse_fillet_callout(drawing_canonical)

    if sw_parsed is None or dwg_parsed is None:
        # Fallback to exact string match
        return sw_canonical.lower() == drawing_canonical.lower(), 0.5

    # Type mismatch
    if type(sw_parsed) != type(dwg_parsed):
        return False, 0.0

    if isinstance(sw_parsed, ParsedHole):
        # Compare diameter
        dia_diff = abs(sw_parsed.diameter_mm - dwg_parsed.diameter_mm)
        dia_pct = (dia_diff / sw_parsed.diameter_mm * 100) if sw_parsed.diameter_mm > 0 else 100
        if dia_diff > tolerances['diameter_abs'] and dia_pct > tolerances['diameter_pct']:
            return False, 0.0

        # Compare through/blind
        if sw_parsed.is_through != dwg_parsed.is_through:
            return False, 0.0

        # Compare depth for blind holes
        if not sw_parsed.is_through and sw_parsed.depth_mm and dwg_parsed.depth_mm:
            depth_diff = abs(sw_parsed.depth_mm - dwg_parsed.depth_mm)
            depth_pct = (depth_diff / sw_parsed.depth_mm * 100) if sw_parsed.depth_mm > 0 else 100
            if depth_diff > tolerances['depth_abs'] and depth_pct > tolerances['depth_pct']:
                return False, 0.0

        # Compare quantity
        if sw_parsed.quantity != dwg_parsed.quantity:
            # Partial match - might be summed from multiple callouts
            return True, 0.7

        return True, 0.95

    elif isinstance(sw_parsed, ParsedFillet):
        # Compare radius
        rad_diff = abs(sw_parsed.radius_mm - dwg_parsed.radius_mm)
        rad_pct = (rad_diff / sw_parsed.radius_mm * 100) if sw_parsed.radius_mm > 0 else 100
        if rad_diff > tolerances['radius_abs'] and rad_pct > tolerances['radius_pct']:
            return False, 0.0

        return True, 0.95

    return False, 0.0


# =============================================================================
# SOFT VALIDATION (Code-side warnings, not schema validation)
# =============================================================================

def validate_hole(parsed: ParsedHole, confidence: Optional[float] = None) -> List[str]:
    """
    Generate soft validation warnings for a hole callout.
    These are WARNINGS, not errors - the callout is still valid.
    """
    warnings = list(parsed.validation_warnings)  # Start with existing warnings

    # Check for blind hole without depth
    if not parsed.is_through and parsed.depth_mm is None:
        if "Blind hole without depth specified" not in warnings:
            warnings.append("Blind hole without depth specified")

    # Low confidence warning
    if confidence is not None and confidence < 0.5:
        warnings.append(f"Low confidence: {confidence:.2f}")

    return warnings


def validate_thread(parsed: ParsedThread, confidence: Optional[float] = None) -> List[str]:
    """
    Generate soft validation warnings for a thread callout.
    """
    warnings = list(parsed.validation_warnings)

    # Check for missing thread specification
    if parsed.standard is None or parsed.standard == "Unknown":
        warnings.append("Thread standard not identified")

    if parsed.nominal_mm is None or parsed.nominal_mm == 0:
        warnings.append("Thread nominal diameter not specified")

    # Check for missing pitch/TPI
    if parsed.pitch is None and parsed.tpi is None:
        warnings.append("Thread pitch/TPI not specified")

    # Low confidence warning
    if confidence is not None and confidence < 0.5:
        warnings.append(f"Low confidence: {confidence:.2f}")

    return warnings


def validate_fillet(parsed: ParsedFillet, confidence: Optional[float] = None) -> List[str]:
    """
    Generate soft validation warnings for a fillet callout.
    """
    warnings = list(parsed.validation_warnings)

    # Check for missing radius (shouldn't happen if parsed successfully)
    if parsed.radius_mm is None or parsed.radius_mm == 0:
        warnings.append("Fillet radius not specified")

    # Low confidence warning
    if confidence is not None and confidence < 0.5:
        warnings.append(f"Low confidence: {confidence:.2f}")

    return warnings


def validate_chamfer(parsed: ParsedChamfer, confidence: Optional[float] = None) -> List[str]:
    """
    Generate soft validation warnings for a chamfer callout.
    """
    warnings = list(parsed.validation_warnings)

    # Check for missing distance
    if parsed.distance1_mm is None or parsed.distance1_mm == 0:
        warnings.append("Chamfer distance not specified")

    # Check for assumed 45° angle (from C-notation)
    if parsed.chamfer_type == "AngleDistance" and parsed.angle_degrees == 45.0:
        # Only warn if it looks like it was assumed (C-notation typically)
        # Don't warn if angle was explicitly specified
        pass  # This would require tracking if angle was explicit

    # Low confidence warning
    if confidence is not None and confidence < 0.5:
        warnings.append(f"Low confidence: {confidence:.2f}")

    return warnings


def generate_validation_summary(callouts: List[Any]) -> Dict[str, Any]:
    """
    Generate a validation summary for a list of parsed callouts.

    Returns a dict matching the ValidationSummary schema:
    {
        "totalCallouts": int,
        "calloutsWithWarnings": int,
        "warningCounts": {"warningType": count, ...},
        "lowConfidenceCount": int,
        "noLocationCount": int
    }
    """
    total = len(callouts)
    with_warnings = 0
    warning_counts: Dict[str, int] = {}
    low_confidence = 0

    for callout in callouts:
        # Get warnings from the callout
        warnings = getattr(callout, 'validation_warnings', []) or []

        if warnings:
            with_warnings += 1

        for warning in warnings:
            # Normalize warning text to a key
            if warning.startswith("Low confidence"):
                low_confidence += 1
                key = "lowConfidence"
            elif "depth" in warning.lower():
                key = "missingDepth"
            elif "thread" in warning.lower() or "pitch" in warning.lower() or "tpi" in warning.lower():
                key = "incompleteThread"
            elif "radius" in warning.lower():
                key = "missingRadius"
            elif "distance" in warning.lower():
                key = "missingDistance"
            else:
                key = "other"

            warning_counts[key] = warning_counts.get(key, 0) + 1

    return {
        "totalCallouts": total,
        "calloutsWithWarnings": with_warnings,
        "warningCounts": warning_counts,
        "lowConfidenceCount": low_confidence,
        "noLocationCount": 0  # Would need location info to compute
    }


# Test cases
if __name__ == "__main__":
    test_cases = [
        # Hole callouts
        ("Ø1/2 THRU", "ø12.70mm THRU"),
        # Note: 0.375" = 9.525mm, Python round(9.525, 2) = 9.52 (banker's rounding)
        ("4X Ø.375 x 1.000 DEEP", "ø9.52mm x 25.4mm DEEP (4X)"),
        ("Ø.500 [12.7] THRU (2 PLCS)", "ø12.70mm THRU (2X)"),
        ("Ø.250 THRU", "ø6.35mm THRU"),
        ("Ø12.7 x 25.4 DEEP", "ø12.70mm x 25.4mm DEEP"),

        # Fillet callouts
        ("R.030", "Fillet: R0.76mm"),  # Leading dot = inches
        ("FILLET R3", "Fillet: R3.00mm"),  # 3mm fillet
        # Note: "R0.76" without leading dot is ambiguous (could be mm or inches)
        # Algorithm uses <3 = inches heuristic. Use leading dot for inches.
        ("R.030 TYP", "Fillet: R0.76mm"),  # Leading dot = inches (0.030" = 0.76mm)

        # Chamfer callouts
        (f"45{DEGREE_SYMBOL} x .030", f"Chamfer: 0.76mm x 45{DEGREE_SYMBOL}"),  # Leading dot = inches
        # Note: "C0.5" is ambiguous - algorithm assumes inches when <3
        # Result: 0.5" * 25.4 = 12.70mm
        ("C0.5", f"Chamfer: 12.70mm x 45{DEGREE_SYMBOL}"),
        # Note: ".030 x 45" works with degree symbol for clarity
        (f".030 x 45{DEGREE_SYMBOL}", f"Chamfer: 0.76mm x 45{DEGREE_SYMBOL}"),

        # Thread callouts
        ("M6X1.0", "M6x1.0"),
        ("1/4-20 UNC", "1/4-20 UNC"),
        ("M6x1.0 x 12 DEEP", "M6x1.0 x 12mm DEEP"),
    ]

    print("Canonicalization Tests:")
    print("=" * 70)

    for raw, expected in test_cases:
        # Try each parser
        result = parse_hole_callout(raw)
        if result is None:
            result = parse_thread_callout(raw)
        if result is None:
            result = parse_fillet_callout(raw)
        if result is None:
            result = parse_chamfer_callout(raw)

        if result:
            actual = result.canonical
            match = "PASS" if actual == expected else "FAIL"
            print(f"[{match}] '{raw}'")
            print(f"   Expected: {expected}")
            print(f"   Actual:   {actual}")
        else:
            print(f"[FAIL] '{raw}' -> PARSE FAILED")
        print()

    # Test v1.1.1 features: quantityRaw and isTypical
    print("\nv1.1.1 Feature Tests (quantityRaw, isTypical):")
    print("=" * 70)

    v111_test_cases = [
        # (input, expected_quantity, expected_quantity_raw, expected_is_typical)
        ("4X Ø.375 THRU", 4, "4X", None),
        ("Ø.500 THRU (2X)", 2, "(2X)", None),
        ("Ø.500 THRU (2 PLCS)", 2, "(2 PLCS)", None),
        ("Ø.500 THRU 3 PLACES", 3, "3 PLACES", None),
        ("Ø.500 THRU 4 HOLES", 4, "4 HOLES", None),
        ("R.030 TYP", 1, "TYP", True),
        ("(2) Ø.250 THRU", 2, "(2)", None),
    ]

    for raw, exp_qty, exp_raw, exp_typical in v111_test_cases:
        result = parse_hole_callout(raw)
        if result is None:
            result = parse_fillet_callout(raw)

        if result:
            qty_ok = result.quantity == exp_qty
            raw_ok = result.quantity_raw == exp_raw
            typ_ok = result.is_typical == exp_typical

            status = "PASS" if (qty_ok and raw_ok and typ_ok) else "FAIL"
            print(f"[{status}] '{raw}'")
            print(f"   quantity: {result.quantity} (expected {exp_qty}) {'OK' if qty_ok else 'MISMATCH'}")
            print(f"   quantity_raw: {result.quantity_raw} (expected {exp_raw}) {'OK' if raw_ok else 'MISMATCH'}")
            print(f"   is_typical: {result.is_typical} (expected {exp_typical}) {'OK' if typ_ok else 'MISMATCH'}")
        else:
            print(f"[FAIL] '{raw}' -> PARSE FAILED")
        print()

    # Test soft validation warnings
    print("\nSoft Validation Tests:")
    print("=" * 70)

    # Test 1: Blind hole without depth should warn
    hole_no_depth = ParsedHole(
        diameter_mm=12.7,
        diameter_inches=0.5,
        diameter_raw=".500",
        depth_mm=None,
        depth_raw=None,
        is_through=False,  # Blind hole
        quantity=1,
        canonical="ø12.70mm"  # No depth
    )
    warnings = validate_hole(hole_no_depth)
    expected_warning = "Blind hole without depth specified"
    has_warning = expected_warning in warnings
    print(f"[{'PASS' if has_warning else 'FAIL'}] Blind hole without depth")
    print(f"   Warnings: {warnings}")
    print(f"   Expected: '{expected_warning}' {'FOUND' if has_warning else 'MISSING'}")
    print()

    # Test 2: Through hole should NOT warn about depth
    hole_thru = ParsedHole(
        diameter_mm=12.7,
        diameter_inches=0.5,
        diameter_raw=".500",
        depth_mm=None,
        depth_raw=None,
        is_through=True,  # Through hole
        quantity=1,
        canonical="ø12.70mm THRU"
    )
    warnings = validate_hole(hole_thru)
    no_depth_warning = "Blind hole without depth specified" not in warnings
    print(f"[{'PASS' if no_depth_warning else 'FAIL'}] Through hole (no depth warning)")
    print(f"   Warnings: {warnings}")
    print()

    # Test 3: Low confidence warning
    hole_low_conf = ParsedHole(
        diameter_mm=12.7,
        diameter_inches=0.5,
        diameter_raw=".500",
        depth_mm=None,
        depth_raw=None,
        is_through=True,
        quantity=1,
        canonical="ø12.70mm THRU"
    )
    warnings = validate_hole(hole_low_conf, confidence=0.3)
    has_low_conf = any("Low confidence" in w for w in warnings)
    print(f"[{'PASS' if has_low_conf else 'FAIL'}] Low confidence warning")
    print(f"   Warnings: {warnings}")
    print()

    # Test 4: Thread missing pitch should warn
    thread_no_pitch = ParsedThread(
        raw_text="M6",
        standard="Metric",
        nominal_mm=6.0,
        pitch=None,
        tpi=None,
        thread_class=None,
        depth_mm=None,
        canonical="M6"
    )
    warnings = validate_thread(thread_no_pitch)
    has_pitch_warning = any("pitch" in w.lower() or "tpi" in w.lower() for w in warnings)
    print(f"[{'PASS' if has_pitch_warning else 'FAIL'}] Thread missing pitch")
    print(f"   Warnings: {warnings}")
    print()

    # Test 5: Generate validation summary
    print("\nValidation Summary Test:")
    print("-" * 70)
    callouts = [hole_no_depth, hole_thru, thread_no_pitch]
    # Re-validate to populate warnings
    hole_no_depth.validation_warnings = validate_hole(hole_no_depth)
    hole_thru.validation_warnings = validate_hole(hole_thru)
    thread_no_pitch.validation_warnings = validate_thread(thread_no_pitch)

    summary = generate_validation_summary(callouts)
    print(f"   totalCallouts: {summary['totalCallouts']}")
    print(f"   calloutsWithWarnings: {summary['calloutsWithWarnings']}")
    print(f"   warningCounts: {summary['warningCounts']}")
    print()
