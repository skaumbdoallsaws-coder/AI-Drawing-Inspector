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

    # Degree
    '\u02DA': '\u00B0',
    '\u00BA': '\u00B0',

    # Counterbore / Countersink symbols
    '\u2334': '\u2334',      # Counterbore (canonical)
    '\u2335': '\u2335',      # Countersink (canonical)

    # Dash variants
    '\u2013': '-',       # En dash
    '\u2014': '-',       # Em dash
    '\u2212': '-',       # Minus sign
}

# Regex-based replacements (applied after symbol map)
REGEX_REPLACEMENTS: List[Tuple[str, str]] = [
    # Collapse multiple spaces to single space
    (r'[ \t]+', ' '),

    # Normalize "2 X" or "2x" or "2 x" to "2X" (quantity prefix)
    (r'(\d+)\s*[xX\u00D7]\s+', r'\1X '),

    # Remove leading/trailing whitespace per line
    (r'^\s+|\s+$', ''),
]


def canonicalize(text: str) -> str:
    """
    Canonicalize OCR text for consistent downstream parsing.

    Steps:
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

    # Step 1: Symbol map replacements
    for old, new in SYMBOL_MAP.items():
        result = result.replace(old, new)

    # Step 2: Regex replacements
    for pattern, replacement in REGEX_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.MULTILINE)

    # Step 3: Final strip
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
