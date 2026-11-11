"""Metric-compatible rich typography. Mirrored in documentation_rich_text_core.js.

Vertical metrics are the Windows canvas fonts' hhea/win values (em), supplied
at the P3a-1 supervisor gate. Advances still come from the PDF built-in programs.
OS/2 script metrics are recorded for reference; the explicit CSS contract uses
SCRIPT_SIZE/SUB_OFFSET/SUP_OFFSET instead. The decoration thicknesses are the
fonts' own; their positions follow Chromium, which ignores the fonts' underline
and strikeout positions (decoration). No system fonts are read at runtime.
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
    underline_regular: float
    underline_bold: float
    strike_size: float = .0498
    script_size: float = .6499
    sub_offset: float = .1382
    sup_offset: float = .4771


_ARIAL = Font("Arial", "Helvetica", "Arial", .9053, .2119, .0732, .1050)
_TIMES = Font("Times New Roman", "Times", "Times New Roman", .8911, .2163, .0488, .0952,
              sub_offset=.1431, sup_offset=.4531)
_COURIER = Font("Courier New", "Courier", "Courier New", .8325, .3003, .0410, .1001,
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


def decoration(family, size, bold, kind, *, auto=False):
    """(Offset of the stroke's centre from the baseline, down positive; stroke thickness), in points.

    As Chromium 141 draws text-decoration (measured at the P3a-1 gate: three fonts, 12 to 100 px, regular and bold):
    - line-through is centred a third of the ascent above the baseline;
    - an underline's top edge lies half its thickness below the baseline (Blink's auto offset), so its centre lies
      one thickness below.
    The fonts' own underline and strikeout positions are not used. Chromium also puts both on whole device pixels
    (rounded ascent, thickness and gap; a gap of at least 1 px); the PDF keeps the exact values, within a pixel.
    Schema-2 CSS sets the fonts' thicknesses; auto is CSS text-decoration-thickness: auto, which schema-1 and plain
    text keep on the canvas: a tenth of the size, whatever the font or weight.
    """
    metrics = font(family)
    if kind == "strike":
        return -metrics.ascent / 3 * size, metrics.strike_size * size
    thickness = size / 10 if auto else (metrics.underline_bold if bold else metrics.underline_regular) * size
    return thickness, thickness
