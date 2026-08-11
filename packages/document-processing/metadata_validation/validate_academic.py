"""Academic-year and academic-organization validation."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .comparison import canonical_text
from .config import ValidationConfig
from .models import FieldValidationResult, ReasonSeverity
from .reference_data import ValidationReferenceData
from .validation_utils import (
    candidate_values,
    common_signal_reasons,
    make_field_result,
    make_reason,
    scalar_conflict_reasons,
)


_YEAR_RE = re.compile(
    r"^(?:(พ\.?\s*ศ\.?|ค\.?\s*ศ\.?|BE|CE)\s*)?(\d{4})(?:\s*(BE|CE))?$",
    re.IGNORECASE,
)
_ACADEMIC_LABELS = (
    "degree",
    "department",
    "faculty",
    "academic year",
    "ปริญญา",
    "ภาควิชา",
    "คณะ",
    "ปีการศึกษา",
)


def normalize_academic_year_candidate(
    value: Any,
    config: ValidationConfig,
) -> dict[str, Any] | None:
    original = "" if value is None else str(value).strip()
    match = _YEAR_RE.fullmatch(original)
    if match is None:
        return None
    prefix, digits, suffix = match.groups()
    year = int(digits)
    marker = canonical_text(prefix or suffix).replace(".", "").replace(" ", "")
    if marker in {"พศ", "be"}:
        calendar = "BE"
    elif marker in {"คศ", "ce"}:
        calendar = "CE"
    elif config.minimum_be_year <= year <= config.maximum_be_year:
        calendar = "BE"
    elif config.minimum_ce_year <= year <= config.maximum_ce_year:
        calendar = "CE"
    else:
        return None
    equivalent_ce = year - config.buddhist_era_offset if calendar == "BE" else year
    if not config.minimum_ce_year <= equivalent_ce <= config.maximum_ce_year:
        return None
    return {
        "original": original,
        "calendar": calendar,
        "year": year,
        "equivalent_ce": equivalent_ce,
    }


def validate_academic_year(
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> FieldValidationResult:
    reasons = common_signal_reasons("academic_year", field, config)
    normalized = normalize_academic_year_candidate(value, config)
    details: dict[str, Any] = {
        "candidate_conflicts_received": 0,
        "candidate_conflicts_resolved": 0,
        "candidate_conflicts_unresolved": 0,
        "semantic_equivalence_resolutions": 0,
    }
    if value is None or not str(value).strip():
        reasons.append(
            make_reason(
                "missing_required_field",
                ReasonSeverity.WARNING,
                "Academic year is required but missing.",
                details={"field": "academic_year"},
            )
        )
    elif normalized is None:
        reasons.append(
            make_reason(
                "invalid_academic_year",
                ReasonSeverity.ERROR,
                "Academic year is malformed or outside configured BE/CE ranges.",
                details={"value": value},
            )
        )
    else:
        details["normalized_comparable"] = normalized

    warnings = [str(item) for item in field.get("warnings", [])]
    conflict_received = any(
        warning == "candidate_conflict" or warning.startswith("conflicting_academic_year")
        for warning in warnings
    )
    if conflict_received:
        details["candidate_conflicts_received"] = 1
        normalized_candidates = [
            item
            for item in (
                normalize_academic_year_candidate(candidate, config)
                for candidate in candidate_values(field)
            )
            if item is not None
        ]
        comparable = {item["equivalent_ce"] for item in normalized_candidates}
        if normalized_candidates and len(comparable) == 1:
            details["candidate_conflicts_resolved"] = 1
            details["semantic_equivalence_resolutions"] = 1
            reasons.append(
                make_reason(
                    "academic_year_semantic_equivalent",
                    ReasonSeverity.INFO,
                    "Academic-year candidates are equivalent after "
                    "deterministic BE/CE conversion.",
                    details={"candidates": normalized_candidates},
                )
            )
        else:
            details["candidate_conflicts_unresolved"] = 1
            reasons.append(
                make_reason(
                    "academic_year_conflict",
                    ReasonSeverity.WARNING,
                    "Academic-year candidates represent different calendar years.",
                    details={"candidates": normalized_candidates},
                )
            )
    return make_field_result(
        "academic_year",
        value,
        field,
        config,
        reasons,
        details=details,
    )


def validate_academic_field(
    field_name: str,
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
    reference_data: ValidationReferenceData | None,
) -> FieldValidationResult:
    reasons = common_signal_reasons(field_name, field, config)
    conflict_reasons, details = scalar_conflict_reasons(field_name, field)
    reasons.extend(conflict_reasons)
    text = "" if value is None else str(value).strip()
    if not text:
        reasons.append(
            make_reason(
                "missing_required_field",
                ReasonSeverity.WARNING,
                f"{field_name} is required but missing.",
                details={"field": field_name},
            )
        )
    elif len(text) > config.maximum_academic_field_characters:
        reasons.append(
            make_reason(
                f"invalid_{field_name}_length",
                ReasonSeverity.ERROR,
                f"{field_name} exceeds the configured maximum length.",
                details={"length": len(text)},
            )
        )
    elif any(canonical_text(label) == canonical_text(text) for label in _ACADEMIC_LABELS):
        reasons.append(
            make_reason(
                "label_artifact",
                ReasonSeverity.ERROR,
                f"{field_name} contains only a structural label.",
                details={"field": field_name},
            )
        )

    collection = {
        "degree": "degrees",
        "faculty": "faculties",
    }.get(field_name)
    reference_check = "not_applicable"
    if field_name == "department":
        collection = "departments"
    if collection:
        if reference_data is None:
            reference_check = "skipped_unavailable"
            if field_name in config.reference_required_fields:
                reasons.append(
                    make_reason(
                        "reference_data_unavailable",
                        ReasonSeverity.WARNING,
                        "Required reference lookup could not be performed.",
                        details={"field": field_name},
                    )
                )
        elif text:
            reference_check = "performed"
            found = (
                reference_data.department(text) is not None
                if field_name == "department"
                else reference_data.contains(collection, text)
            )
            if not found:
                severity = (
                    ReasonSeverity.ERROR
                    if config.unknown_reference_value_status == "INVALID"
                    else ReasonSeverity.WARNING
                )
                reasons.append(
                    make_reason(
                        f"{field_name}_not_in_reference_data",
                        severity,
                        f"{field_name} was not found in supplied reference data.",
                    )
                )
    return make_field_result(
        field_name,
        value,
        field,
        config,
        reasons,
        reference_check=reference_check,
        details=details,
    )
