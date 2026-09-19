"""One-page PDF export for evidence-bound product specification sheets."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Dict, Mapping

from ai_inspector.operations_manual.artifacts import draft_render_path


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


def _insert_textbox_checked(page: Any, rect: Any, text: str, **kwargs: Any) -> None:
    remaining = page.insert_textbox(rect, str(text or ""), **kwargs)
    if remaining < -0.01:
        raise SpecificationSheetExportError(f"specification-sheet text overflow: {text[:80]}")


def build_specification_pdf_bytes(
    document: Mapping[str, Any],
    *,
    render_root: str | Path,
    assembly_number: str,
) -> bytes:
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
    for block_id in ("spec-kicker", "spec-title", "spec-tagline", "features-heading"):
        block = blocks.get(block_id) or {}
        frame = block.get("frame") or {}
        style = block.get("style") or {}
        rect = fitz.Rect(
            float(frame.get("x") or 0),
            float(frame.get("y") or 0),
            float(frame.get("x") or 0) + float(frame.get("width") or 0),
            float(frame.get("y") or 0) + float(frame.get("height") or 0),
        )
        _insert_textbox_checked(
            page,
            rect,
            str(block.get("text") or ""),
            fontname="hebo" if int(style.get("fontWeight") or 400) >= 600 else "helv",
            fontsize=float(style.get("fontSize") or 9),
            color=_rgb(style.get("color"), "#18212A"),
            lineheight=max(1.0, float(style.get("lineHeight") or 12) / max(1.0, float(style.get("fontSize") or 9))),
        )

    figure_block = blocks.get("spec-figure") or {}
    figure_frame = figure_block.get("frame") or {}
    figure_bounds = fitz.Rect(
        float(figure_frame.get("x") or 36),
        float(figure_frame.get("y") or 176),
        float(figure_frame.get("x") or 36) + float(figure_frame.get("width") or 318),
        float(figure_frame.get("y") or 176) + float(figure_frame.get("height") or 346) - 18,
    )
    image_path = draft_render_path(
        render_root,
        assembly_number,
        str(document.get("documentRevision") or ""),
        str(descriptor.get("pageId") or ""),
    )
    page.insert_image(_fit_image_rect(fitz, figure_bounds, image_path), filename=_filesystem_path(image_path))
    page.draw_rect(figure_bounds, color=rule, width=0.6)
    caption_rect = fitz.Rect(figure_bounds.x0, figure_bounds.y1 + 2, figure_bounds.x1, figure_bounds.y1 + 16)
    _insert_textbox_checked(
        page,
        caption_rect,
        str(figure_block.get("caption") or ""),
        fontname="helv",
        fontsize=6.5,
        color=muted,
        align=1,
    )

    heading = blocks.get("specifications-heading") or {}
    heading_frame = heading.get("frame") or {}
    _insert_textbox_checked(
        page,
        fitz.Rect(
            float(heading_frame.get("x") or 374),
            float(heading_frame.get("y") or 176),
            float(heading_frame.get("x") or 374) + float(heading_frame.get("width") or 202),
            float(heading_frame.get("y") or 176) + float(heading_frame.get("height") or 20),
        ),
        str(heading.get("text") or "Specifications"),
        fontname="hebo",
        fontsize=15,
        color=primary,
    )
    table = blocks.get("specifications-table") or {}
    table_frame = table.get("frame") or {}
    x = float(table_frame.get("x") or 374)
    y = float(table_frame.get("y") or 198)
    table_width = float(table_frame.get("width") or 202)
    split = x + table_width * 0.58
    row_height = float(table_frame.get("height") or 324) / max(1, len(table.get("rows") or []))
    for index, row in enumerate(table.get("rows") or []):
        top = y + row_height * index
        bottom = top + row_height
        page.draw_line(fitz.Point(x, bottom), fitz.Point(x + table_width, bottom), color=rule, width=0.55)
        cells = list(row.get("cells") or [])
        _insert_textbox_checked(
            page, fitz.Rect(x, top + 7, split - 5, bottom - 4),
            str(cells[0] if cells else ""), fontname="hebo", fontsize=7.8,
            color=text_color,
        )
        _insert_textbox_checked(
            page, fitz.Rect(split, top + 7, x + table_width, bottom - 4),
            str(cells[1] if len(cells) > 1 else ""), fontname="helv", fontsize=7.8,
            color=text_color, align=2,
        )

    for index in range(3):
        block = blocks.get(f"spec-feature-{index + 1}") or {}
        frame = block.get("frame") or {}
        rect = fitz.Rect(
            float(frame.get("x") or 0),
            float(frame.get("y") or 0),
            float(frame.get("x") or 0) + float(frame.get("width") or 0),
            float(frame.get("y") or 0) + float(frame.get("height") or 0),
        )
        page.draw_line(fitz.Point(rect.x0, rect.y0), fitz.Point(rect.x0 + 34, rect.y0), color=accent, width=3)
        _insert_textbox_checked(
            page, fitz.Rect(rect.x0, rect.y0 + 11, rect.x1, rect.y0 + 40),
            str(block.get("title") or ""), fontname="hebo", fontsize=9.2,
            color=primary,
        )
        _insert_textbox_checked(
            page, fitz.Rect(rect.x0, rect.y0 + 42, rect.x1, rect.y1),
            str(block.get("text") or ""), fontname="helv", fontsize=7.6,
            color=text_color, lineheight=1.35,
        )
        if index:
            page.draw_line(
                fitz.Point(rect.x0 - 9, rect.y0),
                fitz.Point(rect.x0 - 9, rect.y1 - 10),
                color=rule,
                width=0.45,
            )

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
    pdf.set_metadata(
        {
            "title": str(document.get("title") or "Product Specification Sheet"),
            "author": str(theme.get("companyName") or "InspectorPro"),
            "subject": "Evidence-bound product specification sheet",
            "keywords": f"InspectorPro,{assembly_number},specification sheet",
        }
    )
    payload = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    return payload


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
    kicker = output.add_paragraph(str((blocks.get("spec-kicker") or {}).get("text") or "PRODUCT SPECIFICATION"))
    kicker.paragraph_format.space_after = Pt(2)
    _docx_format_paragraph(kicker, color=accent, size=8.5, bold=True, font_name=heading_font)
    title = output.add_paragraph(str((blocks.get("spec-title") or {}).get("text") or product_name))
    title.style = styles["Title"]
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(2)
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
        str(document.get("documentRevision") or ""),
        str(descriptor.get("pageId") or ""),
    )
    image_paragraph = image_cell.paragraphs[0]
    image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image_paragraph.add_run().add_picture(
        _filesystem_path(image_path),
        width=Inches(max(2.5, image_width - 0.18)),
    )
    caption = image_cell.add_paragraph(
        str((blocks.get("spec-figure") or {}).get("caption") or "")
    )
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.space_before = Pt(2)
    caption.paragraph_format.space_after = Pt(0)
    _docx_format_paragraph(caption, color=muted, size=6.5, font_name=body_font)

    specifications_heading = specification_cell.paragraphs[0]
    specifications_heading.add_run("Specifications")
    specifications_heading.paragraph_format.space_after = Pt(3)
    _docx_format_paragraph(
        specifications_heading,
        color=primary,
        size=13,
        bold=True,
        font_name=heading_font,
    )
    specifications = list(descriptor.get("specifications") or [])
    specifications_table = specification_cell.add_table(
        rows=max(1, len(specifications)), cols=2
    )
    specifications_table.autofit = False
    for index, specification in enumerate(specifications):
        cells = specifications_table.rows[index].cells
        cells[0].text = str(specification.get("label") or "Specification")
        cells[1].text = str(specification.get("value") or "")
        cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for cell in cells:
            _docx_set_cell_border(cell, "bottom", rule, 4)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _docx_format_paragraph(cells[0].paragraphs[0], color=text_color, size=7.7, bold=True)
        _docx_format_paragraph(cells[1].paragraphs[0], color=text_color, size=7.7)

    features_heading = output.add_paragraph("Key Features")
    features_heading.paragraph_format.space_before = Pt(8)
    features_heading.paragraph_format.space_after = Pt(4)
    _docx_format_paragraph(
        features_heading,
        color=primary,
        size=12,
        bold=True,
        font_name=heading_font,
    )
    features = list(descriptor.get("features") or [])
    feature_table = output.add_table(rows=1, cols=max(1, len(features)))
    feature_table.autofit = False
    _docx_clear_table_borders(feature_table)
    feature_width = content_width / max(1, len(features))
    for index, feature in enumerate(features):
        cell = feature_table.cell(0, index)
        cell.width = Inches(feature_width)
        _docx_shade_cell(cell, "F3F7F9")
        _docx_set_cell_border(cell, "top", accent, 18)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        heading = cell.paragraphs[0]
        heading.add_run(str(feature.get("title") or "Feature"))
        heading.paragraph_format.space_after = Pt(3)
        _docx_format_paragraph(heading, color=primary, size=8.5, bold=True)
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
