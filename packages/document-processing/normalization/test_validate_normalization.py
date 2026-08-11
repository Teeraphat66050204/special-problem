"""Tests for reproducible offline normalization validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.validate_normalization import (
    _content_signature,
    validate_benchmark,
)


class NormalizationValidationTests(unittest.TestCase):
    def test_content_signature_ignores_only_allowed_formatting(self) -> None:
        self.assertEqual(
            _content_signature("\ufeffCafe\u0301\u00a0A\u200bB"),
            _content_signature("Caf\u00e9 A B"),
        )
        self.assertNotEqual(
            _content_signature("Student ID: 6501234567"),
            _content_signature("Student ID 6501234567"),
        )

    def test_validation_rejects_directory_without_pdfs(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "contains no PDF files"):
                validate_benchmark(temporary_directory)

    def test_validation_routes_good_layer_and_precomputed_text_offline(self) -> None:
        analysis = {
            "abstract_pages": [
                {
                    "page_number": 4,
                    "page_index": 3,
                    "language": "thai",
                    "text_layer": {
                        "requires_ocr": True,
                        "raw_text": "unsafe",
                    },
                },
                {
                    "page_number": 5,
                    "page_index": 4,
                    "language": "english",
                    "text_layer": {
                        "requires_ocr": False,
                        "raw_text": "ABSTRACT:  Safe",
                    },
                },
            ]
        }
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_dir = root / "pdfs"
            text_dir = root / "text"
            pdf_dir.mkdir()
            text_dir.mkdir()
            (pdf_dir / "document_001.pdf").write_bytes(b"not opened")
            (text_dir / "document_001.txt").write_text(
                "บทคัดย่อ  ทดสอบ",
                encoding="utf-8",
            )
            manifest = root / "manifest.csv"
            manifest.write_text(
                "document_id,page_number,ground_truth_file\n"
                "document_001,4,document_001.txt\n",
                encoding="utf-8",
            )
            with patch(
                "normalization.validate_normalization.analyze_abstract_text_layers",
                return_value=analysis,
            ) as analyzer:
                report = validate_benchmark(
                    pdf_dir,
                    manifest_path=manifest,
                    precomputed_text_directory=text_dir,
                )

        analyzer.assert_called_once()
        self.assertTrue(report["offline_only"])
        self.assertEqual(report["source_counts"]["ocr_precomputed"], 1)
        self.assertEqual(report["source_counts"]["text_layer"], 1)
        self.assertEqual(report["content_preservation"]["failures"], [])
        self.assertEqual(report["idempotence"]["failures"], [])


if __name__ == "__main__":
    unittest.main()
