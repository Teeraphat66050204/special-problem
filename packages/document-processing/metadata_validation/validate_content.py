"""Title, abstract, and keyword validation without re-extraction."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from .comparison import canonical_text
from .config import ValidationConfig
from .models import FieldStatus, FieldValidationResult, ReasonSeverity
from .validation_utils import (
    common_signal_reasons,
    make_field_result,
    make_reason,
    scalar_conflict_reasons,
)


_TITLE_HEADINGS = {"abstract", "บทคัดย่อ", "title", "หัวข้อ", "ชื่อเรื่อง"}
_TITLE_CONTAMINATION_RE = re.compile(
    r"(?:student(?:\s+id|\s+name)?|advisor|รหัสนักศึกษา|ชื่อนักศึกษา|อาจารย์ที่ปรึกษา)\s*[:：]",
    re.IGNORECASE,
)
_ABSTRACT_HEADING_RE = re.compile(r"^(?:abstract|บทคัดย่อ)\s*[:：]?$", re.IGNORECASE)
_ABSTRACT_FRONT_MATTER_RE = re.compile(
    r"^(?:title|student(?:\s+id|\s+name)?|advisor|หัวข้อ|รหัสนักศึกษา|อาจารย์ที่ปรึกษา)\s*[:：]",
    re.IGNORECASE,
)
_ABSTRACT_KEYWORD_TAIL_RE = re.compile(
    r"(?:keywords?|คำสำคัญ|คำสำคัญ)\s*[:：]\s*\S+\s*$",
    re.IGNORECASE,
)
_FOOTER_KEYWORD_RE = re.compile(
    r"^(?:page\s+\d+|หน้า\s*\d+|\d+\s*/\s*\d+)$",
    re.IGNORECASE,
)


def validate_title(
    field_name: str,
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> FieldValidationResult:
    reasons = common_signal_reasons(field_name, field, config)
    conflict_reasons, details = scalar_conflict_reasons(field_name, field)
    reasons.extend(conflict_reasons)
    text = "" if value is None else str(value).strip()
    if not text:
        reasons.append(
            make_reason(
                "missing_value",
                ReasonSeverity.INFO,
                "This language-specific title was not extracted.",
                details={"field": field_name},
            )
        )
    elif canonical_text(text) in _TITLE_HEADINGS:
        reasons.append(
            make_reason(
                "heading_only_title",
                ReasonSeverity.ERROR,
                "Title contains only a structural heading.",
            )
        )
    elif len(text) < config.minimum_title_characters:
        reasons.append(
            make_reason(
                "title_too_short",
                ReasonSeverity.ERROR,
                "Title is shorter than the configured minimum.",
                details={"length": len(text)},
            )
        )
    elif len(text) > config.maximum_title_characters:
        reasons.append(
            make_reason(
                "title_too_long",
                ReasonSeverity.WARNING,
                "Title exceeds the configured review threshold.",
                details={"length": len(text)},
            )
        )
    if text and _TITLE_CONTAMINATION_RE.search(text):
        reasons.append(
            make_reason(
                "title_label_contamination",
                ReasonSeverity.ERROR,
                "Title contains a student or advisor field label.",
            )
        )
    return make_field_result(
        field_name,
        value,
        field,
        config,
        reasons,
        details=details,
    )


def validate_abstract(
    field_name: str,
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> FieldValidationResult:
    reasons = common_signal_reasons(field_name, field, config)
    conflict_reasons, details = scalar_conflict_reasons(field_name, field)
    reasons.extend(conflict_reasons)
    text = "" if value is None else str(value).strip()
    if not text:
        reasons.append(
            make_reason(
                "missing_value",
                ReasonSeverity.INFO,
                "This language-specific abstract was not extracted.",
                details={"field": field_name},
            )
        )
    elif _ABSTRACT_HEADING_RE.fullmatch(text):
        reasons.append(
            make_reason(
                "heading_only_abstract",
                ReasonSeverity.ERROR,
                "Abstract contains only its heading.",
            )
        )
    elif len(text) < config.minimum_abstract_characters:
        reasons.append(
            make_reason(
                "abstract_too_short",
                ReasonSeverity.WARNING,
                "Abstract is shorter than the configured review threshold.",
                details={"length": len(text)},
            )
        )
    elif len(text) > config.maximum_abstract_characters:
        reasons.append(
            make_reason(
                "abstract_too_long",
                ReasonSeverity.WARNING,
                "Abstract exceeds the configured review threshold.",
                details={"length": len(text)},
            )
        )
    if text and _ABSTRACT_FRONT_MATTER_RE.search(text):
        reasons.append(
            make_reason(
                "abstract_front_matter_contamination",
                ReasonSeverity.ERROR,
                "Abstract begins with a front-matter field label.",
            )
        )
    if text and _ABSTRACT_KEYWORD_TAIL_RE.search(text):
        reasons.append(
            make_reason(
                "abstract_keywords_contamination",
                ReasonSeverity.WARNING,
                "Abstract appears to retain a trailing keyword section.",
            )
        )
    return make_field_result(
        field_name,
        value,
        field,
        config,
        reasons,
        details=details,
    )


def validate_keywords(
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> FieldValidationResult:
    reasons = common_signal_reasons("keywords", field, config)
    values = value if isinstance(value, list) else []
    if value is not None and not isinstance(value, list):
        reasons.append(
            make_reason(
                "invalid_keywords_structure",
                ReasonSeverity.ERROR,
                "Keywords must be represented as a list.",
            )
        )
    if not values and config.keywords_missing_requires_review:
        reasons.append(
            make_reason(
                "missing_optional_keywords",
                ReasonSeverity.WARNING,
                "Keywords are absent under the configured review policy.",
            )
        )
    empty_items = sum(not str(item).strip() for item in values)
    if empty_items:
        reasons.append(
            make_reason(
                "empty_keyword_item",
                ReasonSeverity.ERROR,
                "Keyword list contains empty items.",
                details={"count": empty_items},
            )
        )
    canonical_items = [canonical_text(item) for item in values if str(item).strip()]
    duplicates = [item for item, count in Counter(canonical_items).items() if count > 1]
    if duplicates:
        reasons.append(
            make_reason(
                "duplicate_keyword",
                ReasonSeverity.WARNING,
                "Keyword list contains duplicate items.",
                details={"duplicate_count": len(duplicates)},
            )
        )
    suspicious = [item for item in values if _FOOTER_KEYWORD_RE.fullmatch(str(item).strip())]
    if suspicious:
        reasons.append(
            make_reason(
                "suspicious_keyword_item",
                ReasonSeverity.WARNING,
                "Keyword list contains a page/footer-like item.",
                details={"count": len(suspicious)},
            )
        )
    if len(values) > config.maximum_keyword_items:
        reasons.append(
            make_reason(
                "excessive_keyword_count",
                ReasonSeverity.WARNING,
                "Keyword count exceeds the configured review threshold.",
                details={"count": len(values)},
            )
        )
    return make_field_result(
        "keywords",
        values,
        field,
        config,
        reasons,
        details={"keyword_count": len(values)},
        missing_status=FieldStatus.VALID,
    )
