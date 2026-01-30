"""PDF rendering utilities using PyMuPDF."""

import fitz  # PyMuPDF
from PIL import Image
from typing import List

from ..models.page import PageArtifact
from ..config import default_config


def render_pdf(pdf_path: str, dpi: int = None) -> List[PageArtifact]:
    """
    Render all pages of a PDF to images.

    Uses PyMuPDF (fitz) for high-quality rendering. Each page becomes
    a PageArtifact with the rendered image and metadata.

    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for rendering (default from config: 300)

    Returns:
        List of PageArtifact, one per page

    Example:
        artifacts = render_pdf("drawing.pdf")
        print(f"Rendered {len(artifacts)} pages")
        artifacts[0].image.show()  # Display first page
    """
    if dpi is None:
        dpi = default_config.render_dpi

    artifacts = []
    doc = fitz.open(pdf_path)

    for page_idx in range(len(doc)):
        page = doc.load_page(page_idx)

        # Render at specified DPI (72 is PDF default)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Extract text directly from PDF (if available)
        direct_text = page.get_text("text")
        direct_text = direct_text if len(direct_text.strip()) > 10 else None

        artifacts.append(
            PageArtifact(
                page_index=page_idx,
                page_number=page_idx + 1,
                image=img,
                width=pix.width,
                height=pix.height,
                dpi=dpi,
                direct_text=direct_text,
            )
        )

    doc.close()
    return artifacts
