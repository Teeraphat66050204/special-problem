"""Integrate normalization with unified OCR-fallback page results."""

from __future__ import annotations

from typing import Any, Mapping

from .models import DEFAULT_NORMALIZATION_CONFIG, NormalizationConfig
from .normalize_text import normalize_text


def _skipped_metadata(
    warning: str,
    original_text: object,
) -> dict[str, object]:
    return {
        "status": "skipped",
        "changed": False,
        "operations": [],
        "warnings": [warning],
        "stats": {
            "original_length": len(original_text) if isinstance(original_text, str) else None,
            "normalized_length": None,
            "line_count": 0,
        },
    }


def normalize_page_text(
    page_result: Mapping[str, Any],
    config: NormalizationConfig = DEFAULT_NORMALIZATION_CONFIG,
) -> dict[str, object]:
    """Add canonical text to one page without overwriting unified ``text``."""
    if not isinstance(page_result, Mapping):
        raise TypeError("page_result must be a mapping")

    page = dict(page_result)
    text = page.get("text")
    processing_status = page.get("processing_status")
    if processing_status != "success":
        metadata = _skipped_metadata("source_processing_failed", text)
        return {
            **page,
            "normalized_text": None,
            "normalization_status": "skipped",
            "requires_manual_review": True,
            "normalization": metadata,
        }
    if text is None:
        metadata = _skipped_metadata("missing_text", text)
        return {
            **page,
            "normalized_text": None,
            "normalization_status": "skipped",
            "requires_manual_review": True,
            "normalization": metadata,
        }
    if not isinstance(text, str):
        metadata = _skipped_metadata("invalid_text_type", text)
        return {
            **page,
            "normalized_text": None,
            "normalization_status": "skipped",
            "requires_manual_review": True,
            "normalization": metadata,
        }

    result = normalize_text(text, config)
    metadata = result.normalization_metadata()
    status = "success"
    requires_manual_review = bool(page.get("requires_manual_review", False))
    if not result.normalized_text:
        status = "empty"
        metadata["status"] = status
        metadata["warnings"].append("empty_normalized_text")
        requires_manual_review = True
    return {
        **page,
        "normalized_text": result.normalized_text,
        "normalization_status": status,
        "requires_manual_review": requires_manual_review,
        "normalization": metadata,
    }


def normalize_processed_document(
    processing_result: Mapping[str, Any],
    config: NormalizationConfig = DEFAULT_NORMALIZATION_CONFIG,
) -> dict[str, object]:
    """Normalize every abstract page independently and preserve page order."""
    if not isinstance(processing_result, Mapping):
        raise TypeError("processing_result must be a mapping")
    pages = processing_result.get("abstract_pages", [])
    if not isinstance(pages, list):
        raise ValueError("processing_result contains invalid abstract_pages")
    if any(not isinstance(page, Mapping) for page in pages):
        raise ValueError("abstract_pages must contain mappings")

    normalized_pages = [normalize_page_text(page, config) for page in pages]
    statuses = [str(page["normalization_status"]) for page in normalized_pages]
    warnings = sum(
        len(page["normalization"]["warnings"])  # type: ignore[index]
        for page in normalized_pages
    )
    changed = sum(
        bool(page["normalization"]["changed"])  # type: ignore[index]
        for page in normalized_pages
    )
    normalized_count = sum(status != "skipped" for status in statuses)
    original_length = sum(
        len(page["text"])
        for page in normalized_pages
        if isinstance(page.get("text"), str)
    )
    normalized_length = sum(
        len(page["normalized_text"])
        for page in normalized_pages
        if isinstance(page.get("normalized_text"), str)
    )
    source_counts = {
        "text_layer": sum(
            page.get("text_source") == "text_layer" for page in normalized_pages
        ),
        "ocr": sum(page.get("text_source") == "ocr" for page in normalized_pages),
        "none": sum(
            page.get("text_source") not in {"text_layer", "ocr"}
            for page in normalized_pages
        ),
    }
    return {
        **dict(processing_result),
        "abstract_pages": normalized_pages,
        "normalization": {
            "status": "partial" if any(status != "success" for status in statuses) else "success",
            "pages": len(normalized_pages),
            "changed": changed,
            "unchanged": normalized_count - changed,
            "warnings": warnings,
            "skipped": statuses.count("skipped"),
            "empty": statuses.count("empty"),
            "source_counts": source_counts,
            "original_length": original_length,
            "normalized_length": normalized_length,
        },
    }
