"""Canonical publication geometry shared by manual previews and PDF output."""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping


PUBLICATION_LAYOUT_VERSION = 1
PAGE_WIDTH_PT = 792.0
PAGE_HEIGHT_PT = 612.0


def _rect(x: float, y: float, width: float, height: float) -> Dict[str, float]:
    return {
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
    }


_PUBLICATION_LAYOUT: Dict[str, Any] = {
    "schemaVersion": PUBLICATION_LAYOUT_VERSION,
    "coordinateSystem": "pdf_points_top_left",
    "page": {
        "width": PAGE_WIDTH_PT,
        "height": PAGE_HEIGHT_PT,
    },
    "shared": {
        "header": _rect(0, 0, PAGE_WIDTH_PT, 50),
        "footer": _rect(28, PAGE_HEIGHT_PT - 27, PAGE_WIDTH_PT - 56, 27),
        "safeArea": _rect(28, 62, PAGE_WIDTH_PT - 56, PAGE_HEIGHT_PT - 110),
    },
    "pageTypes": {
        "cover": {
            "coverStyleVersion": 2,
            "illustrationFramed": False,
            "brandBand": _rect(0, 0, PAGE_WIDTH_PT, 150),
            "topAccent": _rect(10, 4, PAGE_WIDTH_PT - 20, 13),
            "topRule": _rect(10, 17, PAGE_WIDTH_PT - 20, 5),
            "leftAccent": _rect(10, 22, 12, 523),
            "bottomBand": _rect(10, 545, PAGE_WIDTH_PT - 20, 55),
            "footerLeft": _rect(42, 565, 404, 14),
            "footerRight": _rect(454, 565, PAGE_WIDTH_PT - 496, 14),
            "illustration": _rect(86, 168, PAGE_WIDTH_PT - 172, 300),
            "documentControl": _rect(80, 482, PAGE_WIDTH_PT - 160, 50),
        },
        "document_information": {
            "content": _rect(48, 70, PAGE_WIDTH_PT - 96, PAGE_HEIGHT_PT - 118),
        },
        "table_of_contents": {
            "content": _rect(48, 66, PAGE_WIDTH_PT - 96, PAGE_HEIGHT_PT - 114),
        },
        "assembly_overview": {
            "illustration": _rect(30, 62, 545, PAGE_HEIGHT_PT - 110),
            "groupIndex": _rect(592, 68, PAGE_WIDTH_PT - 620, PAGE_HEIGHT_PT - 116),
        },
        "manual_section": {
            "small_bom": {
                "illustration": _rect(28, 62, 516, PAGE_HEIGHT_PT - 110),
                "bom": _rect(558, 70, PAGE_WIDTH_PT - 586, PAGE_HEIGHT_PT - 118),
            },
            "standard_bom": {
                "illustration": _rect(28, 62, 478, PAGE_HEIGHT_PT - 110),
                "bom": _rect(520, 70, PAGE_WIDTH_PT - 548, PAGE_HEIGHT_PT - 118),
            },
        },
        "manual_section_parts_list": {
            "bom": _rect(38, 70, PAGE_WIDTH_PT - 76, PAGE_HEIGHT_PT - 118),
        },
        "parts_index": {
            "content": _rect(48, 66, PAGE_WIDTH_PT - 96, PAGE_HEIGHT_PT - 114),
        },
    },
}


def publication_layout() -> Dict[str, Any]:
    """Return an isolated copy suitable for API/document serialization."""
    return copy.deepcopy(_PUBLICATION_LAYOUT)


def page_layout(
    page_type: str,
    *,
    layout_mode: str | None = None,
    layout: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Resolve one page's canonical rectangles from a publication contract."""
    source = layout if isinstance(layout, Mapping) else _PUBLICATION_LAYOUT
    page_types = source.get("pageTypes") if isinstance(source, Mapping) else None
    descriptor = page_types.get(page_type) if isinstance(page_types, Mapping) else None
    if not isinstance(descriptor, Mapping):
        return {}
    if page_type == "manual_section":
        mode = "small_bom" if layout_mode == "small_bom" else "standard_bom"
        descriptor = descriptor.get(mode)
        if not isinstance(descriptor, Mapping):
            return {}
    return copy.deepcopy(dict(descriptor))


def rect_tuple(rect: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """Convert a top-left width/height rectangle into x0/y0/x1/y1."""
    x = float(rect["x"])
    y = float(rect["y"])
    return (
        x,
        y,
        x + float(rect["width"]),
        y + float(rect["height"]),
    )
