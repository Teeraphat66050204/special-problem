"""Tests for provider-neutral conditional OCR orchestration."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.fallback import process_abstract_pages
from ocr.models import OCRError, OCRPageImage, OCRResult


PNG = b"\x89PNG\r\n\x1a\nunit-test"


def page(
    number: int,
    language: str,
    quality: str,
    *,
    raw_text: str = "layer text",
) -> dict[str, object]:
    return {
        "page_number": number,
        "page_index": number - 1,
        "language": language,
        "score": 10.0,
        "matched_features": [f"{language}_abstract_heading"],
        "text_layer": {
            "quality": quality,
            "requires_ocr": quality != "good",
            "raw_text": raw_text,
        },
    }


def analyzer_for(pages: list[dict[str, object]]):
    def analyze(*args: Any, **kwargs: Any) -> dict[str, object]:
        return {
            "abstract_pages": pages,
            "primary_candidate": pages[0] if pages else None,
            "requires_manual_selection": not pages,
        }

    return analyze


class RecordingRenderer:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(
        self,
        pdf_path: object,
        page_index: int,
        *,
        page_number: int,
        dpi: int,
    ) -> OCRPageImage:
        self.calls.append(page_index)
        return OCRPageImage(
            data=PNG,
            page_number=page_number,
            page_index=page_index,
            width_px=100,
            height_px=200,
            dpi=dpi,
        )


class FakeProvider:
    name = "fake"

    def __init__(self, result: OCRResult | None = None) -> None:
        self.calls: list[OCRPageImage] = []
        self.result = result or OCRResult.succeeded(
            provider=self.name,
            text="ocr text",
            raw_text="# ocr text",
            raw_format="markdown",
            processing_time_ms=12.0,
        )

    def extract(self, page_image: OCRPageImage) -> OCRResult:
        self.calls.append(page_image)
        return self.result


class FallbackTests(unittest.TestCase):
    def run_pipeline(
        self,
        pages: list[dict[str, object]],
        provider: FakeProvider | None = None,
    ) -> tuple[dict[str, object], FakeProvider, RecordingRenderer]:
        selected_provider = provider or FakeProvider()
        renderer = RecordingRenderer()
        result = process_abstract_pages(
            "unused.pdf",
            ocr_provider=selected_provider,
            analyzer=analyzer_for(pages),
            renderer=renderer,
        )
        return result, selected_provider, renderer

    def test_good_text_layer_does_not_call_provider_or_renderer(self) -> None:
        result, provider, renderer = self.run_pipeline([page(2, "thai", "good")])
        output = result["abstract_pages"][0]
        self.assertEqual(output["text_source"], "text_layer")
        self.assertEqual(output["text"], "layer text")
        self.assertEqual(provider.calls, [])
        self.assertEqual(renderer.calls, [])

    def test_poor_text_layer_calls_provider(self) -> None:
        result, provider, renderer = self.run_pipeline([page(3, "thai", "poor")])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(renderer.calls, [2])
        self.assertEqual(result["abstract_pages"][0]["text_source"], "ocr")

    def test_missing_text_layer_calls_provider(self) -> None:
        result, provider, _ = self.run_pipeline(
            [page(4, "english", "missing", raw_text="")]
        )
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["summary"]["ocr_routed_pages"], 1)

    def test_thai_and_english_abstracts_are_processed_separately(self) -> None:
        pages = [page(4, "thai", "poor"), page(5, "english", "good")]
        result, provider, renderer = self.run_pipeline(pages)
        outputs = result["abstract_pages"]
        self.assertEqual([item["language"] for item in outputs], ["thai", "english"])
        self.assertEqual([item["text_source"] for item in outputs], ["ocr", "text_layer"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(renderer.calls, [3])

    def test_ocr_success_exposes_unified_text(self) -> None:
        result, _, _ = self.run_pipeline([page(3, "thai", "poor")])
        output = result["abstract_pages"][0]
        self.assertEqual(output["text"], "ocr text")
        self.assertEqual(output["ocr"]["raw_format"], "markdown")
        self.assertFalse(output["requires_manual_review"])

    def test_ocr_failure_requires_manual_review_without_layer_fallback(self) -> None:
        failure = OCRResult.failed(
            provider="fake",
            error=OCRError(code="timeout", message="timed out", transient=True),
            attempts=3,
        )
        result, _, _ = self.run_pipeline(
            [page(3, "thai", "poor", raw_text="unsafe layer")],
            FakeProvider(failure),
        )
        output = result["abstract_pages"][0]
        self.assertIsNone(output["text_source"])
        self.assertIsNone(output["text"])
        self.assertEqual(output["processing_status"], "ocr_failed")
        self.assertTrue(output["requires_manual_review"])

    def test_empty_ocr_success_is_converted_to_failure(self) -> None:
        empty = OCRResult.succeeded(
            provider="fake",
            text="  ",
            raw_text="",
            raw_format="markdown",
            processing_time_ms=1,
        )
        result, _, _ = self.run_pipeline([page(2, "thai", "poor")], FakeProvider(empty))
        output = result["abstract_pages"][0]
        self.assertEqual(output["error"]["code"], "empty_response")
        self.assertTrue(output["requires_manual_review"])

    def test_fake_provider_satisfies_provider_abstraction(self) -> None:
        provider = FakeProvider()
        result, used_provider, _ = self.run_pipeline([page(2, "thai", "poor")], provider)
        self.assertIs(used_provider, provider)
        self.assertEqual(result["ocr_provider"], "fake")

    def test_only_pages_requiring_ocr_are_rendered(self) -> None:
        pages = [
            page(2, "thai", "good"),
            page(3, "english", "poor"),
            page(4, "thai", "missing"),
        ]
        result, provider, renderer = self.run_pipeline(pages)
        self.assertEqual(renderer.calls, [2, 3])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result["summary"]["text_layer_pages"], 1)
        self.assertEqual(result["summary"]["ocr_routed_pages"], 2)


if __name__ == "__main__":
    unittest.main()
