"""Tests for Typhoon OCR setup, response handling, and retry policy."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.models import OCRPageImage
from ocr.typhoon_provider import TyphoonConfig, TyphoonProvider


PNG = b"\x89PNG\r\n\x1a\nunit-test"


def image() -> OCRPageImage:
    return OCRPageImage(
        data=PNG,
        page_number=4,
        page_index=3,
        width_px=100,
        height_px=200,
    )


def response(content: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class HTTPFailure(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


def provider_for(outcomes: list[Any], *, max_retries: int = 2) -> tuple[TyphoonProvider, FakeClient, list[float]]:
    client = FakeClient(outcomes)
    sleeps: list[float] = []
    provider = TyphoonProvider(
        TyphoonConfig(
            max_retries=max_retries,
            initial_backoff_seconds=0.25,
            request_interval_seconds=0,
        ),
        api_key_resolver=lambda: "test-key",
        client_factory=lambda key, config: client,
        prompt_factory=lambda config: "OCR prompt",
        markdown_converter=lambda raw: raw.removeprefix("# "),
        sleep=sleeps.append,
    )
    return provider, client, sleeps


class TyphoonProviderTests(unittest.TestCase):
    def test_missing_api_key_is_controlled_error_without_request(self) -> None:
        factory_calls: list[str] = []
        provider = TyphoonProvider(
            TyphoonConfig(request_interval_seconds=0),
            api_key_resolver=lambda: None,
            client_factory=lambda key, config: factory_calls.append(key),
        )
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "missing_api_key")
        self.assertEqual(result.attempts, 0)
        self.assertEqual(factory_calls, [])

    def test_success_preserves_raw_markdown_and_returns_plain_text(self) -> None:
        provider, client, _ = provider_for([response("# recognized text")])
        result = provider.extract(image())
        self.assertTrue(result.success)
        self.assertEqual(result.text, "recognized text")
        self.assertEqual(result.raw_text, "# recognized text")
        request = client.chat.completions.calls[0]
        url = request["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertNotIn("test-key", str(result.to_dict()))

    def test_transient_rate_limit_retries_with_backoff(self) -> None:
        provider, client, sleeps = provider_for(
            [HTTPFailure(429), response("# recovered")]
        )
        result = provider.extract(image())
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(client.chat.completions.calls), 2)
        self.assertEqual(sleeps, [0.25])

    def test_server_error_retries_until_bound(self) -> None:
        provider, client, sleeps = provider_for(
            [HTTPFailure(503), HTTPFailure(503), HTTPFailure(503)]
        )
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "service_unavailable")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(client.chat.completions.calls), 3)
        self.assertEqual(sleeps, [0.25, 0.5])

    def test_permanent_authentication_error_does_not_retry(self) -> None:
        provider, client, sleeps = provider_for([HTTPFailure(401)], max_retries=3)
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "authentication_error")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(client.chat.completions.calls), 1)
        self.assertEqual(sleeps, [])

    def test_timeout_retries(self) -> None:
        provider, _, _ = provider_for([TimeoutError(), response("# ok")])
        result = provider.extract(image())
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)

    def test_connection_error_retries(self) -> None:
        provider, _, _ = provider_for([ConnectionError(), response("# ok")])
        result = provider.extract(image())
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)

    def test_permanent_client_error_does_not_retry(self) -> None:
        provider, client, _ = provider_for(
            [HTTPFailure(400), response("unused")],
            max_retries=3,
        )
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "invalid_request")
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_invalid_response_is_not_retried(self) -> None:
        provider, client, _ = provider_for([response(None), response("unused")])
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "invalid_response")
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_empty_converted_text_is_failure(self) -> None:
        provider, _, _ = provider_for([response("# ")])
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "empty_response")

    def test_converter_exception_is_controlled_failure(self) -> None:
        provider, _, _ = provider_for([response("# text")])
        provider._markdown_converter = lambda raw: (_ for _ in ()).throw(ValueError())
        result = provider.extract(image())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "conversion_error")

    def test_invalid_image_is_rejected_before_setup_or_request(self) -> None:
        provider, client, _ = provider_for([response("unused")])
        invalid = OCRPageImage(
            data=b"not png",
            page_number=1,
            page_index=0,
            width_px=10,
            height_px=10,
        )
        result = provider.extract(invalid)
        self.assertEqual(result.error.code, "invalid_image")
        self.assertEqual(client.chat.completions.calls, [])


if __name__ == "__main__":
    unittest.main()
