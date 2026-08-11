"""Structural Thai and English title extraction near the top of each page."""

from __future__ import annotations

from typing import Iterable

from .line_utils import collect_labeled_value, compact_spaces, first_label_index
from .models import ExtractionConfig, FieldCandidate, PageContext
from .patterns import (
    LATIN_CHARACTER_RE,
    PAGE_MARKER_RE,
    STRONG_BOUNDARY_FIELDS,
    THAI_CHARACTER_RE,
    is_abstract_heading,
    match_label,
    truncate_at_inline_student_section,
)
from .resolution import make_candidate


TITLE_STOP_FIELDS = tuple(field for field in STRONG_BOUNDARY_FIELDS if field != "title")


def _title_field(page: PageContext, value: str) -> str | None:
    has_thai = THAI_CHARACTER_RE.search(value) is not None
    has_latin = LATIN_CHARACTER_RE.search(value) is not None
    if page.language == "thai" and has_thai:
        return "title_th"
    if page.language == "english" and has_latin:
        return "title_en"
    if has_thai and not has_latin:
        return "title_th"
    if has_latin and not has_thai:
        return "title_en"
    if page.language == "thai" and has_thai:
        return "title_th"
    if page.language == "english" and has_latin:
        return "title_en"
    return None


def _reasonable_title(value: str, config: ExtractionConfig) -> bool:
    length = len(value)
    return config.minimum_title_characters <= length <= config.maximum_title_characters


def _script_compatible_continuation(page: PageContext, value: str) -> bool:
    has_thai = THAI_CHARACTER_RE.search(value) is not None
    has_latin = LATIN_CHARACTER_RE.search(value) is not None
    if page.language == "thai":
        return has_thai or not has_latin
    if page.language == "english":
        return has_latin or not has_thai
    return True


def extract_title_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> dict[str, list[FieldCandidate]]:
    results: dict[str, list[FieldCandidate]] = {"title_th": [], "title_en": []}
    for page in pages:
        labeled = False
        for line_index, line in enumerate(page.lines):
            label = match_label(line, ("title",))
            if label is None:
                continue
            value, indexes, evidence, same_line = collect_labeled_value(
                page.lines,
                line_index,
                label,
                maximum_continuation_lines=config.maximum_title_lines,
                stop_fields=TITLE_STOP_FIELDS,
            )
            selected_lines = [page.lines[index].strip() for index in indexes]
            if selected_lines and same_line:
                selected_lines[0] = label.value
            compatible_lines: list[str] = []
            compatible_indexes: list[int] = []
            for index, candidate_line in zip(indexes, selected_lines, strict=True):
                candidate_line = truncate_at_inline_student_section(candidate_line)
                if not candidate_line:
                    break
                if compatible_lines and not _script_compatible_continuation(page, candidate_line):
                    break
                compatible_lines.append(candidate_line)
                compatible_indexes.append(index)
            value = compact_spaces(" ".join(compatible_lines))
            indexes = tuple(compatible_indexes)
            evidence = tuple(page.lines[index].strip() for index in indexes)
            field_name = _title_field(page, value)
            if field_name is None or not _reasonable_title(value, config):
                continue
            labeled = True
            results[field_name].append(
                make_candidate(
                    page,
                    value=value,
                    confidence=(
                        config.same_line_label_confidence
                        if same_line
                        else config.next_line_label_confidence
                    ),
                    line_indexes=indexes or (line_index,),
                    method="title_label_and_section_boundary",
                    evidence=evidence,
                    config=config,
                )
            )
        if labeled:
            continue

        boundary = first_label_index(page.lines, TITLE_STOP_FIELDS)
        if boundary is None or boundary <= 0:
            continue
        indexes: list[int] = []
        values: list[str] = []
        for index in range(boundary):
            line = page.lines[index].strip()
            if not line or PAGE_MARKER_RE.fullmatch(line) or is_abstract_heading(line):
                continue
            if match_label(line) is not None:
                continue
            indexes.append(index)
            values.append(line)
        if len(values) > config.maximum_title_lines:
            values = values[-config.maximum_title_lines :]
            indexes = indexes[-config.maximum_title_lines :]
        value = compact_spaces(" ".join(values))
        field_name = _title_field(page, value)
        if field_name is None or not _reasonable_title(value, config):
            continue
        results[field_name].append(
            make_candidate(
                page,
                value=value,
                confidence=config.inferred_title_confidence,
                line_indexes=indexes,
                method="inferred_top_lines_before_metadata",
                evidence=values,
                config=config,
            )
        )
    return results
