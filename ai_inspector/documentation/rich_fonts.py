"""Metric-compatible rich typography. Mirrored in documentation_rich_text_core.js.

Vertical metrics are the Windows canvas fonts' hhea/win values (em), supplied
at the P3a-1 supervisor gate. Advances still come from the PDF built-in programs.
OS/2 script metrics are recorded for reference; the explicit CSS contract uses
SCRIPT_SIZE/SUB_OFFSET/SUP_OFFSET instead. Decorations use Chromium's CSS auto
rules in every schema. No system fonts are read at runtime.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Font:
    canvas: str
    pdf: str
    docx: str
    ascent: float
    descent: float
    script_size: float = .6499
    sub_offset: float = .1382
    sup_offset: float = .4771


_ARIAL = Font("Arial", "Helvetica", "Arial", .9053, .2119)
_TIMES = Font("Times New Roman", "Times", "Times New Roman", .8911, .2163,
              sub_offset=.1431, sup_offset=.4531)
_COURIER = Font("Courier New", "Courier", "Courier New", .8325, .3003,
                sub_offset=.1392, sup_offset=.4224)
FONT_MAP = {"Arial": _ARIAL, "Helvetica": _ARIAL, "Times New Roman": _TIMES, "Courier New": _COURIER}
SCRIPT_SIZE, SUB_OFFSET, SUP_OFFSET = .65, .14, .45


def font(value):
    """Also resolve legacy box fonts, exactly as the existing export family map."""
    if value in FONT_MAP:
        return FONT_MAP[value]
    name = str(value or "Arial").casefold()
    return _COURIER if "courier" in name else _TIMES if "times" in name or "georgia" in name else _ARIAL


def rounded_metrics(size, family):
    """Chromium at device scale 1: SimpleFontData rounds the font's ascent and descent to whole pixels."""
    metrics = font(family)
    return math.floor(metrics.ascent * size + .5), math.floor(metrics.descent * size + .5)


def line_box(size, family, multiplier, *, canvas_rounding=False):
    """(above, below) the baseline of one inline box with a unitless line-height (CSS half-leading).

    canvas_rounding reproduces Blink at device scale 1, for measuring the real canvas only: whole-pixel ascent and
    descent, the line height in LayoutUnits (1/64 px, truncated), and the ascent-side half-leading floored to a whole
    pixel (CalculateLeadingSpace). Exports never round: Blink rounds in device pixels, so any rounding fits one display
    scale only, while the exact metrics stay within about a pixel of every scale.
    """
    metrics = font(family)
    if canvas_rounding:
        ascent, descent = rounded_metrics(size, family)
        height = math.floor(multiplier * size * 64) / 64
        above = ascent + math.floor((height - ascent - descent) / 2)
        return above, height - above
    difference = (metrics.ascent - metrics.descent) * size
    return (multiplier * size + difference) / 2, (multiplier * size - difference) / 2


def decoration(family, size, kind):
    """Chromium 141 CSS auto: continuous strokes of size / 10 in every schema.

    Strike is centred ascent / 3 above the baseline; underline is centred one
    thickness below. Chromium snaps to device pixels; exports retain exact units.
    """
    thickness = size / 10
    return (-font(family).ascent * size / 3 if kind == "strike" else thickness), thickness


# Mirrored in documentation_rich_text_core.js; styles add to the box's emphasis.
NAMED_STYLES = {
    "title": {"scale": 2.25, "bold": True},
    "caption": {"scale": .85, "italic": True, "color": "#5b6670"},
    "note": {"scale": .9, "color": "#5b6670"},
}
