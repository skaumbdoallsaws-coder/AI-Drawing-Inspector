"""Approved engineering symbols; 69 entries, 68 distinct code points (Omega twice)."""
import unicodedata

_SYMBOL_CODES = (
    ("Units and math", "00B0 00B1 00D7 00F7 2212 00B5 03A9 00B9 00B2 00B3 00BC 00BD 00BE 2030 2264 2265 2260 2248 2261 221E 221A 2202 222B 2211 2206 2032 2033 00D8 00F8 2116 2044 00AC 2229"),
    ("Greek", "03B1 03B2 03B3 03B4 03B5 03B7 03B8 03BA 03BB 03BC 03BD 03C0 03C1 03C3 03C4 03C6 03C9 0394 03A3 03A6 03A8 03A9"),
    ("Arrows and marks", "2192 2190 2191 2193 2194 2022 00B7 2013 2014 00A7 00B6 00A9 00AE 2122"),
)
SYMBOL_GROUPS = [{"group": group, "symbols": [{"text": chr(int(code, 16)),
    "name": unicodedata.name(chr(int(code, 16)))} for code in codes.split()]} for group, codes in _SYMBOL_CODES]
