"""Page artifact model for rendered PDF pages."""

from dataclasses import dataclass
from typing import Optional
from PIL import Image


@dataclass
class PageArtifact:
    """
    A rendered PDF page with metadata.

    Created by pdf_render.render_pdf(). The direct_text field is used
    by DrawingClassifier to determine the drawing type.

    Attributes:
        page_index: 0-based page index
        page_number: 1-based page number (for display)
        image: Rendered PIL Image
        width: Image width in pixels
        height: Image height in pixels
        dpi: Rendering resolution
        direct_text: Text extracted directly by PyMuPDF (for classification)
        drawing_type: v4 drawing type (MACHINED_PART, SHEET_METAL, etc.)
        needs_ocr: Whether this page needs OCR (from drawing type)
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

    # Classification fields (set after DrawingClassifier runs)
    drawing_type: Optional[str] = None
    needs_ocr: bool = True
    has_bom: bool = False
