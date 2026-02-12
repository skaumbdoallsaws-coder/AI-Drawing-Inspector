"""Canonicalize OCR text for consistent parsing.

Normalizes symbols and whitespace BEFORE regex parsing and CER/WER evaluation,
so downstream patterns only need to handle canonical forms.
"""

import re
from typing import Dict, List, Tuple


# Symbol normalization map: variants -> canonical form
SYMBOL_MAP: Dict[str, str] = {
    # Diameter
    'Ø': '\u2300',
    'ø': '\u2300',
    '\u2205': '\u2300',
    'O/': '\u2300',     # Common OCR misread
    '0/': '\u2300',     # Common OCR misread
    '\u03c6': '\u2300',  # Greek phi
    '\u03d5': '\u2300',  # Variant phi
    '\u03b8': '\u2300',  # Theta (common OCR confusion)
    '\u00d8': '\u2300',
    '\u00f8': '\u2300',
    # UTF-8 mojibake that appears in Windows console/log paths
    '\u00e2\u0152\u20ac': '\u2300',  # "âŒ€"
    '\u00c3\u02dc': '\u2300',        # "Ã˜"
    '\u00c3\u00b8': '\u2300',        # "Ã¸"

    # Inch marks
    '\u2033': '"',  # Double prime
    '\u2036': '"',
    '\u02DD': '"',

    # Multiplication
    '\u00D7': 'x',
    '\u2715': 'x',
    '\u2716': 'x',
    '\u2A2F': 'x',

    # Plus-minus
    '+/-': '\u00B1',
    '+/\u2212': '\u00B1',
    '\u00c2\u00b1': '\u00B1',  # "Â±"

    # Degree
    '\u02DA': '\u00B0',
    '\u00BA': '\u00B0',
    '\u00c2\u00b0': '\u00B0',  # "Â°"

    # Counterbore / Countersink symbols
    '\u2334': '\u2334',      # Counterbore (canonical)
    '\u2335': '\u2335',      # Countersink (canonical)

    # Dash variants
    '\u2013': '-',       # En dash
    '\u2014': '-',       # Em dash
    '\u2212': '-',       # Minus sign
}

# LaTeX notation replacements (LightOnOCR-2 outputs LaTeX for math symbols)
LATEX_REPLACEMENTS: List[Tuple[str, str]] = [
    # Strip double dollar-sign wrappers first: $$...$$ -> ...
    (r'\$\$([^$]*)\$\$', r'\1'),
    # Strip single dollar-sign wrappers: $...$ -> ...
    (r'\$([^$]*)\$', r'\1'),

    # Diameter symbol variants -> ⌀ (U+2300)
    # \phi or \Phi -> ⌀
    (r'\\[Pp]hi', '\u2300'),
    # \varphi -> ⌀ (variant phi)
    (r'\\varphi', '\u2300'),
    # \varnothing -> ⌀ (empty set symbol, often misread as diameter)
    (r'\\varnothing', '\u2300'),
    (r'\\oslash', '\u2300'),
    (r'\\emptyset', '\u2300'),
    # \theta -> ⌀ (OCR misreads diameter as theta in engineering drawings)
    (r'\\theta', '\u2300'),
    # \mathcal{O} or \mathcal{o} -> ⌀
    (r'\\mathcal\{[Oo]\}', '\u2300'),
    # \diameter -> ⌀
    (r'\\diameter', '\u2300'),

    # Plus-minus
    # \pm -> ±
    (r'\\pm', '±'),

    # Degree symbol variants
    # \degree or \deg -> °
    (r'\\deg(?:ree)?', '°'),
    # \circ -> °
    (r'\\circ', '°'),

    # Multiplication
    # \times -> x
    (r'\\times', 'x'),

    # Subscript/superscript notation
    # Subscript: _{...} -> just the content (e.g., _{.75} -> .75)
    (r'_\{([^}]*)\}', r'\1'),
    # Superscript: ^{...} -> just the content
    (r'\^\{([^}]*)\}', r'\1'),

    # LaTeX garbage removal (OCR hallucinations)
    # \frac{a}{b} -> a/b (supports drill fractions like 33/64)
    (r'\\frac\{\s*([0-9]+)\s*\}\{\s*([0-9]+)\s*\}', r'\1/\2'),
    # \left( or \left[ or \left\{ -> remove
    (r'\\left[\(\[\{]', ''),
    # \right) or \right] or \right\} -> remove
    (r'\\right[\)\]\}]', ''),
    # \int -> remove (integral symbol, OCR hallucination)
    (r'\\int', ''),
    # \quad or \qquad -> remove (spacing commands)
    (r'\\qquad|\\quad', ''),
    # \% -> % (escaped percent)
    (r'\\%', '%'),
    # Generic backslash command cleanup: \text{...} -> ...
    (r'\\text\{([^}]*)\}', r'\1'),
    # Remove any remaining backslash commands that aren't caught above
    (r'\\[a-zA-Z]+', ''),

    # European comma-as-decimal in numbers: 1,5380 -> 1.5380
    # (only when between digits, no space after comma)
    (r'(\d),(\d)', r'\1.\2'),
]

# Regex-based replacements (applied after symbol map)
REGEX_REPLACEMENTS: List[Tuple[str, str]] = [
    # Collapse multiple spaces to single space
    (r'[ \t]+', ' '),

    # Normalize "2 X" or "2x" or "2 x" to "2X" (quantity prefix)
    (r'(\d+)\s*[xX\u00D7]\s+', r'\1X '),

    # Remove leading/trailing whitespace per line
    (r'^\s+|\s+$', ''),
]


def _repair_missing_leading_decimals(text: str) -> str:
    """
    Repair common OCR misses where a leading decimal point disappears.

    Example:
      "⌀52 THRU"  -> "⌀.52 THRU"
      "⌀125 DRILL" -> "⌀.125 DRILL"

    This is intentionally conservative and only applies when the number is
    directly attached to a diameter symbol and contains 2-3 digits with no dot.
    """

    def repl(match: re.Match[str]) -> str:
        symbol = match.group(1)
        digits = match.group(2)
        return f"{symbol}.{digits}"

    return re.sub(r'([\u2300])\s*(\d{2,3})(?![\d./])', repl, text)


def canonicalize(text: str) -> str:
    """
    Canonicalize OCR text for consistent downstream parsing.

    Steps:
    0. LaTeX cleanup (LightOnOCR-2 outputs LaTeX notation)
    1. Apply symbol map (character-level replacements)
    2. Apply regex-based normalization
    3. Strip leading/trailing whitespace

    Args:
        text: Raw OCR text

    Returns:
        Canonicalized text with normalized symbols and whitespace
    """
    if not text:
        return ""

    result = text

    # Step 0: LaTeX cleanup (LightOnOCR-2 outputs LaTeX notation)
    for pattern, replacement in LATEX_REPLACEMENTS:
        result = re.sub(pattern, replacement, result)

    # Step 1: Symbol map replacements
    for old, new in SYMBOL_MAP.items():
        result = result.replace(old, new)

    # Step 2: Regex replacements
    for pattern, replacement in REGEX_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.MULTILINE)

    # Step 3: Numeric OCR repairs
    result = _repair_missing_leading_decimals(result)

    # Step 4: Final strip
    result = result.strip()

    return result


def canonicalize_lines(lines: List[str]) -> List[str]:
    """
    Canonicalize a list of OCR text lines.

    Args:
        lines: List of raw OCR text lines

    Returns:
        List of canonicalized lines (empty lines removed)
    """
    result = []
    for line in lines:
        canon = canonicalize(line)
        if canon:
            result.append(canon)
    return result
