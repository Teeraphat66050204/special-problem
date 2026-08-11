"""Reusable structured result models for deterministic metadata validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class FieldStatus(str, Enum):
    VALID = "VALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVALID = "INVALID"
    MISSING = "MISSING"


class DocumentStatus(str, Enum):
    VALID = "VALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVALID = "INVALID"
    FAILED = "FAILED"


class ReasonSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationReason:
    code: str
    severity: ReasonSeverity
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = deepcopy(dict(self.details))
        if self.evidence:
            result["evidence"] = list(self.evidence)
        return result


@dataclass(frozen=True)
class FieldValidationResult:
    value: Any
    status: FieldStatus
    criticality: str
    reasons: tuple[ValidationReason, ...] = ()
    source_pages: tuple[int, ...] = ()
    extraction_confidence: float | None = None
    reference_check: str = "not_applicable"
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": deepcopy(self.value),
            "status": self.status.value,
            "criticality": self.criticality,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "source_page": self.source_pages[0] if self.source_pages else None,
            "source_pages": list(self.source_pages),
            "extraction_confidence": self.extraction_confidence,
            "reference_check": self.reference_check,
            "details": deepcopy(dict(self.details)),
        }


@dataclass(frozen=True)
class ValidationResult:
    metadata: Mapping[str, Any]
    fields: Mapping[str, FieldValidationResult]
    document_status: DocumentStatus
    requires_manual_review: bool
    warnings: tuple[ValidationReason, ...]
    summary: Mapping[str, Any]
    stats: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": deepcopy(dict(self.metadata)),
            "validation": {
                "document_status": self.document_status.value,
                "requires_manual_review": self.requires_manual_review,
                "fields": {
                    name: result.to_dict() for name, result in self.fields.items()
                },
                "warnings": [warning.to_dict() for warning in self.warnings],
                "summary": deepcopy(dict(self.summary)),
                "stats": deepcopy(dict(self.stats)),
            },
        }
