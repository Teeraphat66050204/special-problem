"""Advisor and co-advisor extraction with bounded label context."""

from __future__ import annotations

import re
from typing import Iterable

from .line_utils import collect_labeled_value, is_reasonable_person_name
from .models import ExtractionConfig, FieldCandidate, PageContext
from .patterns import STRONG_BOUNDARY_FIELDS, match_label
from .resolution import make_candidate


CO_ADVISOR_SEPARATOR_RE = re.compile(r"\s*;\s*")


def extract_advisor_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> tuple[list[FieldCandidate], list[FieldCandidate]]:
    advisors: list[FieldCandidate] = []
    co_advisors: list[FieldCandidate] = []
    for page in pages:
        for line_index, line in enumerate(page.lines):
            label = match_label(line, ("co_advisor", "advisor"))
            if label is None:
                continue
            maximum_lines = 3 if label.field == "co_advisor" else 1
            if label.value and label.field != "co_advisor":
                value = label.value
                indexes = (line_index,)
                evidence = (line.strip(),)
                same_line = True
            else:
                value, indexes, evidence, same_line = collect_labeled_value(
                    page.lines,
                    line_index,
                    label,
                    maximum_continuation_lines=maximum_lines,
                    stop_fields=STRONG_BOUNDARY_FIELDS,
                )
            if not value:
                continue
            confidence = (
                config.same_line_label_confidence
                if same_line
                else config.next_line_label_confidence
            )
            if label.field == "advisor":
                if is_reasonable_person_name(value):
                    advisors.append(
                        make_candidate(
                            page,
                            value=value,
                            confidence=confidence,
                            line_indexes=indexes or (line_index,),
                            method="advisor_label",
                            evidence=evidence,
                            config=config,
                        )
                    )
                continue

            values = [item for item in CO_ADVISOR_SEPARATOR_RE.split(value) if item]
            if not same_line and len(indexes) > 1:
                values = [page.lines[index].strip() for index in indexes]
            for value_index, person in enumerate(values):
                if not is_reasonable_person_name(person):
                    continue
                source_index = (
                    indexes[min(value_index, len(indexes) - 1)]
                    if indexes
                    else line_index
                )
                co_advisors.append(
                    make_candidate(
                        page,
                        value=person,
                        confidence=confidence,
                        line_indexes=(source_index,),
                        method="co_advisor_label",
                        evidence=(line.strip(), person),
                        config=config,
                    )
                )
    return advisors, co_advisors
