"""Reusable normalized-line parsing without mutating upstream page objects."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .models import PageContext
from .patterns import PAGE_MARKER_RE, LabelMatch, match_label


def compact_spaces(value: str) -> str:
    return " ".join(value.split()).strip()


def page_context_from_mapping(page: Mapping[str, Any]) -> PageContext | None:
    text = page.get("normalized_text")
    if not isinstance(text, str) or not text.strip():
        return None
    processing_status = page.get("processing_status")
    if processing_status is not None and processing_status != "success":
        return None
    if page.get("normalization_status") in {"skipped", "empty"}:
        return None
    page_number = page.get("page_number")
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        return None
    language = page.get("language", "unknown")
    if not isinstance(language, str):
        language = "unknown"
    normalization = page.get("normalization")
    warnings: list[str] = []
    if isinstance(normalization, Mapping):
        raw_warnings = normalization.get("warnings", [])
        if isinstance(raw_warnings, Sequence) and not isinstance(raw_warnings, str):
            warnings.extend(str(warning) for warning in raw_warnings)
    return PageContext(
        page_number=page_number,
        language=language.lower(),
        normalized_text=text,
        lines=tuple(text.split("\n")),
        upstream_warnings=tuple(dict.fromkeys(warnings)),
        upstream_requires_review=bool(page.get("requires_manual_review", False)),
    )


def nonempty_line_indexes(lines: Sequence[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if line.strip()]


def next_nonempty_line(
    lines: Sequence[str],
    start_index: int,
) -> tuple[int, str] | None:
    for index in range(start_index, len(lines)):
        value = lines[index].strip()
        if value:
            return index, value
    return None


def previous_nonempty_line(
    lines: Sequence[str],
    start_index: int,
) -> tuple[int, str] | None:
    for index in range(start_index, -1, -1):
        value = lines[index].strip()
        if value:
            return index, value
    return None


def first_label_index(
    lines: Sequence[str],
    fields: Iterable[str],
) -> int | None:
    for index, line in enumerate(lines):
        if match_label(line, fields) is not None:
            return index
    return None


def collect_labeled_value(
    lines: Sequence[str],
    label_index: int,
    label_match: LabelMatch,
    *,
    maximum_continuation_lines: int,
    stop_fields: Iterable[str],
) -> tuple[str, tuple[int, ...], tuple[str, ...], bool]:
    """Collect a same-line or bounded following-line value.

    The final boolean distinguishes same-line evidence from a following-line
    value for deterministic confidence scoring.
    """
    values: list[str] = []
    indexes: list[int] = []
    evidence: list[str] = [lines[label_index].strip()]
    if label_match.value:
        values.append(label_match.value)
        indexes.append(label_index)
        same_line = True
    else:
        same_line = False

    continuation_count = 0
    for index in range(label_index + 1, len(lines)):
        line = lines[index].strip()
        if not line:
            if values:
                break
            continue
        if match_label(line, stop_fields) is not None:
            break
        if PAGE_MARKER_RE.fullmatch(line) and not values:
            continue
        values.append(line)
        indexes.append(index)
        evidence.append(line)
        continuation_count += 1
        if continuation_count >= maximum_continuation_lines:
            break
    return compact_spaces(" ".join(values)), tuple(indexes), tuple(evidence), same_line


def is_reasonable_person_name(value: str) -> bool:
    cleaned = compact_spaces(value)
    if not cleaned or len(cleaned) > 180 or any(character.isdigit() for character in cleaned):
        return False
    if match_label(cleaned) is not None:
        return False
    return bool(re.search(r"[A-Za-z\u0e00-\u0e7f]", cleaned))


def deduplicate_strings(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = compact_spaces(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)
    return unique
