"""Offline metadata extraction evaluation against manual ground truth."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from metadata_extraction import extract_metadata  # type: ignore[import-not-found]
else:
    from . import extract_metadata

from normalization import normalize_processed_document
from normalization.validate_normalization import (
    _build_unified_page,
    _load_precomputed_manifest,
)
from text_layer import analyze_abstract_text_layers


DEFAULT_GROUND_TRUTH = Path(__file__).with_name("benchmark_metadata_ground_truth.json")
EVALUATED_FIELDS = (
    "title_th",
    "title_en",
    "students",
    "student_id",
    "degree",
    "department",
    "faculty",
    "academic_year",
    "advisor",
    "co_advisors",
    "keywords",
)
SCALAR_FIELDS = (
    "title_th",
    "title_en",
    "degree",
    "department",
    "faculty",
    "academic_year",
    "advisor",
)
LIST_FIELDS = ("co_advisors", "keywords")
ABSTRACT_FIELDS = ("abstract_th", "abstract_en")


class MetadataEvaluationError(Exception):
    """A controlled benchmark configuration or input failure."""


def evaluation_normalize(value: object) -> str:
    """Conservative evaluation-only NFC and whitespace/case normalization."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFC", str(value))
    return " ".join(normalized.split()).casefold()


def load_ground_truth(path: str | Path = DEFAULT_GROUND_TRUTH) -> dict[str, dict[str, Any]]:
    ground_truth_path = Path(path)
    try:
        payload = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MetadataEvaluationError(
            f"Could not read ground truth '{ground_truth_path}': {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MetadataEvaluationError(f"Ground truth is not valid JSON: {exc}") from exc
    documents = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(documents, dict) or not documents:
        raise MetadataEvaluationError("Ground truth must contain a non-empty documents object")
    if any(not isinstance(value, dict) for value in documents.values()):
        raise MetadataEvaluationError("Every ground-truth document must be an object")
    return documents


def _student_pairs(value: object) -> set[tuple[str, str]]:
    if not isinstance(value, list):
        return set()
    pairs: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        pairs.add(
            (
                evaluation_normalize(item.get("name")),
                evaluation_normalize(item.get("student_id")),
            )
        )
    return pairs


def _student_ids(value: object) -> set[str]:
    return {student_id for _, student_id in _student_pairs(value) if student_id}


def _normalized_items(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {evaluation_normalize(item) for item in value if evaluation_normalize(item)}


def _prf(true_positive: int, predicted: int, expected: int) -> dict[str, float | int]:
    precision = true_positive / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = true_positive / expected if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "predicted": predicted,
        "expected": expected,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _character_distance(reference: str, prediction: str) -> int:
    if len(reference) < len(prediction):
        reference, prediction = prediction, reference
    previous = list(range(len(prediction) + 1))
    for reference_index, reference_character in enumerate(reference, start=1):
        current = [reference_index]
        for prediction_index, prediction_character in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[prediction_index] + 1,
                    previous[prediction_index - 1]
                    + (reference_character != prediction_character),
                )
            )
        previous = current
    return previous[-1]


def _error_category(field: str, predicted: object) -> str:
    missing = predicted is None or predicted == [] or predicted == ""
    if missing:
        return "missing_source_text" if field == "title_en" else "missing_extraction"
    return {
        "title_th": "title_boundary",
        "title_en": "title_boundary",
        "students": "student_pairing",
        "student_id": "student_pairing",
        "degree": "label_variant",
        "department": "multiline_boundary",
        "faculty": "multiline_boundary",
        "academic_year": "candidate_conflict",
        "advisor": "advisor_boundary",
        "co_advisors": "advisor_boundary",
        "keywords": "keyword_splitting",
    }.get(field, "other")


def evaluate_predictions(
    predictions: Mapping[str, Mapping[str, Any] | None],
    ground_truth: Mapping[str, Mapping[str, Any]],
    *,
    extraction_times_ms: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    counters = {
        field: Counter({"evaluable": 0, "correct": 0, "extracted": 0})
        for field in EVALUATED_FIELDS
    }
    item_counts = {
        "students": Counter(),
        "student_id": Counter(),
        "co_advisors": Counter(),
        "keywords": Counter(),
    }
    mismatches: list[dict[str, Any]] = []
    unavailable: list[str] = []
    manual_review_count = 0
    abstract_counts = {
        field: Counter({"evaluable": 0, "exact": 0, "distance": 0, "characters": 0})
        for field in ABSTRACT_FIELDS
    }

    for document_id, expected in ground_truth.items():
        prediction = predictions.get(document_id)
        if prediction is None:
            unavailable.append(document_id)
            continue
        metadata = prediction.get("metadata", {})
        if not isinstance(metadata, Mapping):
            unavailable.append(document_id)
            continue
        if bool(prediction.get("requires_manual_review")):
            manual_review_count += 1

        for field in ABSTRACT_FIELDS:
            if field not in expected:
                continue
            expected_abstract = evaluation_normalize(expected.get(field))
            predicted_abstract = evaluation_normalize(metadata.get(field))
            abstract_counts[field]["evaluable"] += 1
            abstract_counts[field]["exact"] += predicted_abstract == expected_abstract
            abstract_counts[field]["distance"] += _character_distance(
                expected_abstract,
                predicted_abstract,
            )
            abstract_counts[field]["characters"] += len(expected_abstract)

        for field in EVALUATED_FIELDS:
            source_field = "students" if field == "student_id" else field
            if source_field not in expected:
                continue
            counters[field]["evaluable"] += 1
            predicted_value = metadata.get(source_field)
            expected_value = expected.get(source_field)
            if field in SCALAR_FIELDS:
                extracted = predicted_value is not None and str(predicted_value).strip() != ""
                correct = evaluation_normalize(predicted_value) == evaluation_normalize(
                    expected_value
                )
            elif field == "students":
                predicted_set = _student_pairs(predicted_value)
                expected_set = _student_pairs(expected_value)
                extracted = bool(predicted_set) or not expected_set
                correct = predicted_set == expected_set
                item_counts[field]["tp"] += len(predicted_set & expected_set)
                item_counts[field]["predicted"] += len(predicted_set)
                item_counts[field]["expected"] += len(expected_set)
            elif field == "student_id":
                predicted_set = _student_ids(predicted_value)
                expected_set = _student_ids(expected_value)
                extracted = bool(predicted_set) or not expected_set
                correct = predicted_set == expected_set
                item_counts[field]["tp"] += len(predicted_set & expected_set)
                item_counts[field]["predicted"] += len(predicted_set)
                item_counts[field]["expected"] += len(expected_set)
            else:
                predicted_set = _normalized_items(predicted_value)
                expected_set = _normalized_items(expected_value)
                extracted = bool(predicted_set) or not expected_set
                correct = predicted_set == expected_set
                item_counts[field]["tp"] += len(predicted_set & expected_set)
                item_counts[field]["predicted"] += len(predicted_set)
                item_counts[field]["expected"] += len(expected_set)
            if extracted:
                counters[field]["extracted"] += 1
            if correct:
                counters[field]["correct"] += 1
            else:
                mismatches.append(
                    {
                        "document_id": document_id,
                        "field": field,
                        "expected": expected_value,
                        "predicted": predicted_value,
                        "category": _error_category(field, predicted_value),
                    }
                )

    field_metrics: dict[str, dict[str, Any]] = {}
    total_correct = 0
    total_evaluable = 0
    for field, counts in counters.items():
        evaluable = counts["evaluable"]
        total_correct += counts["correct"]
        total_evaluable += evaluable
        field_metrics[field] = {
            "correct": counts["correct"],
            "evaluable": evaluable,
            "accuracy": round(counts["correct"] / evaluable, 4) if evaluable else None,
            "extracted": counts["extracted"],
            "coverage": round(counts["extracted"] / evaluable, 4) if evaluable else None,
        }

    item_metrics = {
        field: _prf(counts["tp"], counts["predicted"], counts["expected"])
        for field, counts in item_counts.items()
    }
    error_categories = Counter(item["category"] for item in mismatches)
    times = list((extraction_times_ms or {}).values())
    abstract_metrics = {}
    for field, counts in abstract_counts.items():
        evaluable = counts["evaluable"]
        characters = counts["characters"]
        abstract_metrics[field] = {
            "evaluable": evaluable,
            "normalized_exact_matches": counts["exact"],
            "normalized_exact_accuracy": (
                round(counts["exact"] / evaluable, 4) if evaluable else None
            ),
            "character_error_rate": (
                round(counts["distance"] / characters, 4) if characters else None
            ),
        }
    return {
        "definition": {
            "field_accuracy": (
                "exact field matches / evaluable ground-truth fields after NFC, "
                "case-folding, and whitespace collapse only"
            ),
            "coverage": (
                "non-empty extractions / evaluable ground-truth fields; an "
                "expected empty list is a covered valid value"
            ),
            "list_exact_match": (
                "order-independent normalized item set equality; students use "
                "(name, student_id) pairs"
            ),
        },
        "documents_in_ground_truth": len(ground_truth),
        "documents_evaluated": len(ground_truth) - len(unavailable),
        "documents_unavailable": unavailable,
        "field_metrics": field_metrics,
        "overall_field_accuracy": (
            round(total_correct / total_evaluable, 4) if total_evaluable else None
        ),
        "overall_correct": total_correct,
        "overall_evaluable": total_evaluable,
        "item_metrics": item_metrics,
        "abstract_metrics": abstract_metrics,
        "mismatches": mismatches,
        "error_categories": dict(sorted(error_categories.items())),
        "requires_manual_review_count": manual_review_count,
        "performance": {
            "documents_timed": len(times),
            "total_extraction_ms": round(sum(times), 3),
            "average_extraction_ms": round(sum(times) / len(times), 3) if times else None,
        },
    }


def run_offline_evaluation(
    pdf_directory: str | Path,
    *,
    manifest_path: str | Path,
    precomputed_text_directory: str | Path,
    ground_truth_path: str | Path = DEFAULT_GROUND_TRUTH,
    max_pages: int = 15,
    top_k: int = 5,
) -> dict[str, Any]:
    ground_truth = load_ground_truth(ground_truth_path)
    pdf_dir = Path(pdf_directory)
    references = _load_precomputed_manifest(
        Path(manifest_path),
        Path(precomputed_text_directory),
    )
    predictions: dict[str, Mapping[str, Any] | None] = {}
    extraction_times: dict[str, float] = {}
    pipeline_errors: dict[str, str] = {}
    for document_id in ground_truth:
        pdf_path = pdf_dir / f"{document_id}.pdf"
        if not pdf_path.is_file():
            predictions[document_id] = None
            pipeline_errors[document_id] = "pdf_unavailable"
            continue
        try:
            analysis = analyze_abstract_text_layers(
                pdf_path,
                max_pages=max_pages,
                top_k=top_k,
            )
            pages = analysis.get("abstract_pages", [])
            if not isinstance(pages, list):
                raise ValueError("invalid abstract_pages from text-layer analysis")
            unified_pages = [
                _build_unified_page(page, document_id, references) for page in pages
            ]
            normalized = normalize_processed_document({"abstract_pages": unified_pages})
            started = time.perf_counter()
            extraction = extract_metadata(normalized)
            extraction_times[document_id] = (time.perf_counter() - started) * 1000
            predictions[document_id] = extraction.to_dict()
        except Exception as exc:
            predictions[document_id] = None
            pipeline_errors[document_id] = str(exc)
    report = evaluate_predictions(
        predictions,
        ground_truth,
        extraction_times_ms=extraction_times,
    )
    report["offline_only"] = True
    report["pipeline_errors"] = pipeline_errors
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic metadata extraction without an OCR API.",
    )
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--precomputed-text-dir", required=True, type=Path)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--max-pages", type=int, default=15)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        report = run_offline_evaluation(
            args.pdf_dir,
            manifest_path=args.manifest,
            precomputed_text_directory=args.precomputed_text_dir,
            ground_truth_path=args.ground_truth,
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except (MetadataEvaluationError, OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["documents_unavailable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
