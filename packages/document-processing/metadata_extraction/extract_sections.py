"""Abstract and keyword extraction using explicit section boundaries."""

from __future__ import annotations

from typing import Iterable

from .line_utils import deduplicate_strings
from .models import ExtractionConfig, FieldCandidate, PageContext
from .patterns import KEYWORD_SEPARATOR_RE, PAGE_MARKER_RE, match_label
from .resolution import make_candidate


def extract_abstract_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> dict[str, list[FieldCandidate]]:
    results: dict[str, list[FieldCandidate]] = {"abstract_th": [], "abstract_en": []}
    for page in pages:
        for heading_index, line in enumerate(page.lines):
            heading = match_label(line, ("abstract",))
            if heading is None:
                continue
            body_lines: list[str] = []
            body_indexes: list[int] = []
            if heading.value:
                body_lines.append(heading.value)
                body_indexes.append(heading_index)
            for index in range(heading_index + 1, len(page.lines)):
                body_line = page.lines[index].strip()
                if match_label(body_line, ("keywords",)) is not None:
                    break
                body_lines.append(body_line)
                body_indexes.append(index)
            while body_lines and not body_lines[0]:
                body_lines.pop(0)
                body_indexes.pop(0)
            while body_lines and not body_lines[-1]:
                body_lines.pop()
                body_indexes.pop()
            if (
                body_lines
                and PAGE_MARKER_RE.fullmatch(body_lines[-1])
                and body_indexes[-1] > 0
                and not page.lines[body_indexes[-1] - 1].strip()
            ):
                body_lines.pop()
                body_indexes.pop()
            body = "\n".join(body_lines).strip()
            if not body:
                continue
            field_name = "abstract_th" if page.language == "thai" else "abstract_en"
            if page.language not in {"thai", "english"}:
                field_name = (
                    "abstract_th"
                    if any("ก" <= char <= "๛" for char in body)
                    else "abstract_en"
                )
            results[field_name].append(
                make_candidate(
                    page,
                    value=body,
                    confidence=config.abstract_boundary_confidence,
                    line_indexes=body_indexes,
                    method="abstract_heading_to_keywords_or_page_end",
                    evidence=(line.strip(), *body_lines[:3]),
                    config=config,
                )
            )
            break
    return results


def extract_keyword_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for page in pages:
        for label_index, line in enumerate(page.lines):
            label = match_label(line, ("keywords",))
            if label is None:
                continue
            raw_parts: list[tuple[int, str]] = []
            if label.value:
                raw_parts.append((label_index, label.value))
            for index in range(label_index + 1, min(len(page.lines), label_index + 4)):
                next_line = page.lines[index].strip()
                if not next_line:
                    if raw_parts:
                        break
                    continue
                if match_label(next_line) is not None or PAGE_MARKER_RE.fullmatch(next_line):
                    break
                raw_parts.append((index, next_line))
            combined_value = " ".join(raw_value for _, raw_value in raw_parts)
            keywords = deduplicate_strings(KEYWORD_SEPARATOR_RE.split(combined_value))
            if not keywords:
                continue
            same_line = bool(label.value)
            candidates.append(
                make_candidate(
                    page,
                    value=keywords,
                    confidence=(
                        config.same_line_label_confidence
                        if same_line
                        else config.next_line_label_confidence
                    ),
                    line_indexes=[index for index, _ in raw_parts],
                    method="keywords_label_and_separator",
                    evidence=(line.strip(), *(value for _, value in raw_parts[:3])),
                    config=config,
                )
            )
            break
    return candidates
