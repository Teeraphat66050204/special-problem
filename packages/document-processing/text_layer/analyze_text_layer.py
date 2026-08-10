"""Orchestrate abstract detection, text extraction, and quality assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from text_layer.extract_text_layer import (  # type: ignore[import-not-found]
        TextLayerError,
        extract_abstract_text_layers,
    )
    from text_layer.quality import (  # type: ignore[import-not-found]
        DEFAULT_QUALITY_CONFIG,
        QualityConfig,
        assess_text_quality,
    )
else:
    from .extract_text_layer import TextLayerError, extract_abstract_text_layers
    from .quality import DEFAULT_QUALITY_CONFIG, QualityConfig, assess_text_quality

from abstract_detection import AbstractDetectionError, detect_abstract_page


def analyze_abstract_text_layers(
    pdf_path: str | Path,
    *,
    max_pages: int = 15,
    top_k: int = 5,
    quality_config: QualityConfig = DEFAULT_QUALITY_CONFIG,
) -> dict[str, object]:
    """Analyze the text layer of every detected abstract page."""
    detection = detect_abstract_page(pdf_path, max_pages=max_pages, top_k=top_k)
    abstract_pages = detection.get("abstract_pages", [])
    if not isinstance(abstract_pages, list):
        raise TextLayerError("Abstract Detection returned invalid abstract_pages.")
    extracted_pages = extract_abstract_text_layers(pdf_path, abstract_pages)

    analyzed_pages: list[dict[str, object]] = []
    for candidate, extracted in zip(abstract_pages, extracted_pages, strict=True):
        assessment = assess_text_quality(
            str(extracted["raw_text"]),
            language=str(extracted["language"]),
            normalized_text=str(extracted["normalized_for_quality_text"]),
            config=quality_config,
        )
        text_layer = {
            "available": assessment["available"],
            "raw_text": extracted["raw_text"],
            "normalized_for_quality_text": extracted[
                "normalized_for_quality_text"
            ],
            "character_count": extracted["character_count"],
            "non_whitespace_character_count": extracted[
                "non_whitespace_character_count"
            ],
            **{key: value for key, value in assessment.items() if key != "available"},
        }
        analyzed_pages.append({**candidate, "text_layer": text_layer})

    return {
        "input_file": str(Path(pdf_path)),
        "primary_candidate": detection.get("primary_candidate"),
        "abstract_pages": analyzed_pages,
        "requires_manual_selection": detection.get("requires_manual_selection", False),
        "requires_ocr_pages": [
            page["page_number"]
            for page in analyzed_pages
            if page["text_layer"]["requires_ocr"]
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect abstract pages and assess their PDF text layers.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to a PDF")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="Pages to scan for abstracts (default: 15)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Abstract candidate ranking size (default: 5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete structured result as JSON",
    )
    return parser.parse_args(argv)


def _language_label(language: object) -> str:
    labels = {"thai": "Thai", "english": "English", "mixed": "Mixed"}
    return labels.get(str(language).casefold(), str(language).title())


def print_human_result(result: dict[str, object]) -> None:
    pages = result["abstract_pages"]
    if not pages:
        print("No abstract page passed the detection threshold.")
        return
    for position, page in enumerate(pages):
        if position:
            print()
        text_layer = page["text_layer"]
        print(f"{_language_label(page['language'])} Abstract")
        print(f"Page: {page['page_number']}")
        availability = "available" if text_layer["available"] else "missing"
        print(f"Text Layer: {availability}")
        print(f"Quality: {text_layer['quality']}")
        print(f"Score: {text_layer['quality_score']:.4f}")
        requires_ocr = "yes" if text_layer["requires_ocr"] else "no"
        print(f"Requires OCR: {requires_ocr}")
        print(f"Reasons: {', '.join(text_layer['reasons'])}")


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    try:
        result = analyze_abstract_text_layers(
            args.input,
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except (AbstractDetectionError, TextLayerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
