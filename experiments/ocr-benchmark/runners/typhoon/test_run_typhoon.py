"""Tests for the Typhoon OCR benchmark runner."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from markdown_it import MarkdownIt

from run_typhoon import (
    RunnerError,
    ensure_outputs_available,
    load_render_metadata,
    markdown_to_plain_text,
    resolve_api_key,
    run_image,
    sha256_file,
)


class FakeCompletions:
    def create(self, **kwargs: object) -> SimpleNamespace:
        message = SimpleNamespace(
            content=(
                "# หัวเรื่อง\n\nข้อความ **ตัวหนา**\n\n"
                "<table><tr><td>ไทย</td><td>English</td></tr></table>"
            )
        )
        choice = SimpleNamespace(message=message, finish_reason="stop")
        usage = SimpleNamespace(
            model_dump=lambda: {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        )
        return SimpleNamespace(
            id="response-1", model="typhoon-ocr", choices=[choice], usage=usage
        )


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


def create_benchmark_image(root: Path) -> Path:
    image = root / "document_007_page_004.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nbenchmark")
    image_sha256 = sha256_file(image)
    sidecar = image.with_suffix(".render.json")
    sidecar.write_text(
        json.dumps(
            {
                "dpi": 300,
                "color_space": "RGB",
                "format": "PNG",
                "preprocessing": False,
                "width_px": 2550,
                "height_px": 3300,
                "output_file": image.name,
                "output_sha256": image_sha256,
            }
        ),
        encoding="utf-8",
    )
    return image


class TyphoonRunnerTests(unittest.TestCase):
    def test_render_metadata_requires_benchmark_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image = create_benchmark_image(Path(temporary_directory))
            metadata_path = image.with_suffix(".render.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["dpi"] = 200
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "dpi=200"):
                load_render_metadata(image, sha256_file(image))

    def test_markdown_conversion_is_deterministic(self) -> None:
        markdown = (
            "# หัวเรื่อง\n\nข้อความ **ตัวหนา** และ [ลิงก์](https://example.com)\n\n"
            "| ไทย | English |\n| --- | --- |\n| หนึ่ง | one |\n\n"
            "<page_number>4</page_number>"
        )
        expected = (
            "หัวเรื่อง\nข้อความ ตัวหนา และ ลิงก์\nไทย\tEnglish\nหนึ่ง\tone\n4\n"
        )
        first = markdown_to_plain_text(markdown, MarkdownIt)
        second = markdown_to_plain_text(markdown, MarkdownIt)
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)

    def test_missing_api_key_has_clear_error(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "TYPHOON_OCR_API_KEY": "",
                "TYPHOON_API_KEY": "",
                "OPENAI_API_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RunnerError, "API key is missing"):
                resolve_api_key()

    def test_overwrite_protects_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = create_benchmark_image(root)
            (root / "document_007_page_004.md").write_text("existing")
            with self.assertRaisesRegex(RunnerError, "--overwrite"):
                ensure_outputs_available([image], root, overwrite=False)

    def test_run_image_preserves_markdown_and_hashes_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = create_benchmark_image(root)
            markdown_path, text_path, json_path, _ = run_image(
                client=FakeClient(),
                prompt="official prompt",
                markdown_it_class=MarkdownIt,
                image_path=image,
                output_dir=root,
                api_key_environment="TYPHOON_OCR_API_KEY",
                typhoon_ocr_version="0.4.1",
                openai_version="2.53.0",
                markdown_it_version="4.2.0",
                overwrite=False,
            )
            expected_markdown = (
                "# หัวเรื่อง\n\nข้อความ **ตัวหนา**\n\n"
                "<table><tr><td>ไทย</td><td>English</td></tr></table>"
            )
            self.assertEqual(markdown_path.read_text(encoding="utf-8"), expected_markdown)
            self.assertEqual(
                text_path.read_text(encoding="utf-8"),
                "หัวเรื่อง\nข้อความ ตัวหนา\nไทย\tEnglish\n",
            )
            result = json.loads(json_path.read_text(encoding="utf-8"))
            markdown_bytes = markdown_path.read_bytes()
            text_bytes = text_path.read_bytes()
            self.assertEqual(
                result["raw_markdown_sha256"],
                hashlib.sha256(markdown_bytes).hexdigest(),
            )
            self.assertEqual(
                result["output_sha256"], hashlib.sha256(text_bytes).hexdigest()
            )
            self.assertEqual(result["render"]["dpi"], 300)
            self.assertEqual(result["preprocessing"], "none")


if __name__ == "__main__":
    unittest.main()
