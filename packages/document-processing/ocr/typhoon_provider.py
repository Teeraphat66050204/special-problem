"""Typhoon OCR provider for the production document-processing pipeline."""

from __future__ import annotations

import base64
import os
import threading
import time
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable

from .markdown import markdown_to_plain_text
from .models import OCRError, OCRPageImage, OCRResult


API_KEY_ENVIRONMENT = "TYPHOON_OCR_API_KEY"


class ProviderSetupError(Exception):
    """A dependency or configuration failure before an API request."""


@dataclass(frozen=True)
class TyphoonConfig:
    """Safe Typhoon request, retry, rate, and concurrency configuration."""

    base_url: str = "https://api.opentyphoon.ai/v1"
    model: str = "typhoon-ocr"
    task_type: str = "v1.5"
    figure_language: str = "Thai"
    max_tokens: int = 16384
    temperature: float = 0.1
    top_p: float = 0.6
    repetition_penalty: float = 1.1
    timeout_seconds: float = 180.0
    max_retries: int = 2
    initial_backoff_seconds: float = 1.0
    request_interval_seconds: float = 3.1
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be zero or greater.")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be zero or greater.")
        if self.request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must be zero or greater.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero.")


def _environment_api_key() -> str | None:
    return os.environ.get(API_KEY_ENVIRONMENT)


def _default_client_factory(api_key: str, config: TyphoonConfig) -> Any:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise ProviderSetupError(
            "The OpenAI client dependency for Typhoon OCR is unavailable."
        ) from exc
    try:
        return OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
    except Exception as exc:
        raise ProviderSetupError("Could not initialize the Typhoon API client.") from exc


def _default_prompt_factory(config: TyphoonConfig) -> str:
    try:
        from typhoon_ocr import get_prompt  # type: ignore[import-not-found]
    except Exception as exc:
        raise ProviderSetupError("The Typhoon OCR dependency is unavailable.") from exc
    try:
        prompt_factory = get_prompt(config.task_type)
        prompt = prompt_factory(figure_language=config.figure_language)
    except Exception as exc:
        raise ProviderSetupError("Could not build the Typhoon OCR prompt.") from exc
    if not isinstance(prompt, str) or not prompt:
        raise ProviderSetupError("The Typhoon OCR prompt is empty or invalid.")
    return prompt


def _default_markdown_converter(raw_markdown: str) -> str:
    try:
        from markdown_it import MarkdownIt  # type: ignore[import-not-found]
    except Exception as exc:
        raise ProviderSetupError(
            "The Markdown dependency for Typhoon OCR is unavailable."
        ) from exc
    try:
        return markdown_to_plain_text(raw_markdown, MarkdownIt)
    except Exception as exc:
        raise ProviderSetupError("Could not convert Typhoon Markdown to text.") from exc


def _package_version(package_name: str) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _http_status(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _classify_request_error(exc: Exception) -> OCRError:
    status = _http_status(exc)
    class_name = type(exc).__name__.casefold()
    if status in {401, 403}:
        return OCRError(
            code="authentication_error",
            message="Typhoon OCR rejected the configured API key.",
            http_status=status,
        )
    if status == 429:
        return OCRError(
            code="rate_limited",
            message="Typhoon OCR rate limit was reached.",
            transient=True,
            http_status=status,
        )
    if status == 408 or (status is not None and status >= 500):
        return OCRError(
            code="service_unavailable",
            message="Typhoon OCR is temporarily unavailable.",
            transient=True,
            http_status=status,
        )
    if status is not None and 400 <= status < 500:
        return OCRError(
            code="invalid_request",
            message="Typhoon OCR rejected the request.",
            http_status=status,
        )
    if isinstance(exc, TimeoutError) or "timeout" in class_name:
        return OCRError(
            code="timeout",
            message="Typhoon OCR request timed out.",
            transient=True,
        )
    if isinstance(exc, (ConnectionError, OSError)) or any(
        token in class_name for token in ("connection", "network")
    ):
        return OCRError(
            code="connection_error",
            message="Could not connect to Typhoon OCR.",
            transient=True,
        )
    return OCRError(
        code="provider_error",
        message="Typhoon OCR request failed.",
    )


class TyphoonProvider:
    """Synchronous Typhoon provider with bounded retries and request pacing."""

    name = "typhoon"

    def __init__(
        self,
        config: TyphoonConfig = TyphoonConfig(),
        *,
        api_key_resolver: Callable[[], str | None] = _environment_api_key,
        client_factory: Callable[[str, TyphoonConfig], Any] = _default_client_factory,
        prompt_factory: Callable[[TyphoonConfig], str] = _default_prompt_factory,
        markdown_converter: Callable[[str], str] = _default_markdown_converter,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._api_key_resolver = api_key_resolver
        self._client_factory = client_factory
        self._prompt_factory = prompt_factory
        self._markdown_converter = markdown_converter
        self._sleep = sleep
        self._monotonic = monotonic
        self._client: Any | None = None
        self._prompt: str | None = None
        self._setup_lock = threading.Lock()
        self._schedule_lock = threading.Lock()
        self._request_slots = threading.BoundedSemaphore(config.max_concurrency)
        self._last_request_started: float | None = None

    def _setup(self) -> OCRError | None:
        if self._client is not None and self._prompt is not None:
            return None
        with self._setup_lock:
            if self._client is not None and self._prompt is not None:
                return None
            api_key = self._api_key_resolver()
            if not api_key:
                return OCRError(
                    code="missing_api_key",
                    message=(
                        "Typhoon OCR API key is missing. Set "
                        f"{API_KEY_ENVIRONMENT} in the environment."
                    ),
                )
            try:
                self._client = self._client_factory(api_key, self.config)
                self._prompt = self._prompt_factory(self.config)
            except ProviderSetupError as exc:
                return OCRError(
                    code="dependency_unavailable",
                    message=str(exc),
                )
        return None

    def _wait_for_request_slot(self) -> None:
        with self._schedule_lock:
            now = self._monotonic()
            if self._last_request_started is not None:
                elapsed = now - self._last_request_started
                remaining = self.config.request_interval_seconds - elapsed
                if remaining > 0:
                    self._sleep(remaining)
            self._last_request_started = self._monotonic()

    def _request(self, page_image: OCRPageImage) -> Any:
        encoded_png = base64.b64encode(page_image.data).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self._prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{page_image.mime_type};base64,{encoded_png}"
                        },
                    },
                ],
            }
        ]
        with self._request_slots:
            self._wait_for_request_slot()
            return self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=self.config.max_tokens,
                extra_body={
                    "repetition_penalty": self.config.repetition_penalty,
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                },
            )

    def _response_markdown(self, response: Any) -> str | None:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        return content if isinstance(content, str) and content.strip() else None

    def extract(self, page_image: OCRPageImage) -> OCRResult:
        """OCR one PNG page, retrying transient provider errors only."""
        started = self._monotonic()
        if (
            page_image.mime_type != "image/png"
            or page_image.dpi != 300
            or page_image.color_space != "RGB"
            or page_image.preprocessing != "none"
            or not page_image.data.startswith(b"\x89PNG\r\n\x1a\n")
        ):
            return OCRResult.failed(
                provider=self.name,
                error=OCRError(
                    code="invalid_image",
                    message=(
                        "Typhoon OCR requires an in-memory 300 DPI RGB PNG page "
                        "with no preprocessing."
                    ),
                ),
            )
        setup_error = self._setup()
        if setup_error is not None:
            return OCRResult.failed(
                provider=self.name,
                error=setup_error,
                processing_time_ms=round((self._monotonic() - started) * 1000, 3),
            )

        attempts = 0
        for attempts in range(1, self.config.max_retries + 2):
            try:
                response = self._request(page_image)
            except Exception as exc:
                error = _classify_request_error(exc)
                if error.transient and attempts <= self.config.max_retries:
                    delay = self.config.initial_backoff_seconds * (2 ** (attempts - 1))
                    if delay:
                        self._sleep(delay)
                    continue
                return OCRResult.failed(
                    provider=self.name,
                    error=error,
                    processing_time_ms=round(
                        (self._monotonic() - started) * 1000,
                        3,
                    ),
                    attempts=attempts,
                )

            raw_markdown = self._response_markdown(response)
            if raw_markdown is None:
                return OCRResult.failed(
                    provider=self.name,
                    error=OCRError(
                        code="invalid_response",
                        message="Typhoon OCR returned no Markdown content.",
                    ),
                    processing_time_ms=round(
                        (self._monotonic() - started) * 1000,
                        3,
                    ),
                    attempts=attempts,
                    raw_format="markdown",
                )
            try:
                plain_text = self._markdown_converter(raw_markdown)
            except ProviderSetupError as exc:
                return OCRResult.failed(
                    provider=self.name,
                    error=OCRError(
                        code="dependency_unavailable",
                        message=str(exc),
                    ),
                    processing_time_ms=round(
                        (self._monotonic() - started) * 1000,
                        3,
                    ),
                    attempts=attempts,
                    raw_text=raw_markdown,
                    raw_format="markdown",
                )
            except Exception:
                return OCRResult.failed(
                    provider=self.name,
                    error=OCRError(
                        code="conversion_error",
                        message="Could not convert Typhoon Markdown to plain text.",
                    ),
                    processing_time_ms=round(
                        (self._monotonic() - started) * 1000,
                        3,
                    ),
                    attempts=attempts,
                    raw_text=raw_markdown,
                    raw_format="markdown",
                )
            if not plain_text.strip():
                return OCRResult.failed(
                    provider=self.name,
                    error=OCRError(
                        code="empty_response",
                        message="Typhoon OCR returned no usable text.",
                    ),
                    processing_time_ms=round(
                        (self._monotonic() - started) * 1000,
                        3,
                    ),
                    attempts=attempts,
                    raw_text=raw_markdown,
                    raw_format="markdown",
                )
            return OCRResult.succeeded(
                provider=self.name,
                text=plain_text,
                raw_text=raw_markdown,
                raw_format="markdown",
                processing_time_ms=round(
                    (self._monotonic() - started) * 1000,
                    3,
                ),
                attempts=attempts,
                metadata={
                    "model": self.config.model,
                    "typhoon_ocr_version": _package_version("typhoon-ocr"),
                    "openai_version": _package_version("openai"),
                },
            )

        raise AssertionError("Typhoon retry loop exited unexpectedly.")
