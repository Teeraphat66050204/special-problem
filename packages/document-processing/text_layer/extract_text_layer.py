"""Extract unmodified text from PDF pages with PyMuPDF."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence


class TextLayerError(Exception):
    """A user-facing text-layer extraction failure."""


def normalize_for_quality(text: str) -> str:
    """Normalize only the copy used for quality calculation."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def load_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TextLayerError(
            "PyMuPDF is not installed. Install dependencies with "
            "'python -m pip install -r packages/document-processing/requirements.txt'."
        ) from exc
    return pymupdf


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    path = Path(pdf_path)
    if not path.exists():
        raise TextLayerError(f"PDF does not exist: '{path}'.")
    if not path.is_file():
        raise TextLayerError(f"PDF path is not a file: '{path}'.")
    return path


def _open_pdf(pdf_path: str | Path) -> Any:
    path = _validate_pdf_path(pdf_path)
    pymupdf = load_pymupdf()
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise TextLayerError(f"Could not open PDF '{path}': {exc}") from exc

    if not document.is_pdf:
        document.close()
        raise TextLayerError(f"Input file is not a PDF: '{path}'.")
    if document.needs_pass:
        document.close()
        raise TextLayerError(f"PDF requires a password: '{path}'.")
    if document.page_count <= 0:
        document.close()
        raise TextLayerError(f"PDF contains no pages: '{path}'.")
    return document


def _extract_from_document(
    document: Any,
    page_index: int,
    *,
    language: str,
) -> dict[str, object]:
    if isinstance(page_index, bool) or not isinstance(page_index, int):
        raise TextLayerError("page_index must be an integer.")
    if page_index < 0 or page_index >= document.page_count:
        raise TextLayerError(
            f"Invalid page_index {page_index}. PDF has {document.page_count} page(s)."
        )
    try:
        raw_text = document.load_page(page_index).get_text("text", sort=True)
    except Exception as exc:
        raise TextLayerError(
            f"Could not extract text layer from page {page_index + 1}: {exc}"
        ) from exc

    normalized = normalize_for_quality(raw_text)
    return {
        "page_number": page_index + 1,
        "page_index": page_index,
        "language": language,
        "raw_text": raw_text,
        "normalized_for_quality_text": normalized,
        "character_count": len(raw_text),
        "non_whitespace_character_count": sum(
            not character.isspace() for character in raw_text
        ),
    }


def extract_page_text(
    pdf_path: str | Path,
    page_index: int,
    *,
    language: str = "unknown",
) -> dict[str, object]:
    """Extract one zero-based page while retaining the unmodified raw text."""
    document = _open_pdf(pdf_path)
    try:
        return _extract_from_document(document, page_index, language=language)
    finally:
        document.close()


def _candidate_page_index(candidate: Mapping[str, object]) -> int:
    page_index = candidate.get("page_index")
    page_number = candidate.get("page_number")
    if page_index is None and page_number is None:
        raise TextLayerError("Abstract candidate has no page_index or page_number.")
    if page_index is not None and (
        isinstance(page_index, bool) or not isinstance(page_index, int)
    ):
        raise TextLayerError("Abstract candidate page_index must be an integer.")
    if page_number is not None and (
        isinstance(page_number, bool) or not isinstance(page_number, int)
    ):
        raise TextLayerError("Abstract candidate page_number must be an integer.")

    resolved_index = page_index if isinstance(page_index, int) else int(page_number) - 1
    if resolved_index < 0:
        raise TextLayerError("Abstract candidate page must be greater than zero.")
    if isinstance(page_number, int) and page_number != resolved_index + 1:
        raise TextLayerError(
            "Abstract candidate page_number and page_index refer to different pages."
        )
    return resolved_index


def extract_abstract_text_layers(
    pdf_path: str | Path,
    abstract_pages: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Extract every page from an Abstract Detection ``abstract_pages`` list."""
    document = _open_pdf(pdf_path)
    try:
        extracted: list[dict[str, object]] = []
        for candidate in abstract_pages:
            page_index = _candidate_page_index(candidate)
            language = candidate.get("language", "unknown")
            if not isinstance(language, str):
                raise TextLayerError("Abstract candidate language must be a string.")
            extracted.append(
                _extract_from_document(document, page_index, language=language)
            )
        return extracted
    finally:
        document.close()
