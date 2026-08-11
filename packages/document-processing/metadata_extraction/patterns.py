"""Central label and boundary patterns for Thai and English front matter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "title": (
        r"หัวข้อ(?:(?:โครงงาน(?:พิเศษ)?|ปัญหาพิเศษ|สหกิจศึกษา|"
        r"ปริญญานิพนธ์|สารนิพนธ์)(?:\s*/\s*)?)+",
        r"ชื่อ(?:เรื่อง|โครงงาน)",
        r"(?:project\s+)?title\b",
    ),
    "student_name": (
        r"ชื่อนักศึกษา",
        r"นักศึกษา",
        r"ผู้จัดท[ำํา]",
        r"students?\s+names?\b",
        r"students?(?!\s*(?:id|number))\b",
    ),
    "student_id": (
        r"รหัส(?:นักศึกษา)?",
        r"student\s*(?:id|number)\b",
    ),
    "degree": (
        r"ปริญญา",
        r"degree\b",
    ),
    "department": (
        r"(?:สาขาวิชา|ภาควิชา|หลักสูตร)",
        r"(?:department|program)\b",
    ),
    "faculty": (
        r"คณะ",
        r"(?:faculty|school)\b",
    ),
    "academic_year": (
        r"ปีการศึกษา",
        r"academic\s+year\b",
    ),
    "co_advisor": (
        r"(?:อาจารย์)?ที่ปรึกษาร่วม",
        r"co[\s-]*advis(?:o|e)rs?\b",
    ),
    "advisor": (
        r"อาจารย์ที่ปรึกษา(?!ร่วม)",
        r"(?:project\s+)?advis(?:o|e)rs?\b",
    ),
    "abstract": (
        r"บทคัดย่อ(?:ภาษาไทย)?",
        r"(?:english\s+)?abstract\b",
    ),
    "keywords": (
        r"คำ\s*สำคัญ",
        r"key\s*words?\b",
    ),
}

STRONG_BOUNDARY_FIELDS = (
    "title",
    "student_name",
    "student_id",
    "degree",
    "department",
    "faculty",
    "academic_year",
    "co_advisor",
    "advisor",
    "abstract",
    "keywords",
)

THAI_CHARACTER_RE = re.compile(r"[\u0e00-\u0e7f]")
LATIN_CHARACTER_RE = re.compile(r"[A-Za-z]")
KEYWORD_SEPARATOR_RE = re.compile(r"\s*[,;，、؛]\s*")
PAGE_MARKER_RE = re.compile(r"^(?:\d{1,3}|[ก-ฮ]|[ivxlcdm]{1,8})$", re.IGNORECASE)
INLINE_STUDENT_SECTION_RE = re.compile(
    r"\s+students?\s+(?=(?:mr\.?|miss|mrs\.?|ms\.?|mister)\b)"
    r"|\s+ชื่อนักศึกษา\s*[:：]?\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LabelMatch:
    field: str
    label: str
    value: str


def _compiled_label(field: str) -> re.Pattern[str]:
    variants = "|".join(f"(?:{pattern})" for pattern in LABEL_PATTERNS[field])
    return re.compile(
        rf"^\s*(?P<label>{variants})\s*(?:[:：]\s*)?(?P<value>.*)$",
        re.IGNORECASE,
    )


COMPILED_LABELS = {
    field: _compiled_label(field) for field in STRONG_BOUNDARY_FIELDS
}


def match_label(line: str, fields: Iterable[str] = STRONG_BOUNDARY_FIELDS) -> LabelMatch | None:
    """Return a conservative start-of-line label match."""
    for field in fields:
        match = COMPILED_LABELS[field].match(line)
        if match is not None:
            return LabelMatch(
                field=field,
                label=match.group("label").strip(),
                value=match.group("value").strip(),
            )
    return None


def is_abstract_heading(line: str, language: str | None = None) -> bool:
    match = match_label(line, ("abstract",))
    if match is None or match.value:
        return False
    if language == "thai":
        return THAI_CHARACTER_RE.search(match.label) is not None
    if language == "english":
        return LATIN_CHARACTER_RE.search(match.label) is not None
    return True


def truncate_at_inline_student_section(value: str) -> str:
    """Stop flattened titles before a structurally clear student section."""
    match = INLINE_STUDENT_SECTION_RE.search(value)
    return value[: match.start()].rstrip() if match is not None else value
