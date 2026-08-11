"""Conservative validation-only comparison helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([([{])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([)\]}])")


def canonical_text(value: Any, *, casefold: bool = True) -> str:
    """NFC, trim, whitespace collapse, and conservative punctuation spacing."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFC", str(value))
    normalized = " ".join(normalized.split())
    normalized = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", normalized)
    normalized = _SPACE_AFTER_OPEN_RE.sub(r"\1", normalized)
    normalized = _SPACE_BEFORE_CLOSE_RE.sub(r"\1", normalized)
    return normalized.casefold() if casefold else normalized


def equivalent_text(left: Any, right: Any) -> bool:
    return canonical_text(left) == canonical_text(right)


def nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def contains_any_label(value: str, labels: tuple[str, ...]) -> bool:
    canonical = canonical_text(value)
    return any(canonical_text(label) in canonical for label in labels)
