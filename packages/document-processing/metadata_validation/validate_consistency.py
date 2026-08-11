"""Cross-field consistency checks that never rewrite extracted values."""

from __future__ import annotations

from dataclasses import replace

from .comparison import equivalent_text
from .config import ValidationConfig
from .models import FieldStatus, FieldValidationResult, ReasonSeverity
from .reference_data import ValidationReferenceData
from .validation_utils import make_reason, status_from_reasons


def validate_department_faculty_consistency(
    department: FieldValidationResult,
    faculty: FieldValidationResult,
    config: ValidationConfig,
    reference_data: ValidationReferenceData | None,
) -> tuple[FieldValidationResult, FieldValidationResult, int]:
    if reference_data is None or not department.value or not faculty.value:
        return department, faculty, 0
    department_reference = reference_data.department(department.value)
    if department_reference is None or not department_reference.faculty:
        return department, faculty, 0
    if equivalent_text(department_reference.faculty, faculty.value):
        reason = make_reason(
            "department_faculty_match",
            ReasonSeverity.INFO,
            "Department/faculty relation matches supplied reference data.",
        )
        return (
            replace(department, reasons=(*department.reasons, reason)),
            replace(faculty, reasons=(*faculty.reasons, reason)),
            1,
        )
    severity = (
        ReasonSeverity.ERROR
        if config.relation_mismatch_status == "INVALID"
        else ReasonSeverity.WARNING
    )
    reason = make_reason(
        "department_faculty_mismatch",
        severity,
        "Department/faculty relation conflicts with supplied reference data.",
        details={"expected_faculty": department_reference.faculty},
    )
    department_reasons = (*department.reasons, reason)
    faculty_reasons = (*faculty.reasons, reason)
    return (
        replace(
            department,
            reasons=department_reasons,
            status=status_from_reasons(department.value, department_reasons),
        ),
        replace(
            faculty,
            reasons=faculty_reasons,
            status=status_from_reasons(faculty.value, faculty_reasons),
        ),
        1,
    )
