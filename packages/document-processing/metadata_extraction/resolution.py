"""Deterministic candidate scoring, deduplication, and conflict resolution."""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from .line_utils import compact_spaces, deduplicate_strings
from .models import ExtractionConfig, FieldCandidate, FieldResult, PageContext


def source_adjusted_confidence(
    page: PageContext,
    base_confidence: float,
    config: ExtractionConfig,
) -> float:
    penalty = 0.0
    if "suspicious_thai_character_spacing" in page.upstream_warnings:
        penalty += config.suspicious_source_penalty
    if page.upstream_requires_review:
        penalty += min(0.10, config.suspicious_source_penalty)
    return max(0.0, min(1.0, base_confidence - penalty))


def make_candidate(
    page: PageContext,
    *,
    value: Any,
    confidence: float,
    line_indexes: Sequence[int],
    method: str,
    evidence: Sequence[str],
    config: ExtractionConfig,
) -> FieldCandidate:
    return FieldCandidate(
        value=value,
        confidence=source_adjusted_confidence(page, confidence, config),
        source_page=page.page_number,
        source_language=page.language,
        source_line_indexes=tuple(line_indexes),
        method=method,
        evidence=tuple(evidence),
    )


def normalized_candidate_key(value: Any) -> str:
    if isinstance(value, str):
        return compact_spaces(value).casefold()
    return json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()


def _candidate_sort_key(
    candidate: FieldCandidate,
    preferred_languages: Sequence[str],
) -> tuple[int, float, int, int, str]:
    try:
        language_rank = preferred_languages.index(candidate.source_language)
    except ValueError:
        language_rank = len(preferred_languages)
    first_line = candidate.source_line_indexes[0] if candidate.source_line_indexes else 10**9
    return (
        language_rank,
        -candidate.confidence,
        candidate.source_page,
        first_line,
        normalized_candidate_key(candidate.value),
    )


def resolve_scalar_candidates(
    field_name: str,
    candidates: Iterable[FieldCandidate],
    config: ExtractionConfig,
    *,
    preferred_languages: Sequence[str] = ("thai", "english", "mixed", "unknown"),
) -> FieldResult:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: _candidate_sort_key(item, preferred_languages),
        )
    )
    if not ordered:
        return FieldResult.missing()

    selected = ordered[0]
    selected_key = normalized_candidate_key(selected.value)
    alternatives = tuple(
        candidate
        for candidate in ordered[1:]
        if normalized_candidate_key(candidate.value) != selected_key
    )
    warnings: list[str] = []
    if alternatives:
        warnings.append(f"conflicting_{field_name}_candidates")
    if selected.confidence < config.minimum_review_confidence:
        warnings.append(f"low_confidence_{field_name}")
    return FieldResult(
        value=selected.value,
        confidence=selected.confidence,
        source_pages=tuple(dict.fromkeys(candidate.source_page for candidate in ordered)),
        source_languages=tuple(
            dict.fromkeys(candidate.source_language for candidate in ordered)
        ),
        method=selected.method,
        evidence=selected.evidence,
        candidates=ordered,
        alternatives=alternatives,
        warnings=tuple(warnings),
    )


def resolve_string_list(
    candidates: Iterable[FieldCandidate],
    *,
    method: str,
) -> FieldResult:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.source_page,
                item.source_line_indexes,
                -item.confidence,
            ),
        )
    )
    values = deduplicate_strings(
        str(value)
        for candidate in ordered
        for value in (
            candidate.value if isinstance(candidate.value, list) else [candidate.value]
        )
        if value is not None
    )
    if not values:
        return FieldResult.missing([])
    return FieldResult(
        value=values,
        confidence=min(candidate.confidence for candidate in ordered),
        source_pages=tuple(dict.fromkeys(candidate.source_page for candidate in ordered)),
        source_languages=tuple(
            dict.fromkeys(candidate.source_language for candidate in ordered)
        ),
        method=method,
        evidence=tuple(
            dict.fromkeys(item for candidate in ordered for item in candidate.evidence)
        ),
        candidates=ordered,
    )


def resolve_page_scoped_string_list(
    field_name: str,
    candidates: Iterable[FieldCandidate],
    *,
    preferred_languages: Sequence[str] = ("thai", "english", "mixed", "unknown"),
) -> FieldResult:
    """Choose one most-complete page list and retain other pages as alternatives."""
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (item.source_page, item.source_line_indexes, -item.confidence),
        )
    )
    if not ordered:
        return FieldResult.missing([])
    page_groups: dict[tuple[int, str], list[FieldCandidate]] = {}
    for candidate in ordered:
        page_groups.setdefault(
            (candidate.source_page, candidate.source_language), []
        ).append(candidate)

    def group_key(
        item: tuple[tuple[int, str], list[FieldCandidate]],
    ) -> tuple[int, int, float, int]:
        (page_number, language), group = item
        try:
            language_rank = preferred_languages.index(language)
        except ValueError:
            language_rank = len(preferred_languages)
        return (-len(group), language_rank, -max(value.confidence for value in group), page_number)

    selected_key, selected_group = min(page_groups.items(), key=group_key)
    values = deduplicate_strings(str(candidate.value) for candidate in selected_group)
    alternatives = tuple(
        candidate
        for key, group in page_groups.items()
        if key != selected_key
        for candidate in group
    )
    warnings: list[str] = []
    selected_values = {value.casefold() for value in values}
    if any(
        normalized_candidate_key(candidate.value) not in selected_values
        for candidate in alternatives
    ):
        warnings.append(f"conflicting_{field_name}_candidates")
    return FieldResult(
        value=values,
        confidence=min(candidate.confidence for candidate in selected_group),
        source_pages=(selected_key[0],),
        source_languages=(selected_key[1],),
        method="preferred_complete_page_list",
        evidence=tuple(
            dict.fromkeys(item for candidate in selected_group for item in candidate.evidence)
        ),
        candidates=ordered,
        alternatives=alternatives,
        warnings=tuple(warnings),
    )


def resolve_students(
    candidates: Iterable[FieldCandidate],
    config: ExtractionConfig,
) -> FieldResult:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: _candidate_sort_key(
                item,
                ("thai", "english", "mixed", "unknown"),
            ),
        )
    )
    if not ordered:
        return FieldResult.missing([])

    complete_candidates = [
        candidate
        for candidate in ordered
        if isinstance(candidate.value, dict)
        and candidate.value.get("name")
        and candidate.value.get("student_id")
    ]
    candidates_for_values = complete_candidates or list(ordered)
    excluded_incomplete = tuple(
        candidate for candidate in ordered if candidate not in candidates_for_values
    )
    groups: dict[str, list[FieldCandidate]] = {}
    group_order: list[str] = []
    for candidate in candidates_for_values:
        value = candidate.value
        if not isinstance(value, dict):
            continue
        student_id = value.get("student_id")
        name = value.get("name")
        key = (
            f"id:{compact_spaces(str(student_id)).casefold()}"
            if student_id
            else f"name:{compact_spaces(str(name)).casefold()}"
        )
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(candidate)

    selected_values: list[dict[str, str | None]] = []
    alternatives: list[FieldCandidate] = list(excluded_incomplete)
    warnings: list[str] = []
    selected_candidates: list[FieldCandidate] = []
    if excluded_incomplete:
        warnings.append("unpaired_student_candidate_ignored")
    for key in group_order:
        group = groups[key]
        selected = group[0]
        selected_candidates.append(selected)
        value = dict(selected.value)
        selected_values.append(
            {
                "name": value.get("name"),
                "student_id": value.get("student_id"),
            }
        )
        names = {
            compact_spaces(str(candidate.value.get("name"))).casefold()
            for candidate in group
            if isinstance(candidate.value, dict) and candidate.value.get("name")
        }
        if len(names) > 1:
            warnings.append("conflicting_student_name_candidates")
            alternatives.extend(group[1:])
        if value.get("name") is None or value.get("student_id") is None:
            warnings.append("incomplete_student_candidate")
        if selected.confidence < config.minimum_review_confidence:
            warnings.append("low_confidence_students")

    return FieldResult(
        value=selected_values,
        confidence=min(candidate.confidence for candidate in selected_candidates),
        source_pages=tuple(
            dict.fromkeys(candidate.source_page for candidate in selected_candidates)
        ),
        source_languages=tuple(
            dict.fromkeys(candidate.source_language for candidate in selected_candidates)
        ),
        method="student_id_grouping_and_proximity",
        evidence=tuple(
            dict.fromkeys(
                item for candidate in selected_candidates for item in candidate.evidence
            )
        ),
        candidates=ordered,
        alternatives=tuple(alternatives),
        warnings=tuple(dict.fromkeys(warnings)),
    )
