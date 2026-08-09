"""Evaluate text-layer quality predictions against manual usability labels."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from text_layer.extract_text_layer import (  # type: ignore[import-not-found]
        TextLayerError,
        extract_page_text,
    )
    from text_layer.quality import assess_text_quality  # type: ignore[import-not-found]
else:
    from .extract_text_layer import TextLayerError, extract_page_text
    from .quality import assess_text_quality


DEFAULT_GROUND_TRUTH = Path(__file__).with_name(
    "benchmark_quality_ground_truth.json"
)
VALID_LABELS = {"good", "poor", "missing"}
VALID_LANGUAGES = {"thai", "english"}


class QualityEvaluationError(Exception):
    """A user-facing quality evaluation failure."""


def load_ground_truth(path: str | Path) -> list[dict[str, object]]:
    """Load and validate manually assigned page-level usability labels."""
    ground_truth_path = Path(path)
    if not ground_truth_path.is_file():
        raise QualityEvaluationError(
            f"Ground truth is not a file: '{ground_truth_path}'."
        )
    try:
        payload = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityEvaluationError(f"Could not read ground truth: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        raise QualityEvaluationError("Ground truth must contain a pages list.")

    pages: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for position, item in enumerate(payload["pages"], start=1):
        if not isinstance(item, dict):
            raise QualityEvaluationError(
                f"Ground-truth page {position} must be an object."
            )
        document_id = item.get("document_id")
        language = item.get("language")
        page_number = item.get("page_number")
        label = item.get("label")
        rationale = item.get("rationale")
        if not isinstance(document_id, str) or not document_id:
            raise QualityEvaluationError(
                f"Ground-truth page {position} has an invalid document_id."
            )
        if language not in VALID_LANGUAGES:
            raise QualityEvaluationError(
                f"Ground-truth page {position} has an invalid language."
            )
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number <= 0
        ):
            raise QualityEvaluationError(
                f"Ground-truth page {position} has an invalid page_number."
            )
        if label not in VALID_LABELS:
            raise QualityEvaluationError(
                f"Ground-truth page {position} has an invalid label."
            )
        if not isinstance(rationale, str) or not rationale.strip():
            raise QualityEvaluationError(
                f"Ground-truth page {position} has no review rationale."
            )
        key = (document_id, language)
        if key in seen:
            raise QualityEvaluationError(
                f"Duplicate ground-truth page for {document_id}/{language}."
            )
        seen.add(key)
        pages.append(dict(item))
    if not pages:
        raise QualityEvaluationError("Ground truth contains no page records.")
    return pages


def classify_pages(
    pages: Sequence[Mapping[str, object]],
    pdf_dir: str | Path,
) -> list[dict[str, object]]:
    """Run the production classifier on each independently labeled page."""
    directory = Path(pdf_dir)
    if not directory.is_dir():
        raise QualityEvaluationError(f"PDF directory is not a directory: '{directory}'.")

    results: list[dict[str, object]] = []
    for page in pages:
        document_id = str(page["document_id"])
        language = str(page["language"])
        page_number = int(page["page_number"])
        pdf_path = directory / f"{document_id}.pdf"
        try:
            extracted = extract_page_text(
                pdf_path,
                page_number - 1,
                language=language,
            )
        except TextLayerError as exc:
            raise QualityEvaluationError(
                f"Could not evaluate {document_id}/{language}: {exc}"
            ) from exc
        assessment = assess_text_quality(
            str(extracted["raw_text"]),
            language=language,
            normalized_text=str(extracted["normalized_for_quality_text"]),
        )
        expected = str(page["label"])
        predicted = str(assessment["quality"])
        results.append(
            {
                "document_id": document_id,
                "language": language,
                "page_number": page_number,
                "ground_truth": expected,
                "prediction": predicted,
                "quality_score": assessment["quality_score"],
                "reasons": assessment["reasons"],
                "ground_truth_requires_ocr": expected in {"poor", "missing"},
                "predicted_requires_ocr": bool(assessment["requires_ocr"]),
            }
        )
    return results


def _accuracy(rows: Sequence[Mapping[str, object]]) -> float:
    if not rows:
        return 0.0
    matches = sum(row["ground_truth"] == row["prediction"] for row in rows)
    return matches / len(rows)


def summarize_results(
    results: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Calculate multiclass accuracy and binary requires-OCR metrics."""
    if not results:
        raise QualityEvaluationError("Cannot summarize an empty result set.")

    true_positive = false_positive = false_negative = true_negative = 0
    mismatches: list[dict[str, object]] = []
    for row in results:
        expected_ocr = bool(row["ground_truth_requires_ocr"])
        predicted_ocr = bool(row["predicted_requires_ocr"])
        if expected_ocr and predicted_ocr:
            true_positive += 1
        elif not expected_ocr and predicted_ocr:
            false_positive += 1
        elif expected_ocr and not predicted_ocr:
            false_negative += 1
        else:
            true_negative += 1
        if row["ground_truth"] != row["prediction"]:
            mismatches.append(dict(row))

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    thai_rows = [row for row in results if row["language"] == "thai"]
    english_rows = [row for row in results if row["language"] == "english"]

    def distribution(key: str, rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
        counts = Counter(str(row[key]) for row in rows)
        return {label: counts[label] for label in ("good", "poor", "missing")}

    return {
        "pages_evaluated": len(results),
        "ground_truth_distribution": {
            "thai": distribution("ground_truth", thai_rows),
            "english": distribution("ground_truth", english_rows),
            "overall": distribution("ground_truth", results),
        },
        "predicted_distribution": {
            "thai": distribution("prediction", thai_rows),
            "english": distribution("prediction", english_rows),
            "overall": distribution("prediction", results),
        },
        "classification": {
            "overall_accuracy": _accuracy(results),
            "thai_accuracy": _accuracy(thai_rows),
            "english_accuracy": _accuracy(english_rows),
        },
        "requires_ocr": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "mismatches": mismatches,
    }


def _load_ocr_metric_functions(
    repository_root: Path,
) -> tuple[Callable[[str], str], Callable[[Sequence[str], Sequence[str]], int]]:
    evaluator_path = (
        repository_root
        / "experiments"
        / "ocr-benchmark"
        / "evaluation"
        / "evaluate_ocr.py"
    )
    if not evaluator_path.is_file():
        raise QualityEvaluationError(
            f"OCR evaluator is not a file: '{evaluator_path}'."
        )
    spec = importlib.util.spec_from_file_location(
        "ocr_benchmark_evaluator",
        evaluator_path,
    )
    if spec is None or spec.loader is None:
        raise QualityEvaluationError("Could not load the existing OCR evaluator.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normalize_text, module.levenshtein_distance


def calculate_thai_cer(
    pages: Sequence[Mapping[str, object]],
    pdf_dir: str | Path,
    manifest_path: str | Path,
    reference_dir: str | Path,
    *,
    repository_root: str | Path,
) -> dict[str, object]:
    """Calculate supplementary Thai CER with the existing OCR methodology."""
    manifest = Path(manifest_path)
    references = Path(reference_dir)
    if not manifest.is_file():
        raise QualityEvaluationError(f"Manifest is not a file: '{manifest}'.")
    if not references.is_dir():
        raise QualityEvaluationError(
            f"Thai reference directory is not a directory: '{references}'."
        )
    try:
        with manifest.open(encoding="utf-8-sig", newline="") as handle:
            manifest_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError) as exc:
        raise QualityEvaluationError(f"Could not read manifest: {exc}") from exc
    by_document = {str(row.get("document_id")): row for row in manifest_rows}
    normalize_text, distance = _load_ocr_metric_functions(Path(repository_root))

    rows: list[dict[str, object]] = []
    for page in pages:
        if page["language"] != "thai":
            continue
        document_id = str(page["document_id"])
        manifest_row = by_document.get(document_id)
        if manifest_row is None:
            raise QualityEvaluationError(f"Manifest has no row for {document_id}.")
        expected_page = int(page["page_number"])
        manifest_page = int(str(manifest_row.get("page_number", "0")))
        if manifest_page != expected_page:
            raise QualityEvaluationError(
                f"Manifest page mismatch for {document_id}: "
                f"quality GT={expected_page}, OCR GT={manifest_page}."
            )
        reference_path = references / str(manifest_row.get("ground_truth_file", ""))
        if not reference_path.is_file():
            raise QualityEvaluationError(
                f"Thai reference is not a file: '{reference_path}'."
            )
        extracted = extract_page_text(
            Path(pdf_dir) / f"{document_id}.pdf",
            expected_page - 1,
            language="thai",
        )
        reference = normalize_text(reference_path.read_text(encoding="utf-8-sig"))
        hypothesis = normalize_text(str(extracted["raw_text"]))
        edits = distance(reference, hypothesis)
        if not reference:
            raise QualityEvaluationError(f"Thai reference is empty for {document_id}.")
        rows.append(
            {
                "document_id": document_id,
                "page_number": expected_page,
                "reference_characters": len(reference),
                "hypothesis_characters": len(hypothesis),
                "character_edits": edits,
                "cer": edits / len(reference),
            }
        )
    total_edits = sum(int(row["character_edits"]) for row in rows)
    total_characters = sum(int(row["reference_characters"]) for row in rows)
    if not rows or total_characters <= 0:
        raise QualityEvaluationError("No non-empty Thai references were evaluated.")
    return {
        "documents": len(rows),
        "macro_cer": sum(float(row["cer"]) for row in rows) / len(rows),
        "corpus_cer": total_edits / total_characters,
        "per_document": rows,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate PDF text-layer usability predictions.",
    )
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH,
        help="Manual quality labels (default: adjacent benchmark file)",
    )
    parser.add_argument("--manifest", type=Path, help="Optional Thai OCR manifest")
    parser.add_argument(
        "--thai-reference-dir",
        type=Path,
        help="Optional Thai OCR reference directory",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def print_human_report(report: Mapping[str, Any]) -> None:
    classification = report["classification"]
    ocr = report["requires_ocr"]
    print(f"Pages evaluated: {report['pages_evaluated']}")
    for title, key in (
        ("Ground truth", "ground_truth_distribution"),
        ("Predicted", "predicted_distribution"),
    ):
        for language in ("thai", "english", "overall"):
            counts = report[key][language]
            print(
                f"{title} {language}: good={counts['good']} "
                f"poor={counts['poor']} missing={counts['missing']}"
            )
    print(f"Overall accuracy: {classification['overall_accuracy']:.4f}")
    print(f"Thai accuracy: {classification['thai_accuracy']:.4f}")
    print(f"English accuracy: {classification['english_accuracy']:.4f}")
    print(
        "Requires OCR: "
        f"precision={ocr['precision']:.4f} "
        f"recall={ocr['recall']:.4f} f1={ocr['f1']:.4f} "
        f"FP={ocr['false_positive']} FN={ocr['false_negative']}"
    )
    print("Mismatches:")
    if not report["mismatches"]:
        print("  none")
    for row in report["mismatches"]:
        reasons = ",".join(row["reasons"])
        print(
            f"  {row['document_id']} {row['language']} page={row['page_number']} "
            f"ground_truth={row['ground_truth']} prediction={row['prediction']} "
            f"score={row['quality_score']:.4f} reasons={reasons}"
        )
    thai_cer = report.get("supplementary_thai_cer")
    if thai_cer:
        print(
            f"Supplementary Thai Text Layer CER: macro={thai_cer['macro_cer']:.6f} "
            f"corpus={thai_cer['corpus_cer']:.6f}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    if (args.manifest is None) != (args.thai_reference_dir is None):
        print(
            "Error: --manifest and --thai-reference-dir must be supplied together.",
            file=sys.stderr,
        )
        return 1
    try:
        pages = load_ground_truth(args.ground_truth)
        results = classify_pages(pages, args.pdf_dir)
        report = summarize_results(results)
        if args.manifest is not None:
            repository_root = Path(__file__).resolve().parents[3]
            report["supplementary_thai_cer"] = calculate_thai_cer(
                pages,
                args.pdf_dir,
                args.manifest,
                args.thai_reference_dir,
                repository_root=repository_root,
            )
    except (OSError, TextLayerError, QualityEvaluationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
