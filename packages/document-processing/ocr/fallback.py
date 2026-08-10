"""Conditional OCR fallback and unified abstract-page text orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from text_layer import analyze_abstract_text_layers

from .base import OCRProvider
from .models import OCRError, OCRPageImage, OCRResult
from .render import PageRenderError, render_page_for_ocr


Analyzer = Callable[..., dict[str, object]]
Renderer = Callable[..., OCRPageImage]


def _provider_name(provider: OCRProvider) -> str:
    name = getattr(provider, "name", None)
    return str(name) if isinstance(name, str) and name else "unknown"


def _failed_provider_result(
    provider_name: str,
    code: str,
    message: str,
) -> OCRResult:
    return OCRResult.failed(
        provider=provider_name,
        error=OCRError(code=code, message=message),
    )


def _call_provider(
    provider: OCRProvider,
    page_image: OCRPageImage,
) -> OCRResult:
    provider_name = _provider_name(provider)
    try:
        result = provider.extract(page_image)
    except Exception:
        return _failed_provider_result(
            provider_name,
            "provider_exception",
            "OCR provider raised an unexpected error.",
        )
    if not isinstance(result, OCRResult):
        return _failed_provider_result(
            provider_name,
            "invalid_provider_result",
            "OCR provider returned an invalid result object.",
        )
    if result.success and (not isinstance(result.text, str) or not result.text.strip()):
        return OCRResult.failed(
            provider=result.provider,
            error=OCRError(
                code="empty_response",
                message="OCR provider returned no usable text.",
            ),
            processing_time_ms=result.processing_time_ms,
            attempts=result.attempts,
            raw_text=result.raw_text,
            raw_format=result.raw_format,
            metadata=result.metadata,
        )
    if not result.success and result.error is None:
        return OCRResult.failed(
            provider=result.provider,
            error=OCRError(
                code="invalid_provider_result",
                message="OCR provider failure did not include an error.",
            ),
            processing_time_ms=result.processing_time_ms,
            attempts=result.attempts,
            raw_text=result.raw_text,
            raw_format=result.raw_format,
            metadata=result.metadata,
        )
    return result


def _process_page(
    pdf_path: str | Path,
    page: Mapping[str, Any],
    provider: OCRProvider,
    renderer: Renderer,
) -> dict[str, object]:
    text_layer = page.get("text_layer")
    if not isinstance(text_layer, Mapping):
        raise ValueError("Analyzed abstract page has no text_layer result.")
    requires_ocr = bool(text_layer.get("requires_ocr"))
    base_result: dict[str, object] = {
        **dict(page),
        "requires_ocr": requires_ocr,
    }
    if not requires_ocr:
        return {
            **base_result,
            "text_source": "text_layer",
            "text": text_layer.get("raw_text"),
            "processing_status": "success",
            "requires_manual_review": False,
            "ocr": None,
            "error": None,
        }

    page_number = int(page["page_number"])
    page_index = int(page["page_index"])
    try:
        page_image = renderer(
            pdf_path,
            page_index,
            page_number=page_number,
            dpi=300,
        )
    except PageRenderError as exc:
        error = OCRError(
            code="render_failed",
            message=str(exc),
        )
        return {
            **base_result,
            "text_source": None,
            "text": None,
            "processing_status": "ocr_failed",
            "requires_manual_review": True,
            "ocr": None,
            "error": error.to_dict(),
        }
    except Exception:
        error = OCRError(
            code="render_failed",
            message="PDF page renderer raised an unexpected error.",
        )
        return {
            **base_result,
            "text_source": None,
            "text": None,
            "processing_status": "ocr_failed",
            "requires_manual_review": True,
            "ocr": None,
            "error": error.to_dict(),
        }

    ocr_result = _call_provider(provider, page_image)
    if not ocr_result.success:
        return {
            **base_result,
            "text_source": None,
            "text": None,
            "processing_status": "ocr_failed",
            "requires_manual_review": True,
            "ocr": ocr_result.to_dict(),
            "error": ocr_result.error.to_dict() if ocr_result.error else None,
        }
    return {
        **base_result,
        "text_source": "ocr",
        "text": ocr_result.text,
        "processing_status": "success",
        "requires_manual_review": False,
        "ocr": ocr_result.to_dict(),
        "error": None,
    }


def process_abstract_pages(
    pdf_path: str | Path,
    *,
    ocr_provider: OCRProvider,
    max_pages: int = 15,
    top_k: int = 5,
    analyzer: Analyzer = analyze_abstract_text_layers,
    renderer: Renderer = render_page_for_ocr,
) -> dict[str, object]:
    """Return one unified text field for every detected abstract page."""
    analysis = analyzer(pdf_path, max_pages=max_pages, top_k=top_k)
    pages = analysis.get("abstract_pages", [])
    if not isinstance(pages, list):
        raise ValueError("Text-layer analysis returned invalid abstract_pages.")

    processed = [
        _process_page(pdf_path, page, ocr_provider, renderer) for page in pages
    ]
    text_layer_pages = sum(page["text_source"] == "text_layer" for page in processed)
    ocr_routed_pages = sum(bool(page["requires_ocr"]) for page in processed)
    ocr_successes = sum(page["text_source"] == "ocr" for page in processed)
    ocr_failures = sum(page["processing_status"] == "ocr_failed" for page in processed)
    return {
        "input_file": str(Path(pdf_path)),
        "ocr_provider": _provider_name(ocr_provider),
        "processing_status": "partial_failure" if ocr_failures else "success",
        "requires_manual_selection": analysis.get(
            "requires_manual_selection",
            False,
        ),
        "primary_candidate": analysis.get("primary_candidate"),
        "abstract_pages": processed,
        "summary": {
            "abstract_pages": len(processed),
            "text_layer_pages": text_layer_pages,
            "ocr_routed_pages": ocr_routed_pages,
            "ocr_successes": ocr_successes,
            "ocr_failures": ocr_failures,
        },
    }
