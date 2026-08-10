"""Tests for the PaddleOCR benchmark runner."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from run_paddleocr import (
    RunnerError,
    collect_images,
    ensure_outputs_available,
    initialize_ocr,
    load_dependencies,
    run_image,
)


class FakeResult:
    @property
    def json(self) -> dict[str, object]:
        return {
            "res": {
                "rec_texts": ["ทดสอบ", "PaddleOCR"],
                "rec_scores": [0.9, 0.8],
                "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]] * 2,
                "rec_boxes": [[0, 0, 1, 1], [0, 2, 1, 3]],
            }
        }


class FakeOCR:
    def predict(self, image_path: str) -> list[FakeResult]:
        return [FakeResult()]


class PaddleOCRRunnerTests(unittest.TestCase):
    def test_invalid_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid = Path(temporary_directory) / "input.jpg"
            invalid.write_bytes(b"not-an-image")
            with self.assertRaisesRegex(RunnerError, "not a PNG"):
                collect_images(invalid, None)

    def test_missing_dependencies_have_clear_error(self) -> None:
        with mock.patch.dict(sys.modules, {"paddle": None, "paddleocr": None}):
            with self.assertRaisesRegex(RunnerError, "dependencies are unavailable"):
                load_dependencies()

    def test_model_initialization_error_is_wrapped(self) -> None:
        failing_class = mock.Mock(side_effect=RuntimeError("model unavailable"))
        with self.assertRaisesRegex(RunnerError, "official PaddleOCR models"):
            initialize_ocr(failing_class)

    def test_existing_output_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / "document_007_page_004.png"
            image.write_bytes(b"png")
            (root / "document_007_page_004.txt").write_text("existing")
            with self.assertRaisesRegex(RunnerError, "--overwrite"):
                ensure_outputs_available([image], root, overwrite=False)

    def test_run_image_writes_raw_text_and_correct_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / "document_007_page_004.png"
            image.write_bytes(b"png")
            text_path, json_path, _, count = run_image(
                ocr=FakeOCR(),
                image_path=image,
                output_dir=root,
                paddleocr_version="3.7.0",
                paddlepaddle_version="3.3.1",
                official_model_hashes={"det": "a", "rec": "b"},
                overwrite=False,
            )
            raw_bytes = text_path.read_bytes()
            self.assertEqual(raw_bytes.decode("utf-8"), "ทดสอบ\nPaddleOCR\n")
            self.assertEqual(count, 2)
            result = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(result["document_id"], "document_007")
            self.assertEqual(result["engine"], "paddleocr")
            self.assertEqual(result["preprocessing"], "none")
            self.assertEqual(
                result["output_sha256"], hashlib.sha256(raw_bytes).hexdigest()
            )
            self.assertEqual(
                result["configuration"]["text_recognition_model"],
                "th_PP-OCRv5_mobile_rec",
            )


if __name__ == "__main__":
    unittest.main()
