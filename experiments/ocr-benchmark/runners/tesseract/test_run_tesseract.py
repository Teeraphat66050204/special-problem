"""Tests for the Tesseract OCR runner."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from run_tesseract import (
    RunnerError,
    collect_images,
    ensure_outputs_available,
    parse_args,
    resolve_tesseract,
    run_image,
    validate_required_languages,
)


class TesseractRunnerTests(unittest.TestCase):
    def test_languages_default_and_custom_expression(self) -> None:
        required = ["--input", "image.png", "--output", "output"]
        self.assertEqual(parse_args(required).languages, "tha+eng")
        self.assertEqual(
            parse_args([*required, "--languages", "ocr_train+eng"]).languages,
            "ocr_train+eng",
        )

    def test_missing_executable_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing-tesseract.exe"
            with self.assertRaisesRegex(RunnerError, "does not exist"):
                resolve_tesseract(missing)

    def test_missing_language_has_clear_error(self) -> None:
        with self.assertRaisesRegex(RunnerError, "Missing required.*tha"):
            validate_required_languages(["tha", "eng"], ["eng", "osd"])

    def test_invalid_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid = Path(temporary_directory) / "input.jpg"
            invalid.write_bytes(b"not-an-image")
            with self.assertRaisesRegex(RunnerError, "not a PNG"):
                collect_images([invalid], None)

    def test_existing_output_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / "document_007_page_004.png"
            image.write_bytes(b"png")
            (root / "document_007_page_004.txt").write_text("existing")
            with self.assertRaisesRegex(RunnerError, "--overwrite"):
                ensure_outputs_available([image], root, overwrite=False)

    @mock.patch("run_tesseract.subprocess.run")
    def test_run_image_writes_raw_output_and_metadata(
        self, run_mock: mock.Mock
    ) -> None:
        raw_text = "ทดสอบ OCR\n".encode()
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=raw_text, stderr=b""
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / "document_007_page_004.png"
            image.write_bytes(b"png")

            text_path, json_path, _ = run_image(
                executable=Path("tesseract.exe"),
                tessdata_directory=Path("tessdata"),
                image_path=image,
                output_dir=root,
                tesseract_version="5.5.3",
                language_expression="tha+eng",
                languages=["tha", "eng"],
                model_hashes={"tha": "a", "eng": "b"},
                overwrite=False,
            )

            self.assertEqual(text_path.read_bytes(), raw_text)
            metadata = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["document_id"], "document_007")
            self.assertEqual(metadata["engine"], "tesseract")
            self.assertEqual(metadata["languages"], ["tha", "eng"])
            self.assertEqual(metadata["status"], "success")
            command = run_mock.call_args.args[0]
            self.assertIn("tha+eng", command)
            self.assertIn("300", command)


if __name__ == "__main__":
    unittest.main()
