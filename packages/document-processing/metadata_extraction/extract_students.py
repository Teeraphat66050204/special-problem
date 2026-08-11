"""Deterministic multi-student name/ID extraction and proximity pairing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .line_utils import compact_spaces, is_reasonable_person_name
from .models import ExtractionConfig, FieldCandidate, PageContext
from .patterns import match_label
from .resolution import make_candidate


ID_LABEL_RE = re.compile(
    r"(?:รหัส(?:นักศึกษา)?|student\s*(?:id|number)|student(?=\s*[A-Z]?\d{7,13}))\s*[:：]?\s*",
    re.IGNORECASE,
)
STUDENT_BOUNDARY_FIELDS = (
    "degree",
    "department",
    "faculty",
    "academic_year",
    "co_advisor",
    "advisor",
    "abstract",
    "keywords",
)


@dataclass(frozen=True)
class _NameEvidence:
    name: str
    line_index: int
    evidence: str


def _student_section(lines: tuple[str, ...]) -> tuple[int, int] | None:
    start: int | None = None
    for index, line in enumerate(lines):
        if match_label(line, ("student_name", "student_id")) is not None:
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if match_label(lines[index], STUDENT_BOUNDARY_FIELDS) is not None:
            end = index
            break
    return start, end


def _line_components(
    line: str,
    student_id_re: re.Pattern[str],
) -> tuple[str | None, str | None, bool]:
    label = match_label(line, ("student_name", "student_id"))
    content = label.value if label is not None else line.strip()
    labeled_id = ID_LABEL_RE.search(content)
    student_id: str | None = None
    name_text = content
    has_id_label = labeled_id is not None or (label is not None and label.field == "student_id")
    if labeled_id is not None:
        id_match = student_id_re.search(content, labeled_id.end())
        if id_match is not None:
            student_id = id_match.group(0)
            name_text = content[: labeled_id.start()].strip(" :-–—")
    elif label is not None and label.field == "student_id":
        id_match = student_id_re.search(content)
        if id_match is not None:
            student_id = id_match.group(0)
            name_text = ""
    else:
        id_match = student_id_re.search(content)
        if id_match is not None:
            student_id = id_match.group(0)
            name_text = (content[: id_match.start()] + " " + content[id_match.end() :]).strip()

    name_text = re.sub(
        r"\s+นักศึกษาชั้นปีที่\s*[0-9๐-๙]+\s*$",
        "",
        name_text,
        flags=re.IGNORECASE,
    )
    name = compact_spaces(name_text.strip(" :-–—"))
    if not is_reasonable_person_name(name):
        name = ""
    return name or None, student_id, has_id_label


def extract_student_candidates(
    pages: Iterable[PageContext],
    config: ExtractionConfig,
) -> tuple[list[FieldCandidate], list[str]]:
    student_id_re = re.compile(config.student_id_pattern, re.IGNORECASE)
    candidates: list[FieldCandidate] = []
    warnings: list[str] = []

    for page in pages:
        section = _student_section(page.lines)
        if section is None:
            continue
        start, end = section
        pending_names: list[_NameEvidence] = []
        pending_ids: list[tuple[str, int, str]] = []

        for line_index in range(start, end):
            line = page.lines[line_index].strip()
            if not line:
                continue
            name, student_id, has_id_label = _line_components(line, student_id_re)
            if name is not None and student_id is not None:
                candidates.append(
                    make_candidate(
                        page,
                        value={"name": name, "student_id": student_id},
                        confidence=config.student_direct_pair_confidence,
                        line_indexes=(line_index,),
                        method="student_name_and_id_same_line",
                        evidence=(line,),
                        config=config,
                    )
                )
                continue
            if name is not None:
                pending_names.append(_NameEvidence(name, line_index, line))
            if student_id is not None:
                eligible = [
                    item
                    for item in pending_names
                    if 0 <= line_index - item.line_index <= config.maximum_student_pair_distance
                ]
                if len(eligible) == 1:
                    matched_name = eligible[0]
                    pending_names.remove(matched_name)
                    candidates.append(
                        make_candidate(
                            page,
                            value={"name": matched_name.name, "student_id": student_id},
                            confidence=config.student_proximity_pair_confidence,
                            line_indexes=(matched_name.line_index, line_index),
                            method="student_name_id_line_proximity",
                            evidence=(matched_name.evidence, line),
                            config=config,
                        )
                    )
                else:
                    pending_ids.append((student_id, line_index, line))
                    if len(eligible) > 1:
                        warnings.append("ambiguous_student_pairing")
                    elif not has_id_label:
                        warnings.append("unlabeled_student_id_candidate")

        if pending_names and pending_ids:
            warnings.append("ambiguous_student_pairing")
        for pending in pending_names:
            candidates.append(
                make_candidate(
                    page,
                    value={"name": pending.name, "student_id": None},
                    confidence=0.55,
                    line_indexes=(pending.line_index,),
                    method="unpaired_student_name",
                    evidence=(pending.evidence,),
                    config=config,
                )
            )
        for student_id, line_index, evidence in pending_ids:
            candidates.append(
                make_candidate(
                    page,
                    value={"name": None, "student_id": student_id},
                    confidence=0.55,
                    line_indexes=(line_index,),
                    method="unpaired_student_id",
                    evidence=(evidence,),
                    config=config,
                )
            )

    return candidates, list(dict.fromkeys(warnings))
