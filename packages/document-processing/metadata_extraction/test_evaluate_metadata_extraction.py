"""Tests for metadata field coverage, exact match, and list metrics."""

from __future__ import annotations

import unittest

from metadata_extraction.evaluate_metadata_extraction import (
    evaluate_predictions,
    evaluation_normalize,
    load_ground_truth,
)


class MetadataEvaluationTests(unittest.TestCase):
    def test_evaluation_normalization_is_conservative(self) -> None:
        self.assertEqual(evaluation_normalize("  Cafe\u0301   Title "), "café title")
        self.assertNotEqual(evaluation_normalize("2569"), evaluation_normalize("2026"))
        self.assertNotEqual(evaluation_normalize("A/B"), evaluation_normalize("AB"))

    def test_scalar_accuracy_and_coverage_are_separate(self) -> None:
        ground_truth = {
            "one": {"title_th": "ชื่อหนึ่ง"},
            "two": {"title_th": "ชื่อสอง"},
        }
        predictions = {
            "one": {"metadata": {"title_th": "ชื่อหนึ่ง"}},
            "two": {"metadata": {"title_th": None}},
        }

        report = evaluate_predictions(predictions, ground_truth)

        metric = report["field_metrics"]["title_th"]
        self.assertEqual(metric["accuracy"], 0.5)
        self.assertEqual(metric["coverage"], 0.5)

    def test_student_pairing_must_be_correct_not_only_names_and_ids(self) -> None:
        ground_truth = {
            "doc": {
                "students": [
                    {"name": "A", "student_id": "1"},
                    {"name": "B", "student_id": "2"},
                ]
            }
        }
        predictions = {
            "doc": {
                "metadata": {
                    "students": [
                        {"name": "A", "student_id": "2"},
                        {"name": "B", "student_id": "1"},
                    ]
                }
            }
        }

        report = evaluate_predictions(predictions, ground_truth)

        self.assertEqual(report["field_metrics"]["students"]["accuracy"], 0.0)
        self.assertEqual(report["item_metrics"]["students"]["f1"], 0.0)
        self.assertEqual(report["item_metrics"]["student_id"]["f1"], 1.0)

    def test_keyword_metrics_are_item_based_and_order_independent(self) -> None:
        ground_truth = {"doc": {"keywords": ["OCR", "Deep Learning"]}}
        predictions = {"doc": {"metadata": {"keywords": ["deep learning", "OCR"]}}}

        report = evaluate_predictions(predictions, ground_truth)

        self.assertEqual(report["field_metrics"]["keywords"]["accuracy"], 1.0)
        self.assertEqual(report["item_metrics"]["keywords"]["f1"], 1.0)

    def test_expected_empty_optional_list_is_covered_and_correct(self) -> None:
        ground_truth = {"doc": {"co_advisors": []}}
        predictions = {"doc": {"metadata": {"co_advisors": []}}}

        report = evaluate_predictions(predictions, ground_truth)

        self.assertEqual(report["field_metrics"]["co_advisors"]["coverage"], 1.0)
        self.assertEqual(report["field_metrics"]["co_advisors"]["accuracy"], 1.0)

    def test_abstract_exact_match_and_cer_are_supplementary(self) -> None:
        ground_truth = {"doc": {"abstract_en": "A short abstract."}}
        predictions = {
            "doc": {"metadata": {"abstract_en": "A short abstract!"}}
        }

        report = evaluate_predictions(predictions, ground_truth)

        metric = report["abstract_metrics"]["abstract_en"]
        self.assertEqual(metric["evaluable"], 1)
        self.assertEqual(metric["normalized_exact_accuracy"], 0.0)
        self.assertGreater(metric["character_error_rate"], 0.0)

    def test_manual_ground_truth_contains_twenty_independent_documents(self) -> None:
        ground_truth = load_ground_truth()

        self.assertEqual(len(ground_truth), 20)
        for metadata in ground_truth.values():
            self.assertIn("title_th", metadata)
            self.assertIn("title_en", metadata)
            self.assertIn("students", metadata)
            self.assertIn("advisor", metadata)


if __name__ == "__main__":
    unittest.main()
