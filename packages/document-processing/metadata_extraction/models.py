"""Structured models and deterministic configuration for metadata extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


SCALAR_FIELDS = (
    "title_th",
    "title_en",
    "degree",
    "department",
    "faculty",
    "academic_year",
    "advisor",
    "abstract_th",
    "abstract_en",
)
LIST_FIELDS = ("students", "co_advisors", "keywords")
METADATA_FIELDS = (*SCALAR_FIELDS, *LIST_FIELDS)


@dataclass(frozen=True)
class ExtractionConfig:
    """Explainable scores and structural limits used by every extractor."""

    student_id_pattern: str = r"(?<![A-Za-z0-9])[A-Z]?\d{7,13}(?!\d)"
    same_line_label_confidence: float = 0.97
    next_line_label_confidence: float = 0.90
    inferred_title_confidence: float = 0.68
    abstract_boundary_confidence: float = 0.96
    student_direct_pair_confidence: float = 0.97
    student_proximity_pair_confidence: float = 0.86
    minimum_review_confidence: float = 0.70
    suspicious_source_penalty: float = 0.20
    maximum_title_lines: int = 6
    maximum_scalar_continuation_lines: int = 2
    maximum_student_pair_distance: int = 2
    minimum_title_characters: int = 4
    maximum_title_characters: int = 500

    def __post_init__(self) -> None:
        confidence_values = (
            self.same_line_label_confidence,
            self.next_line_label_confidence,
            self.inferred_title_confidence,
            self.abstract_boundary_confidence,
            self.student_direct_pair_confidence,
            self.student_proximity_pair_confidence,
            self.minimum_review_confidence,
            self.suspicious_source_penalty,
        )
        if any(value < 0.0 or value > 1.0 for value in confidence_values):
            raise ValueError("confidence values and penalties must be between 0 and 1")
        integer_limits = (
            self.maximum_title_lines,
            self.maximum_scalar_continuation_lines,
            self.maximum_student_pair_distance,
            self.minimum_title_characters,
            self.maximum_title_characters,
        )
        if any(isinstance(value, bool) or value <= 0 for value in integer_limits):
            raise ValueError("extraction structural limits must be positive integers")
        if self.minimum_title_characters > self.maximum_title_characters:
            raise ValueError("minimum title length cannot exceed maximum title length")


DEFAULT_EXTRACTION_CONFIG = ExtractionConfig()


@dataclass(frozen=True)
class PageContext:
    page_number: int
    language: str
    normalized_text: str
    lines: tuple[str, ...]
    upstream_warnings: tuple[str, ...] = ()
    upstream_requires_review: bool = False


@dataclass(frozen=True)
class FieldCandidate:
    """One traceable value proposed by one structural extraction rule."""

    value: Any
    confidence: float
    source_page: int
    source_language: str
    source_line_indexes: tuple[int, ...]
    method: str
    evidence: tuple[str, ...]

    def with_confidence(self, confidence: float) -> "FieldCandidate":
        return FieldCandidate(
            value=self.value,
            confidence=max(0.0, min(1.0, confidence)),
            source_page=self.source_page,
            source_language=self.source_language,
            source_line_indexes=self.source_line_indexes,
            method=self.method,
            evidence=self.evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source_page": self.source_page,
            "source_language": self.source_language,
            "source_line_indexes": list(self.source_line_indexes),
            "method": self.method,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class FieldResult:
    value: Any
    confidence: float
    source_pages: tuple[int, ...]
    source_languages: tuple[str, ...]
    method: str
    evidence: tuple[str, ...]
    candidates: tuple[FieldCandidate, ...] = ()
    alternatives: tuple[FieldCandidate, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def missing(cls, value: Any = None) -> "FieldResult":
        return cls(
            value=value,
            confidence=0.0,
            source_pages=(),
            source_languages=(),
            method="not_found",
            evidence=(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source_page": self.source_pages[0] if self.source_pages else None,
            "source_pages": list(self.source_pages),
            "source_language": (
                self.source_languages[0] if self.source_languages else None
            ),
            "source_languages": list(self.source_languages),
            "method": self.method,
            "evidence": list(self.evidence),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "alternatives": [candidate.to_dict() for candidate in self.alternatives],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ExtractionResult:
    metadata: Mapping[str, Any]
    fields: Mapping[str, FieldResult]
    warnings: tuple[str, ...]
    extraction_status: str
    requires_manual_review: bool
    stats: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "fields": {
                name: result.to_dict() for name, result in self.fields.items()
            },
            "warnings": list(self.warnings),
            "extraction_status": self.extraction_status,
            "requires_manual_review": self.requires_manual_review,
            "stats": dict(self.stats),
        }
