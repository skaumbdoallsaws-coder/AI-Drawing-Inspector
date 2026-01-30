"""Page artifact model for rendered PDF pages."""

from dataclasses import dataclass
from typing import Optional
from PIL import Image


@dataclass
class PageArtifact:
    """
    A rendered PDF page with metadata.

    Created by pdf_render.render_pdf(), then enriched by the classifier
    with drawing_type, needs_ocr, and has_bom fields.

    Attributes:
        page_index: 0-based page index
        page_number: 1-based page number (for display)
        image: Rendered PIL Image
        width: Image width in pixels
        height: Image height in pixels
        dpi: Rendering resolution
        direct_text: Text extracted directly by PyMuPDF (if available)
        drawing_type: Classification result (PART_DETAIL, ASSEMBLY_BOM, MIXED)
        needs_ocr: Whether this page needs OCR processing
        has_bom: Whether this page contains a Bill of Materials
    """

    # Core fields (set at render time)
    page_index: int
    page_number: int
    image: Image.Image
    width: int
    height: int
    dpi: int
    direct_text: Optional[str] = None

    # Classification fields (set by classifier)
    drawing_type: Optional[str] = None
    needs_ocr: bool = True
    has_bom: bool = False
