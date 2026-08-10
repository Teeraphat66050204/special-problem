"""Provider-neutral OCR input, output, and error models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class OCRPageImage:
    """One rendered PDF page supplied to an OCR provider."""

    data: bytes
    page_number: int
    page_index: int
    width_px: int
    height_px: int
    dpi: int = 300
    color_space: str = "RGB"
    mime_type: str = "image/png"
    preprocessing: str = "none"


@dataclass(frozen=True)
class OCRError:
    """A safe, structured error suitable for downstream handling."""

    code: str
    message: str
    transient: bool = False
    http_status: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "transient": self.transient,
            "http_status": self.http_status,
        }


@dataclass(frozen=True)
class OCRResult:
    """Provider-neutral OCR result with plain text for downstream use."""

    provider: str
    success: bool
    text: str | None
    raw_text: str | None
    raw_format: str | None
    processing_time_ms: float
    attempts: int
    error: OCRError | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def succeeded(
        cls,
        *,
        provider: str,
        text: str,
        raw_text: str,
        raw_format: str,
        processing_time_ms: float,
        attempts: int = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OCRResult":
        return cls(
            provider=provider,
            success=True,
            text=text,
            raw_text=raw_text,
            raw_format=raw_format,
            processing_time_ms=processing_time_ms,
            attempts=attempts,
            metadata=metadata or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        provider: str,
        error: OCRError,
        processing_time_ms: float = 0.0,
        attempts: int = 0,
        raw_text: str | None = None,
        raw_format: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OCRResult":
        return cls(
            provider=provider,
            success=False,
            text=None,
            raw_text=raw_text,
            raw_format=raw_format,
            processing_time_ms=processing_time_ms,
            attempts=attempts,
            error=error,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "success": self.success,
            "text": self.text,
            "raw_text": self.raw_text,
            "raw_format": self.raw_format,
            "processing_time_ms": self.processing_time_ms,
            "attempts": self.attempts,
            "error": self.error.to_dict() if self.error else None,
            "metadata": dict(self.metadata),
        }
