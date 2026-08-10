"""Render only selected PDF pages for OCR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import OCRPageImage


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PageRenderError(Exception):
    """A controlled PDF page rendering failure."""


def _load_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PageRenderError(
            "PyMuPDF is not installed. Install document-processing dependencies."
        ) from exc
    return pymupdf


def render_page_for_ocr(
    pdf_path: str | Path,
    page_index: int,
    *,
    page_number: int | None = None,
    dpi: int = 300,
) -> OCRPageImage:
    """Render one zero-based PDF page as in-memory 300 DPI RGB PNG data."""
    path = Path(pdf_path)
    if not path.is_file():
        raise PageRenderError(f"PDF is not a file: '{path}'.")
    if isinstance(page_index, bool) or not isinstance(page_index, int):
        raise PageRenderError("page_index must be an integer.")
    if dpi != 300:
        raise PageRenderError("OCR fallback rendering must use 300 DPI.")
    resolved_page_number = page_index + 1 if page_number is None else page_number
    if resolved_page_number != page_index + 1:
        raise PageRenderError("page_number and page_index refer to different pages.")

    pymupdf = _load_pymupdf()
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise PageRenderError(f"Could not open PDF '{path}': {exc}") from exc
    try:
        if not document.is_pdf:
            raise PageRenderError(f"Input is not a PDF: '{path}'.")
        if document.needs_pass:
            raise PageRenderError(f"PDF requires a password: '{path}'.")
        if page_index < 0 or page_index >= document.page_count:
            raise PageRenderError(
                f"Invalid page_index {page_index}. PDF has {document.page_count} page(s)."
            )
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
        png_data = pixmap.tobytes("png")
    except PageRenderError:
        raise
    except Exception as exc:
        raise PageRenderError(
            f"Could not render PDF page {resolved_page_number}: {exc}"
        ) from exc
    finally:
        document.close()

    if not png_data.startswith(PNG_SIGNATURE):
        raise PageRenderError(
            f"Rendered page {resolved_page_number} is not valid PNG data."
        )
    if pixmap.n != 3 or pixmap.alpha:
        raise PageRenderError(
            f"Rendered page {resolved_page_number} is not RGB without alpha."
        )
    return OCRPageImage(
        data=png_data,
        page_number=resolved_page_number,
        page_index=page_index,
        width_px=pixmap.width,
        height_px=pixmap.height,
        dpi=dpi,
    )
