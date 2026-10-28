"""The inspection sheet as a fillable PDF (US Letter landscape) and the reading of a returned, filled copy.

Pages: a cover with the job fields, the summary and the information still needed; per part a ballooned drawing
page (when the part has a drawing) and its characteristics table; the assembly check; the sign-off. Every blank is
a plain AcroForm field (documentation/form_fields.py), so any PDF reader can fill it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ai_inspector.documentation.form_fields import (
    FormFieldError,
    add_form_fields,
    form_field,
    read_form_fields,
    validate_form_fields,
)

PAGE_WIDTH = 792.0
PAGE_HEIGHT = 612.0
MARGIN = 28.0
CONTENT_TOP = 66.0
CONTENT_BOTTOM = PAGE_HEIGHT - 34.0
KEYWORD_PREFIX = "inspectorpro-inspection-sheet"
COVER_LIST_TOP = 362.0

# DEFAULT_DOCUMENT_THEME (parts_manual/documentation.py).
PRIMARY = (0.027, 0.106, 0.165)
ACCENT = (0.263, 0.71, 0.933)
INK = (0.094, 0.129, 0.165)
MUTED = (0.349, 0.416, 0.463)
RULE = (0.671, 0.729, 0.769)
BAND = (0.91, 0.953, 0.98)
AMBER_TEXT = (0.6, 0.38, 0.0)
FAIL_FILL = (0.992, 0.894, 0.894)
FAIL_TEXT = (0.72, 0.11, 0.11)

_CHARACTERISTIC_COLUMNS = (("#", 26), ("View", 72), ("Characteristic", 238), ("Requirement", 74),
                           ("Tolerance", 58), ("Lower", 44), ("Upper", 44), ("Measured", 66), ("OK", 26),
                           ("Gauge / method", 88))
_FEATURE_COLUMNS = (("#", 26), ("Feature", 150), ("Qty", 30), ("Why it is inspected", 236), ("Requirement", 130),
                    ("Measured", 66), ("OK", 26), ("Gauge / method", 72))
_BOM_COLUMNS = (("Item", 40), ("Part number", 110), ("Description", 396), ("Qty", 50), ("Qty found", 100),
                ("OK", 40))
_LATIN = {"\u2300": "\u00d8", "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"',
          "\u201d": '"', "\u2264": "<=", "\u2265": ">=", "\u2192": "->", "\u2026": "..."}


class InspectionSheetExportError(RuntimeError):
    pass


def _latin(text: Any) -> str:
    """Helvetica (the PDF base font) prints Latin-1; map the usual typography into it."""
    result = str(text if text is not None else "")
    for source, target in _LATIN.items():
        result = result.replace(source, target)
    return result.encode("latin-1", "replace").decode("latin-1")


def _format(value: Optional[float], decimals: int) -> str:
    return "" if value is None else f"{value:.{max(0, min(decimals, 4))}f}"


class _Writer:
    def __init__(self, fitz: Any, document: Mapping[str, Any]):
        self.fitz = fitz
        self.document = document
        self.pdf = fitz.open()
        self.fields: List[Dict[str, Any]] = []
        self.page: Any = None
        self.y = CONTENT_TOP
        self.values = {field["name"]: field for field in document["fields"]}

    # -- primitives ---------------------------------------------------------------------------------------------
    def new_page(self) -> Any:
        self.page = self.pdf.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        document = self.document
        self.line(MARGIN, 40, "INSPECTION SHEET", 9, bold=True, color=PRIMARY)
        self.line(MARGIN + 104, 40, f"{document['assemblyNumber']}  {document['assemblyName']}", 9,
                  max_width=430)
        self.line(PAGE_WIDTH - MARGIN, 40, f"Sheet revision {document['documentRevision'][:12]}", 7,
                  color=MUTED, align="right")
        self.page.draw_line((MARGIN, 48), (PAGE_WIDTH - MARGIN, 48), color=ACCENT, width=1.2)
        self.y = CONTENT_TOP
        return self.page

    def line(self, x: float, baseline: float, text: Any, size: float, *, bold: bool = False,
             color: Tuple[float, float, float] = INK, max_width: Optional[float] = None, align: str = "left") -> None:
        font = "hebo" if bold else "helv"
        text = _latin(text)
        width = self.fitz.get_text_length(text, fontname=font, fontsize=size)
        if max_width is not None and width > max_width:
            while text and self.fitz.get_text_length(text + "...", fontname=font, fontsize=size) > max_width:
                text = text[:-1]
            text = text.rstrip() + "..."
            width = self.fitz.get_text_length(text, fontname=font, fontsize=size)
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        self.page.insert_text((x, baseline), text, fontname=font, fontsize=size, color=color)

    def wrapped(self, rect: Sequence[float], text: Any, size: float, *, bold: bool = False,
                color: Tuple[float, float, float] = INK) -> None:
        """Text in a box: shrink to 6 pt, then shorten by words; never overflows."""
        fitz = self.fitz
        box = fitz.Rect(*rect)
        font = "hebo" if bold else "helv"
        words = _latin(text).split()
        sizes = sorted({max(6.0, size - step) for step in (0, 0.5, 1)}, reverse=True)
        for font_size in sizes:
            count = len(words)
            # Full text at each size; at the smallest size, drop words until it fits.
            while count >= 1:
                body = " ".join(words[:count]) + ("" if count == len(words) else "...")
                shape = self.page.new_shape()
                if shape.insert_textbox(box, body, fontname=font, fontsize=font_size, color=color) >= 0:
                    shape.commit()
                    return
                if font_size != sizes[-1]:
                    break
                count -= 1
        self.line(box.x0, box.y0 + 7, " ".join(words), 6, color=color, max_width=box.width)

    def field(self, name: str, rect: Sequence[float]) -> None:
        definition = self.values[name]
        field = form_field(name, definition["label"], rect, page=self.pdf.page_count - 1, kind=definition["kind"],
                           role=definition["role"], value=definition.get("value"), font_size=8)
        if definition.get("problem"):
            field["problem"] = definition["problem"]  # given but unusable: stays tinted as still needed
        self.fields.append(field)

    def ensure(self, height: float) -> None:
        if self.page is None or self.y + height > CONTENT_BOTTOM:
            self.new_page()

    def header_row(self, columns: Sequence[Tuple[str, float]], height: float = 16) -> None:
        x = MARGIN
        self.page.draw_rect((MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y + height), color=None, fill=BAND)
        for title, width in columns:
            self.line(x + 3, self.y + height - 5, title, 6.5, bold=True, color=MUTED, max_width=width - 4)
            x += width
        self.y += height

    def rule(self) -> None:
        self.page.draw_line((MARGIN, self.y), (PAGE_WIDTH - MARGIN, self.y), color=RULE, width=0.4)

    # -- pages --------------------------------------------------------------------------------------------------
    def cover(self, built_at: str, returned: Optional[Mapping[str, Any]]) -> None:
        document = self.document
        summary = document["summary"]
        self.new_page()
        self.y = PAGE_HEIGHT  # the cover is full: the sections start on the next page
        self.line(MARGIN, 92, "Inspection Sheet", 22, bold=True, color=PRIMARY)
        self.line(MARGIN, 112, f"Assembly {document['assemblyNumber']} - {document['assemblyName']}", 12)
        self.line(MARGIN, 127, f"CAD source {document['sourceRevision'][:12] or 'unknown'}   Sheet revision "
                               f"{document['documentRevision'][:12]}   Built {built_at}", 7.5, color=MUTED)

        # Job information: open fields first, then the inspection date.
        self.line(MARGIN, 152, "Job", 10, bold=True, color=PRIMARY)
        job = [field for field in document["fields"] if field["name"].startswith("header.")]
        for index, field in enumerate(job):
            column, row = index % 2, index // 2
            x = MARGIN + column * 178
            y = 162 + row * 34
            self.line(x, y + 7, field["label"], 6.5, color=MUTED, max_width=168)
            self.field(field["name"], (x, y + 10, x + 168, y + 26))

        # Summary.
        left = 400
        self.line(left, 152, "Summary", 10, bold=True, color=PRIMARY)
        lines = [
            f"Parts: {summary['parts']} ({summary['partsWithDrawing']} with a drawing, "
            f"{summary['partsWithProfileOnly']} with an inspection profile only"
            + (f", {summary['partsWithNothing']} with neither" if summary["partsWithNothing"] else "") + ")",
            f"Characteristics: {summary['characteristics']} "
            f"({summary['balloonedCharacteristics']} ballooned on drawings)",
            f"Information still needed: {summary['openFields']} field"
            + ("" if summary["openFields"] == 1 else "s") + " (amber)",
        ]
        results = summary.get("results") or {}
        if any(results.get(key) for key in ("PASS", "FAIL", "NO_LIMITS", "UNREADABLE")):
            lines.append("Results recorded: " + ", ".join(f"{results[key]} {key.lower().replace('_', ' ')}"
                                                          for key in ("PASS", "FAIL", "NO_LIMITS", "UNREADABLE",
                                                                      "PENDING") if results.get(key)))
        for index, text in enumerate(lines):
            self.line(left, 170 + index * 14, text, 8.5, max_width=PAGE_WIDTH - MARGIN - left)
        self.contents_y = 170 + len(lines) * 14 + 16

        # The information still needed, below the job fields and the contents.
        open_fields = document["openFields"]
        top = COVER_LIST_TOP
        self.line(MARGIN, top, f"Information still needed ({len(open_fields)})", 10, bold=True, color=PRIMARY)
        if not open_fields:
            self.line(MARGIN, top + 16, "None. Every value the sheet needs before inspection is provided.", 8.5)
            return
        self.line(MARGIN, top + 13, "Tell Sage, type it in InspectorPro, or fill the amber fields in this PDF and "
                                    "return it. Nothing here is guessed.", 7.5, color=MUTED)
        per_column, column_width = 15, 245
        shown = open_fields[:per_column * 3]
        for index, field in enumerate(shown):
            column, row = index // per_column, index % per_column
            x = MARGIN + column * column_width
            y = top + 28 + row * 12.5
            self.page.draw_rect((x, y - 6.5, x + 6, y - 0.5), color=RULE, fill=(1.0, 0.957, 0.839), width=0.4)
            self.line(x + 10, y, field["label"], 7, max_width=column_width - 16)
        if len(open_fields) > len(shown):
            self.line(MARGIN, top + 28 + per_column * 12.5, f"... and {len(open_fields) - len(shown)} more",
                      7, color=MUTED)

    def contents(self, entries: Sequence[Tuple[str, int]]) -> None:
        page = self.pdf[0]
        self.page = page
        left = 400
        self.line(left, self.contents_y, "Contents", 8.5, bold=True, color=PRIMARY)
        room = max(1, int((COVER_LIST_TOP - 16 - self.contents_y - 12) // 10.5))
        shown = entries if len(entries) <= room else entries[:room - 1]
        for index, (title, number) in enumerate(shown):
            y = self.contents_y + 12 + index * 10.5
            self.line(left, y, title, 7.5, max_width=300)
            self.line(PAGE_WIDTH - MARGIN, y, str(number), 7.5, align="right")
        if len(shown) < len(entries):
            self.line(left, self.contents_y + 12 + len(shown) * 10.5, f"... and {len(entries) - len(shown)} more",
                      7.5, color=MUTED)

    def drawing_page(self, section: Mapping[str, Any], source: Any) -> None:
        fitz = self.fitz
        self.new_page()
        self.line(MARGIN, CONTENT_TOP + 2, f"Item {section['item']}   {section['partNumber']}  "
                                           f"{section['description']}   Qty {section['quantity']}", 10, bold=True,
                  max_width=560)
        self.line(PAGE_WIDTH - MARGIN, CONTENT_TOP + 2, "Balloon numbers match the table", 7.5, color=MUTED,
                  align="right")
        area = fitz.Rect(MARGIN, CONTENT_TOP + 10, PAGE_WIDTH - MARGIN, CONTENT_BOTTOM)
        sheet_page = source[0]
        ratio = sheet_page.rect.width / max(1.0, sheet_page.rect.height)
        width, height = area.width, area.width / ratio
        if height > area.height:
            height, width = area.height, area.height * ratio
        placed = fitz.Rect(area.x0 + (area.width - width) / 2, area.y0, area.x0 + (area.width - width) / 2 + width,
                           area.y0 + height)
        self.page.show_pdf_page(placed, source, 0)
        self.page.draw_rect(placed, color=RULE, width=0.5)
        sheets = section.get("sheets") or []
        if not sheets or not sheets[0].get("width") or not sheets[0].get("height"):
            return
        sheet_w, sheet_h = sheets[0]["width"], sheets[0]["height"]

        def to_page(x_m: float, y_m: float) -> Tuple[float, float]:
            return placed.x0 + x_m / sheet_w * placed.width, placed.y0 + (1 - y_m / sheet_h) * placed.height

        views = []
        for view in sheets[0].get("views") or []:
            outline = view.get("outline")
            if isinstance(outline, (list, tuple)) and len(outline) == 4:
                (x0, y0), (x1, y1) = to_page(outline[0], outline[1]), to_page(outline[2], outline[3])
                views.append((view.get("name"), fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))))
        balloons: List[Tuple[float, float]] = []
        radius, reach = 6.5, 20.0
        for characteristic in section.get("characteristics") or []:
            if characteristic["sheet"] != 0 or characteristic["anchor"]["x"] is None:
                continue
            ax, ay = to_page(characteristic["anchor"]["x"], characteristic["anchor"]["y"])
            owning = next((rect for name, rect in views if name == characteristic["view"]), None)
            centre = owning if owning is not None else placed
            qx = -1 if ax < (centre.x0 + centre.x1) / 2 else 1
            qy = 1 if ay < (centre.y0 + centre.y1) / 2 else -1
            best, best_score = None, -math.inf
            for dx, dy in ((qx, -qy * 0.75), (qx, 0), (0, -qy), (-qx, -qy * 0.75), (qx, qy * 0.75), (-qx, 0),
                           (0, qy), (-qx, qy * 0.75)):
                bx = min(max(ax + dx * reach, placed.x0 + radius + 2), placed.x1 - radius - 2)
                by = min(max(ay + dy * reach, placed.y0 + radius + 2), placed.y1 - radius - 2)
                nearest = min((math.hypot(bx - px, by - py) for px, py in balloons), default=math.inf)
                score = -200 if nearest < 2 * radius + 3 else min(nearest, 80)
                for _name, rect in views:
                    if rect.contains(fitz.Point(bx, by)):
                        score -= 30 if rect is owning else 80
                if score > best_score:
                    best, best_score = (bx, by), score
            bx, by = best
            balloons.append(best)
            distance = math.hypot(ax - bx, ay - by)
            if distance > radius:
                edge = (bx + (ax - bx) / distance * radius, by + (ay - by) / distance * radius)
                self.page.draw_line(edge, (ax, ay), color=ACCENT, width=0.6)
            self.page.draw_circle((bx, by), radius, color=PRIMARY, fill=(1, 1, 1), width=0.8)
            self.line(bx, by + 2.5, str(characteristic["number"]), 7, bold=True, color=PRIMARY, align="center")

    def part_band(self, section: Mapping[str, Any]) -> None:
        self.ensure(42 + 16 + 2 * (24 if section["source"] == "drawing" else 32))
        top = self.y + 4
        self.page.draw_rect((MARGIN, top, PAGE_WIDTH - MARGIN, top + 26), color=None, fill=PRIMARY)
        self.line(MARGIN + 6, top + 16.5, f"Item {section['item']}   {section['partNumber']}  {section['description']}"
                                          f"   Qty {section['quantity']}", 9.5, bold=True, color=(1, 1, 1),
                  max_width=360)
        fields = section.get("fields") or {}
        x = PAGE_WIDTH - MARGIN - 6
        for key, title, width in (("generalTolerance", "General tolerance", 70),
                                  ("drawingRevision", "Drawing revision" if section["source"] == "drawing"
                                   else "Drawing and revision", 92)):
            if key not in fields:
                continue
            x -= width
            self.field(fields[key], (x, top + 5, x + width, top + 21))
            self.line(x - 4, top + 16, title, 7, color=(1, 1, 1), align="right")
            x -= self.fitz.get_text_length(_latin(title), fontname="helv", fontsize=7) + 14
        self.y = top + 30
        source = section["source"]
        if source == "drawing" and not section.get("generalTolerance") and "generalTolerance" in fields:
            note = section.get("generalToleranceProblem") or (
                "The drawing gives no tolerance for most dimensions and its title block is not read, so their "
                "limits are blank until the general tolerance is provided.")
            self.line(MARGIN, self.y + 8, note, 7, color=AMBER_TEXT, max_width=PAGE_WIDTH - 2 * MARGIN)
            self.y += 12
        elif source == "profile":
            self.line(MARGIN, self.y + 8, "No drawing in the library: features from the part's inspection profile; "
                                          "each requirement comes from the drawing.", 7, color=AMBER_TEXT,
                      max_width=PAGE_WIDTH - 2 * MARGIN)
            self.y += 12
        elif source == "none":
            self.line(MARGIN, self.y + 8, "No drawing and no inspection profile in the library.", 7,
                      color=AMBER_TEXT)
            self.y += 12

    def characteristics(self, section: Mapping[str, Any]) -> None:
        self.header_row(_CHARACTERISTIC_COLUMNS)
        height = 24
        for characteristic in section["characteristics"]:
            if self.y + height > CONTENT_BOTTOM:
                self.new_page()
                self.line(MARGIN, CONTENT_TOP + 2, f"{section['partNumber']} {section['description']} (continued)",
                          8.5, bold=True)
                self.y = CONTENT_TOP + 8
                self.header_row(_CHARACTERISTIC_COLUMNS)
            top, x = self.y, MARGIN
            cells = [width for _title, width in _CHARACTERISTIC_COLUMNS]
            self._result_tint(characteristic, top, height, MARGIN + sum(cells[:7]) - 3)
            middle = top + height / 2 + 2.5
            self.page.draw_circle((x + 13, top + height / 2), 6.5, color=PRIMARY, width=0.7)
            self.line(x + 13, middle, str(characteristic["number"]), 7, bold=True, color=PRIMARY, align="center")
            x += cells[0]
            self.line(x + 3, middle, characteristic["view"], 7, max_width=cells[1] - 6)
            x += cells[1]
            self.wrapped((x + 3, top + 5, x + cells[2] - 3, top + height),
                         characteristic["description"] or characteristic["text"], 7)
            x += cells[2]
            self.line(x + 3, middle, characteristic["text"], 7.5, bold=True, max_width=cells[3] - 6)
            x += cells[3]
            tolerance = characteristic.get("tolerance") or {}
            decimals = characteristic["decimals"]
            if characteristic["reference"]:
                tolerance_text, color = "reference", MUTED
            elif tolerance.get("kind") == "basic":
                tolerance_text, color = "basic", MUTED
            elif tolerance.get("kind") in ("drawing", "general"):
                plus, minus = tolerance["plus"], tolerance["minus"]
                decimals = max(decimals, len(f"{plus:g}".partition(".")[2]), len(f"{minus:g}".partition(".")[2]))
                tolerance_text = (f"\u00b1{_format(plus, decimals)}" if abs(plus - minus) < 1e-9
                                  else f"+{_format(plus, decimals)}/-{_format(minus, decimals)}")
                color = INK if tolerance["kind"] == "drawing" else MUTED
            else:
                tolerance_text, color = "open", AMBER_TEXT
            self.line(x + 3, middle, tolerance_text, 7, color=color, max_width=cells[4] - 6)
            x += cells[4]
            self.line(x + 3, middle, _format(characteristic.get("lower"), decimals), 7, max_width=cells[5] - 6)
            x += cells[5]
            self.line(x + 3, middle, _format(characteristic.get("upper"), decimals), 7, max_width=cells[6] - 6)
            x += cells[6]
            names = characteristic.get("fields") or {}
            if names:
                self.field(names["measured"], (x + 2, top + 4, x + cells[7] - 2, top + height - 4))
                x += cells[7]
                self.field(names["conforms"], (x + 8, top + 7, x + 18, top + 17))
                x += cells[8]
                self.field(names["gauge"], (x + 2, top + 4, x + cells[9] - 2, top + height - 4))
            else:
                self.line(x + 3, middle, "not inspected", 7, color=MUTED)
            self.y = top + height
            self.rule()

    def _result_tint(self, row: Mapping[str, Any], top: float, height: float, label_right: float) -> None:
        """A measured value outside its limits (or unreadable) tints the row and says so next to the measured cell;
        nothing else is coloured by the app."""
        if row.get("status") in ("FAIL", "UNREADABLE"):
            self.page.draw_rect((MARGIN, top, PAGE_WIDTH - MARGIN, top + height), color=None, fill=FAIL_FILL)
            self.line(label_right, top + height - 3, row["status"], 6, bold=True, color=FAIL_TEXT, align="right")

    def features(self, section: Mapping[str, Any]) -> None:
        self.header_row(_FEATURE_COLUMNS)
        height = 32
        for feature in section["features"]:
            if self.y + height > CONTENT_BOTTOM:
                self.new_page()
                self.line(MARGIN, CONTENT_TOP + 2, f"{section['partNumber']} {section['description']} (continued)",
                          8.5, bold=True)
                self.y = CONTENT_TOP + 8
                self.header_row(_FEATURE_COLUMNS)
            top, x = self.y, MARGIN
            cells = [width for _title, width in _FEATURE_COLUMNS]
            self._result_tint(feature, top, height, MARGIN + sum(cells[:4]) - 3)
            middle = top + height / 2 + 2.5
            self.line(x + 13, middle, str(feature["number"]), 7, bold=True, color=PRIMARY, align="center")
            x += cells[0]
            self.wrapped((x + 3, top + 4, x + cells[1] - 3, top + height - 2), feature["name"], 7.5, bold=True)
            x += cells[1]
            self.line(x + 3, middle, str(feature.get("count") or ""), 7)
            x += cells[2]
            self.wrapped((x + 3, top + 3, x + cells[3] - 3, top + height - 1), feature.get("reason") or "", 6.5,
                         color=MUTED)
            x += cells[3]
            names = feature["fields"]
            self.field(names["requirement"], (x + 2, top + 5, x + cells[4] - 2, top + height - 5))
            x += cells[4]
            self.field(names["measured"], (x + 2, top + 5, x + cells[5] - 2, top + height - 5))
            x += cells[5]
            self.field(names["conforms"], (x + 8, top + 11, x + 18, top + 21))
            x += cells[6]
            self.field(names["gauge"], (x + 2, top + 5, x + cells[7] - 2, top + height - 5))
            self.y = top + height
            self.rule()

    def assembly_check(self) -> None:
        self.ensure(70)
        top = self.y + 6
        self.page.draw_rect((MARGIN, top, PAGE_WIDTH - MARGIN, top + 24), color=None, fill=PRIMARY)
        self.line(MARGIN + 6, top + 16, "Assembly check: every BOM line present, correct part number and quantity",
                  9.5, bold=True, color=(1, 1, 1))
        self.y = top + 28
        self.header_row(_BOM_COLUMNS)
        height = 20
        for row in self.document["bom"]:
            if self.y + height > CONTENT_BOTTOM:
                self.new_page()
                self.header_row(_BOM_COLUMNS)
            top, x = self.y, MARGIN
            cells = [width for _title, width in _BOM_COLUMNS]
            middle = top + height / 2 + 2.5
            for index, text in enumerate((row["item"], row["partNumber"], row["description"], row["quantity"])):
                self.line(x + 3, middle, "" if text is None else text, 7.5, bold=index == 1,
                          max_width=cells[index] - 6)
                x += cells[index]
            self.field(row["fields"]["found"], (x + 2, top + 3, x + cells[4] - 2, top + height - 3))
            x += cells[4]
            self.field(row["fields"]["conforms"], (x + 15, top + 5, x + 25, top + 15))
            self.y = top + height
            self.rule()

    def signoff(self) -> None:
        self.ensure(150)
        top = self.y + 10
        self.page.draw_rect((MARGIN, top, PAGE_WIDTH - MARGIN, top + 24), color=None, fill=PRIMARY)
        self.line(MARGIN + 6, top + 16, "Sign-off", 9.5, bold=True, color=(1, 1, 1))
        y = top + 34
        for role, title in (("inspector", "Inspector"), ("reviewer", "Reviewer")):
            self.line(MARGIN, y + 11, title, 8.5, bold=True)
            for key, label, x, width in (("name", "Name", 110, 190), ("date", "Date", 336, 100),
                                         ("signature", "Signature", 486, 250)):
                self.line(MARGIN + x - 5, y + 11, label, 7, color=MUTED, align="right")
                if key == "signature":
                    self.page.draw_rect((MARGIN + x, y, MARGIN + x + width, y + 16), color=RULE, width=0.6)
                self.field(f"signoff.{role}.{key}", (MARGIN + x, y, MARGIN + x + width, y + 16))
            y += 24
        self.line(MARGIN, y + 11, "Result", 8.5, bold=True)
        self.field("result.accept", (MARGIN + 110, y + 3, MARGIN + 120, y + 13))
        self.line(MARGIN + 125, y + 11, "Accept", 8)
        self.field("result.reject", (MARGIN + 180, y + 3, MARGIN + 190, y + 13))
        self.line(MARGIN + 195, y + 11, "Reject", 8)
        y += 22
        self.line(MARGIN, y + 11, "Notes", 8.5, bold=True)
        self.field("signoff.notes", (MARGIN + 110, y, PAGE_WIDTH - MARGIN, y + 40))
        self.y = y + 44

    def footers(self, built_at: str) -> None:
        total = self.pdf.page_count
        for index in range(total):
            self.page = self.pdf[index]
            self.page.draw_line((MARGIN, PAGE_HEIGHT - 26), (PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 26), color=RULE,
                                width=0.4)
            self.line(MARGIN, PAGE_HEIGHT - 16, f"Amber fields: information still needed. Built by InspectorPro "
                                                f"{built_at}.", 6.5, color=MUTED)
            self.line(PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 16, f"Page {index + 1} of {total}", 6.5, color=MUTED,
                      align="right")


def build_inspection_sheet_pdf_bytes(
    document: Mapping[str, Any],
    *,
    drawing_pdfs: Mapping[str, Path],
    built_at: str,
    returned: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The PDF and what it holds: {pdf, pages, fields}. drawing_pdfs maps a part number to its drawing PDF."""
    try:
        import fitz
    except ImportError as exc:
        raise InspectionSheetExportError("PyMuPDF is required for inspection-sheet export") from exc
    writer = _Writer(fitz, document)
    writer.cover(built_at, returned)
    contents: List[Tuple[str, int]] = []
    sources = []
    try:
        for section in document["sections"]:
            title = f"{section['partNumber']} {section['description']}"
            drawing = drawing_pdfs.get(section["partNumber"]) if section["source"] == "drawing" else None
            if drawing is not None:
                source = fitz.open(str(drawing))
                sources.append(source)
                writer.drawing_page(section, source)
                contents.append((f"{title}: drawing", writer.pdf.page_count))
                writer.new_page()
            elif section["source"] == "drawing":
                writer.new_page()
            writer.part_band(section)
            contents.append((title, writer.pdf.page_count))
            if section["source"] == "drawing":
                writer.characteristics(section)
            else:
                writer.features(section)
        writer.assembly_check()
        contents.append(("Assembly check and sign-off", writer.pdf.page_count))
        writer.signoff()
        writer.contents(contents)
        writer.footers(built_at)
        page_sizes = [(page.rect.width, page.rect.height) for page in writer.pdf]
        try:
            validate_form_fields(writer.fields, page_sizes)
        except FormFieldError as exc:
            raise InspectionSheetExportError(str(exc)) from exc
        add_form_fields(fitz, writer.pdf, writer.fields)
        writer.pdf.set_metadata({
            "title": f"Inspection Sheet {document['assemblyNumber']}",
            "author": "InspectorPro",
            "subject": f"Inspection sheet for {document['assemblyNumber']} {document['assemblyName']}",
            "keywords": f"{KEYWORD_PREFIX};assembly={document['assemblyNumber']};"
                        f"revision={document['documentRevision']}",
            "creator": "InspectorPro",
        })
        payload = writer.pdf.tobytes(garbage=3, deflate=True)
        return {"pdf": payload, "pages": writer.pdf.page_count, "fields": len(writer.fields)}
    finally:
        for source in sources:
            source.close()
        writer.pdf.close()


def read_returned_inspection_sheet(pdf_bytes: bytes) -> Dict[str, Any]:
    """A filled copy given back: which sheet it is (from its keywords) and its field values."""
    try:
        import fitz
    except ImportError as exc:
        raise InspectionSheetExportError("PyMuPDF is required to read a returned inspection sheet") from exc
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise InspectionSheetExportError("the returned file is not a readable PDF") from exc
    try:
        keywords = str((document.metadata or {}).get("keywords") or "")
    finally:
        document.close()
    parts = dict(item.split("=", 1) for item in keywords.split(";")[1:] if "=" in item)
    if not keywords.startswith(KEYWORD_PREFIX) or not parts.get("assembly"):
        raise InspectionSheetExportError("this PDF is not an InspectorPro inspection sheet")
    try:
        fields = read_form_fields(pdf_bytes)
    except FormFieldError as exc:
        raise InspectionSheetExportError(str(exc)) from exc
    return {"assemblyNumber": parts["assembly"], "documentRevision": parts.get("revision") or "", "fields": fields}
