"""One-page PDF export for evidence-bound product specification sheets.

Every text is a slot (slots.py). The final PDF and the DOCX leave open slots out: a row whose value is open, a
prose slot with nothing in it. The fillable PDF is the same page with the open slots as amber form fields named by
slot id, and a returned, filled copy is read back by those names.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Dict, List, Mapping, Tuple

from ai_inspector.documentation.form_fields import (
    FormFieldError,
    add_form_fields,
    form_field,
    read_form_fields,
    validate_form_fields,
)
from ai_inspector.operations_manual.artifacts import draft_render_path

FILLABLE_KEYWORD_PREFIX = "inspectorpro-specification-sheet-fillable"
# A slot's text shrinks to fit its box, down to 70% of its size; past that the export names the slot.
_FIT_SCALES = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7)


class SpecificationSheetExportError(RuntimeError):
    pass


_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")


def _safe(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if _SAFE_RE.fullmatch(result) is None:
        raise SpecificationSheetExportError(f"invalid {label}")
    return result


def _filesystem_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-specification-sheet-{uuid.uuid4().hex}{path.suffix}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(_filesystem_path(temporary), flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(_filesystem_path(temporary), _filesystem_path(path))
    finally:
        try:
            os.unlink(_filesystem_path(temporary))
        except FileNotFoundError:
            pass


def specification_export_readiness(document: Mapping[str, Any]) -> Dict[str, Any]:
    required = [
        page
        for page in document.get("pages") or []
        if isinstance(page, Mapping) and isinstance(page.get("renderRequest"), Mapping)
    ]
    current_revision = str(document.get("documentRevision") or "")
    pending = []
    for page in required:
        image = (page.get("renderRequest") or {}).get("image") or {}
        if image.get("status") != "ready" or str(image.get("documentRevision") or "") != current_revision:
            pending.append(str(page.get("pageId") or ""))
    return {
        "status": "READY" if not pending else "CAPTURE_REQUIRED",
        "requiredCaptureCount": len(required),
        "acceptedCaptureCount": len(required) - len(pending),
        "pendingPageIds": pending,
    }


def _rgb(value: Any, fallback: str) -> tuple[float, float, float]:
    text = str(value or fallback).strip().lstrip("#")
    if len(text) != 6 or any(character not in "0123456789abcdefABCDEF" for character in text):
        text = fallback.lstrip("#")
    return tuple(int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _fit_image_rect(fitz: Any, bounds: Any, image_path: Path) -> Any:
    pixmap = fitz.Pixmap(_filesystem_path(image_path))
    try:
        ratio = pixmap.width / max(1, pixmap.height)
    finally:
        pixmap = None
    width = bounds.width
    height = width / ratio
    if height > bounds.height:
        height = bounds.height
        width = height * ratio
    x = bounds.x0 + (bounds.width - width) / 2
    y = bounds.y0 + (bounds.height - height) / 2
    return fitz.Rect(x, y, x + width, y + height)


def _element_override(descriptor: Mapping[str, Any], block_id: str) -> Mapping[str, Any]:
    composition = descriptor.get("documentationComposition")
    overrides = composition.get("pageElementOverrides") if isinstance(composition, Mapping) else None
    value = overrides.get(block_id) if isinstance(overrides, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _block_frame(
    descriptor: Mapping[str, Any],
    block: Mapping[str, Any],
    page_width: float,
    page_height: float,
    default: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> tuple[float, float, float, float]:
    """The block's frame where the viewport shows it: moves and resizes are fractions of the page."""
    frame = block.get("frame") if isinstance(block.get("frame"), Mapping) else {}
    x, y, width, height = (
        float(frame.get(key) or fallback)
        for key, fallback in zip(("x", "y", "width", "height"), default)
    )
    override = _element_override(descriptor, str(block.get("blockId") or ""))
    move = override.get("translation") if isinstance(override.get("translation"), (list, tuple)) else []
    size = override.get("sizeDelta") if isinstance(override.get("sizeDelta"), (list, tuple)) else []
    x += float(move[0]) * page_width if len(move) > 0 else 0.0
    y += float(move[1]) * page_height if len(move) > 1 else 0.0
    if len(size) > 0:
        width = max(24.0, width + float(size[0]) * page_width)
    if len(size) > 1:
        height = max(24.0, height + float(size[1]) * page_height)
    return x, y, width, height


def _block_style(descriptor: Mapping[str, Any], block: Mapping[str, Any]) -> Dict[str, Any]:
    style = dict(block.get("style") or {}) if isinstance(block.get("style"), Mapping) else {}
    override = _element_override(descriptor, str(block.get("blockId") or "")).get("style")
    if isinstance(override, Mapping):
        style.update({key: value for key, value in override.items() if value not in (None, "")})
    return style


# The PDF's built-in fonts draw Latin-1 only: typographic characters are drawn as their plain equivalents.
_PLAIN_TEXT = {
    **{code: "-" for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0x207B, 0x2022)},
    **{code: " " for code in (0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A, 0x202F)},
    **{code: chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)},  # full-width letters, digits and signs
    0x200B: "", 0x2018: "'", 0x2019: "'", 0x2032: "'", 0x201C: '"', 0x201D: '"', 0x2033: '"', 0x2026: "...",
    0x3010: "[", 0x3011: "]", 0x3014: "[", 0x3015: "]", 0x2264: "<=", 0x2265: ">=", 0x3000: " ",
}


def _plain(text: Any) -> str:
    return str(text or "").translate(_PLAIN_TEXT)


def _drawable(text: Any, name: str) -> str:
    plain = _plain(text)
    missing = sorted({char for char in plain if ord(char) > 255 or 127 <= ord(char) < 160})
    if missing:
        raise SpecificationSheetExportError(
            f"{name} has characters the PDF font cannot draw ({' '.join(missing)}). Write them another way."
        )
    return plain


def _insert_textbox_checked(page: Any, rect: Any, text: str, **kwargs: Any) -> None:
    text = _drawable(text, f"The text {_plain(text)[:60]!r}")
    remaining = page.insert_textbox(rect, text, **kwargs)
    if remaining < -0.01:
        raise SpecificationSheetExportError(f"specification-sheet text overflow: {text[:80]}")


def _text_height(scratch: Any, text: str, width: float, fontname: str, fontsize: float) -> float:
    """The height a text takes when wrapped to width (insert_textbox reports the shortfall of a box too small)."""
    import fitz

    probe = 400.0
    spare = scratch.insert_textbox(fitz.Rect(0, 0, max(1.0, width), probe), _plain(text), fontname=fontname,
                                   fontsize=fontsize)
    return probe - spare


def _table_layout(rows: List[Mapping[str, Any]], heights: List[float], widths: Tuple[float, float],
                  frame_height: float, shown: List[bool], fontsize: float) -> Tuple[List[float], float]:
    """Each shown row as tall as its text needs (at least its layout height); when the rows outgrow the frame,
    every row and its text are drawn smaller together, as the viewport shrinks the table to fit."""
    import fitz

    scratch = fitz.open().new_page()
    for scale in _FIT_SCALES:
        sized = []
        for row, height, visible in zip(rows, heights, shown):
            if not visible:
                sized.append(0.0)
                continue
            cells = list(row.get("cells") or []) + ["", ""]
            needed = max(_text_height(scratch, str(cells[0]), widths[0], "hebo", fontsize * scale),
                         _text_height(scratch, str(cells[1]), widths[1], "helv", fontsize * scale)) + 11.0
            sized.append(max(height * scale, needed))
        if sum(sized) <= frame_height + 0.5:
            return sized, scale
    return [height if visible else 0.0 for height, visible in zip(heights, shown)], 1.0


def _insert_fitted(page: Any, rect: Any, text: str, *, name: str, fontsize: float, **kwargs: Any) -> None:
    text = _drawable(text, name)
    for scale in _FIT_SCALES:
        # insert_textbox writes nothing when the text does not fit, so each smaller size starts clean.
        if page.insert_textbox(rect, text, fontsize=fontsize * scale, **kwargs) >= -0.01:
            return
    raise SpecificationSheetExportError(
        f"{name} does not fit its box on the page, even at 70% of its size. "
        "Shorten it, or make its box larger in the viewport."
    )


def build_specification_pdf_bytes(
    document: Mapping[str, Any],
    *,
    render_root: str | Path,
    assembly_number: str,
) -> bytes:
    payload, _fields = _build_specification_pdf(
        document, render_root=render_root, assembly_number=assembly_number, fillable=False
    )
    return payload


def build_specification_fillable_pdf_bytes(
    document: Mapping[str, Any],
    *,
    render_root: str | Path,
    assembly_number: str,
) -> Tuple[bytes, List[Dict[str, Any]]]:
    """The same page with every open slot as an amber form field; returns the PDF and its fields."""
    return _build_specification_pdf(
        document, render_root=render_root, assembly_number=assembly_number, fillable=True
    )


def _build_specification_pdf(
    document: Mapping[str, Any],
    *,
    render_root: str | Path,
    assembly_number: str,
    fillable: bool,
) -> Tuple[bytes, List[Dict[str, Any]]]:
    readiness = specification_export_readiness(document)
    if readiness["status"] != "READY":
        raise SpecificationSheetExportError("the current product image must be captured before export")
    try:
        import fitz
    except ImportError as exc:
        raise SpecificationSheetExportError("PyMuPDF is required for specification-sheet export") from exc

    descriptor = (document.get("pages") or [None])[0]
    if not isinstance(descriptor, Mapping):
        raise SpecificationSheetExportError("the specification-sheet page is missing")
    layout = document.get("publicationLayout") or {}
    page_size = layout.get("page") or {}
    width = float(page_size.get("width") or 612)
    height = float(page_size.get("height") or 792)
    theme = document.get("theme") or {}
    colors = theme.get("colors") or {}
    primary = _rgb(colors.get("primary"), "#071B2A")
    accent = _rgb(colors.get("accent"), "#43B5EE")
    text_color = _rgb(colors.get("text"), "#18212A")
    muted = _rgb(colors.get("muted"), "#596A76")
    rule = _rgb(colors.get("rule"), "#ABBAC4")

    pdf = fitz.open()
    page = pdf.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), fill=(1, 1, 1), color=None)
    page.draw_rect(fitz.Rect(0, 0, width, 64), fill=primary, color=None)
    page.draw_rect(fitz.Rect(0, 61, width, 64), fill=accent, color=None)
    _insert_textbox_checked(
        page, fitz.Rect(30, 18, 230, 48), "InspectorPro",
        fontname="helv", fontsize=14, color=(1, 1, 1), align=0,
    )
    _insert_textbox_checked(
        page, fitz.Rect(310, 20, 582, 47), "PRODUCT SPECIFICATION",
        fontname="helv", fontsize=9, color=(1, 1, 1), align=2,
    )

    blocks = {
        str(block.get("blockId") or ""): block
        for block in descriptor.get("layoutBlocks") or []
        if isinstance(block, Mapping)
    }
    def rect_of(block: Mapping[str, Any], default: tuple[float, float, float, float]) -> Any:
        x, y, w, h = _block_frame(descriptor, block, width, height, default)
        return fitz.Rect(x, y, x + w, y + h)

    slots = document.get("slots") if isinstance(document.get("slots"), Mapping) else {}
    fields: List[Dict[str, Any]] = []

    def name_of(slot: Any) -> str:
        info = slots.get(str(slot or ""))
        return str(info.get("name") or slot) if isinstance(info, Mapping) else str(slot or "A text")

    def add_field(slot: Any, rect: Any, size: float, kind: str = "text") -> None:
        info = slots.get(str(slot or ""))
        hint = str(info.get("hint") or "") if isinstance(info, Mapping) else ""
        fields.append(form_field(
            str(slot), name_of(slot) + (f" ({hint})" if hint else ""), (rect.x0, rect.y0, rect.x1, rect.y1),
            kind=kind, role="provide", font_size=size,
        ))

    def line_field(rect: Any, size: float) -> Any:
        """A one-line field centred in a taller box."""
        middle = (rect.y0 + rect.y1) / 2
        half = min((rect.y1 - rect.y0) / 2, max(7.0, size * 0.85))
        return fitz.Rect(rect.x0, middle - half, rect.x1, middle + half)

    feature_blocks = [blocks.get(f"spec-feature-{index}") or {} for index in range(1, 4)]

    def feature_open(block: Mapping[str, Any]) -> Mapping[str, Any]:
        return block.get("open") if isinstance(block.get("open"), Mapping) else {}

    features_shown = fillable or any(
        not (feature_open(block).get("title") and feature_open(block).get("text")) for block in feature_blocks
    )
    for block_id in ("spec-kicker", "spec-title", "spec-tagline", "features-heading"):
        block = blocks.get(block_id) or {}
        style = _block_style(descriptor, block)
        rect = rect_of(block, (0.0, 0.0, 0.0, 0.0))
        size = float(style.get("fontSize") or 9)
        if block_id == "features-heading" and not features_shown:
            continue
        if block.get("open"):
            if fillable:
                add_field(block.get("slot"), rect, size)
            continue
        _insert_fitted(
            page,
            rect,
            str(block.get("text") or ""),
            name=name_of(block.get("slot")),
            fontname="hebo" if int(style.get("fontWeight") or 400) >= 600 else "helv",
            fontsize=size,
            color=_rgb(style.get("color"), "#18212A"),
            lineheight=max(1.0, float(style.get("lineHeight") or 12) / max(1.0, float(style.get("fontSize") or 9))),
            align={"center": 1, "right": 2, "justify": 3}.get(str(style.get("textAlign") or ""), 0),
        )

    figure_block = blocks.get("spec-figure") or {}
    figure_bounds = rect_of(figure_block, (36.0, 176.0, 318.0, 346.0))
    figure_bounds.y1 -= 18
    image_path = draft_render_path(
        render_root,
        assembly_number,
        str(document.get("figureRevision") or document.get("documentRevision") or ""),
        str(descriptor.get("pageId") or ""),
    )
    page.insert_image(_fit_image_rect(fitz, figure_bounds, image_path), filename=_filesystem_path(image_path))
    page.draw_rect(figure_bounds, color=rule, width=0.6)
    caption_rect = fitz.Rect(figure_bounds.x0, figure_bounds.y1 + 2, figure_bounds.x1, figure_bounds.y1 + 16)
    if figure_block.get("open"):
        if fillable:
            add_field(figure_block.get("slot") or "caption", caption_rect, 6.5)
    else:
        _insert_fitted(
            page,
            caption_rect,
            str(figure_block.get("caption") or ""),
            name=name_of(figure_block.get("slot") or "caption"),
            fontname="helv",
            fontsize=6.5,
            color=muted,
            align=1,
        )

    heading = blocks.get("specifications-heading") or {}
    heading_rect = rect_of(heading, (374.0, 176.0, 202.0, 20.0))
    if heading.get("open"):
        if fillable:
            add_field(heading.get("slot"), heading_rect, 15)
    else:
        _insert_fitted(
            page,
            heading_rect,
            str(heading.get("text") or "Specifications"),
            name=name_of(heading.get("slot")),
            fontname="hebo",
            fontsize=15,
            color=primary,
        )
    table = blocks.get("specifications-table") or {}
    x, y, table_width, table_height = _block_frame(descriptor, table, width, height, (374.0, 198.0, 202.0, 324.0))
    split = x + table_width * 0.58
    rows = list(table.get("rows") or [])
    heights = [float(value) for value in table.get("rowHeights") or []]
    if len(heights) != len(rows):
        heights = [table_height / max(1, len(rows))] * len(rows)
    shown = [fillable or not any(bool(item) for item in (row.get("open") or [])) for row in rows]
    heights, table_scale = _table_layout(rows, heights, (split - 5 - x, x + table_width - split), table_height,
                                         shown, 7.8)
    top = y
    for row, row_height, visible in zip(rows, heights, shown):
        flags = [bool(item) for item in (row.get("open") or [])] + [False, False]
        if not visible:
            continue  # the final PDF leaves out a row with nothing to say
        bottom = top + row_height
        page.draw_line(fitz.Point(x, bottom), fitz.Point(x + table_width, bottom), color=rule, width=0.55)
        cells = list(row.get("cells") or []) + ["", ""]
        row_slots = list(row.get("slots") or []) + ["", ""]
        for column, (rect, font, align) in enumerate((
            (fitz.Rect(x, top + 7, split - 5, bottom - 4), "hebo", 0),
            (fitz.Rect(split, top + 7, x + table_width, bottom - 4), "helv", 2),
        )):
            if flags[column]:
                add_field(row_slots[column], line_field(fitz.Rect(rect.x0, top + 2, rect.x1, bottom - 2), 7.8),
                          7.8)
                continue
            _insert_fitted(
                page, rect, str(cells[column]), name=name_of(row_slots[column]), fontname=font,
                fontsize=7.8 * table_scale, color=text_color, align=align,
            )
        top = bottom

    previous_shown = False
    for index, block in enumerate(feature_blocks):
        flags = feature_open(block)
        card_slots = block.get("slots") if isinstance(block.get("slots"), Mapping) else {}
        if not fillable and flags.get("title") and flags.get("text"):
            previous_shown = False
            continue  # a card with nothing in it is left out with its frame
        rect = rect_of(block, (0.0, 0.0, 0.0, 0.0))
        page.draw_line(fitz.Point(rect.x0, rect.y0), fitz.Point(rect.x0 + 34, rect.y0), color=accent, width=3)
        title_rect = fitz.Rect(rect.x0, rect.y0 + 11, rect.x1, rect.y0 + 40)
        if flags.get("title"):
            if fillable:
                add_field(card_slots.get("title"), fitz.Rect(rect.x0, rect.y0 + 11, rect.x1, rect.y0 + 27), 9.2)
        else:
            _insert_fitted(
                page, title_rect, str(block.get("title") or ""), name=name_of(card_slots.get("title")),
                fontname="hebo", fontsize=9.2, color=primary,
            )
        text_rect = fitz.Rect(rect.x0, rect.y0 + 42, rect.x1, rect.y1)
        if flags.get("text"):
            if fillable:
                add_field(card_slots.get("text"), fitz.Rect(rect.x0, rect.y0 + 42, rect.x1, rect.y1 - 10), 7.6,
                          kind="multiline")
        else:
            _insert_fitted(
                page, text_rect, str(block.get("text") or ""), name=name_of(card_slots.get("text")),
                fontname="helv", fontsize=7.6, color=text_color, lineheight=1.35,
            )
        if index and previous_shown:
            page.draw_line(
                fitz.Point(rect.x0 - 9, rect.y0),
                fitz.Point(rect.x0 - 9, rect.y1 - 10),
                color=rule,
                width=0.45,
            )
        previous_shown = True

    page.draw_rect(fitz.Rect(24, 754, 588, 780), fill=primary, color=None)
    product = document.get("product") or {}
    _insert_textbox_checked(
        page, fitz.Rect(36, 762, 340, 776), str(product.get("name") or "Product"),
        fontname="helv", fontsize=6.8, color=(1, 1, 1),
    )
    _insert_textbox_checked(
        page,
        fitz.Rect(350, 762, 576, 776),
        f"{document.get('documentNumber') or ''} | REVIEW",
        fontname="helv",
        fontsize=6.8,
        color=(1, 1, 1),
        align=2,
    )
    keywords = f"InspectorPro,{assembly_number},specification sheet"
    if fillable:
        keywords = (f"{FILLABLE_KEYWORD_PREFIX};assembly={assembly_number};"
                    f"revision={document.get('documentRevision') or ''}")
        try:
            validate_form_fields(fields, [(width, height)])
            add_form_fields(fitz, pdf, fields)
        except FormFieldError as exc:
            pdf.close()
            raise SpecificationSheetExportError(str(exc)) from exc
    pdf.set_metadata(
        {
            "title": str(document.get("title") or "Product Specification Sheet"),
            "author": str(theme.get("companyName") or "InspectorPro"),
            "subject": "Evidence-bound product specification sheet",
            "keywords": keywords,
        }
    )
    payload = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    return payload, fields


def read_returned_specification_sheet(pdf_bytes: bytes) -> Dict[str, Any]:
    """A filled copy given back: which sheet it is (from its keywords) and its field values by slot id."""
    try:
        import fitz
    except ImportError as exc:
        raise SpecificationSheetExportError("PyMuPDF is required to read a returned specification sheet") from exc
    try:
        opened = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise SpecificationSheetExportError("the returned file is not a readable PDF") from exc
    try:
        keywords = str((opened.metadata or {}).get("keywords") or "")
    finally:
        opened.close()
    parts = dict(item.split("=", 1) for item in keywords.split(";")[1:] if "=" in item)
    if not keywords.startswith(FILLABLE_KEYWORD_PREFIX) or not parts.get("assembly"):
        raise SpecificationSheetExportError("this PDF is not a fillable InspectorPro specification sheet")
    try:
        fields = read_form_fields(pdf_bytes)
    except FormFieldError as exc:
        raise SpecificationSheetExportError(str(exc)) from exc
    return {"assemblyNumber": parts["assembly"], "documentRevision": parts.get("revision") or "", "fields": fields}


def _docx_hex(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lstrip("#")
    if len(text) != 6 or any(character not in "0123456789abcdefABCDEF" for character in text):
        text = fallback.lstrip("#")
    return text.upper()


def _docx_shade_cell(cell: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), _docx_hex(color, "FFFFFF"))


def _docx_set_cell_border(cell: Any, edge: str, color: str, size: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = cell._tc.get_or_add_tcPr()
    borders = properties.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        properties.append(borders)
    border = borders.find(qn(f"w:{edge}"))
    if border is None:
        border = OxmlElement(f"w:{edge}")
        borders.append(border)
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), str(size))
    border.set(qn("w:color"), _docx_hex(color, "ABBAC4"))


def _docx_clear_table_borders(table: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table._tbl.tblPr
    borders = properties.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        properties.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = borders.find(qn(f"w:{edge}"))
        if border is None:
            border = OxmlElement(f"w:{edge}")
            borders.append(border)
        border.set(qn("w:val"), "nil")


def _docx_format_paragraph(
    paragraph: Any,
    *,
    color: str,
    size: float,
    bold: bool = False,
    font_name: str = "Arial",
) -> None:
    from docx.shared import Pt, RGBColor

    for run in paragraph.runs:
        run.font.name = font_name
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(_docx_hex(color, "18212A"))


def build_specification_docx_bytes(
    document: Mapping[str, Any],
    *,
    render_root: str | Path,
    assembly_number: str,
) -> bytes:
    readiness = specification_export_readiness(document)
    if readiness["status"] != "READY":
        raise SpecificationSheetExportError(
            "the current product image must be captured before export"
        )
    try:
        from docx import Document
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor
    except ImportError as exc:
        raise SpecificationSheetExportError(
            "python-docx is required for specification-sheet DOCX export"
        ) from exc

    descriptor = (document.get("pages") or [None])[0]
    if not isinstance(descriptor, Mapping):
        raise SpecificationSheetExportError("the specification-sheet page is missing")
    layout = document.get("publicationLayout") or {}
    page_size = layout.get("page") or {}
    width_pt = float(page_size.get("width") or 612.0)
    height_pt = float(page_size.get("height") or 792.0)
    theme = document.get("theme") or {}
    colors = theme.get("colors") or {}
    typography = theme.get("typography") or {}
    primary = _docx_hex(colors.get("primary"), "071B2A")
    accent = _docx_hex(colors.get("accent"), "43B5EE")
    text_color = _docx_hex(colors.get("text"), "18212A")
    muted = _docx_hex(colors.get("muted"), "596A76")
    rule = _docx_hex(colors.get("rule"), "ABBAC4")
    body_font = str(typography.get("bodyFont") or "Arial")
    heading_font = str(typography.get("headingFont") or "Arial")

    output = Document()
    section = output.sections[0]
    section.page_width = Inches(width_pt / 72.0)
    section.page_height = Inches(height_pt / 72.0)
    section.top_margin = Inches(0.52)
    section.bottom_margin = Inches(0.42)
    section.left_margin = Inches(0.52)
    section.right_margin = Inches(0.52)
    section.header_distance = Inches(0.12)
    section.footer_distance = Inches(0.12)
    content_width = max(1.0, (width_pt / 72.0) - 1.04)

    styles = output.styles
    styles["Normal"].font.name = body_font
    styles["Normal"].font.size = Pt(8.5)
    styles["Title"].font.name = heading_font
    styles["Title"].font.size = Pt(22)
    styles["Title"].font.color.rgb = RGBColor.from_string(primary)
    styles["Heading 1"].font.name = heading_font
    styles["Heading 1"].font.size = Pt(13)
    styles["Heading 1"].font.color.rgb = RGBColor.from_string(primary)

    header = section.header
    header.paragraphs[0].paragraph_format.space_after = Pt(0)
    header_table = header.add_table(rows=1, cols=2, width=Inches(content_width))
    header_table.autofit = False
    header_table.columns[0].width = Inches(content_width * 0.55)
    header_table.columns[1].width = Inches(content_width * 0.45)
    for cell in header_table.rows[0].cells:
        _docx_shade_cell(cell, primary)
        _docx_set_cell_border(cell, "bottom", accent, 20)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    brand = header_table.cell(0, 0).paragraphs[0]
    brand.add_run("Inspector").bold = True
    brand.add_run("Pro").bold = True
    _docx_format_paragraph(brand, color="FFFFFF", size=10.5, bold=True)
    brand.runs[-1].font.color.rgb = RGBColor.from_string(accent)
    label = header_table.cell(0, 1).paragraphs[0]
    label.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    label.add_run("PRODUCT SPECIFICATION")
    _docx_format_paragraph(label, color="FFFFFF", size=8.5, bold=True)

    footer = section.footer
    footer.paragraphs[0].paragraph_format.space_after = Pt(0)
    footer_table = footer.add_table(rows=1, cols=2, width=Inches(content_width))
    footer_table.autofit = False
    footer_table.columns[0].width = Inches(content_width * 0.64)
    footer_table.columns[1].width = Inches(content_width * 0.36)
    for cell in footer_table.rows[0].cells:
        _docx_shade_cell(cell, primary)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    product_name = str((document.get("product") or {}).get("name") or "Product")
    footer_identity = footer_table.cell(0, 0).paragraphs[0]
    footer_identity.add_run(product_name)
    _docx_format_paragraph(footer_identity, color="FFFFFF", size=7)
    footer_meta = footer_table.cell(0, 1).paragraphs[0]
    footer_meta.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer_meta.add_run(f"{document.get('documentNumber') or ''} | REVIEW")
    _docx_format_paragraph(footer_meta, color="FFFFFF", size=7)

    blocks = {
        str(block.get("blockId") or ""): block
        for block in descriptor.get("layoutBlocks") or []
        if isinstance(block, Mapping)
    }

    def shown(block_id: str) -> bool:
        return not (blocks.get(block_id) or {}).get("open")

    if shown("spec-kicker"):
        kicker = output.add_paragraph(
            str((blocks.get("spec-kicker") or {}).get("text") or "PRODUCT SPECIFICATION")
        )
        kicker.paragraph_format.space_after = Pt(2)
        _docx_format_paragraph(kicker, color=accent, size=8.5, bold=True, font_name=heading_font)
    title = output.add_paragraph(str((blocks.get("spec-title") or {}).get("text") or product_name))
    title.style = styles["Title"]
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(2)
    if shown("spec-tagline"):
        tagline = output.add_paragraph(str((blocks.get("spec-tagline") or {}).get("text") or ""))
        tagline.paragraph_format.space_after = Pt(8)
        _docx_format_paragraph(tagline, color=muted, size=8.5, font_name=body_font)

    main = output.add_table(rows=1, cols=2)
    main.autofit = False
    _docx_clear_table_borders(main)
    image_width = content_width * 0.58
    spec_width = content_width - image_width
    main.columns[0].width = Inches(image_width)
    main.columns[1].width = Inches(spec_width)
    image_cell, specification_cell = main.rows[0].cells
    image_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    specification_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    image_path = draft_render_path(
        render_root,
        assembly_number,
        str(document.get("figureRevision") or document.get("documentRevision") or ""),
        str(descriptor.get("pageId") or ""),
    )
    image_paragraph = image_cell.paragraphs[0]
    image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image_paragraph.add_run().add_picture(
        _filesystem_path(image_path),
        width=Inches(max(2.5, image_width - 0.18)),
    )
    if shown("spec-figure"):
        caption = image_cell.add_paragraph(
            str((blocks.get("spec-figure") or {}).get("caption") or "")
        )
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption.paragraph_format.space_before = Pt(2)
        caption.paragraph_format.space_after = Pt(0)
        _docx_format_paragraph(caption, color=muted, size=6.5, font_name=body_font)

    specifications_heading = specification_cell.paragraphs[0]
    if shown("specifications-heading"):
        specifications_heading.add_run(
            str((blocks.get("specifications-heading") or {}).get("text") or "Specifications")
        )
    specifications_heading.paragraph_format.space_after = Pt(3)
    _docx_format_paragraph(
        specifications_heading,
        color=primary,
        size=13,
        bold=True,
        font_name=heading_font,
    )
    specifications = [
        list(row.get("cells") or []) + ["", ""]
        for row in (blocks.get("specifications-table") or {}).get("rows") or []
        if isinstance(row, Mapping) and not any(row.get("open") or [])
    ]
    specifications_table = specification_cell.add_table(
        rows=max(1, len(specifications)), cols=2
    )
    specifications_table.autofit = False
    for index, specification in enumerate(specifications):
        cells = specifications_table.rows[index].cells
        cells[0].text = str(specification[0] or "Specification")
        cells[1].text = str(specification[1] or "")
        cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for cell in cells:
            _docx_set_cell_border(cell, "bottom", rule, 4)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _docx_format_paragraph(cells[0].paragraphs[0], color=text_color, size=7.7, bold=True)
        _docx_format_paragraph(cells[1].paragraphs[0], color=text_color, size=7.7)

    def feature_flags(feature: Mapping[str, Any]) -> Mapping[str, Any]:
        return feature.get("open") if isinstance(feature.get("open"), Mapping) else {}

    features = [
        blocks[f"spec-feature-{index}"] for index in range(1, 4)
        if f"spec-feature-{index}" in blocks
        and not (feature_flags(blocks[f"spec-feature-{index}"]).get("title")
                 and feature_flags(blocks[f"spec-feature-{index}"]).get("text"))
    ]
    if features and shown("features-heading"):
        features_heading = output.add_paragraph(
            str((blocks.get("features-heading") or {}).get("text") or "Key Features")
        )
        features_heading.paragraph_format.space_before = Pt(8)
        features_heading.paragraph_format.space_after = Pt(4)
        _docx_format_paragraph(
            features_heading,
            color=primary,
            size=12,
            bold=True,
            font_name=heading_font,
        )
    if features:
        feature_table = output.add_table(rows=1, cols=len(features))
        feature_table.autofit = False
        _docx_clear_table_borders(feature_table)
        feature_width = content_width / len(features)
    for index, feature in enumerate(features):
        flags = feature_flags(feature)
        cell = feature_table.cell(0, index)
        cell.width = Inches(feature_width)
        _docx_shade_cell(cell, "F3F7F9")
        _docx_set_cell_border(cell, "top", accent, 18)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        heading = cell.paragraphs[0]
        if not flags.get("title"):
            heading.add_run(str(feature.get("title") or "Feature"))
            heading.paragraph_format.space_after = Pt(3)
            _docx_format_paragraph(heading, color=primary, size=8.5, bold=True)
        if not flags.get("text"):
            detail = cell.add_paragraph(str(feature.get("text") or ""))
            detail.paragraph_format.space_after = Pt(0)
            _docx_format_paragraph(detail, color=text_color, size=7.2)

    output.core_properties.title = str(
        document.get("title") or "Product Specification Sheet"
    )
    output.core_properties.author = str(theme.get("companyName") or "InspectorPro")
    output.core_properties.subject = "Evidence-bound product specification sheet"
    output.core_properties.keywords = (
        f"InspectorPro, {assembly_number}, product specification sheet"
    )
    buffer = io.BytesIO()
    output.save(buffer)
    return buffer.getvalue()


def _document_directory(root: str | Path, assembly_number: str, revision: str) -> Path:
    base = Path(root).resolve()
    directory = (
        base
        / _safe(assembly_number, "assembly number").lower()
        / "documents"
        / _safe(revision, "document revision")
    ).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise SpecificationSheetExportError("invalid specification-sheet export path") from exc
    return directory


def store_specification_pdf(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    revision = str(document.get("documentRevision") or "")
    payload = build_specification_pdf_bytes(
        document,
        render_root=root,
        assembly_number=assembly_number,
    )
    directory = _document_directory(root, assembly_number, revision)
    filename = f"{_safe(assembly_number, 'assembly number')}-specification-sheet.pdf"
    path = directory / filename
    _write_atomic(path, payload)
    artifact = {
        "status": "ready",
        "reviewOnly": True,
        "controlledRelease": False,
        "documentRevision": revision,
        "pageCount": 1,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "url": f"/api/specification-sheet/{assembly_number}/documents/{revision}/pdf",
    }
    _write_atomic(
        directory / "pdf.json",
        (json.dumps(artifact, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    return copy.deepcopy(artifact)


def store_specification_fillable_pdf(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    revision = str(document.get("documentRevision") or "")
    payload, fields = build_specification_fillable_pdf_bytes(
        document,
        render_root=root,
        assembly_number=assembly_number,
    )
    directory = _document_directory(root, assembly_number, revision)
    filename = f"{_safe(assembly_number, 'assembly number')}-specification-sheet-fillable.pdf"
    _write_atomic(directory / filename, payload)
    artifact = {
        "status": "ready",
        "reviewOnly": True,
        "controlledRelease": False,
        "fillable": True,
        "documentRevision": revision,
        "pageCount": 1,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "fieldCount": len(fields),
        "openFields": [{"slot": field["name"], "name": field["label"]} for field in fields],
        "url": f"/api/specification-sheet/{assembly_number}/documents/{revision}/fillable-pdf",
    }
    _write_atomic(
        directory / "fillable.json",
        (json.dumps(artifact, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    return copy.deepcopy(artifact)


def specification_fillable_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    directory = _document_directory(root, assembly_number, document_revision)
    path = directory / f"{_safe(assembly_number, 'assembly number')}-specification-sheet-fillable.pdf"
    if not os.path.isfile(_filesystem_path(path)):
        raise SpecificationSheetExportError("fillable specification-sheet PDF not found")
    return Path(_filesystem_path(path))


def store_specification_docx(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    revision = str(document.get("documentRevision") or "")
    payload = build_specification_docx_bytes(
        document,
        render_root=root,
        assembly_number=assembly_number,
    )
    directory = _document_directory(root, assembly_number, revision)
    filename = f"{_safe(assembly_number, 'assembly number')}-specification-sheet.docx"
    path = directory / filename
    _write_atomic(path, payload)
    artifact = {
        "status": "ready",
        "reviewOnly": True,
        "controlledRelease": False,
        "documentRevision": revision,
        "pageCount": 1,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "mimeType": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "rendererVersion": "specification-sheet-docx-v1",
        "url": f"/api/specification-sheet/{assembly_number}/documents/{revision}/docx",
    }
    _write_atomic(
        directory / "docx.json",
        (json.dumps(artifact, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    return copy.deepcopy(artifact)


def specification_export_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    directory = _document_directory(root, assembly_number, document_revision)
    path = directory / f"{_safe(assembly_number, 'assembly number')}-specification-sheet.pdf"
    if not os.path.isfile(_filesystem_path(path)):
        raise SpecificationSheetExportError("specification-sheet export not found")
    return Path(_filesystem_path(path))


def specification_docx_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    directory = _document_directory(root, assembly_number, document_revision)
    metadata_path = directory / "docx.json"
    if not os.path.isfile(_filesystem_path(metadata_path)):
        raise SpecificationSheetExportError("specification-sheet DOCX export not found")
    try:
        with open(_filesystem_path(metadata_path), "r", encoding="ascii") as handle:
            artifact = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecificationSheetExportError(
            "specification-sheet DOCX metadata is invalid"
        ) from exc
    path = directory / _safe(artifact.get("filename"), "filename")
    if not os.path.isfile(_filesystem_path(path)):
        raise SpecificationSheetExportError("specification-sheet DOCX export not found")
    return Path(_filesystem_path(path))
