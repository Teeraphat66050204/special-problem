"""Shared field-result construction and extraction-signal helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .comparison import canonical_text, nonempty
from .config import ValidationConfig
from .models import (
    FieldStatus,
    FieldValidationResult,
    ReasonSeverity,
    ValidationReason,
)


def make_reason(
    code: str,
    severity: ReasonSeverity,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
    evidence: Iterable[str] = (),
) -> ValidationReason:
    return ValidationReason(
        code=code,
        severity=severity,
        message=message,
        details=dict(details or {}),
        evidence=tuple(evidence),
    )


def field_mapping(fields: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = fields.get(name, {})
    return value if isinstance(value, Mapping) else {}


def source_pages(field: Mapping[str, Any]) -> tuple[int, ...]:
    raw = field.get("source_pages", [])
    if isinstance(raw, list):
        return tuple(
            value
            for value in raw
            if isinstance(value, int) and not isinstance(value, bool)
        )
    single = field.get("source_page")
    return (single,) if isinstance(single, int) and not isinstance(single, bool) else ()


def extraction_confidence(field: Mapping[str, Any]) -> float | None:
    value = field.get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 4)
    return None


def extraction_warnings(field: Mapping[str, Any]) -> tuple[str, ...]:
    raw = field.get("warnings", [])
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    return ()


def candidate_values(field: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for collection in ("candidates", "alternatives"):
        raw = field.get(collection, [])
        if not isinstance(raw, list):
            continue
        for candidate in raw:
            if isinstance(candidate, Mapping) and "value" in candidate:
                values.append(deepcopy(candidate["value"]))
    if "value" in field:
        values.insert(0, deepcopy(field.get("value")))
    return values


def common_signal_reasons(
    field_name: str,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> list[ValidationReason]:
    reasons: list[ValidationReason] = []
    confidence = extraction_confidence(field)
    if confidence is not None and confidence < config.minimum_extraction_confidence:
        reasons.append(
            make_reason(
                "low_extraction_confidence",
                ReasonSeverity.WARNING,
                "Extraction confidence is below the configured review threshold.",
                details={
                    "field": field_name,
                    "confidence": confidence,
                    "threshold": config.minimum_extraction_confidence,
                },
            )
        )
    warning_map = {
        "ambiguous_student_pairing": "ambiguous_student_pairing",
        "incomplete_student_candidate": "incomplete_student_candidate",
        "unpaired_student_candidate_ignored": "ambiguous_student_pairing",
        "suspicious_thai_character_spacing": "suspicious_source_text",
        "source_processing_failed": "suspicious_source_text",
    }
    seen: set[str] = set()
    for warning in extraction_warnings(field):
        code = warning_map.get(warning)
        if code is None or code in seen:
            continue
        seen.add(code)
        reasons.append(
            make_reason(
                code,
                ReasonSeverity.WARNING,
                "An extraction or upstream warning can affect this field.",
                details={"field": field_name, "upstream_warning": warning},
            )
        )
    return reasons


def scalar_conflict_reasons(
    field_name: str,
    field: Mapping[str, Any],
) -> tuple[list[ValidationReason], dict[str, int]]:
    warnings = extraction_warnings(field)
    conflict_received = any(
        warning == "candidate_conflict" or warning.startswith("conflicting_")
        for warning in warnings
    )
    values = [value for value in candidate_values(field) if nonempty(value)]
    distinct = {canonical_text(value) for value in values}
    stats = {
        "candidate_conflicts_received": int(conflict_received),
        "candidate_conflicts_resolved": 0,
        "candidate_conflicts_unresolved": 0,
        "semantic_equivalence_resolutions": 0,
    }
    if not conflict_received:
        return [], stats
    if len(distinct) <= 1:
        stats["candidate_conflicts_resolved"] = 1
        return [
            make_reason(
                "candidate_conflict_resolved",
                ReasonSeverity.INFO,
                "Candidate differences are limited to conservative formatting "
                "or case normalization.",
                details={"field": field_name, "resolution": "whitespace_or_case"},
            )
        ], stats
    stats["candidate_conflicts_unresolved"] = 1
    return [
        make_reason(
            "candidate_conflict",
            ReasonSeverity.WARNING,
            "Candidate values remain semantically different after conservative comparison.",
            details={"field": field_name, "distinct_candidate_count": len(distinct)},
        )
    ], stats


def status_from_reasons(
    value: Any,
    reasons: Iterable[ValidationReason],
    *,
    missing_status: FieldStatus = FieldStatus.MISSING,
) -> FieldStatus:
    if not nonempty(value):
        return missing_status
    reason_list = list(reasons)
    if any(reason.severity is ReasonSeverity.ERROR for reason in reason_list):
        return FieldStatus.INVALID
    if any(reason.severity is ReasonSeverity.WARNING for reason in reason_list):
        return FieldStatus.REVIEW_REQUIRED
    return FieldStatus.VALID


def make_field_result(
    field_name: str,
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
    reasons: Iterable[ValidationReason],
    *,
    reference_check: str = "not_applicable",
    details: Mapping[str, Any] | None = None,
    missing_status: FieldStatus = FieldStatus.MISSING,
) -> FieldValidationResult:
    reason_tuple = tuple(reasons)
    return FieldValidationResult(
        value=deepcopy(value),
        status=status_from_reasons(value, reason_tuple, missing_status=missing_status),
        criticality=config.criticality_for(field_name),
        reasons=reason_tuple,
        source_pages=source_pages(field),
        extraction_confidence=extraction_confidence(field),
        reference_check=reference_check,
        details=dict(details or {}),
    )
