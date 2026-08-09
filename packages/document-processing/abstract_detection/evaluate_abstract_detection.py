"""Evaluate abstract page detection against manually verified page numbers."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from detect_abstract_page import (
    DEFAULT_MAX_PAGES,
    AbstractDetectionError,
    detect_abstract_page,
)


DEFAULT_GROUND_TRUTH = Path(__file__).with_name("benchmark_ground_truth.json")


class EvaluationError(Exception):
    """A user-facing evaluation failure."""


def load_ground_truth(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"Could not read ground truth '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Ground truth is not valid JSON: {exc}") from exc

    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(documents, list) or not documents:
        raise EvaluationError("Ground truth must contain a non-empty documents list.")

    validated: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for position, item in enumerate(documents, start=1):
        if not isinstance(item, dict):
            raise EvaluationError(f"Ground-truth item {position} must be an object.")
        document_id = item.get("document_id")
        thai_page = item.get("thai_abstract_page")
        english_page = item.get("english_abstract_page")
        if not isinstance(document_id, str) or not document_id:
            raise EvaluationError(f"Ground-truth item {position} has no document_id.")
        if document_id in seen_ids:
            raise EvaluationError(f"Duplicate document_id in ground truth: {document_id}.")
        if not isinstance(thai_page, int) or thai_page <= 0:
            raise EvaluationError(f"Invalid Thai abstract page for {document_id}.")
        if not isinstance(english_page, int) or english_page <= 0:
            raise EvaluationError(f"Invalid English abstract page for {document_id}.")
        seen_ids.add(document_id)
        validated.append(
            {
                "document_id": document_id,
                "thai_abstract_page": thai_page,
                "english_abstract_page": english_page,
            }
        )
    return validated


def _language_pages(result: Mapping[str, Any], language: str) -> list[int]:
    pages = {
        item["page_number"]
        for item in result.get("abstract_pages", [])
        if isinstance(item, dict)
        and isinstance(item.get("page_number"), int)
        and item.get("language") in {language, "mixed"}
    }
    return sorted(pages)


def _metric(correct: int, total: int) -> dict[str, int | float]:
    return {
        "correct": correct,
        "total": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
    }


def evaluate_predictions(
    ground_truth: Sequence[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    document_results: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    thai_correct = 0
    english_correct = 0
    any_correct = 0
    top_three_hits = 0

    for expected in ground_truth:
        document_id = str(expected["document_id"])
        expected_thai = int(expected["thai_abstract_page"])
        expected_english = int(expected["english_abstract_page"])
        result = predictions.get(document_id, {})
        predicted_thai = _language_pages(result, "thai")
        predicted_english = _language_pages(result, "english")
        predicted_abstract_pages = sorted(set(predicted_thai + predicted_english))
        top_three = [
            item["page_number"]
            for item in result.get("candidates", [])[:3]
            if isinstance(item, dict) and isinstance(item.get("page_number"), int)
        ]
        primary = result.get("primary_candidate")
        primary_page = primary.get("page_number") if isinstance(primary, dict) else None

        thai_match = expected_thai in predicted_thai
        english_match = expected_english in predicted_english
        any_match = bool(
            {expected_thai, expected_english}.intersection(predicted_abstract_pages)
        )
        top_three_hits += int(expected_thai in top_three)
        top_three_hits += int(expected_english in top_three)
        thai_correct += int(thai_match)
        english_correct += int(english_match)
        any_correct += int(any_match)

        document_result = {
            "document_id": document_id,
            "expected": {
                "thai_abstract_page": expected_thai,
                "english_abstract_page": expected_english,
            },
            "predicted": {
                "thai_abstract_pages": predicted_thai,
                "english_abstract_pages": predicted_english,
                "primary_candidate_page": primary_page,
                "top_3_pages": top_three,
            },
            "thai_correct": thai_match,
            "english_correct": english_match,
            "any_correct": any_match,
        }
        if result.get("detection_error"):
            document_result["detection_error"] = result["detection_error"]
        document_results.append(document_result)
        if not thai_match or not english_match:
            errors.append(document_result)

    document_count = len(ground_truth)
    return {
        "document_count": document_count,
        "metrics": {
            "thai_abstract_detection_accuracy": _metric(thai_correct, document_count),
            "english_abstract_detection_accuracy": _metric(
                english_correct, document_count
            ),
            "any_abstract_detection_accuracy": _metric(any_correct, document_count),
            "top_3_recall": _metric(top_three_hits, document_count * 2),
        },
        "error_count": len(errors),
        "errors": errors,
        "documents": document_results,
    }


def run_evaluation(
    ground_truth: Sequence[Mapping[str, object]],
    *,
    pdf_directory: Path,
    max_pages: int,
) -> dict[str, object]:
    predictions: dict[str, Mapping[str, Any]] = {}
    started = time.perf_counter()
    for expected in ground_truth:
        document_id = str(expected["document_id"])
        pdf_path = pdf_directory / f"{document_id}.pdf"
        try:
            predictions[document_id] = detect_abstract_page(
                pdf_path,
                max_pages=max_pages,
                top_k=3,
            )
        except AbstractDetectionError as exc:
            predictions[document_id] = {
                "primary_candidate": None,
                "abstract_pages": [],
                "candidates": [],
                "detection_error": str(exc),
            }

    evaluation = evaluate_predictions(ground_truth, predictions)
    evaluation["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
    evaluation["configuration"] = {"max_pages": max_pages, "top_k": 3}
    return evaluation


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate abstract page detection on manually verified PDFs.",
    )
    parser.add_argument("--pdf-dir", required=True, type=Path, help="PDF directory")
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH,
        help=f"Ground-truth JSON (default: {DEFAULT_GROUND_TRUTH})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Pages to scan from each PDF (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    if args.max_pages <= 0:
        print("Error: --max-pages must be greater than zero.", file=sys.stderr)
        return 1
    try:
        ground_truth = load_ground_truth(args.ground_truth)
        evaluation = run_evaluation(
            ground_truth,
            pdf_directory=args.pdf_dir,
            max_pages=args.max_pages,
        )
        report = json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
    except (EvaluationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
