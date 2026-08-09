"""Tests for manual text-layer quality ground truth and evaluation."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text_layer.evaluate_text_layer_quality import (
    DEFAULT_GROUND_TRUTH,
    load_ground_truth,
    summarize_results,
)
from text_layer.quality import assess_text_quality
import text_layer.quality as quality_module


class QualityGroundTruthTests(unittest.TestCase):
    def test_ground_truth_covers_twenty_documents_and_both_languages(self) -> None:
        pages = load_ground_truth(DEFAULT_GROUND_TRUTH)

        self.assertEqual(len(pages), 40)
        self.assertEqual(len({page["document_id"] for page in pages}), 20)
        self.assertEqual(
            sum(page["language"] == "thai" for page in pages),
            20,
        )
        self.assertEqual(
            sum(page["language"] == "english" for page in pages),
            20,
        )
        self.assertEqual(
            len({(page["document_id"], page["language"]) for page in pages}),
            40,
        )

    def test_ground_truth_distribution_matches_manual_review(self) -> None:
        pages = load_ground_truth(DEFAULT_GROUND_TRUTH)

        thai_labels = [page["label"] for page in pages if page["language"] == "thai"]
        english_labels = [
            page["label"] for page in pages if page["language"] == "english"
        ]
        self.assertEqual(thai_labels.count("good"), 6)
        self.assertEqual(thai_labels.count("poor"), 14)
        self.assertEqual(thai_labels.count("missing"), 0)
        self.assertEqual(english_labels.count("good"), 20)
        self.assertEqual(english_labels.count("poor"), 0)
        self.assertEqual(english_labels.count("missing"), 0)

    def test_reviewed_edge_cases_are_explicit_in_ground_truth(self) -> None:
        pages = load_ground_truth(DEFAULT_GROUND_TRUTH)
        labels = {
            (page["document_id"], page["language"]): page["label"] for page in pages
        }

        self.assertEqual(labels[("document_022", "thai")], "poor")
        self.assertEqual(labels[("document_064", "english")], "good")

    def test_production_classifier_has_no_ground_truth_access(self) -> None:
        source_path = Path(quality_module.__file__).resolve()
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        self.assertNotIn("benchmark_quality_ground_truth", source)
        self.assertNotIn("document_", source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("json", imported_modules)
        with patch(
            "pathlib.Path.read_text",
            side_effect=AssertionError("production attempted to read a file"),
        ):
            result = assess_text_quality(
                "ABSTRACT\nAdvisor: Example\n" + ("Readable abstract text. " * 40),
                language="english",
            )
        self.assertIn(result["quality"], {"good", "poor"})


class QualityMetricTests(unittest.TestCase):
    def test_accuracy_and_requires_ocr_metrics(self) -> None:
        results = [
            self._row("thai", "poor", "poor"),
            self._row("thai", "poor", "good"),
            self._row("english", "good", "poor"),
            self._row("english", "good", "good"),
        ]

        report = summarize_results(results)

        self.assertEqual(report["classification"]["overall_accuracy"], 0.5)
        self.assertEqual(report["classification"]["thai_accuracy"], 0.5)
        self.assertEqual(report["classification"]["english_accuracy"], 0.5)
        self.assertEqual(report["requires_ocr"]["true_positive"], 1)
        self.assertEqual(report["requires_ocr"]["false_positive"], 1)
        self.assertEqual(report["requires_ocr"]["false_negative"], 1)
        self.assertEqual(report["requires_ocr"]["true_negative"], 1)
        self.assertEqual(report["requires_ocr"]["precision"], 0.5)
        self.assertEqual(report["requires_ocr"]["recall"], 0.5)
        self.assertEqual(report["requires_ocr"]["f1"], 0.5)
        self.assertEqual(len(report["mismatches"]), 2)

    @staticmethod
    def _row(language: str, expected: str, predicted: str) -> dict[str, object]:
        return {
            "document_id": "synthetic",
            "language": language,
            "page_number": 1,
            "ground_truth": expected,
            "prediction": predicted,
            "quality_score": 0.5,
            "reasons": ["synthetic"],
            "ground_truth_requires_ocr": expected in {"poor", "missing"},
            "predicted_requires_ocr": predicted in {"poor", "missing"},
        }


if __name__ == "__main__":
    unittest.main()
