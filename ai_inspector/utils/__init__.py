"""Utility modules (PDF render, SW library, schemas)."""

from .pdf_render import (
    PageArtifact,
    render_pdf,
    render_single_page,
    get_pdf_page_count,
    extract_pdf_text,
)

from .sw_library import (
    SwJsonLibrary,
    SwPartEntry,
    load_json_robust,
)

__all__ = [
    # PDF rendering
    "PageArtifact",
    "render_pdf",
    "render_single_page",
    "get_pdf_page_count",
    "extract_pdf_text",
    # SolidWorks library
    "SwJsonLibrary",
    "SwPartEntry",
    "load_json_robust",
]
