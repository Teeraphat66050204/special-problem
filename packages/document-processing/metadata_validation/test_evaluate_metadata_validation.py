from __future__ import annotations

import unittest

from metadata_validation.evaluate_metadata_validation import (
    ValidationEvaluationError,
    evaluate_validation_results,
    load_validation_ground_truth,
)


def _result(status: str, review: bool, field_status: str) -> dict:
    return {
        "metadata": {},
        "validation": {
            "document_status": status,
            "requires_manual_review": review,
            "fields": {
                "advisor": {
                    "status": field_status,
                    "details": {},
                }
            },
        },
    }


class ValidationEvaluationTests(unittest.TestCase):
    def test_status_and_manual_review_metrics(self) -> None:
        ground_truth = {
            "good": {
                "expected_document_status": "VALID",
                "expected_manual_review": False,
                "fields": {"advisor": "VALID"},
            },
            "review": {
                "expected_document_status": "REVIEW_REQUIRED",
                "expected_manual_review": True,
                "fields": {"advisor": "REVIEW_REQUIRED"},
            },
        }
        report = evaluate_validation_results(
            {
                "good": _result("VALID", False, "VALID"),
                "review": _result("REVIEW_REQUIRED", True, "REVIEW_REQUIRED"),
            },
            ground_truth,
        )
        self.assertEqual(report["document_status_accuracy"], 1.0)
        self.assertEqual(report["field_status_accuracy"], 1.0)
        self.assertEqual(report["manual_review_metrics"]["recall"], 1.0)

    def test_false_positive_is_reported(self) -> None:
        ground_truth = {
            "doc": {
                "expected_document_status": "VALID",
                "expected_manual_review": False,
                "fields": {"advisor": "VALID"},
            }
        }
        report = evaluate_validation_results(
            {"doc": _result("REVIEW_REQUIRED", True, "REVIEW_REQUIRED")},
            ground_truth,
        )
        self.assertEqual(report["manual_review_false_positives"], ["doc"])

    def test_false_negative_is_reported(self) -> None:
        ground_truth = {
            "doc": {
                "expected_document_status": "REVIEW_REQUIRED",
                "expected_manual_review": True,
                "fields": {"advisor": "REVIEW_REQUIRED"},
            }
        }
        report = evaluate_validation_results(
            {"doc": _result("VALID", False, "VALID")},
            ground_truth,
        )
        self.assertEqual(report["manual_review_false_negatives"], ["doc"])
        self.assertEqual(report["manual_review_metrics"]["recall"], 0.0)

    def test_unavailable_result_is_reported(self) -> None:
        ground_truth = {
            "doc": {
                "expected_document_status": "VALID",
                "expected_manual_review": False,
                "fields": {},
            }
        }
        report = evaluate_validation_results({"doc": None}, ground_truth)
        self.assertEqual(report["documents_unavailable"], ["doc"])

    def test_bundled_ground_truth_has_representative_coverage(self) -> None:
        ground_truth = load_validation_ground_truth()
        self.assertGreaterEqual(len(ground_truth), 7)
        self.assertTrue(any(not row["expected_manual_review"] for row in ground_truth.values()))
        self.assertTrue(any(row["expected_manual_review"] for row in ground_truth.values()))

    def test_empty_ground_truth_is_rejected(self) -> None:
        with self.assertRaises(ValidationEvaluationError):
            evaluate_validation_results({}, {})


if __name__ == "__main__":
    unittest.main()
