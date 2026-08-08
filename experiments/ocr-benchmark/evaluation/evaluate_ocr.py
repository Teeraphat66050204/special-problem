"""Evaluate OCR text predictions with CER and WER."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
from importlib import metadata
from pathlib import Path
from typing import Callable, Sequence


REQUIRED_MANIFEST_COLUMNS = {
    "document_id",
    "page_number",
    "ground_truth_file",
}
NORMALIZATION_SETTINGS = {
    "unicode_form": "NFC",
    "trim_leading_trailing_whitespace": True,
    "collapse_internal_whitespace": True,
    "applied_to": ["ground_truth", "ocr_prediction"],
}
TOKENIZER_NAME = "pythainlp.tokenize.word_tokenize"
TOKENIZER_ENGINE = "newmm"
TOKENIZER_KEEP_WHITESPACE = False


class EvaluationError(Exception):
    """A user-facing evaluation failure."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def engine_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise argparse.ArgumentTypeError(
            "engine must contain only letters, numbers, '-' or '_'"
        )
    return value.lower()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate OCR predictions against ground truth using CER and WER.",
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--engine",
        type=engine_name,
        default="easyocr",
        help="Engine label used in output filenames (default: easyocr)",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Evaluate only the first N manifest rows",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing metrics outputs",
    )
    return parser.parse_args(argv)


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize(
        str(NORMALIZATION_SETTINGS["unicode_form"]), text
    )
    return " ".join(normalized.split())


def load_thai_tokenizer() -> tuple[Callable[..., list[str]], str]:
    try:
        import pythainlp  # type: ignore[import-not-found]
        from pythainlp.tokenize import word_tokenize
    except ImportError as exc:
        raise EvaluationError(
            "PyThaiNLP is unavailable. Install evaluation dependencies with "
            "'python -m pip install -r "
            "experiments/ocr-benchmark/evaluation/requirements.txt'."
        ) from exc

    try:
        version = metadata.version("PyThaiNLP")
    except metadata.PackageNotFoundError:
        version = str(getattr(pythainlp, "__version__", "unknown"))
    return word_tokenize, version


def tokenize_thai_words(
    text: str, tokenizer: Callable[..., list[str]]
) -> list[str]:
    tokens = tokenizer(
        text,
        engine=TOKENIZER_ENGINE,
        keep_whitespace=TOKENIZER_KEEP_WHITESPACE,
    )
    return [str(token) for token in tokens if str(token) and not str(token).isspace()]


def levenshtein_distance(
    reference: Sequence[str], hypothesis: Sequence[str]
) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference

    previous_row = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current_row = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            insertion = current_row[hypothesis_index - 1] + 1
            deletion = previous_row[hypothesis_index] + 1
            substitution = previous_row[hypothesis_index - 1] + (
                reference_item != hypothesis_item
            )
            current_row.append(min(insertion, deletion, substitution))
        previous_row = current_row
    return previous_row[-1]


def load_manifest(manifest_path: Path, limit: int | None) -> list[dict[str, str]]:
    if not manifest_path.is_file():
        raise EvaluationError(f"Manifest is not a file: '{manifest_path}'.")
    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing_columns = REQUIRED_MANIFEST_COLUMNS - columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise EvaluationError(
                    f"Manifest is missing required column(s): {missing}."
                )
            rows = list(reader)
    except OSError as exc:
        raise EvaluationError(f"Could not read manifest: {exc}") from exc

    if not rows:
        raise EvaluationError("Manifest contains no data rows.")
    return rows[:limit] if limit is not None else rows


def read_text(path: Path, label: str) -> str:
    if not path.is_file():
        raise EvaluationError(f"Missing {label}: '{path}'.")
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise EvaluationError(f"Could not read {label} '{path}': {exc}") from exc


def prediction_filename(document_id: str, page_number: int) -> str:
    return f"{document_id}_page_{page_number:03d}.txt"


def safe_rate(edits: int, reference_units: int, metric: str) -> float:
    if reference_units <= 0:
        raise EvaluationError(f"Cannot calculate {metric}: ground truth is empty.")
    return edits / reference_units


def evaluate_rows(
    manifest_rows: Sequence[dict[str, str]],
    ground_truth_dir: Path,
    predictions_dir: Path,
    tokenizer: Callable[..., list[str]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for row_number, row in enumerate(manifest_rows, start=2):
        document_id = (row.get("document_id") or "").strip()
        ground_truth_file = (row.get("ground_truth_file") or "").strip()
        try:
            page_number = int((row.get("page_number") or "").strip())
        except ValueError as exc:
            raise EvaluationError(
                f"Manifest row {row_number} has an invalid page_number."
            ) from exc
        if not document_id or not ground_truth_file or page_number <= 0:
            raise EvaluationError(
                f"Manifest row {row_number} has missing or invalid values."
            )

        prediction_file = prediction_filename(document_id, page_number)
        reference = normalize_text(
            read_text(ground_truth_dir / ground_truth_file, "ground truth")
        )
        hypothesis = normalize_text(
            read_text(predictions_dir / prediction_file, "prediction")
        )

        reference_words = tokenize_thai_words(reference, tokenizer)
        hypothesis_words = tokenize_thai_words(hypothesis, tokenizer)
        character_edits = levenshtein_distance(reference, hypothesis)
        word_edits = levenshtein_distance(reference_words, hypothesis_words)
        results.append(
            {
                "document_id": document_id,
                "page_number": page_number,
                "ground_truth_file": ground_truth_file,
                "prediction_file": prediction_file,
                "reference_characters": len(reference),
                "hypothesis_characters": len(hypothesis),
                "character_edits": character_edits,
                "cer": safe_rate(character_edits, len(reference), "CER"),
                "reference_words": len(reference_words),
                "hypothesis_words": len(hypothesis_words),
                "word_edits": word_edits,
                "wer": safe_rate(word_edits, len(reference_words), "WER"),
            }
        )
    return results


def summarize(
    results: Sequence[dict[str, object]],
    engine: str,
    pythainlp_version: str,
) -> dict[str, object]:
    character_edits = sum(int(row["character_edits"]) for row in results)
    reference_characters = sum(int(row["reference_characters"]) for row in results)
    word_edits = sum(int(row["word_edits"]) for row in results)
    reference_words = sum(int(row["reference_words"]) for row in results)
    return {
        "engine": engine,
        "normalization": NORMALIZATION_SETTINGS,
        "word_tokenizer": {
            "name": TOKENIZER_NAME,
            "engine": TOKENIZER_ENGINE,
            "keep_whitespace": TOKENIZER_KEEP_WHITESPACE,
            "pythainlp_version": pythainlp_version,
        },
        "cer_definition": "character-level Levenshtein distance / reference characters",
        "wer_definition": "Thai word-level Levenshtein distance / reference tokens",
        "documents_evaluated": len(results),
        "macro_cer": sum(float(row["cer"]) for row in results) / len(results),
        "corpus_cer": character_edits / reference_characters,
        "macro_wer": sum(float(row["wer"]) for row in results) / len(results),
        "corpus_wer": word_edits / reference_words,
        "total_character_edits": character_edits,
        "total_reference_characters": reference_characters,
        "total_word_edits": word_edits,
        "total_reference_words": reference_words,
        "per_document": list(results),
    }


def output_paths(output_dir: Path, engine: str) -> tuple[Path, Path]:
    return (
        output_dir / f"{engine}_metrics.csv",
        output_dir / f"{engine}_summary.json",
    )


def ensure_outputs_available(paths: Sequence[Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [path.name for path in paths if path.exists()]
    if existing:
        raise EvaluationError(
            f"Output already exists: {', '.join(existing)}. "
            "Use --overwrite to replace it."
        )


def temporary_path(output_dir: Path, suffix: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir, prefix=".evaluation.", suffix=suffix, delete=False
        ) as handle:
            return Path(handle.name)
    except OSError as exc:
        raise EvaluationError(f"Could not create temporary output: {exc}") from exc


def write_results(
    csv_path: Path,
    json_path: Path,
    results: Sequence[dict[str, object]],
    summary: dict[str, object],
    overwrite: bool,
) -> None:
    ensure_outputs_available((csv_path, json_path), overwrite)
    temp_csv = temporary_path(csv_path.parent, ".tmp.csv")
    temp_json = temporary_path(json_path.parent, ".tmp.json")
    try:
        with temp_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        temp_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        ensure_outputs_available((csv_path, json_path), overwrite)
        os.replace(temp_csv, csv_path)
        temp_csv = None
        os.replace(temp_json, json_path)
        temp_json = None
    except OSError as exc:
        raise EvaluationError(f"Could not write evaluation output: {exc}") from exc
    finally:
        for path in (temp_csv, temp_json):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.ground_truth.is_dir():
            raise EvaluationError(
                f"Ground-truth path is not a directory: '{args.ground_truth}'."
            )
        if not args.predictions.is_dir():
            raise EvaluationError(
                f"Predictions path is not a directory: '{args.predictions}'."
            )
        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise EvaluationError(f"Output path is not a directory: '{args.output}'.")

        tokenizer, pythainlp_version = load_thai_tokenizer()
        manifest_rows = load_manifest(args.manifest, args.limit)
        results = evaluate_rows(
            manifest_rows, args.ground_truth, args.predictions, tokenizer
        )
        summary = summarize(results, args.engine, pythainlp_version)
        csv_path, json_path = output_paths(args.output, args.engine)
        write_results(csv_path, json_path, results, summary, args.overwrite)
        print(f"Evaluated {len(results)} document(s) for {args.engine}.")
        print(
            f"Corpus CER={summary['corpus_cer']:.6f} "
            f"Thai WER={summary['corpus_wer']:.6f}"
        )
        print(f"Metrics CSV: {csv_path}")
        print(f"Summary JSON: {json_path}")
        return 0
    except (OSError, EvaluationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
