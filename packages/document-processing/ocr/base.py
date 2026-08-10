"""OCR provider abstraction used by the document-processing pipeline."""

from __future__ import annotations

from typing import Protocol

from .models import OCRPageImage, OCRResult


class OCRProvider(Protocol):
    """A replaceable OCR provider that consumes one in-memory page image."""

    name: str

    def extract(self, page_image: OCRPageImage) -> OCRResult:
        """Extract plain text and provider-native raw text from one page."""
        ...
