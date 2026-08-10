"""Tests for PDF text-layer extraction and orchestration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text_layer.analyze_text_layer import analyze_abstract_text_layers
from text_layer.extract_text_layer import (
    TextLayerError,
    extract_abstract_text_layers,
    extract_page_text,
    normalize_for_quality,
)


class TextLayerExtractionTests(unittest.TestCase):
    def _make_pdf(self, directory: str, page_texts: list[str]) -> Path:
        import pymupdf

        path = Path(directory) / "sample.pdf"
        document = pymupdf.open()
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)
        document.close()
        return path

    def test_normalization_is_limited_to_quality_copy(self) -> None:
        raw = "  Cafe\u0301\t  report \r\n\r\n second   line  "

        normalized = normalize_for_quality(raw)

        self.assertEqual(normalized, "Caf\u00e9 report\nsecond line")
        self.assertEqual(raw, "  Cafe\u0301\t  report \r\n\r\n second   line  ")

    def test_extract_page_retains_raw_text_and_page_coordinates(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = self._make_pdf(temporary_directory, ["First page", "Second page"])

            result = extract_page_text(path, 1, language="english")

        self.assertEqual(result["page_number"], 2)
        self.assertEqual(result["page_index"], 1)
        self.assertEqual(result["language"], "english")
        self.assertIn("Second page", result["raw_text"])
        self.assertEqual(result["character_count"], len(result["raw_text"]))
        self.assertEqual(
            result["non_whitespace_character_count"],
            sum(not character.isspace() for character in result["raw_text"]),
        )

    def test_extracts_every_abstract_page_in_input_order(self) -> None:
        candidates = [
            {"page_number": 1, "page_index": 0, "language": "thai"},
            {"page_number": 2, "page_index": 1, "language": "english"},
        ]
        with TemporaryDirectory() as temporary_directory:
            path = self._make_pdf(temporary_directory, ["Thai text", "English text"])

            results = extract_abstract_text_layers(path, candidates)

        self.assertEqual([item["page_number"] for item in results], [1, 2])
        self.assertEqual([item["language"] for item in results], ["thai", "english"])

    def test_rejects_invalid_page_index(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = self._make_pdf(temporary_directory, ["Only page"])
            with self.assertRaisesRegex(TextLayerError, "Invalid page_index"):
                extract_page_text(path, 1)

    def test_rejects_non_integer_page_index(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = self._make_pdf(temporary_directory, ["Only page"])
            with self.assertRaisesRegex(TextLayerError, "must be an integer"):
                extract_page_text(path, "0")  # type: ignore[arg-type]

    def test_missing_pdf_has_clear_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing.pdf"
            with self.assertRaisesRegex(TextLayerError, "does not exist"):
                extract_page_text(missing, 0)

    def test_rejects_inconsistent_page_coordinates(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = self._make_pdf(temporary_directory, ["Only page"])
            with self.assertRaisesRegex(TextLayerError, "different pages"):
                extract_abstract_text_layers(
                    path,
                    [{"page_number": 1, "page_index": 1, "language": "thai"}],
                )

    def test_orchestration_assesses_all_abstract_pages(self) -> None:
        detection = {
            "primary_candidate": {"page_number": 1},
            "abstract_pages": [
                {"page_number": 1, "page_index": 0, "language": "thai"},
                {"page_number": 2, "page_index": 1, "language": "english"},
            ],
            "requires_manual_selection": False,
        }
        extracted = [
            {
                "page_number": 1,
                "page_index": 0,
                "language": "thai",
                "raw_text": "Thai raw",
                "normalized_for_quality_text": "Thai raw",
                "character_count": 8,
                "non_whitespace_character_count": 7,
            },
            {
                "page_number": 2,
                "page_index": 1,
                "language": "english",
                "raw_text": "English raw",
                "normalized_for_quality_text": "English raw",
                "character_count": 11,
                "non_whitespace_character_count": 10,
            },
        ]
        assessments = [
            {
                "available": True,
                "quality_score": 0.3,
                "quality": "poor",
                "requires_ocr": True,
                "reasons": ["test_low_quality"],
            },
            {
                "available": True,
                "quality_score": 0.9,
                "quality": "good",
                "requires_ocr": False,
                "reasons": ["quality_checks_passed"],
            },
        ]
        with (
            patch("text_layer.analyze_text_layer.detect_abstract_page", return_value=detection),
            patch(
                "text_layer.analyze_text_layer.extract_abstract_text_layers",
                return_value=extracted,
            ),
            patch(
                "text_layer.analyze_text_layer.assess_text_quality",
                side_effect=assessments,
            ) as assess,
        ):
            result = analyze_abstract_text_layers("sample.pdf")

        self.assertEqual(assess.call_count, 2)
        self.assertEqual(len(result["abstract_pages"]), 2)
        self.assertEqual(result["requires_ocr_pages"], [1])
        self.assertEqual(result["primary_candidate"], {"page_number": 1})


if __name__ == "__main__":
    unittest.main()
