"""Configuration and structured results for conservative text normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizationConfig:
    """Centralized controls for canonical text formatting.

    NFC is intentionally the default. Compatibility normalization is available
    only through an explicit caller choice because it can alter meaningful
    characters.
    """

    unicode_form: str = "NFC"
    collapse_horizontal_whitespace: bool = True
    max_consecutive_blank_lines: int = 2
    replace_tabs: bool = True
    remove_bom: bool = True
    remove_zero_width_characters: bool = True
    zero_width_characters: tuple[str, ...] = ("\u200b", "\u2060")
    normalize_unicode_whitespace: bool = True

    def __post_init__(self) -> None:
        if self.unicode_form not in {"NFC", "NFD", "NFKC", "NFKD"}:
            raise ValueError("unicode_form must be NFC, NFD, NFKC, or NFKD")
        if (
            isinstance(self.max_consecutive_blank_lines, bool)
            or not isinstance(self.max_consecutive_blank_lines, int)
            or self.max_consecutive_blank_lines < 0
        ):
            raise ValueError("max_consecutive_blank_lines must be zero or greater")
        if any(
            not isinstance(character, str) or len(character) != 1
            for character in self.zero_width_characters
        ):
            raise ValueError("zero_width_characters must contain single characters")


DEFAULT_NORMALIZATION_CONFIG = NormalizationConfig()


@dataclass(frozen=True)
class NormalizationStats:
    original_length: int
    normalized_length: int
    line_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "original_length": self.original_length,
            "normalized_length": self.normalized_length,
            "line_count": self.line_count,
        }


@dataclass(frozen=True)
class NormalizationResult:
    """A testable normalization result that retains its source text."""

    original_text: str
    normalized_text: str
    changed: bool
    operations: tuple[str, ...]
    warnings: tuple[str, ...]
    stats: NormalizationStats

    @property
    def lines(self) -> list[str]:
        return self.normalized_text.split("\n") if self.normalized_text else []

    def normalization_metadata(self) -> dict[str, Any]:
        return {
            "status": "success",
            "changed": self.changed,
            "operations": list(self.operations),
            "warnings": list(self.warnings),
            "stats": self.stats.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "lines": self.lines,
            "changed": self.changed,
            "operations": list(self.operations),
            "warnings": list(self.warnings),
            "stats": self.stats.to_dict(),
        }
