"""
PDF Rendering Utilities

Renders PDF pages to images for AI analysis.
Uses PyMuPDF (fitz) for high-quality rendering.
"""

import fitz  # PyMuPDF
from dataclasses import dataclass, field
from typing import List, Optional
from PIL import Image


@dataclass
class PageArtifact:
    """Container for a rendered PDF page with metadata."""
    pageIndex0: int  # 0-based page index
    page: int  # 1-based page number (for display)
    image: Image.Image  # Rendered page as PIL Image
    width: int  # Image width in pixels
    height: int  # Image height in pixels
    dpi: int  # Rendering DPI
    direct_text: Optional[str] = None  # Text extracted directly from PDF

    # Classification fields (populated by classifier)
    drawing_type: Optional[str] = None  # From DrawingType enum
    needs_ocr: bool = True
    has_bom: bool = False

    def get_thumbnail(self, max_width: int = 800) -> Image.Image:
        """Get a resized thumbnail for display."""
        if self.width <= max_width:
            return self.image
        ratio = max_width / self.width
        new_height = int(self.height * ratio)
        return self.image.resize((max_width, new_height), Image.Resampling.LANCZOS)


def render_pdf(pdf_path: str, dpi: int = 300, verbose: bool = True) -> List[PageArtifact]:
    """
    Render all pages of a PDF to images.

    Args:
        pdf_path: Path to the PDF file
        dpi: Rendering resolution (default 300 for good OCR quality)
        verbose: Print progress messages

    Returns:
        List of PageArtifact objects, one per page
    """
    artifacts = []
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if verbose:
        print(f"PDF has {total_pages} page(s)")

    for page_idx in range(total_pages):
        page = doc.load_page(page_idx)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Extract text directly from PDF (if available)
        direct_text = page.get_text("text")
        has_text = len(direct_text.strip()) > 10

        artifacts.append(PageArtifact(
            pageIndex0=page_idx,
            page=page_idx + 1,
            image=img,
            width=pix.width,
            height=pix.height,
            dpi=dpi,
            direct_text=direct_text if has_text else None
        ))

        if verbose:
            print(f"  Page {page_idx + 1}: {pix.width}x{pix.height}px" +
                  (f" ({len(direct_text)} chars text)" if has_text else " (no embedded text)"))

    doc.close()
    return artifacts


def render_single_page(pdf_path: str, page_num: int = 1, dpi: int = 300) -> PageArtifact:
    """
    Render a single page from a PDF.

    Args:
        pdf_path: Path to the PDF file
        page_num: Page number (1-based)
        dpi: Rendering resolution

    Returns:
        PageArtifact for the requested page

    Raises:
        ValueError: If page_num is out of range
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if page_num < 1 or page_num > total_pages:
        doc.close()
        raise ValueError(f"Page {page_num} out of range (PDF has {total_pages} pages)")

    page_idx = page_num - 1
    page = doc.load_page(page_idx)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    direct_text = page.get_text("text")

    artifact = PageArtifact(
        pageIndex0=page_idx,
        page=page_num,
        image=img,
        width=pix.width,
        height=pix.height,
        dpi=dpi,
        direct_text=direct_text if len(direct_text.strip()) > 10 else None
    )

    doc.close()
    return artifact


def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF without rendering."""
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def extract_pdf_text(pdf_path: str) -> str:
    """
    Extract all text from a PDF using PyMuPDF.

    This is fast text extraction without OCR - only works if the PDF
    has embedded text (not scanned images).

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Combined text from all pages
    """
    doc = fitz.open(pdf_path)
    text_parts = []

    for page_idx in range(len(doc)):
        page = doc.load_page(page_idx)
        text = page.get_text("text")
        if text.strip():
            text_parts.append(text)

    doc.close()
    return "\n\n".join(text_parts)
