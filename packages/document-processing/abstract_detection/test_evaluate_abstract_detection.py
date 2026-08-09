"""Tests for abstract detection evaluation metrics."""

from __future__ import annotations

import unittest

from evaluate_abstract_detection import evaluate_predictions


def candidate(page_number: int, language: str) -> dict[str, object]:
    return {
        "page_number": page_number,
        "page_index": page_number - 1,
        "language": language,
        "score": 10.0,
        "matched_features": [],
    }


class AbstractDetectionEvaluationTests(unittest.TestCase):
    def test_language_accuracy_any_accuracy_and_top_three_recall(self) -> None:
        ground_truth = [
            {
                "document_id": "document_a",
                "thai_abstract_page": 4,
                "english_abstract_page": 5,
            },
            {
                "document_id": "document_b",
                "thai_abstract_page": 4,
                "english_abstract_page": 5,
            },
        ]
        predictions = {
            "document_a": {
                "primary_candidate": candidate(4, "thai"),
                "abstract_pages": [candidate(4, "thai"), candidate(5, "english")],
                "candidates": [candidate(4, "thai"), candidate(5, "english")],
            },
            "document_b": {
                "primary_candidate": candidate(5, "english"),
                "abstract_pages": [candidate(5, "english"), candidate(6, "thai")],
                "candidates": [candidate(5, "english"), candidate(6, "thai")],
            },
        }

        result = evaluate_predictions(ground_truth, predictions)

        self.assertEqual(
            result["metrics"]["thai_abstract_detection_accuracy"]["accuracy"],
            0.5,
        )
        self.assertEqual(
            result["metrics"]["english_abstract_detection_accuracy"]["accuracy"],
            1.0,
        )
        self.assertEqual(
            result["metrics"]["any_abstract_detection_accuracy"]["accuracy"],
            1.0,
        )
        self.assertEqual(result["metrics"]["top_3_recall"]["accuracy"], 0.75)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["errors"][0]["document_id"], "document_b")


if __name__ == "__main__":
    unittest.main()
