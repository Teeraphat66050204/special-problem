"""Offline metadata-validation evaluation over stored benchmark inputs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from metadata_validation import validate_metadata  # type: ignore[import-not-found]
else:
    from . import validate_metadata

from metadata_extraction import extract_metadata
from metadata_extraction.evaluate_metadata_extraction import load_ground_truth
from normalization import normalize_processed_document
from normalization.validate_normalization import (
    _build_unified_page,
    _load_precomputed_manifest,
)
from text_layer import analyze_abstract_text_layers


DEFAULT_GROUND_TRUTH = Path(__file__).with_name("benchmark_validation_ground_truth.json")
VALIDATION_STATUSES = ("VALID", "REVIEW_REQUIRED", "INVALID", "MISSING")
DOCUMENT_STATUSES = ("VALID", "REVIEW_REQUIRED", "INVALID", "FAILED")


class ValidationEvaluationError(Exception):
    """Controlled invalid evaluator input or benchmark configuration."""


def load_validation_ground_truth(
    path: str | Path = DEFAULT_GROUND_TRUTH,
) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationEvaluationError(f"Could not read validation ground truth: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationEvaluationError(f"Validation ground truth is invalid JSON: {exc}") from exc
    documents = payload.get("documents") if isinstance(payload, Mapping) else None
    if not isinstance(documents, Mapping) or not documents:
        raise ValidationEvaluationError("Ground truth requires a non-empty documents object")
    return {
        str(name): dict(value)
        for name, value in documents.items()
        if isinstance(value, Mapping)
    }


def _prf(true_positive: int, predicted: int, expected: int) -> dict[str, Any]:
    precision = true_positive / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = true_positive / expected if expected else None
    if recall is None:
        f1 = None
    elif precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0
    return {
        "true_positive": true_positive,
        "predicted": predicted,
        "expected": expected,
        "precision": round(precision, 4),
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def evaluate_validation_results(
    results: Mapping[str, Mapping[str, Any] | None],
    ground_truth: Mapping[str, Mapping[str, Any]],
    *,
    validation_times_ms: Mapping[str, float] | None = None,
    extraction_manual_review_count: int = 0,
) -> dict[str, Any]:
    if not ground_truth:
        raise ValidationEvaluationError("Validation ground truth cannot be empty")
    field_expected = Counter()
    field_predicted = Counter()
    field_true_positive = Counter()
    document_expected = Counter()
    document_predicted = Counter()
    document_true_positive = Counter()
    field_matches = 0
    field_evaluable = 0
    document_matches = 0
    manual_tp = manual_predicted = manual_expected = 0
    false_positives: list[str] = []
    false_negatives: list[str] = []
    field_mismatches: list[dict[str, Any]] = []
    unavailable: list[str] = []
    incorrectly_resolved: list[dict[str, str]] = []

    for document_id, expected in ground_truth.items():
        result = results.get(document_id)
        if not isinstance(result, Mapping):
            unavailable.append(document_id)
            continue
        validation = result.get("validation", {})
        fields = validation.get("fields", {}) if isinstance(validation, Mapping) else {}
        predicted_document = str(validation.get("document_status", "FAILED"))
        expected_document = str(expected.get("expected_document_status", "FAILED"))
        document_expected[expected_document] += 1
        document_predicted[predicted_document] += 1
        if predicted_document == expected_document:
            document_matches += 1
            document_true_positive[expected_document] += 1

        predicted_review = bool(validation.get("requires_manual_review"))
        expected_review = bool(expected.get("expected_manual_review"))
        manual_predicted += predicted_review
        manual_expected += expected_review
        manual_tp += predicted_review and expected_review
        if predicted_review and not expected_review:
            false_positives.append(document_id)
        if expected_review and not predicted_review:
            false_negatives.append(document_id)

        expected_fields = expected.get("fields", {})
        if not isinstance(expected_fields, Mapping) or not isinstance(fields, Mapping):
            continue
        for field_name, expected_status_value in expected_fields.items():
            predicted_field = fields.get(field_name, {})
            predicted_status = (
                str(predicted_field.get("status", "MISSING"))
                if isinstance(predicted_field, Mapping)
                else "MISSING"
            )
            expected_status = str(expected_status_value)
            field_evaluable += 1
            field_expected[expected_status] += 1
            field_predicted[predicted_status] += 1
            if predicted_status == expected_status:
                field_matches += 1
                field_true_positive[expected_status] += 1
            else:
                field_mismatches.append(
                    {
                        "document_id": document_id,
                        "field": field_name,
                        "expected": expected_status,
                        "predicted": predicted_status,
                    }
                )
            if (
                isinstance(predicted_field, Mapping)
                and int(predicted_field.get("details", {}).get("candidate_conflicts_resolved", 0))
                and expected_status in {"REVIEW_REQUIRED", "INVALID"}
                and predicted_status == "VALID"
            ):
                incorrectly_resolved.append({"document_id": document_id, "field": field_name})

    field_class_metrics = {
        status: _prf(
            field_true_positive[status],
            field_predicted[status],
            field_expected[status],
        )
        for status in VALIDATION_STATUSES
    }
    document_class_metrics = {
        status: _prf(
            document_true_positive[status],
            document_predicted[status],
            document_expected[status],
        )
        for status in DOCUMENT_STATUSES
    }
    times = list((validation_times_ms or {}).values())
    return {
        "ground_truth_coverage": {
            "documents": len(ground_truth),
            "fields": field_evaluable,
            "full_benchmark_documents": 20,
        },
        "documents_evaluated": len(ground_truth) - len(unavailable),
        "documents_unavailable": unavailable,
        "document_status_accuracy": round(document_matches / len(ground_truth), 4),
        "document_class_metrics": document_class_metrics,
        "field_status_accuracy": (
            round(field_matches / field_evaluable, 4) if field_evaluable else None
        ),
        "field_class_metrics": field_class_metrics,
        "field_mismatches": field_mismatches,
        "manual_review_metrics": _prf(manual_tp, manual_predicted, manual_expected),
        "manual_review_false_positives": false_positives,
        "manual_review_false_negatives": false_negatives,
        "incorrectly_resolved_conflicts": incorrectly_resolved,
        "extraction_manual_review_count": extraction_manual_review_count,
        "validation_manual_review_count_ground_truth_subset": manual_predicted,
        "performance": {
            "documents_timed": len(times),
            "total_validation_ms": round(sum(times), 3),
            "average_validation_ms": round(sum(times) / len(times), 3) if times else None,
        },
    }


def run_offline_validation_evaluation(
    pdf_directory: str | Path,
    *,
    manifest_path: str | Path,
    precomputed_text_directory: str | Path,
    ground_truth_path: str | Path = DEFAULT_GROUND_TRUTH,
    max_pages: int = 15,
    top_k: int = 5,
) -> dict[str, Any]:
    validation_ground_truth = load_validation_ground_truth(ground_truth_path)
    extraction_ground_truth = load_ground_truth()
    references = _load_precomputed_manifest(
        Path(manifest_path),
        Path(precomputed_text_directory),
    )
    results: dict[str, Mapping[str, Any] | None] = {}
    validation_times: dict[str, float] = {}
    pipeline_errors: dict[str, str] = {}
    document_distribution = Counter()
    field_distribution = Counter()
    conflict_totals = Counter()
    conflict_by_field: dict[str, Counter[str]] = {}
    semantic_by_field = Counter()
    reference_totals = Counter()
    coverage_totals = Counter()
    extraction_manual_review_count = 0
    validation_manual_review_count = 0
    pdf_dir = Path(pdf_directory)
    for document_id in extraction_ground_truth:
        try:
            analysis = analyze_abstract_text_layers(
                pdf_dir / f"{document_id}.pdf",
                max_pages=max_pages,
                top_k=top_k,
            )
            pages = analysis.get("abstract_pages", [])
            if not isinstance(pages, list):
                raise ValueError("invalid abstract_pages from text-layer analysis")
            unified = [_build_unified_page(page, document_id, references) for page in pages]
            normalized = normalize_processed_document({"abstract_pages": unified})
            extraction = extract_metadata(normalized)
            extraction_manual_review_count += extraction.requires_manual_review
            started = time.perf_counter()
            validation = validate_metadata(extraction)
            validation_times[document_id] = (time.perf_counter() - started) * 1000
            payload = validation.to_dict()
            results[document_id] = payload
            validation_payload = payload["validation"]
            document_distribution[validation_payload["document_status"]] += 1
            validation_manual_review_count += validation_payload["requires_manual_review"]
            field_distribution.update(
                item["status"] for item in validation_payload["fields"].values()
            )
            for name in (
                "candidate_conflicts_received",
                "candidate_conflicts_resolved",
                "candidate_conflicts_unresolved",
                "semantic_equivalence_resolutions",
            ):
                conflict_totals[name] += validation_payload["stats"][name]
            for field_name, field_result in validation_payload["fields"].items():
                details = field_result.get("details", {})
                counter = conflict_by_field.setdefault(field_name, Counter())
                for name in (
                    "candidate_conflicts_received",
                    "candidate_conflicts_resolved",
                    "candidate_conflicts_unresolved",
                ):
                    counter[name] += int(details.get(name, 0))
                semantic_by_field[field_name] += int(
                    details.get("semantic_equivalence_resolutions", 0)
                )
            reference_totals.update(validation_payload["stats"]["reference_checks"])
            coverage_totals["fields_extracted"] += validation_payload["stats"][
                "fields_extracted"
            ]
            coverage_totals["fields_validated"] += validation_payload["stats"][
                "fields_validated"
            ]
        except Exception as exc:
            results[document_id] = None
            pipeline_errors[document_id] = str(exc)
    report = evaluate_validation_results(
        results,
        validation_ground_truth,
        validation_times_ms=validation_times,
        extraction_manual_review_count=extraction_manual_review_count,
    )
    report.update(
        {
            "offline_only": True,
            "benchmark_documents_evaluated": len(results) - len(pipeline_errors),
            "document_status_distribution": dict(document_distribution),
            "field_status_distribution": dict(field_distribution),
            "validation_manual_review_count_full_benchmark": validation_manual_review_count,
            "conflict_evaluation": {
                **dict(conflict_totals),
                "incorrectly_resolved": len(report["incorrectly_resolved_conflicts"]),
                "by_field": {
                    field: dict(counts) for field, counts in conflict_by_field.items()
                },
                "semantic_equivalence_by_field": dict(semantic_by_field),
            },
            "validation_coverage_full_benchmark": {
                **dict(coverage_totals),
                "coverage": (
                    round(
                        coverage_totals["fields_validated"]
                        / coverage_totals["fields_extracted"],
                        4,
                    )
                    if coverage_totals["fields_extracted"]
                    else None
                ),
            },
            "reference_dependent_checks": {
                "performed": reference_totals["performed"],
                "skipped_unavailable": reference_totals["skipped_unavailable"],
                "not_applicable": reference_totals["not_applicable"],
                "not_performed_missing_value": reference_totals[
                    "not_performed_missing_value"
                ],
            },
            "pipeline_errors": pipeline_errors,
        }
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate metadata validation using local benchmark inputs only.",
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
        report = run_offline_validation_evaluation(
            args.pdf_dir,
            manifest_path=args.manifest,
            precomputed_text_directory=args.precomputed_text_dir,
            ground_truth_path=args.ground_truth,
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except (OSError, UnicodeError, ValueError, ValidationEvaluationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["pipeline_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
