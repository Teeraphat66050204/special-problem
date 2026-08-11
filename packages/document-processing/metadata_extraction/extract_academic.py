"""Label-based extraction for degree, department, faculty, and academic year."""

from __future__ import annotations

import re
from typing import Iterable

from .line_utils import collect_labeled_value
from .models import ExtractionConfig, FieldCandidate, PageContext
from .patterns import STRONG_BOUNDARY_FIELDS, match_label
from .resolution import make_candidate


ACADEMIC_FIELDS = ("degree", "department", "faculty", "academic_year")
ACADEMIC_YEAR_RE = re.compile(r"(?<![0-9๐-๙])[0-9๐-๙]{4}(?![0-9๐-๙])")


def extract_academic_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> dict[str, list[FieldCandidate]]:
    results = {field: [] for field in ACADEMIC_FIELDS}
    for page in pages:
        for line_index, line in enumerate(page.lines):
            label = match_label(line, ACADEMIC_FIELDS)
            if label is None:
                continue
            if label.value:
                value = label.value
                indexes = (line_index,)
                evidence = (line.strip(),)
                same_line = True
            else:
                value, indexes, evidence, same_line = collect_labeled_value(
                    page.lines,
                    line_index,
                    label,
                    maximum_continuation_lines=config.maximum_scalar_continuation_lines,
                    stop_fields=STRONG_BOUNDARY_FIELDS,
                )
            if label.field == "academic_year":
                year_match = ACADEMIC_YEAR_RE.search(value)
                if year_match is None:
                    continue
                value = year_match.group(0)
            if not value:
                continue
            confidence = (
                config.same_line_label_confidence
                if same_line
                else config.next_line_label_confidence
            )
            results[label.field].append(
                make_candidate(
                    page,
                    value=value,
                    confidence=confidence,
                    line_indexes=indexes or (line_index,),
                    method=f"{label.field}_label_{'same_line' if same_line else 'next_line'}",
                    evidence=evidence,
                    config=config,
                )
            )
    return results
