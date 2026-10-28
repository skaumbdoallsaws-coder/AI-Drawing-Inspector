"""Fillable PDF form fields for documentation exports.

Two kinds of blank: a *provide* field is information the document still needs (the app and Sage never guess it),
a *record* field is filled where the document is used (a measured value, a result, a signature). Fields are plain
AcroForm fields with no scripts, so any PDF reader can fill them, and the app reads the values back from a
returned PDF so the next build keeps them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

FIELD_KINDS = ("text", "multiline", "checkbox", "signature")
FIELD_ROLES = ("provide", "record")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")

# Light amber marks information still to be provided, on screen and on paper; record fields are plain boxes.
PROVIDE_FILL = (1.0, 0.957, 0.839)
FIELD_BORDER = (0.55, 0.6, 0.68)


class FormFieldError(ValueError):
    pass


def form_field(
    name: str,
    label: str,
    rect: Sequence[float],
    *,
    page: int = 0,
    kind: str = "text",
    role: str = "record",
    value: Any = None,
    font_size: float = 0,
) -> Dict[str, Any]:
    """One field: its PDF name, the tooltip a reader shows, where it sits (points, top-left origin) and its value."""
    if _NAME_RE.fullmatch(str(name or "")) is None:
        raise FormFieldError(f"invalid form field name: {name!r}")
    if kind not in FIELD_KINDS:
        raise FormFieldError(f"unknown form field kind: {kind!r}")
    if role not in FIELD_ROLES:
        raise FormFieldError(f"unknown form field role: {role!r}")
    if len(rect) != 4 or not rect[0] < rect[2] or not rect[1] < rect[3]:
        raise FormFieldError(f"invalid rectangle for form field {name}")
    if kind == "signature" and value not in (None, ""):
        raise FormFieldError("a signature field cannot carry a value")
    return {
        "name": str(name),
        "label": str(label or name),
        "rect": [round(float(coordinate), 2) for coordinate in rect],
        "page": int(page),
        "kind": kind,
        "role": role,
        "value": None if value in (None, "") else (bool(value) if kind == "checkbox" else str(value)),
        "fontSize": float(font_size),
    }


def validate_form_fields(fields: Iterable[Mapping[str, Any]], page_sizes: Sequence[Sequence[float]]) -> None:
    names = set()
    for field in fields:
        if field["name"] in names:
            raise FormFieldError(f"duplicate form field name: {field['name']}")
        names.add(field["name"])
        if not 0 <= field["page"] < len(page_sizes):
            raise FormFieldError(f"form field {field['name']} is on a page that does not exist")
        width, height = page_sizes[field["page"]]
        x0, y0, x1, y1 = field["rect"]
        if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
            raise FormFieldError(f"form field {field['name']} is outside its page")


def open_fields(fields: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The information the document still needs: provide fields with no value, or one it cannot use."""
    return [{"name": field["name"], "label": field["label"]}
            for field in fields if field["role"] == "provide" and _needed(field)]


def _needed(field: Mapping[str, Any]) -> bool:
    return field.get("value") in (None, "") or bool(field.get("problem"))


def add_form_fields(fitz: Any, document: Any, fields: Iterable[Mapping[str, Any]]) -> int:
    """Place the fields on an open PyMuPDF document; returns how many were added."""
    kinds = {
        "text": fitz.PDF_WIDGET_TYPE_TEXT,
        "multiline": fitz.PDF_WIDGET_TYPE_TEXT,
        "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX,
        "signature": fitz.PDF_WIDGET_TYPE_SIGNATURE,
    }
    count = 0
    for field in fields:
        widget = fitz.Widget()
        widget.field_type = kinds[field["kind"]]
        widget.field_name = field["name"]
        widget.field_label = field["label"]
        widget.rect = fitz.Rect(*field["rect"])
        widget.border_color = FIELD_BORDER
        widget.border_width = 0.6
        if field["role"] == "provide" and _needed(field):
            widget.fill_color = PROVIDE_FILL
        elif field["kind"] != "signature":
            widget.fill_color = (1, 1, 1)  # readable on any background, coloured bands included
        if field["kind"] in ("text", "multiline"):
            widget.text_font = "Helv"
            widget.text_fontsize = field.get("fontSize") or 0
            if field["kind"] == "multiline":
                widget.field_flags |= fitz.PDF_TX_FIELD_IS_MULTILINE
            if field.get("value") not in (None, ""):
                widget.field_value = str(field["value"])
        elif field["kind"] == "checkbox":
            widget.field_value = bool(field.get("value"))
        document[field["page"]].add_widget(widget)
        count += 1
    return count


def read_form_fields(pdf_bytes: bytes) -> Dict[str, Dict[str, Any]]:
    """The values in a returned PDF, by field name: text as typed, checkboxes as true/false, signatures as signed
    or not. Fields the app did not create are reported too, so the caller decides what it trusts."""
    try:
        import fitz
    except ImportError as exc:
        raise FormFieldError("PyMuPDF is required to read form fields") from exc
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise FormFieldError("the returned file is not a readable PDF") from exc
    if document.needs_pass:
        raise FormFieldError("the returned PDF is password protected")
    values: Dict[str, Dict[str, Any]] = {}
    try:
        for page_index, page in enumerate(document):
            for widget in page.widgets() or []:
                name = str(widget.field_name or "")
                if not name or name in values:
                    continue
                if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    value: Any = str(widget.field_value or "Off") not in ("Off", "", "False")
                    kind = "checkbox"
                elif widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    value = document.xref_get_key(widget.xref, "V")[0] not in ("null", "")
                    kind = "signature"
                else:
                    value = str(widget.field_value or "").strip() or None
                    kind = "text"
                values[name] = {"kind": kind, "value": value, "page": page_index}
    finally:
        document.close()
    return values
