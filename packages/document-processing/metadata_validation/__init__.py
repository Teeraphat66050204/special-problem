"""Deterministic validation for structured Metadata Extraction results."""

from .config import DEFAULT_VALIDATION_CONFIG, ValidationConfig
from .models import (
    DocumentStatus,
    FieldStatus,
    FieldValidationResult,
    ReasonSeverity,
    ValidationReason,
    ValidationResult,
)
from .reference_data import DepartmentReference, ValidationReferenceData
from .validate_academic import normalize_academic_year_candidate
from .validate_metadata import validate_metadata

__all__ = [
    "DEFAULT_VALIDATION_CONFIG",
    "DepartmentReference",
    "DocumentStatus",
    "FieldStatus",
    "FieldValidationResult",
    "ReasonSeverity",
    "ValidationConfig",
    "ValidationReason",
    "ValidationReferenceData",
    "ValidationResult",
    "normalize_academic_year_candidate",
    "validate_metadata",
]
