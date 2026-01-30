"""
Regex patterns for parsing engineering drawing callouts.

These patterns are used by both OCR parser and Qwen parser to extract
structured data from text. All patterns are case-insensitive when used.

Diameter symbols handled:
- Ø (U+00D8) - Latin capital letter O with stroke
- ∅ (U+2205) - Empty set
- ⌀ (U+2300) - Diameter sign
- φ (U+03C6) - Greek small letter phi
- O, o - ASCII fallback

Usage:
    import re
    from ai_inspector.extractors.patterns import PATTERNS

    text = "M6x1.0 THRU"
    match = re.search(PATTERNS['metric_thread'], text, re.IGNORECASE)
    if match:
        diameter = float(match.group(1))  # 6.0
        pitch = float(match.group(2))     # 1.0
"""

# Common diameter symbol character class
# Matches: Ø ∅ ⌀ φ O o
DIA_SYMBOLS = r"[oO\u00d8\u2205\u03c6\u2300]"

PATTERNS = {
    # === THREADS ===

    # Metric threads: M6x1.0, M10X1.5, M12x1.75
    # Group 1: nominal diameter (mm)
    # Group 2: pitch (mm)
    "metric_thread": r"M(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)",

    # Imperial threads: 1/2-13, 3/8-16, 1/4-20
    # Group 1: fraction (e.g., "1/2")
    # Group 2: TPI (threads per inch)
    "imperial_thread": r"(\d+/\d+)\s*[-]\s*(\d+)",

    # UNC/UNF threads: .500-13 UNC, .375-16 UNF
    # Group 1: decimal diameter (with optional leading dot)
    # Group 2: TPI
    # Group 3: thread class (UNC/UNF)
    "unified_thread": r"(\.?\d+\.?\d*)\s*-\s*(\d+)\s*(UNC|UNF)",

    # === HOLES ===

    # Through holes: Ø.500 THRU, ∅12.7 THRU ALL
    # Group 1: diameter (with optional leading dot)
    "thru_hole": rf"{DIA_SYMBOLS}?\s*(\.?\d+\.?\d*)\s*(?:THRU|THR)",

    # Blind holes: Ø.500 x .750 DEEP, ∅10 X 15 DP
    # Group 1: diameter (with optional leading dot)
    # Group 2: depth (with optional leading dot)
    "blind_hole": rf"{DIA_SYMBOLS}?\s*(\.?\d+\.?\d*)\s*[xX]\s*(\.?\d+\.?\d*)\s*(?:DEEP|DP)",

    # Counterbore: CBORE Ø.750, C'BORE ∅19
    # Group 1: diameter (with optional leading dot)
    "counterbore": rf"(?:CBORE|C'BORE|C-BORE)\s*{DIA_SYMBOLS}?\s*(\.?\d+\.?\d*)",

    # Countersink: CSK Ø.500, CSINK 82°
    # Group 1: diameter or angle (with optional leading dot)
    "countersink": rf"(?:CSK|CSINK|C-SINK)\s*{DIA_SYMBOLS}?\s*(\.?\d+\.?\d*)",

    # Standalone diameter (no THRU/DEEP qualifier)
    # Group 1: diameter value (with optional leading dot)
    "diameter": rf"{DIA_SYMBOLS}\s*(\.?\d+\.?\d*)",

    # Major/Minor diameter (casting drawings): MAJOR Ø1.500/1.495
    # Group 1: primary value
    # Group 2: tolerance value (optional)
    "major_minor_dia": rf"(?:MAJOR|MINOR|MAJ|MIN)\s*{DIA_SYMBOLS}?\s*(\.?\d+\.?\d+)(?:\s*/\s*(\.?\d+\.?\d+))?",

    # === FEATURES ===

    # Fillets: R.125, R3.0, R 0.5
    # Group 1: radius value (with optional leading dot)
    # Negative lookbehind prevents matching "THRU" etc.
    "fillet": r"(?<![A-Za-z])R\s*(\.?\d+\.?\d*)(?!\w)",

    # Chamfers: .030 x 45°, 1.0 X 45
    # Group 1: distance (with optional leading dot)
    "chamfer": r"(\.?\d+\.?\d*)\s*[xX]\s*45\s*[\u00b0]?",

    # === QUANTITIES ===

    # Quantity prefix: 4X, 2x, (3X)
    # Group 1: quantity number
    "quantity_prefix": r"[\(]?(\d+)\s*[xX][\)]?\s*",

    # Quantity suffix: (4X), (2 PLACES)
    # Group 1: quantity number
    "quantity_suffix": r"\((\d+)\s*[xX]?\s*(?:PLACES?)?\)",

    # === SPECIAL ===

    # GD&T position tolerance: ⌖ Ø.010 (M) A B C
    # Group 1: tolerance value (with optional leading dot)
    "position_tolerance": rf"[⌖\u2316]?\s*{DIA_SYMBOLS}?\s*(\.?\d+\.?\d*)\s*\(?[MLSmlsⓂⓁⓈ]?\)?",

    # Surface finish: 63▽, 125 Ra, 32 RMS
    # Group 1: roughness value
    "surface_finish": r"(\d+)\s*(?:[\u25bd\u25b3]|Ra|RMS|rms)",
}


# Compiled patterns for performance (optional usage)
import re

COMPILED_PATTERNS = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in PATTERNS.items()
}
