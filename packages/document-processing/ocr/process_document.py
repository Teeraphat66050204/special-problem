"""CLI for conditional OCR fallback and unified abstract-page text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ocr.fallback import process_abstract_pages  # type: ignore[import-not-found]
    from ocr.typhoon_provider import (  # type: ignore[import-not-found]
        TyphoonConfig,
        TyphoonProvider,
    )
else:
    from .fallback import process_abstract_pages
    from .typhoon_provider import TyphoonConfig, TyphoonProvider

from abstract_detection import AbstractDetectionError
from text_layer import TextLayerError


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process abstract pages with conditional Typhoon OCR fallback.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to a PDF")
    parser.add_argument("--max-pages", type=int, default=15)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-retries", type=nonnegative_int, default=2)
    parser.add_argument(
        "--request-interval-seconds",
        type=nonnegative_float,
        default=3.1,
    )
    parser.add_argument("--timeout-seconds", type=positive_float, default=180.0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="Print complete JSON")
    return parser.parse_args(argv)


def _language_label(language: object) -> str:
    return {"thai": "Thai", "english": "English"}.get(
        str(language).casefold(),
        str(language).title(),
    )


def print_human_result(result: dict[str, object]) -> None:
    pages = result["abstract_pages"]
    if not pages:
        print("No abstract pages were detected.")
        return
    for position, page in enumerate(pages):
        if position:
            print()
        layer = page["text_layer"]
        ocr = page["ocr"]
        print(f"{_language_label(page['language'])} Abstract")
        print(f"Page: {page['page_number']}")
        print(f"Text Layer Quality: {layer['quality']}")
        print(f"Requires OCR: {'yes' if page['requires_ocr'] else 'no'}")
        print(f"OCR Provider: {ocr['provider'] if ocr else 'not called'}")
        if ocr:
            print(f"OCR Status: {'success' if ocr['success'] else 'failed'}")
        else:
            print("OCR Status: not called")
        print(f"Final Text Source: {page['text_source'] or 'none'}")
        print(f"Processing Status: {page['processing_status']}")
        if page["error"]:
            print(f"Error: {page['error']['code']}: {page['error']['message']}")


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        config = TyphoonConfig(
            max_retries=args.max_retries,
            request_interval_seconds=args.request_interval_seconds,
            timeout_seconds=args.timeout_seconds,
            max_concurrency=args.max_concurrency,
        )
        result = process_abstract_pages(
            args.input,
            ocr_provider=TyphoonProvider(config),
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except (AbstractDetectionError, TextLayerError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_result(result)
    return 1 if result["summary"]["ocr_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
