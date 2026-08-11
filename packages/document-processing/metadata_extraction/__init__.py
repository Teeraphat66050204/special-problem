"""Deterministic metadata extraction from canonical normalized text."""

from .extract_metadata import extract_metadata, extract_metadata_from_pages
from .models import (
    DEFAULT_EXTRACTION_CONFIG,
    ExtractionConfig,
    ExtractionResult,
    FieldCandidate,
    FieldResult,
)

__all__ = [
    "DEFAULT_EXTRACTION_CONFIG",
    "ExtractionConfig",
    "ExtractionResult",
    "FieldCandidate",
    "FieldResult",
    "extract_metadata",
    "extract_metadata_from_pages",
]
