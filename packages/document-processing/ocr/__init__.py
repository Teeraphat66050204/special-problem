"""Conditional OCR fallback for document processing."""

from .base import OCRProvider
from .fallback import process_abstract_pages
from .models import OCRError, OCRPageImage, OCRResult
from .render import PageRenderError, render_page_for_ocr
from .typhoon_provider import TyphoonConfig, TyphoonProvider

__all__ = [
    "OCRError",
    "OCRPageImage",
    "OCRProvider",
    "OCRResult",
    "PageRenderError",
    "TyphoonConfig",
    "TyphoonProvider",
    "process_abstract_pages",
    "render_page_for_ocr",
]
