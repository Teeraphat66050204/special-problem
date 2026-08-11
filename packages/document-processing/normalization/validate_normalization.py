"""Offline normalization validation over benchmark PDFs and stored text."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from normalization import (  # type: ignore[import-not-found]
        DEFAULT_NORMALIZATION_CONFIG,
        normalize_processed_document,
        normalize_text,
    )
    from text_layer import analyze_abstract_text_layers
else:
    from . import (
        DEFAULT_NORMALIZATION_CONFIG,
        normalize_processed_document,
        normalize_text,
    )
    from text_layer import analyze_abstract_text_layers


def _load_precomputed_manifest(
    manifest_path: Path | None,
    text_directory: Path | None,
) -> dict[tuple[str, int], Path]:
    if manifest_path is None or text_directory is None:
        return {}
    references: dict[tuple[str, int], Path] = {}
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            document_id = row.get("document_id", "").strip()
            page_number = int(row.get("page_number", "0"))
            filename = row.get("ground_truth_file", "").strip()
            if document_id and page_number > 0 and filename:
                references[(document_id, page_number)] = text_directory / filename
    return references


def _content_signature(text: str) -> str:
    """Ignore only transformations explicitly permitted by normalization."""
    normalized = unicodedata.normalize("NFC", text)
    removable = {
        "\ufeff",
        *DEFAULT_NORMALIZATION_CONFIG.zero_width_characters,
    }
    return "".join(
        character
        for character in normalized
        if not character.isspace() and character not in removable
    )


def _build_unified_page(
    page: Mapping[str, Any],
    document_id: str,
    references: Mapping[tuple[str, int], Path],
) -> dict[str, object]:
    text_layer = page.get("text_layer")
    if not isinstance(text_layer, Mapping):
        raise ValueError("Analyzed abstract page has no text_layer result")
    if not bool(text_layer.get("requires_ocr")):
        return {
            **dict(page),
            "text_source": "text_layer",
            "text": text_layer.get("raw_text"),
            "processing_status": "success",
            "requires_manual_review": False,
            "validation_input": "production_text_layer",
        }

    page_number = int(page["page_number"])
    reference_path = references.get((document_id, page_number))
    if reference_path is not None and reference_path.is_file():
        return {
            **dict(page),
            "text_source": "ocr",
            "text": reference_path.read_text(encoding="utf-8-sig"),
            "processing_status": "success",
            "requires_manual_review": False,
            "validation_input": "precomputed_reference_text",
        }
    return {
        **dict(page),
        "text_source": None,
        "text": None,
        "processing_status": "ocr_failed",
        "requires_manual_review": True,
        "validation_input": "unavailable_without_ocr_api",
    }


def validate_benchmark(
    pdf_directory: str | Path,
    *,
    manifest_path: str | Path | None = None,
    precomputed_text_directory: str | Path | None = None,
    max_pages: int = 15,
    top_k: int = 5,
) -> dict[str, object]:
    """Run production detection/quality and offline-only normalization."""
    pdf_dir = Path(pdf_directory)
    if not pdf_dir.is_dir():
        raise ValueError(f"PDF directory does not exist: '{pdf_dir}'")
    if (manifest_path is None) != (precomputed_text_directory is None):
        raise ValueError(
            "manifest_path and precomputed_text_directory must be provided together"
        )
    manifest = Path(manifest_path) if manifest_path is not None else None
    text_dir = (
        Path(precomputed_text_directory)
        if precomputed_text_directory is not None
        else None
    )
    references = _load_precomputed_manifest(manifest, text_dir)
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        raise ValueError(f"PDF directory contains no PDF files: '{pdf_dir}'")

    totals: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    documents: list[dict[str, object]] = []
    preservation_failures: list[dict[str, object]] = []
    idempotence_failures: list[dict[str, object]] = []

    for pdf_path in pdf_paths:
        document_id = pdf_path.stem
        try:
            analysis = analyze_abstract_text_layers(
                pdf_path,
                max_pages=max_pages,
                top_k=top_k,
            )
            analyzed_pages = analysis.get("abstract_pages", [])
            if not isinstance(analyzed_pages, list):
                raise ValueError("Text-layer analysis returned invalid abstract_pages")
            unified_pages = [
                _build_unified_page(page, document_id, references)
                for page in analyzed_pages
            ]
            normalized = normalize_processed_document(
                {
                    "input_file": str(pdf_path),
                    "abstract_pages": unified_pages,
                }
            )
        except Exception as exc:
            totals["document_failures"] += 1
            documents.append({"document_id": document_id, "error": str(exc)})
            continue

        document_pages = normalized["abstract_pages"]
        totals["documents_processed"] += 1
        totals["texts_seen"] += len(document_pages)
        page_summaries: list[dict[str, object]] = []
        for page in document_pages:
            status = str(page["normalization_status"])
            source = page.get("text_source")
            totals[f"source_{source or 'none'}"] += 1
            totals[status] += 1
            metadata = page["normalization"]
            if status != "skipped":
                totals["changed" if metadata["changed"] else "unchanged"] += 1
            totals["warnings"] += len(metadata["warnings"])
            totals["original_length"] += metadata["stats"]["original_length"] or 0
            totals["normalized_length"] += metadata["stats"]["normalized_length"] or 0
            operations.update(metadata["operations"])

            original = page.get("text")
            canonical = page.get("normalized_text")
            page_key = {
                "document_id": document_id,
                "page_number": page.get("page_number"),
            }
            preserved: bool | None = None
            idempotent: bool | None = None
            if isinstance(original, str) and isinstance(canonical, str):
                preserved = _content_signature(original) == _content_signature(canonical)
                idempotent = normalize_text(canonical).normalized_text == canonical
                totals["preservation_checks"] += 1
                totals["idempotence_checks"] += 1
                if not preserved:
                    preservation_failures.append(page_key)
                if not idempotent:
                    idempotence_failures.append(page_key)
            page_summaries.append(
                {
                    **page_key,
                    "language": page.get("language"),
                    "text_source": source,
                    "validation_input": page.get("validation_input"),
                    "normalization_status": status,
                    "changed": metadata["changed"],
                    "warnings": metadata["warnings"],
                    "original_length": metadata["stats"]["original_length"],
                    "normalized_length": metadata["stats"]["normalized_length"],
                    "content_preserved": preserved,
                    "idempotent": idempotent,
                }
            )
        documents.append({"document_id": document_id, "pages": page_summaries})

    return {
        "validation_type": "normalization_validation_not_accuracy",
        "offline_only": True,
        "pdfs_found": len(pdf_paths),
        "documents_processed": totals["documents_processed"],
        "document_failures": totals["document_failures"],
        "texts_seen": totals["texts_seen"],
        "source_counts": {
            "text_layer": totals["source_text_layer"],
            "ocr_precomputed": totals["source_ocr"],
            "none": totals["source_none"],
        },
        "changed": totals["changed"],
        "unchanged": totals["unchanged"],
        "warnings": totals["warnings"],
        "empty": totals["empty"],
        "skipped": totals["skipped"],
        "original_length": totals["original_length"],
        "normalized_length": totals["normalized_length"],
        "operations": dict(sorted(operations.items())),
        "content_preservation": {
            "checks": totals["preservation_checks"],
            "failures": preservation_failures,
        },
        "idempotence": {
            "checks": totals["idempotence_checks"],
            "failures": idempotence_failures,
        },
        "documents": documents,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate normalization offline; never invoke an OCR API.",
    )
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--precomputed-text-dir", type=Path)
    parser.add_argument("--max-pages", type=int, default=15)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        report = validate_benchmark(
            args.pdf_dir,
            manifest_path=args.manifest,
            precomputed_text_directory=args.precomputed_text_dir,
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["document_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
