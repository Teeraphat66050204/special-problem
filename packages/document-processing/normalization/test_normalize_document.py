"""Tests for unified page and multi-page document normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization import normalize_page_text, normalize_processed_document


def page(
    number: int,
    language: str,
    source: str | None,
    text: object,
    *,
    status: str = "success",
) -> dict[str, object]:
    return {
        "page_number": number,
        "page_index": number - 1,
        "language": language,
        "text_source": source,
        "text": text,
        "processing_status": status,
        "requires_manual_review": status != "success",
    }


class NormalizePageTests(unittest.TestCase):
    def test_ocr_page_retains_raw_unified_text(self) -> None:
        source = page(4, "thai", "ocr", "  บทคัดย่อ  \r\nเนื้อหา  ")

        result = normalize_page_text(source)

        self.assertEqual(result["text"], source["text"])
        self.assertEqual(result["normalized_text"], "บทคัดย่อ\nเนื้อหา")
        self.assertEqual(result["text_source"], "ocr")
        self.assertEqual(result["normalization_status"], "success")
        self.assertTrue(result["normalization"]["changed"])
        self.assertEqual(source.get("normalized_text"), None)

    def test_text_layer_page_is_supported(self) -> None:
        result = normalize_page_text(
            page(5, "english", "text_layer", "ABSTRACT:  Safe/Title")
        )

        self.assertEqual(result["normalized_text"], "ABSTRACT: Safe/Title")
        self.assertEqual(result["text_source"], "text_layer")

    def test_ocr_failure_is_skipped_and_requires_review(self) -> None:
        result = normalize_page_text(
            page(4, "thai", None, None, status="ocr_failed")
        )

        self.assertIsNone(result["text"])
        self.assertIsNone(result["normalized_text"])
        self.assertEqual(result["normalization_status"], "skipped")
        self.assertEqual(result["normalization"]["warnings"], ["source_processing_failed"])
        self.assertTrue(result["requires_manual_review"])

    def test_none_text_on_success_is_not_stringified(self) -> None:
        result = normalize_page_text(page(4, "thai", "ocr", None))

        self.assertIsNone(result["normalized_text"])
        self.assertNotEqual(result["normalized_text"], "None")
        self.assertEqual(result["normalization_status"], "skipped")
        self.assertTrue(result["requires_manual_review"])

    def test_non_string_text_is_controlled_skip(self) -> None:
        result = normalize_page_text(page(4, "thai", "ocr", 123))

        self.assertIsNone(result["normalized_text"])
        self.assertIn("invalid_text_type", result["normalization"]["warnings"])

    def test_whitespace_only_text_is_empty_and_requires_review(self) -> None:
        result = normalize_page_text(page(4, "thai", "ocr", "  \n\t"))

        self.assertEqual(result["normalized_text"], "")
        self.assertEqual(result["normalization_status"], "empty")
        self.assertTrue(result["requires_manual_review"])


class NormalizeDocumentTests(unittest.TestCase):
    def test_normalizes_all_abstract_pages_independently_in_order(self) -> None:
        processing_result = {
            "processing_status": "success",
            "abstract_pages": [
                page(4, "thai", "ocr", "บทคัดย่อ  ภาษาไทย"),
                page(5, "english", "text_layer", "ABSTRACT:  English"),
            ],
        }

        result = normalize_processed_document(processing_result)
        pages = result["abstract_pages"]

        self.assertEqual([item["page_number"] for item in pages], [4, 5])
        self.assertEqual([item["language"] for item in pages], ["thai", "english"])
        self.assertEqual(
            [item["normalized_text"] for item in pages],
            ["บทคัดย่อ ภาษาไทย", "ABSTRACT: English"],
        )
        self.assertNotIn("บทคัดย่อ ภาษาไทย\nABSTRACT: English", str(pages))
        self.assertEqual(
            result["normalization"]["source_counts"],
            {"text_layer": 1, "ocr": 1, "none": 0},
        )

    def test_document_summary_counts_changed_warnings_and_skips(self) -> None:
        result = normalize_processed_document(
            {
                "abstract_pages": [
                    page(4, "thai", "ocr", "ห ั ว ข้ อ ส ห ก ิ จ"),
                    page(5, "english", "text_layer", "Already clean"),
                    page(6, "thai", None, None, status="ocr_failed"),
                ]
            }
        )

        summary = result["normalization"]
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["pages"], 3)
        self.assertEqual(summary["changed"], 0)
        self.assertEqual(summary["unchanged"], 2)
        self.assertEqual(summary["warnings"], 2)
        self.assertEqual(summary["skipped"], 1)

    def test_document_normalization_is_idempotent(self) -> None:
        original = {
            "abstract_pages": [
                page(4, "thai", "ocr", "  ไทย   text  \r\n"),
                page(5, "english", "text_layer", "  ABSTRACT  "),
            ]
        }
        once = normalize_processed_document(original)
        rerun_input = {
            **once,
            "abstract_pages": [
                {**item, "text": item["normalized_text"]}
                for item in once["abstract_pages"]
            ],
        }
        twice = normalize_processed_document(rerun_input)

        self.assertEqual(
            [item["normalized_text"] for item in twice["abstract_pages"]],
            [item["normalized_text"] for item in once["abstract_pages"]],
        )
        self.assertEqual(twice["normalization"]["changed"], 0)

    def test_rejects_invalid_abstract_pages_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid abstract_pages"):
            normalize_processed_document({"abstract_pages": None})


if __name__ == "__main__":
    unittest.main()
