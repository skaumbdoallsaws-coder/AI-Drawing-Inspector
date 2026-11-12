"""PDF and editable DOCX exporters for operations manuals."""

from __future__ import annotations

import copy
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, Iterable, Mapping, Sequence
import uuid

from ai_inspector.parts_manual.pdf import draw_balloon_manifest

from ai_inspector.documentation.conflict_exports import marker as conflict_marker, mark_pdf, mark_docx
from ai_inspector.documentation.provenance import EDITED_MARKER, EDITED_LEGEND, check_export, export_document
from .artifacts import document_draft_render_path
from .flow import wrap_text


class OperationsManualExportError(RuntimeError):
    pass


_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")
_EXPORT_LOCK = threading.RLock()
_DOCX_RENDERER_VERSION = "operations-docx-rich-v5"


def _safe(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if _SAFE_RE.fullmatch(text) is None:
        raise OperationsManualExportError(f"invalid {label}")
    return text


def _filesystem_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".tmp-operations-export-{uuid.uuid4().hex}{path.suffix}"
    )
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


def _document_directory(
    root: str | Path, assembly_number: str, document_revision: str
) -> Path:
    base = Path(root).resolve()
    directory = (
        base
        / _safe(assembly_number, "assembly number").lower()
        / "documents"
        / _safe(document_revision, "document revision")
    ).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise OperationsManualExportError("invalid export path") from exc
    return directory


def prototype_export_readiness(document: Mapping[str, Any]) -> Dict[str, Any]:
    pending: list[Dict[str, Any]] = []
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping) or not isinstance(page.get("renderRequest"), Mapping):
            continue
        image = page["renderRequest"].get("image") or {}
        if image.get("status") != "ready" or image.get("documentRevision") != document.get("documentRevision"):
            pending.append({
                "pageId": str(page.get("pageId") or ""),
                "pageNumber": int(page.get("pageNumber") or 0),
                "title": str(page.get("title") or "Technical figure"),
            })
    return {
        "status": "READY" if not pending else "CAPTURE_REQUIRED",
        "pendingPages": pending,
        "requiredCaptureCount": len(pending),
    }


def _page_override(page: Mapping[str, Any], block_id: str) -> Mapping[str, Any]:
    stable = page.get("identityOverrides", {}).get(block_id)
    if isinstance(stable, Mapping):
        return stable
    composition = page.get("documentationComposition")
    if not isinstance(composition, Mapping):
        return {}
    overrides = composition.get("pageElementOverrides")
    if not isinstance(overrides, Mapping):
        return {}
    value = overrides.get(block_id)
    return value if isinstance(value, Mapping) else {}


def _block_frame(
    page: Mapping[str, Any],
    block: Mapping[str, Any],
    document: Mapping[str, Any],
) -> Dict[str, float]:
    frame = block.get("frame") if isinstance(block.get("frame"), Mapping) else {}
    result = {
        "x": float(frame.get("x") or 0),
        "y": float(frame.get("y") or 0),
        "width": float(frame.get("width") or 0),
        "height": float(frame.get("height") or 0),
    }
    override = _page_override(page, str(block.get("blockId") or ""))
    translation = override.get("translation") if isinstance(override.get("translation"), Sequence) else []
    size_delta = override.get("sizeDelta") if isinstance(override.get("sizeDelta"), Sequence) else []
    page_width, page_height, _ = _publication_page_geometry(document)
    result["x"] += (float(translation[0]) if len(translation) > 0 else 0.0) * page_width
    result["y"] += (float(translation[1]) if len(translation) > 1 else 0.0) * page_height
    result["width"] = max(
        24.0,
        result["width"]
        + (float(size_delta[0]) if len(size_delta) > 0 else 0.0) * page_width,
    )
    result["height"] = max(
        24.0,
        result["height"]
        + (float(size_delta[1]) if len(size_delta) > 1 else 0.0) * page_height,
    )
    return result


def _edited_block(page: Mapping[str, Any], block: Mapping[str, Any]) -> Mapping[str, Any]:
    """The block as the user edited it on its page: a table cell's text ("<block>.r<row>.c<column>"), a list
    item's text ("<block>.i<item>") or a figure's caption (the block's own text)."""
    block_id = str(block.get("blockId") or "")
    block_type = str(block.get("blockType") or "")
    if block_type in {"table", "key_value_table"}:
        rows = []
        for row_index, row in enumerate(block.get("rows") or []):
            if not isinstance(row, Mapping):
                rows.append(row)
                continue
            cells = list(row.get("cells") or [])
            for column in range(len(cells)):
                override = _page_override(page, (row.get("cellIds") or [])[column]) if column < len(row.get("cellIds") or []) else {}
                if not override:
                    override = _page_override(page, f"{block_id}.r{row_index}.c{column}")
                if "text" in override:
                    cells[column] = str(override.get("text") or "")
            rows.append({**row, "cells": cells})
        return {**block, "rows": rows}
    if block_type in {"list", "figure_legend"}:
        items = []
        for item_index, item in enumerate(block.get("items") or []):
            override = (_page_override(page, item.get("itemId", "")) or
                        _page_override(page, f"{block_id}.i{item_index}")) if isinstance(item, Mapping) else {}
            items.append({**item, "text": str(override.get("text") or "")} if "text" in override else item)
        return {**block, "items": items}
    if block_type == "cad_figure":
        override = _page_override(page, block_id)
        if "text" in override:
            return {**block, "caption": str(override.get("text") or "")}
    return block


def _block_text(page: Mapping[str, Any], block: Mapping[str, Any]) -> str:
    override = _page_override(page, str(block.get("blockId") or ""))
    if "richText" in override:
        from ai_inspector.documentation.rich_text import plain_text
        return plain_text(override["richText"])
    if "text" in override:
        return str(override.get("text") or "")
    return str(block.get("text") or "\n".join(block.get("lines") or []))


def _rgb(hex_value: Any, fallback: str) -> tuple[float, float, float]:
    value = str(hex_value or fallback).strip().lstrip("#")
    if len(value) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = fallback.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4))


def _hex_color(hex_value: Any, fallback: str) -> str:
    value = str(hex_value or fallback).strip().lstrip("#")
    if len(value) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = fallback.strip().lstrip("#")
    return value.upper()


def _layout_rect(fitz: Any, layout: Mapping[str, Any], name: str) -> Any:
    value = layout.get(name) or {}
    x = float(value.get("x") or 0)
    y = float(value.get("y") or 0)
    return fitz.Rect(
        x,
        y,
        x + float(value.get("width") or 0),
        y + float(value.get("height") or 0),
    )


def _fit_image_rect(fitz: Any, bounds: Any, image_path: Path) -> Any:
    pixmap = fitz.Pixmap(str(image_path))
    width, height = max(1, pixmap.width), max(1, pixmap.height)
    ratio = min(bounds.width / width, bounds.height / height)
    fitted_width = width * ratio
    fitted_height = height * ratio
    return fitz.Rect(
        bounds.x0 + (bounds.width - fitted_width) * 0.5,
        bounds.y0 + (bounds.height - fitted_height) * 0.5,
        bounds.x0 + (bounds.width + fitted_width) * 0.5,
        bounds.y0 + (bounds.height + fitted_height) * 0.5,
    )


def _publication_page_geometry(
    document: Mapping[str, Any],
) -> tuple[float, float, Mapping[str, Any]]:
    layout = document.get("publicationLayout") or {}
    page = layout.get("page") or {}
    width = float(page.get("width") or 960.0)
    height = float(page.get("height") or 540.0)
    if width <= 0 or height <= 0:
        raise OperationsManualExportError("publication page dimensions are invalid")
    return width, height, layout


def _draw_header_footer(fitz: Any, page: Any, descriptor: Mapping[str, Any], document: Mapping[str, Any]) -> None:
    if descriptor.get("pageType") == "operations_cover":
        return
    from ai_inspector.documentation.layout import document_geometry
    geometry = document_geometry(document)
    from ai_inspector.documentation import fit
    navy = (0.027, 0.106, 0.165)
    accent = (0.263, 0.710, 0.933)
    muted = (0.35, 0.42, 0.47)
    page_width, _, layout = _publication_page_geometry(document)
    shared = layout.get("shared") or {}
    header = shared.get("header") or {
        "x": 0, "y": 0, "width": page_width, "height": 56
    }
    footer = shared.get("footer") or {
        "x": 40, "y": 516, "width": page_width - 80, "height": 16
    }
    header_rect = fitz.Rect(
        float(header.get("x") or 0),
        float(header.get("y") or 0),
        float(header.get("x") or 0) + float(header.get("width") or page_width),
        float(header.get("y") or 0) + float(header.get("height") or 56),
    )
    footer_rect = fitz.Rect(
        float(footer.get("x") or 40),
        float(footer.get("y") or 516),
        float(footer.get("x") or 40) + float(footer.get("width") or page_width - 80),
        float(footer.get("y") or 516) + float(footer.get("height") or 16),
    )
    page.draw_rect(header_rect, color=None, fill=navy)
    page.draw_rect(
        fitz.Rect(header_rect.x0, header_rect.y1 - 3, header_rect.x1, header_rect.y1),
        color=None,
        fill=accent,
    )
    brand_x = header_rect.x0 + geometry.x(40)
    brand_baseline = header_rect.y0 + min(geometry.y(35), header_rect.height - 14)
    fit.target(page, descriptor, "header_brand")
    page.insert_text(fitz.Point(brand_x, brand_baseline), "Inspector", fontsize=13, fontname="hebo", color=(1, 1, 1))
    inspector_width = fitz.get_text_length("Inspector", fontname="hebo", fontsize=13)
    page.insert_text(fitz.Point(brand_x + inspector_width, brand_baseline), "Pro", fontsize=13, fontname="hebo", color=accent)
    fit.target(page, descriptor, "header_title")
    page.insert_textbox(
        fitz.Rect((page_width * 0.43 if geometry.identity else geometry.x(960 * 0.43)), header_rect.y0 + geometry.y(16), header_rect.x1 - geometry.x(40), header_rect.y1 - 9),
        str(descriptor.get("title") or "Operations and Maintenance Manual"),
        fontsize=9.2,
        fontname="hebo",
        color=(1, 1, 1),
        align=fitz.TEXT_ALIGN_RIGHT,
    )
    page.draw_line(
        fitz.Point(footer_rect.x0, footer_rect.y0),
        fitz.Point(footer_rect.x1, footer_rect.y0),
        color=(0.67, 0.73, 0.77),
        width=0.55,
    )
    status_label = str(document.get("statusLabel") or "DRAFT")
    left = (
        f"{document.get('product', {}).get('name') or 'Product'} | "
        f"{document.get('documentNumber') or 'Document number not specified'} | "
        f"{status_label}"
    )
    fit.target(page, descriptor, "footer")
    page.insert_textbox(
        fitz.Rect(footer_rect.x0, footer_rect.y0 + 4, footer_rect.x1 - geometry.x(130), footer_rect.y1),
        left,
        fontsize=6.2,
        fontname="helv",
        color=muted,
    )
    fit.target(page, descriptor, "footer_page_number")
    page.insert_textbox(
        fitz.Rect(footer_rect.x1 - geometry.x(120), footer_rect.y0 + 4, footer_rect.x1, footer_rect.y1),
        f"Page {descriptor.get('pageNumber')} of {document.get('pageCount')}",
        fontsize=6.2,
        fontname="helv",
        color=muted,
        align=fitz.TEXT_ALIGN_RIGHT,
    )


def _marked(owner):
    return bool(owner.get("manualConflicts")) or (owner.get("provenance") or {}).get("evidenceStatus") == "edited_unverified"


def _has_marked(block):
    return _marked(block) or any(_marked(row) for row in (block.get("rows") or block.get("items") or []))


def _review_marks(document):
    return document.get("exportMode", "review") in {"review", "draft"}


def _draw_table(fitz: Any, page: Any, block: Mapping[str, Any], rect: Any) -> None:
    columns = [str(value) for value in block.get("columns") or []]
    rows = [row for row in block.get("rows") or [] if isinstance(row, Mapping)]
    if not columns:
        return
    column_width = rect.width / len(columns)
    header_height = 25.0
    row_heights = [float(value) for value in block.get("rowHeights") or []]
    if len(row_heights) != len(rows):
        row_height = max(20.0, (rect.height - header_height) / max(1, len(rows)))
        row_heights = [row_height] * len(rows)
    from ai_inspector.documentation import fit
    if header_height + sum(row_heights) > rect.height + .01:
        fit.failure(page, measuredHeight=header_height + sum(row_heights))
    if column_width < 12:
        fit.failure(page, "column_too_narrow")
    rule = (0.48, 0.54, 0.58)
    light = (0.77, 0.81, 0.84)
    page.draw_rect(rect, color=rule, fill=(1, 1, 1), width=0.6)
    page.draw_rect(fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + header_height), color=None, fill=(0.93, 0.96, 0.98))
    for index, label in enumerate(columns):
        cell = fitz.Rect(rect.x0 + index * column_width + 5, rect.y0 + 7, rect.x0 + (index + 1) * column_width - 5, rect.y0 + header_height - 2)
        page.insert_textbox(cell, label.upper(), fontsize=6.6, fontname="hebo", color=(0.03, 0.19, 0.29))
    y = rect.y0 + header_height
    page.draw_line(fitz.Point(rect.x0, y), fitz.Point(rect.x1, y), color=rule, width=0.8)
    for row, row_height in zip(rows, row_heights):
        bottom = min(rect.y1, y + row_height)
        cells = [str(value or "") for value in row.get("cells") or []]
        for index in range(len(columns)):
            value = cells[index] if index < len(cells) else ""
            cell = fitz.Rect(rect.x0 + index * column_width + 5, y + 5, rect.x0 + (index + 1) * column_width - 5, bottom - 3)
            page.insert_textbox(cell, value, fontsize=6.7, fontname="helv", color=(0.10, 0.14, 0.17), lineheight=1.15)
        if _marked(row):
            page.insert_text(fitz.Point(rect.x0 + column_width * (len(columns) - 1) + 5, bottom - 2),
                             conflict_marker(row, EDITED_MARKER), fontsize=5.5, fontname="helv", color=(0.6, 0.22, 0.02))
        page.draw_line(fitz.Point(rect.x0, bottom), fitz.Point(rect.x1, bottom), color=light, width=0.35)
        y = bottom
    for index in range(1, len(columns)):
        x = rect.x0 + index * column_width
        page.draw_line(fitz.Point(x, rect.y0), fitz.Point(x, rect.y1), color=light, width=0.35)


_SAFETY_SYMBOL_STYLES = {
    "DANGER": {"kind": "safety_alert", "color": (0.78, 0.04, 0.09)},
    "WARNING": {"kind": "safety_alert", "color": (0.93, 0.39, 0.05)},
    "CAUTION": {"kind": "safety_alert", "color": (0.90, 0.67, 0.03)},
    "NOTICE": {"kind": "notice_information", "color": (0.03, 0.43, 0.67)},
}


def _safety_symbol_semantics(signal_word: str) -> Dict[str, Any]:
    return copy.deepcopy(
        _SAFETY_SYMBOL_STYLES.get(
            str(signal_word or "NOTICE").upper(),
            _SAFETY_SYMBOL_STYLES["NOTICE"],
        )
    )


def _insert_htmlbox_checked(
    page: Any,
    rect: Any,
    body: str,
    *,
    css: str,
    context: str,
) -> tuple[float, float]:
    from ai_inspector.documentation import fit
    if (rect.width <= 0 or rect.height <= 0) and fit.failure(page, frame=list(rect)):
        return -1.0, 1.0
    result = page.insert_htmlbox(
        rect,
        body,
        css=css,
        scale_low=1,
    )
    if not isinstance(result, tuple) or len(result) != 2:
        raise OperationsManualExportError(
            f"{context} did not return measurable text-fit evidence"
        )
    spare_height, scale = float(result[0]), float(result[1])
    if spare_height < -1e-6 or scale < 0.999999:
        from ai_inspector.documentation import fit
        if fit.failure(page, frame=list(rect)):
            return spare_height, scale
        raise OperationsManualExportError(
            f"{context} does not fit its reserved publication frame"
        )
    return spare_height, scale


def _draw_safety_symbol(
    fitz: Any, page: Any, rect: Any, signal_word: str
) -> None:
    semantics = _safety_symbol_semantics(signal_word)
    accent = tuple(semantics["color"])
    ink = (0.14, 0.16, 0.17)
    center_x = rect.x0 + 26
    top = rect.y0 + 2
    if semantics["kind"] == "notice_information":
        center = fitz.Point(center_x, top + 19)
        page.draw_circle(center, 18, color=accent, width=2.5)
        page.draw_circle(
            fitz.Point(center_x, top + 10),
            1.8,
            color=None,
            fill=accent,
        )
        page.draw_line(
            fitz.Point(center_x, top + 16),
            fitz.Point(center_x, top + 29),
            color=accent,
            width=3.2,
            lineCap=1,
        )
        return
    left = fitz.Point(center_x - 21, top + 37)
    right = fitz.Point(center_x + 21, top + 37)
    apex = fitz.Point(center_x, top)
    page.draw_line(apex, right, color=accent, width=2.5)
    page.draw_line(right, left, color=accent, width=2.5)
    page.draw_line(left, apex, color=accent, width=2.5)
    page.draw_line(
        fitz.Point(center_x, top + 12),
        fitz.Point(center_x, top + 25),
        color=ink,
        width=3.2,
        lineCap=1,
    )
    page.draw_circle(fitz.Point(center_x, top + 31), 1.7, color=None, fill=ink)


def _draw_note(fitz: Any, page: Any, block: Mapping[str, Any], rect: Any, text: str) -> None:
    signal_word = str(
        block.get("signalWord") or block.get("tone") or "notice"
    ).upper()
    _draw_safety_symbol(fitz, page, rect, signal_word)
    body = (
        f"<div><b>{html.escape(signal_word)}</b> "
        f"{html.escape(text)}</div>"
    )
    _insert_htmlbox_checked(
        page,
        fitz.Rect(rect.x0 + 64, rect.y0 + 5, rect.x1, rect.y1 - 3),
        body,
        css=(
            "div { font-family: Arial, sans-serif; font-size: 8.4pt; "
            "line-height: 1.28; color: #18212a; } "
            "b { font-weight: 700; }"
        ),
        context=f"safety note {block.get('blockId') or 'unknown'}",
    )


def _draw_list(fitz: Any, page: Any, block: Mapping[str, Any], rect: Any) -> None:
    items = [row for row in block.get("items") or [] if isinstance(row, Mapping)]
    if not items:
        return
    style = str(block.get("listStyle") or "numbered")
    columns = max(1, min(2, int(block.get("columns") or 1)))
    gap = float(block.get("columnGap") or (22 if columns == 2 else 0))
    column_width = (rect.width - ((columns - 1) * gap)) / columns
    row_heights = [float(value) for value in block.get("rowHeights") or []]
    font_size = float(block.get("fontSize") or (7.8 if style == "keyed" else 9.4))
    y = rect.y0
    item_index = 0
    rows = (len(items) + columns - 1) // columns
    from ai_inspector.documentation import fit
    measured_height = sum(row_heights[i] if i < len(row_heights) else 24.0 for i in range(rows))
    if measured_height > rect.height + .01:
        fit.failure(page, measuredHeight=measured_height)
    if column_width < 12:
        fit.failure(page, "column_too_narrow")
    for row_index in range(rows):
        row_height = row_heights[row_index] if row_index < len(row_heights) else 24.0
        for column in range(columns):
            if item_index >= len(items):
                break
            item = items[item_index]
            x = rect.x0 + column * (column_width + gap)
            marker_width = 24.0 if style in {"numbered", "keyed"} else 0.0
            if style == "keyed":
                center = fitz.Point(x + 9, y + 9)
                page.draw_circle(center, 8, color=(0.07, 0.09, 0.10), width=0.75)
                page.insert_textbox(
                    fitz.Rect(x + 1, y + 3.5, x + 17, y + 15),
                    str(item.get("itemNumber") or item_index + 1),
                    fontsize=6.2,
                    fontname="hebo",
                    color=(0.07, 0.09, 0.10),
                    align=fitz.TEXT_ALIGN_CENTER,
                )
            elif style == "numbered":
                page.insert_textbox(
                    fitz.Rect(x, y + 1, x + 20, y + row_height),
                    f"{item.get('itemNumber') or item_index + 1}.",
                    fontsize=font_size,
                    fontname="hebo",
                    color=(0.10, 0.13, 0.15),
                    align=fitz.TEXT_ALIGN_RIGHT,
                )
            label = str(item.get("label") or "")
            text = str(item.get("text") or "")
            quantity = int(item.get("quantity") or 1)
            body = ""
            if label:
                body += f"<b>{html.escape(label)}</b>"
                if text:
                    body += ": "
            body += html.escape(text)
            if quantity > 1:
                body += f" <b>({quantity}X)</b>"
            _insert_htmlbox_checked(
                page,
                fitz.Rect(
                    x + marker_width + (3 if marker_width else 0),
                    y,
                    x + column_width,
                    y + row_height,
                ),
                f"<div>{body}</div>",
                css=(
                    f"div {{ font-family: Arial, sans-serif; font-size: {font_size}pt; "
                    "line-height: 1.22; color: #18212a; } "
                    "b { font-weight: 700; }"
                ),
                context=(
                    f"{block.get('blockType') or 'list'} "
                    f"{block.get('blockId') or 'unknown'} item "
                    f"{item.get('itemNumber') or item_index + 1}"
                ),
            )
            if _marked(item):
                page.insert_text(fitz.Point(x + marker_width + 3, y + row_height - 1),
                                 conflict_marker(item, EDITED_MARKER), fontsize=5.5, fontname="helv", color=(0.6, 0.22, 0.02))
            item_index += 1
        y += row_height


def _draw_contents(fitz: Any, page: Any, block: Mapping[str, Any], rect: Any) -> None:
    y = rect.y0
    ink = (0.12, 0.13, 0.14)
    muted = (0.55, 0.58, 0.60)
    entries = [row for row in block.get("entries") or [] if isinstance(row, Mapping)]
    row_height = min(24.0, max(18.0, rect.height / max(1, len(entries))))
    if entries and (len(entries) - 1) * row_height + 11 > rect.height:
        from ai_inspector.documentation import fit
        fit.failure(page, measuredHeight=(len(entries) - 1) * row_height + 11)
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        title = str(entry.get("title") or "Section")
        page_text = str(entry.get("pageNumber") or "")
        baseline = y + 11
        page.insert_text(
            fitz.Point(rect.x0, baseline),
            title,
            fontsize=9.2,
            fontname="hebo",
            color=ink,
        )
        title_width = fitz.get_text_length(title, fontname="hebo", fontsize=9.2)
        page_width = fitz.get_text_length(page_text, fontname="hebo", fontsize=9.2)
        line_start = rect.x0 + title_width + 8
        line_end = rect.x1 - page_width - 10
        x = line_start
        while x < line_end:
            page.draw_line(
                fitz.Point(x, baseline - 1),
                fitz.Point(min(x + 1.4, line_end), baseline - 1),
                color=muted,
                width=0.45,
            )
            x += 4.0
        page.insert_text(
            fitz.Point(rect.x1 - page_width, baseline),
            page_text,
            fontsize=9.2,
            fontname="hebo",
            color=ink,
        )
        y += row_height


def _draw_block(
    fitz: Any,
    page: Any,
    descriptor: Mapping[str, Any],
    block: Mapping[str, Any],
    document: Mapping[str, Any],
    root: str | Path,
    assembly_number: str,
    rich_plan=None,
) -> None:
    if rich_plan is not None:
        from ai_inspector.documentation.rich_blocks import block_frame
        frame = block_frame(document, descriptor, block)
    else:
        frame = _block_frame(descriptor, block, document)
    rect = fitz.Rect(frame["x"], frame["y"], frame["x"] + frame["width"], frame["y"] + frame["height"])
    from ai_inspector.documentation import fit
    fit.target(page, descriptor, block.get("stableId") or block.get("blockId"), rect)
    block = _edited_block(descriptor, block)
    block_type = str(block.get("blockType") or "")
    text = _block_text(descriptor, block)
    if _review_marks(document) and _has_marked(block):
        label = (conflict_marker(block, EDITED_MARKER) + ". " if _marked(block) else "") + EDITED_LEGEND
        page.insert_text(fitz.Point(rect.x0, rect.y1 + 6), label, fontsize=5.5,
                         fontname="helv", color=(0.6, 0.22, 0.02))
    style = dict(block.get("style") or {})
    override = _page_override(descriptor, str(block.get("blockId") or ""))
    if isinstance(override.get("style"), Mapping):
        style.update(override["style"])
    if rich_plan is not None and block_type != "cad_figure":
        from ai_inspector.documentation.rich_layout import draw_pdf_object
        if block_type in {"note", "status_panel"}:
            _draw_safety_symbol(fitz, page, rect, rich_plan.style["signalWord"])
        draw_pdf_object(fitz, page, rich_plan)
    elif block_type in {"table", "key_value_table"}:
        _draw_table(fitz, page, block, rect)
    elif block_type in {"list", "figure_legend"}:
        _draw_list(fitz, page, block, rect)
    elif block_type == "contents_list":
        _draw_contents(fitz, page, block, rect)
    elif block_type == "cad_figure":
        request = descriptor.get("renderRequest") or {}
        image = request.get("image") or {}
        image_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 - 18)
        if not fit.collecting():
            image_path = document_draft_render_path(root, assembly_number, document, descriptor)
            fitted = _fit_image_rect(fitz, image_rect, image_path)
            page.draw_rect(image_rect, color=(0.76, 0.81, 0.84), fill=(1, 1, 1), width=0.55)
            page.insert_image(fitted, filename=str(image_path), keep_proportion=True)
            draw_balloon_manifest(fitz, page, fitted, image)
        if rich_plan is not None:
            from ai_inspector.documentation.rich_layout import draw_pdf_object
            draw_pdf_object(fitz, page, rich_plan)
        else:
            page.insert_textbox(fitz.Rect(rect.x0, rect.y1 - 16, rect.x1, rect.y1), str(block.get("caption") or ""), fontsize=6.5, fontname="helv", color=(0.35, 0.42, 0.47), align=fitz.TEXT_ALIGN_CENTER)
    elif block_type in {"note", "status_panel", "draft_banner"}:
        _draw_note(fitz, page, block, rect, text)
    else:
        font_size = float(style.get("fontSize") or (20 if block_type == "heading" else 10))
        font_name = "hebo" if (
            block_type in {"heading", "continuation_heading", "cover_kicker", "cover_title"}
            or int(style.get("fontWeight") or 400) >= 600
        ) else "helv"
        color = _rgb(style.get("color"), "#071B2A" if font_name == "hebo" else "#18212A")
        line_height = max(font_size, float(style.get("lineHeight") or (font_size * 1.35)))
        override_has_text = "text" in _page_override(
            descriptor, str(block.get("blockId") or "")
        )
        authored_lines = block.get("lines")
        lines = (
            [str(value) for value in authored_lines]
            if isinstance(authored_lines, Sequence)
            and not isinstance(authored_lines, (str, bytes))
            and not override_has_text
            else wrap_text(text, rect.width, font_size)
        )
        measured_height = font_size + max(0, len(lines) - 1) * line_height
        if measured_height > rect.height + 0.5:
            fit.failure(page, measuredHeight=measured_height)
        for index, line in enumerate(lines):
            baseline = rect.y0 + font_size + (index * line_height)
            if baseline > rect.y1 + 0.5:
                break
            page.insert_text(
                fitz.Point(rect.x0, baseline),
                line,
                fontsize=font_size,
                fontname=font_name,
                color=color,
            )


def fit_report(root, assembly_number, document, asset_root=None):
    from ai_inspector.documentation import fit
    with fit.collect(document) as report:
        fit.authored_bounds(document)
        build_prototype_pdf_bytes(root, assembly_number, document, asset_root, _fit_check=True)
        return report.report()


def build_prototype_pdf_bytes(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    asset_root: str | Path | None = None,
    *, _fit_check: bool = False,
) -> bytes:
    from ai_inspector.documentation import fit
    from ai_inspector.documentation.layout import document_geometry
    document = export_document(document)
    geometry = document_geometry(document)
    if not _fit_check:
        check_export(document, document.get("exportMode", "review"))
    readiness = prototype_export_readiness(document) if not _fit_check else {"status": "READY"}
    if readiness["status"] != "READY":
        raise OperationsManualExportError(
            f"capture {readiness['requiredCaptureCount']} technical figure(s) before manual export"
        )
    import fitz

    from ai_inspector.documentation.rich_layout import prepare_pdf_objects, draw_pdf_objects
    pages = [row for row in document.get("pages") or [] if isinstance(row, Mapping)]
    page_width, page_height, layout = _publication_page_geometry(document)
    text_plans = prepare_pdf_objects(fitz, document, (page_width, page_height))
    from ai_inspector.documentation.rich_blocks import prepare_pdf_blocks
    block_plans = prepare_pdf_blocks(fitz, document)
    pdf = fitz.open()
    for descriptor in pages:
        page = fit.measured_page(pdf.new_page(width=page_width, height=page_height), descriptor)
        if descriptor.get("pageType") == "operations_cover":
            theme_colors = (document.get("theme") or {}).get("colors") or {}
            navy = _rgb(theme_colors.get("primary"), "#071B2A")
            accent = _rgb(theme_colors.get("accent"), "#43B5EE")
            muted = _rgb(theme_colors.get("muted"), "#596A76")
            cover_layout = (layout.get("pageTypes") or {}).get("operations_cover") or {}
            for region_name, fill in (
                ("topAccent", accent),
                ("topRule", navy),
                ("leftAccent", accent),
                ("bottomBand", navy),
            ):
                page.draw_rect(
                    _layout_rect(fitz, cover_layout, region_name),
                    color=None,
                    fill=fill,
                )
            fit.target(page, descriptor, "cover_brand")
            page.insert_text(fitz.Point(geometry.x(40), geometry.y(59)), "Inspector", fontsize=17, fontname="hebo", color=navy)
            inspector_width = fitz.get_text_length("Inspector", fontname="hebo", fontsize=17)
            page.insert_text(fitz.Point(geometry.x(40) + inspector_width, geometry.y(59)), "Pro", fontsize=17, fontname="hebo", color=accent)
            fit.target(page, descriptor, "cover_publication_label")
            page.insert_text(
                fitz.Point(geometry.x(185), geometry.y(57)),
                "TECHNICAL PUBLICATIONS",
                fontsize=7.2,
                fontname="helv",
                color=muted,
            )
            if not _fit_check:
                image_path = document_draft_render_path(root, assembly_number, document, descriptor)
                image_frame = (descriptor.get("renderRequest") or {}).get("frame") \
                    or cover_layout.get("illustration") \
                    or {"x": 150, "y": 184, "width": 660, "height": 294}
                image_bounds = fitz.Rect(
                    float(image_frame.get("x") or 150),
                    float(image_frame.get("y") or 184),
                    float(image_frame.get("x") or 150) + float(image_frame.get("width") or 660),
                    float(image_frame.get("y") or 184) + float(image_frame.get("height") or 294),
                )
                page.insert_image(_fit_image_rect(fitz, image_bounds, image_path), filename=str(image_path), keep_proportion=True)
            product_name = str((document.get("product") or {}).get("name") or "Product")
            document_number = str(document.get("documentNumber") or "Document number not specified")
            fit.target(page, descriptor, "cover_footer_product")
            page.insert_textbox(
                _layout_rect(fitz, cover_layout, "footerLeft"),
                product_name,
                fontsize=7.4,
                fontname="helv",
                color=(1, 1, 1),
            )
            fit.target(page, descriptor, "cover_footer_identity")
            page.insert_textbox(
                _layout_rect(fitz, cover_layout, "footerRight"),
                f"{document_number} | {document.get('statusLabel') or 'DRAFT'}",
                fontsize=7.4,
                fontname="helv",
                color=(1, 1, 1),
                align=fitz.TEXT_ALIGN_RIGHT,
            )
        else:
            _draw_header_footer(fitz, page, descriptor, document)
        for block in descriptor.get("layoutBlocks") or []:
            if isinstance(block, Mapping):
                _draw_block(fitz, page, descriptor, block, document, root, assembly_number,
                            block_plans.get(descriptor["pageId"], {}).get(block.get("blockId")))
        draw_pdf_objects(fitz, page, descriptor, text_plans, document=document,
                         asset_root=asset_root or root, assembly_number=assembly_number)
    if _fit_check:
        pdf.close()
        return b""
    toc = [[1, str(document.get("title") or "Operations and Maintenance Manual"), 1]]
    seen_sections: set[str] = set()
    for descriptor in pages:
        section_id = str(descriptor.get("sectionId") or "")
        if section_id and section_id not in seen_sections:
            seen_sections.add(section_id)
            toc.append([1, str(descriptor.get("title") or section_id), int(descriptor.get("pageNumber") or 1)])
    pdf.set_toc(toc)
    document_type = str(document.get("documentType") or "")
    subject = (
        "Assembly work instructions"
        if document_type == "work_instructions"
        else "Operations and maintenance manual"
    )
    keywords = (
        "assembly work instructions, operator instructions, technical documentation, InspectorPro"
        if document_type == "work_instructions"
        else "operations manual, maintenance manual, technical documentation, InspectorPro"
    )
    pdf.set_metadata({
        "title": str(document.get("title") or "Operations and Maintenance Manual"),
        "author": "InspectorPro",
        "subject": subject,
        "keywords": keywords,
    })
    mark_pdf(pdf, document)
    from ai_inspector.documentation.rich_layout import finish_pdf_fonts
    finish_pdf_fonts(pdf, {**text_plans, **{key + ":blocks": value for key, value in block_plans.items()}})
    payload = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    return payload


def _docx_cell_shading(cell: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), color)


def _docx_add_page_rect(
    paragraph: Any,
    *,
    shape_id: str,
    frame: Mapping[str, Any],
    color: str,
) -> None:
    """Add a print-safe page-relative theme band behind editable Word content."""
    from docx.oxml import parse_xml

    left = float(frame.get("x") or 0)
    top = float(frame.get("y") or 0)
    width = max(0.0, float(frame.get("width") or 0))
    height = max(0.0, float(frame.get("height") or 0))
    if width <= 0 or height <= 0:
        return
    safe_id = html.escape(shape_id, quote=True)
    fill = _hex_color(color, "071B2A")
    shape = parse_xml(
        f"""
        <w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
             xmlns:v="urn:schemas-microsoft-com:vml"
             xmlns:o="urn:schemas-microsoft-com:office:office"
             xmlns:w10="urn:schemas-microsoft-com:office:word">
          <w:pict>
            <v:rect id="{safe_id}"
                    o:allowincell="f"
                    o:allowoverlap="t"
                    stroked="f"
                    fillcolor="#{fill}"
                    style="position:absolute;left:0;top:0;margin-left:{left:.3f}pt;margin-top:{top:.3f}pt;width:{width:.3f}pt;height:{height:.3f}pt;z-index:-251658240;mso-position-horizontal-relative:page;mso-position-vertical-relative:page;mso-wrap-style:none">
              <v:fill color="#{fill}"/>
              <w10:wrap type="none"/>
            </v:rect>
          </w:pict>
        </w:r>
        """
    )
    paragraph._p.append(shape)


def _docx_format_run(run: Any, *, color: str, size: float, bold: bool = False) -> None:
    from docx.shared import Pt, RGBColor

    run.font.name = "Arial"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(_hex_color(color, "18212A"))


def _docx_append_field(
    paragraph: Any,
    instruction: str,
    *,
    color: str,
    size: float,
) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    begin = paragraph.add_run()
    begin_element = OxmlElement("w:fldChar")
    begin_element.set(qn("w:fldCharType"), "begin")
    begin._r.append(begin_element)
    _docx_format_run(begin, color=color, size=size)

    code = paragraph.add_run()
    instruction_element = OxmlElement("w:instrText")
    instruction_element.set(qn("xml:space"), "preserve")
    instruction_element.text = f" {instruction} "
    code._r.append(instruction_element)
    _docx_format_run(code, color=color, size=size)

    separate = paragraph.add_run()
    separate_element = OxmlElement("w:fldChar")
    separate_element.set(qn("w:fldCharType"), "separate")
    separate._r.append(separate_element)
    _docx_format_run(separate, color=color, size=size)

    result = paragraph.add_run("1")
    _docx_format_run(result, color=color, size=size)

    end = paragraph.add_run()
    end_element = OxmlElement("w:fldChar")
    end_element.set(qn("w:fldCharType"), "end")
    end._r.append(end_element)
    _docx_format_run(end, color=color, size=size)


def _docx_brand_runs(paragraph: Any, *, primary: str, accent: str, inverse: bool) -> None:
    inspector = paragraph.add_run("Inspector")
    _docx_format_run(
        inspector,
        color="FFFFFF" if inverse else primary,
        size=10.5,
        bold=True,
    )
    pro = paragraph.add_run("Pro")
    _docx_format_run(pro, color=accent, size=10.5, bold=True)


def _docx_configure_page_masters(
    section: Any,
    document: Mapping[str, Any],
    *,
    content_width_inches: float,
) -> None:
    """Create theme-driven cover and body masters without flattening the DOCX."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.shared import Inches, Pt

    colors = (document.get("theme") or {}).get("colors") or {}
    primary = _hex_color(colors.get("primary"), "071B2A")
    accent = _hex_color(colors.get("accent"), "43B5EE")
    muted = _hex_color(colors.get("muted"), "596A76")
    rule = _hex_color(colors.get("rule"), "ABBAC4")
    layout = document.get("publicationLayout") or {}
    shared = layout.get("shared") or {}
    cover = (layout.get("pageTypes") or {}).get("operations_cover") or {}
    page = layout.get("page") or {}
    page_width = float(page.get("width") or 960.0)
    page_height = float(page.get("height") or 540.0)
    document_number = str(document.get("documentNumber") or "Not specified")
    product_name = str((document.get("product") or {}).get("name") or "Product")
    document_type = str(document.get("documentType") or "")
    document_label = {
        "work_instructions": "ASSEMBLY WORK INSTRUCTIONS",
        "product_specification_sheet": "PRODUCT SPECIFICATION",
    }.get(document_type, "OPERATIONS AND MAINTENANCE MANUAL")

    section.different_first_page_header_footer = True
    section.header_distance = Pt(12)
    section.footer_distance = Pt(16)

    header = section.header
    header.is_linked_to_previous = False
    header_paragraph = header.paragraphs[0]
    header_paragraph.paragraph_format.space_after = Pt(0)
    header_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(content_width_inches), WD_TAB_ALIGNMENT.RIGHT
    )
    body_header = shared.get("header") or {
        "x": 0,
        "y": 0,
        "width": page_width,
        "height": 56,
    }
    _docx_add_page_rect(
        header_paragraph,
        shape_id="operations-body-header-band",
        frame=body_header,
        color=primary,
    )
    _docx_add_page_rect(
        header_paragraph,
        shape_id="operations-body-header-accent",
        frame={
            "x": float(body_header.get("x") or 0),
            "y": float(body_header.get("y") or 0)
            + max(0.0, float(body_header.get("height") or 56) - 3.0),
            "width": float(body_header.get("width") or page_width),
            "height": 3,
        },
        color=accent,
    )
    _docx_brand_runs(header_paragraph, primary=primary, accent=accent, inverse=True)
    title = header_paragraph.add_run(f"\t{document_label}")
    _docx_format_run(title, color="FFFFFF", size=8.5, bold=True)

    first_header = section.first_page_header
    first_header.is_linked_to_previous = False
    first_header_paragraph = first_header.paragraphs[0]
    first_header_paragraph.paragraph_format.space_before = Pt(14)
    first_header_paragraph.paragraph_format.space_after = Pt(0)
    first_header_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(content_width_inches), WD_TAB_ALIGNMENT.RIGHT
    )
    for region_name, color in (
        ("topAccent", accent),
        ("topRule", primary),
        ("leftAccent", accent),
        ("bottomBand", primary),
    ):
        _docx_add_page_rect(
            first_header_paragraph,
            shape_id=f"operations-cover-{region_name}",
            frame=cover.get(region_name) or {},
            color=color,
        )
    _docx_brand_runs(
        first_header_paragraph,
        primary=primary,
        accent=accent,
        inverse=False,
    )
    cover_meta = first_header_paragraph.add_run(f"\t{document_number}")
    _docx_format_run(cover_meta, color=muted, size=7.5)

    footer = section.footer
    footer.is_linked_to_previous = False
    footer_paragraph = footer.paragraphs[0]
    footer_paragraph.paragraph_format.space_after = Pt(0)
    footer_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(content_width_inches), WD_TAB_ALIGNMENT.RIGHT
    )
    footer_frame = shared.get("footer") or {
        "x": 40,
        "y": page_height - 24,
        "width": page_width - 80,
        "height": 16,
    }
    _docx_add_page_rect(
        footer_paragraph,
        shape_id="operations-body-footer-rule",
        frame={
            "x": float(footer_frame.get("x") or 40),
            "y": float(footer_frame.get("y") or (page_height - 24)),
            "width": float(footer_frame.get("width") or (page_width - 80)),
            "height": 1,
        },
        color=rule,
    )
    footer_identity = footer_paragraph.add_run(f"{document_number} | DRAFT")
    _docx_format_run(footer_identity, color=muted, size=7)
    page_prefix = footer_paragraph.add_run("\tPage ")
    _docx_format_run(page_prefix, color=muted, size=7)
    _docx_append_field(footer_paragraph, "PAGE", color=muted, size=7)
    of_run = footer_paragraph.add_run(" of ")
    _docx_format_run(of_run, color=muted, size=7)
    _docx_append_field(footer_paragraph, "NUMPAGES", color=muted, size=7)

    first_footer = section.first_page_footer
    first_footer.is_linked_to_previous = False
    first_footer_paragraph = first_footer.paragraphs[0]
    first_footer_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    first_footer_paragraph.paragraph_format.space_after = Pt(0)
    first_footer_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(content_width_inches), WD_TAB_ALIGNMENT.RIGHT
    )
    first_identity = first_footer_paragraph.add_run(product_name)
    _docx_format_run(first_identity, color="FFFFFF", size=7.5)
    first_meta = first_footer_paragraph.add_run(f"\t{document_number} | DRAFT")
    _docx_format_run(first_meta, color="FFFFFF", size=7.5)


def _safety_symbol_png(signal_word: str) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=72, height=72)
    _draw_safety_symbol(
        fitz,
        page,
        fitz.Rect(10, 6, 62, 62),
        str(signal_word or "NOTICE").upper(),
    )
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
    payload = pixmap.tobytes("png")
    document.close()
    return payload


def _annotated_figure_png(
    image_path: Path,
    image: Mapping[str, Any],
) -> bytes:
    import fitz

    source = fitz.Pixmap(str(image_path))
    aspect_ratio = source.width / max(1, source.height)
    source = None
    width = 457.2
    height = width / max(0.1, aspect_ratio)
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    frame = fitz.Rect(0, 0, width, height)
    page.insert_image(frame, filename=str(image_path), keep_proportion=True)
    draw_balloon_manifest(fitz, page, frame, image)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
    payload = pixmap.tobytes("png")
    document.close()
    return payload


def build_prototype_docx_bytes(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    asset_root: str | Path | None = None,
) -> bytes:
    document = export_document(document, format="docx")
    check_export(document, document.get("exportMode", "review"), format="docx")
    readiness = prototype_export_readiness(document)
    if readiness["status"] != "READY":
        raise OperationsManualExportError(
            f"capture {readiness['requiredCaptureCount']} technical figure(s) before manual export"
        )
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.shared import Inches, Pt, RGBColor

    output = Document()
    section = output.sections[0]
    page_width_pt, page_height_pt, _ = _publication_page_geometry(document)
    section.orientation = (
        WD_ORIENT.LANDSCAPE if page_width_pt > page_height_pt else WD_ORIENT.PORTRAIT
    )
    section.page_width = Inches(page_width_pt / 72.0)
    section.page_height = Inches(page_height_pt / 72.0)
    section.top_margin = Inches(0.62)
    section.bottom_margin = Inches(0.42)
    section.left_margin = Inches(0.78)
    section.right_margin = Inches(0.78)
    content_width_inches = max(
        1.0,
        (page_width_pt / 72.0) - 1.56,
    )
    styles = output.styles
    theme = document.get("theme") or {}
    theme_colors = theme.get("colors") or {}
    theme_typography = theme.get("typography") or {}
    body_font = str(theme_typography.get("bodyFont") or "Arial")
    heading_font = str(theme_typography.get("headingFont") or "Arial")
    primary = _hex_color(theme_colors.get("primary"), "071B2A")
    accent = _hex_color(theme_colors.get("accent"), "43B5EE")
    styles["Normal"].font.name = body_font
    styles["Normal"].font.size = Pt(9.5)
    for name, size, color in (
        ("Title", 27, primary),
        ("Heading 1", 19, primary),
        ("Heading 2", 13, primary),
    ):
        styles[name].font.name = heading_font
        styles[name].font.size = Pt(size)
        styles[name].font.color.rgb = RGBColor.from_string(color)
    _docx_configure_page_masters(
        section,
        document,
        content_width_inches=content_width_inches,
    )

    from ai_inspector.documentation.rich_docx import DocxObjects, write_content
    from ai_inspector.documentation.rich_layout import content_model
    from ai_inspector.documentation.rich_blocks import rich_value, base_style, effective_override
    from ai_inspector.specification_sheet.exports import _docx_set_cell_border, _docx_clear_table_borders
    authored = DocxObjects(output, document, (page_width_pt, page_height_pt), shade_cell=_docx_cell_shading,
                           border_cell=_docx_set_cell_border, clear_borders=_docx_clear_table_borders, asset_root=asset_root or root, assembly_number=assembly_number)
    pages = [row for row in document.get("pages") or [] if isinstance(row, Mapping)]
    for page_index, descriptor in enumerate(pages):
        if page_index:
            output.add_page_break()
        if descriptor.get("pageType") == "operations_cover":
            cover_blocks = {block.get("blockId"): block for block in descriptor.get("layoutBlocks") or []}
            cover_layout = ((document.get("publicationLayout") or {}).get("pageTypes") or {}).get("operations_cover") or {}

            def cover_top(key, region, fallback):
                block = cover_blocks.get(key)
                return _block_frame(descriptor, block, document)["y"] if block else float((cover_layout.get(region) or {}).get("y", fallback))

            authored.flush(descriptor["pageId"], cover_top("cover-kicker", "kicker", 80))
            paragraph = output.add_paragraph(
                str(document.get("coverKicker") or "OPERATIONS AND MAINTENANCE MANUAL")
            )
            paragraph.style = styles["Heading 2"]
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor.from_string(accent)
            authored.flush(descriptor["pageId"], cover_top("cover-product", "title", 110))
            title = output.add_paragraph(str(document.get("product", {}).get("name") or "Product"))
            title.style = styles["Title"]
            status_label = str(document.get("statusLabel") or "").strip()
            if status_label:
                status = output.add_paragraph(status_label)
                status.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in status.runs:
                    run.font.bold = True
                    run.font.size = Pt(10)
                    run.font.color.rgb = RGBColor.from_string(primary)
            authored.flush(descriptor["pageId"], float(((descriptor.get("renderRequest") or {}).get("frame") or cover_layout.get("illustration") or {}).get("y", 184)))
            image_path = document_draft_render_path(root, assembly_number, document, descriptor)
            image_frame = (descriptor.get("renderRequest") or {}).get("frame") or {}
            image_width = min(
                content_width_inches,
                max(3.0, float(image_frame.get("width") or 660.0) / 72.0),
            )
            output.add_picture(str(image_path), width=Inches(image_width))
            output.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            authored.flush(descriptor["pageId"])
            continue
        for block in descriptor.get("layoutBlocks") or []:
            if not isinstance(block, Mapping):
                continue
            authored.flush(descriptor["pageId"], _block_frame(descriptor, block, document)["y"])
            block = _edited_block(descriptor, block)
            block_type = str(block.get("blockType") or "")
            text = _block_text(descriptor, block)
            if _review_marks(document) and _has_marked(block):
                notice = output.add_paragraph((conflict_marker(block, EDITED_MARKER) + ". " if _marked(block) else "") + EDITED_LEGEND)
                for run in notice.runs:
                    run.font.size = Pt(7)
            rich = rich_value(document, descriptor, block)
            rich_style = base_style(block, effective_override(descriptor, block)) if rich is not None else None
            rich_target = {"pageId": descriptor["pageId"], "targetId": block.get("stableId") or block.get("blockId", "")}
            if rich is not None and block_type != "cad_figure":
                first = None
                if block_type in {"note", "status_panel"}:
                    # Preserve the safety symbol in its own copy-column table, with native text beside it.
                    table = output.add_table(rows=1, cols=2)
                    table.autofit = False
                    _docx_clear_table_borders(table)
                    from docx.oxml.ns import qn
                    from ai_inspector.documentation.rich_docx import _element
                    borders = table._tbl.tblPr.find(qn("w:tblBorders"))
                    table._tbl.tblPr.remove(borders)
                    table._tbl.tblPr.find(qn("w:tblLayout")).addprevious(borders)
                    for cell in table.rows[0].cells:
                        margins = _element("w:tcMar")
                        for edge in ("top", "left", "bottom", "right"):
                            margins.append(_element("w:" + edge, w=40 if edge in {"top", "bottom"} else 0, type="dxa"))
                        cell._tc.get_or_add_tcPr().append(margins)
                    table.cell(0, 0).width = Pt(68)
                    table.cell(0, 1).width = Pt(max(1, content_width_inches * 72 - 68))
                    table.columns[0].width = Pt(68)
                    table.columns[1].width = Pt(max(1, content_width_inches * 72 - 68))
                    table.cell(0, 0).paragraphs[0].add_run().add_picture(
                        io.BytesIO(_safety_symbol_png(rich_style["signalWord"])), width=Inches(.48))
                    copy_cell = table.cell(0, 1)
                    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
                    table.rows[0].height = Pt(_block_frame(descriptor, block, document)["height"])
                    table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
                    copy_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    first = copy_cell.paragraphs[0]
                write_content(output, content_model(rich, rich_style), rich_target,
                              copy_cell.add_paragraph if first is not None else None, first=first, narrative=True)
            elif block_type in {"heading", "continuation_heading"}:
                level = 1 if float((block.get("style") or {}).get("fontSize") or 14) >= 18 else 2
                output.add_heading(text, level=level)
            elif block_type in {"paragraph", "cover_kicker", "cover_title"}:
                output.add_paragraph(text)
            elif block_type in {"note", "status_panel"}:
                signal_word = str(
                    block.get("signalWord") or block.get("tone") or "notice"
                ).upper()
                paragraph = output.add_paragraph()
                icon = paragraph.add_run()
                icon.add_picture(
                    io.BytesIO(_safety_symbol_png(signal_word)),
                    width=Inches(0.48),
                )
                signal = paragraph.add_run(f"  {signal_word} ")
                signal.font.bold = True
                paragraph.add_run(text)
            elif block_type == "draft_banner":
                table = output.add_table(rows=1, cols=1)
                cell = table.cell(0, 0)
                cell.text = text
                tone = str(block.get("tone") or "information")
                color = {
                    "danger": "FDE9E7",
                    "warning": "FFF0E4",
                    "caution": "FFF8D8",
                    "prototype": "FFF0ED",
                    "draft": "FFF0ED",
                }.get(tone, "EAF6FD")
                _docx_cell_shading(cell, color)
                cell.paragraphs[0].runs[0].font.bold = True
            elif block_type in {"list", "figure_legend"}:
                style = str(block.get("listStyle") or "numbered")
                for index, item in enumerate(block.get("items") or [], start=1):
                    if not isinstance(item, Mapping):
                        continue
                    paragraph = output.add_paragraph()
                    if style in {"numbered", "keyed"}:
                        marker = paragraph.add_run(
                            f"{item.get('itemNumber') or index}.  "
                        )
                        marker.font.bold = True
                    label = str(item.get("label") or "")
                    if label:
                        label_run = paragraph.add_run(label)
                        label_run.font.bold = True
                        if item.get("text"):
                            paragraph.add_run(": ")
                    if item.get("text"):
                        paragraph.add_run(str(item.get("text")))
                    if _marked(item):
                        paragraph.add_run("\n" + conflict_marker(item, EDITED_MARKER))
                    if int(item.get("quantity") or 1) > 1:
                        quantity = paragraph.add_run(
                            f"  ({int(item.get('quantity') or 1)}X)"
                        )
                        quantity.font.bold = True
            elif block_type == "contents_list":
                for entry in block.get("entries") or []:
                    if not isinstance(entry, Mapping):
                        continue
                    paragraph = output.add_paragraph()
                    paragraph.paragraph_format.tab_stops.add_tab_stop(
                        Inches(max(1.0, content_width_inches - 0.1)),
                        WD_TAB_ALIGNMENT.RIGHT,
                        WD_TAB_LEADER.DOTS,
                    )
                    title = paragraph.add_run(str(entry.get("title") or "Section"))
                    title.font.bold = True
                    paragraph.add_run("\t" + str(entry.get("pageNumber") or ""))
            elif block_type in {"table", "key_value_table"}:
                columns = [str(value) for value in block.get("columns") or []]
                rows = [row for row in block.get("rows") or [] if isinstance(row, Mapping)]
                if not columns:
                    continue
                table = output.add_table(rows=1, cols=len(columns))
                table.style = "Table Grid"
                for index, value in enumerate(columns):
                    table.cell(0, index).text = value
                    _docx_cell_shading(table.cell(0, index), "EAF1F6")
                    table.cell(0, index).paragraphs[0].runs[0].font.bold = True
                for row in rows:
                    cells = table.add_row().cells
                    values = [str(value or "") for value in row.get("cells") or []]
                    for index in range(len(columns)):
                        cells[index].text = values[index] if index < len(values) else ""
                    if _marked(row):
                        cells[-1].add_paragraph(conflict_marker(row, EDITED_MARKER))
            elif block_type == "cad_figure":
                image_path = document_draft_render_path(root, assembly_number, document, descriptor)
                request = descriptor.get("renderRequest") or {}
                image = request.get("image") or {}
                frame = block.get("frame") or {}
                figure_width = min(
                    content_width_inches,
                    max(3.0, float(frame.get("width") or 848.0) / 72.0),
                )
                if image.get("balloons"):
                    output.add_picture(
                        io.BytesIO(_annotated_figure_png(image_path, image)),
                        width=Inches(figure_width),
                    )
                else:
                    output.add_picture(str(image_path), width=Inches(figure_width))
                if rich is not None:
                    write_content(output, content_model(rich, rich_style), rich_target, narrative=True)
                else:
                    caption = output.add_paragraph(str(block.get("caption") or ""))
                    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    caption.runs[0].font.size = Pt(8)
                    caption.runs[0].font.italic = True

        authored.flush(descriptor["pageId"])

    buffer = io.BytesIO()
    mark_docx(output, document)
    output.save(buffer)
    return buffer.getvalue()


def _store_export(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    *,
    kind: str,
    payload: bytes,
) -> Dict[str, Any]:
    revision = _safe(document.get("documentRevision"), "document revision")
    directory = _document_directory(root, assembly_number, revision)
    extension = "pdf" if kind == "pdf" else "docx"
    mode = document.get("exportMode", "review")
    suffix = "" if mode in {"review", "draft"} else "-" + mode
    filename = f"{_safe(assembly_number, 'assembly number')}-operations-manual{suffix}.{extension}"
    path = directory / filename
    metadata_path = directory / f"review{suffix}-{kind}.json"
    _write_atomic(path, payload)
    descriptor = {
        "status": "ready",
        "artifactClass": "draft_review",
        "provenanceVersion": 1,
        "controlledRelease": False,
        "finalApprovalRequired": True,
        "mimeType": "application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "documentRevision": revision,
        "sourceRevision": str(document.get("sourceRevision") or ""),
        "manualPlanRevision": str(document.get("manualPlanRevision") or ""),
        "pageCount": int(document.get("pageCount") or 0),
        "byteLength": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "url": f"/api/operations-manual/{assembly_number}/documents/{revision}/{extension}" + (f"?mode={mode}" if suffix else ""),
    }
    if kind == "docx":
        descriptor["rendererVersion"] = _DOCX_RENDERER_VERSION
        from ai_inspector.documentation.rich_docx import artifact_metadata
        descriptor.update(artifact_metadata(document, _publication_page_geometry(document)[:2], 1.56 * 72))
    elif kind == "pdf":
        from ai_inspector.documentation.rich_layout import PDF_RENDERER_VERSION
        from ai_inspector.documentation.objects import has_objects
        from ai_inspector.documentation.rich_blocks import has_rich_blocks
        if has_objects(document) or has_rich_blocks(document):
            descriptor["rendererVersion"] = PDF_RENDERER_VERSION
    _write_atomic(
        metadata_path,
        (json.dumps(descriptor, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    return copy.deepcopy(descriptor)


def _cached_export(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    *,
    kind: str,
) -> Dict[str, Any] | None:
    revision = _safe(document.get("documentRevision"), "document revision")
    directory = _document_directory(root, assembly_number, revision)
    extension = "pdf" if kind == "pdf" else "docx"
    mode = document.get("exportMode", "review")
    suffix = "" if mode in {"review", "draft"} else "-" + mode
    filename = f"{_safe(assembly_number, 'assembly number')}-operations-manual{suffix}.{extension}"
    path = directory / filename
    metadata_path = directory / f"review{suffix}-{kind}.json"
    native_path = _filesystem_path(path)
    native_metadata_path = _filesystem_path(metadata_path)
    if not os.path.isfile(native_path) or not os.path.isfile(native_metadata_path):
        return None
    try:
        with open(native_metadata_path, "r", encoding="ascii") as handle:
            descriptor = json.load(handle)
        with open(native_path, "rb") as handle:
            payload = handle.read()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    expected = {
        "status": "ready",
        "provenanceVersion": 1,
        "documentRevision": revision,
        "sourceRevision": str(document.get("sourceRevision") or ""),
        "manualPlanRevision": str(document.get("manualPlanRevision") or ""),
        "pageCount": int(document.get("pageCount") or 0),
        "filename": filename,
        "byteLength": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if kind == "docx":
        expected["rendererVersion"] = _DOCX_RENDERER_VERSION
        from ai_inspector.documentation.rich_docx import artifact_metadata
        expected.update(artifact_metadata(document, _publication_page_geometry(document)[:2], 1.56 * 72))
    elif kind == "pdf":
        from ai_inspector.documentation.rich_layout import PDF_RENDERER_VERSION
        from ai_inspector.documentation.objects import has_objects
        from ai_inspector.documentation.rich_blocks import has_rich_blocks
        if has_objects(document) or has_rich_blocks(document):
            expected["rendererVersion"] = PDF_RENDERER_VERSION
    if any(descriptor.get(key) != value for key, value in expected.items()):
        return None
    result = copy.deepcopy(descriptor)
    result["cacheHit"] = True
    return result


def store_prototype_pdf(
    root: str | Path, assembly_number: str, document: Mapping[str, Any],
    asset_root: str | Path | None = None,
) -> Dict[str, Any]:
    document = export_document(document)
    check_export(document, document.get("exportMode", "review"))
    with _EXPORT_LOCK:
        cached = _cached_export(root, assembly_number, document, kind="pdf")
        if cached is not None:
            return cached
        result = _store_export(
            root,
            assembly_number,
            document,
            kind="pdf",
            payload=build_prototype_pdf_bytes(root, assembly_number, document, asset_root=asset_root),
        )
        result["cacheHit"] = False
        return result


def store_prototype_docx(
    root: str | Path, assembly_number: str, document: Mapping[str, Any],
    asset_root: str | Path | None = None,
) -> Dict[str, Any]:
    document = export_document(document, format="docx")
    check_export(document, document.get("exportMode", "review"), format="docx")
    with _EXPORT_LOCK:
        cached = _cached_export(root, assembly_number, document, kind="docx")
        if cached is not None:
            return cached
        result = _store_export(
            root,
            assembly_number,
            document,
            kind="docx",
            payload=build_prototype_docx_bytes(root, assembly_number, document, asset_root=asset_root),
        )
        result["cacheHit"] = False
        return result


def prototype_export_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
    kind: str,
    mode: str = "review",
) -> Path:
    if mode not in {"review", "draft", "customer", "controlled"}:
        raise OperationsManualExportError("invalid export mode")
    suffix = "" if mode in {"review", "draft"} else "-" + mode
    extension = "pdf" if kind == "pdf" else "docx"
    directory = _document_directory(root, assembly_number, document_revision)
    path = directory / f"{_safe(assembly_number, 'assembly number')}-operations-manual{suffix}.{extension}"
    filesystem_path = _filesystem_path(path)
    if not os.path.isfile(filesystem_path):
        raise OperationsManualExportError("operations-manual export not found")
    return Path(filesystem_path)
