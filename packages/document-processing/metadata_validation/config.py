"""Central policy and structural thresholds for metadata validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


def _default_criticalities() -> dict[str, str]:
    return {
        "title_th": "critical",
        "title_en": "critical",
        "students": "critical",
        "student_id": "critical",
        "degree": "important",
        "department": "important",
        "faculty": "important",
        "academic_year": "critical",
        "advisor": "critical",
        "co_advisors": "optional",
        "abstract_th": "important",
        "abstract_en": "important",
        "keywords": "optional",
    }


@dataclass(frozen=True)
class ValidationConfig:
    """Configurable validation policy; no benchmark-specific values live here."""

    student_id_pattern: str = r"\d{8}"
    minimum_extraction_confidence: float = 0.70
    minimum_title_characters: int = 5
    maximum_title_characters: int = 500
    minimum_abstract_characters: int = 100
    maximum_abstract_characters: int = 50_000
    minimum_person_name_characters: int = 3
    maximum_person_name_characters: int = 200
    maximum_academic_field_characters: int = 250
    maximum_keyword_items: int = 30
    minimum_ce_year: int = 1900
    maximum_ce_year: int = 2200
    minimum_be_year: int = 2400
    maximum_be_year: int = 2800
    buddhist_era_offset: int = 543
    keywords_missing_requires_review: bool = False
    unknown_reference_value_status: str = "REVIEW_REQUIRED"
    relation_mismatch_status: str = "INVALID"
    required_fields: frozenset[str] = frozenset(
        {
            "students",
            "student_id",
            "degree",
            "department",
            "faculty",
            "academic_year",
            "advisor",
        }
    )
    optional_fields: frozenset[str] = frozenset({"co_advisors", "keywords"})
    reference_required_fields: frozenset[str] = frozenset()
    criticalities: Mapping[str, str] = field(default_factory=_default_criticalities)

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_extraction_confidence <= 1.0:
            raise ValueError("minimum_extraction_confidence must be between 0 and 1")
        positive_limits = (
            self.minimum_title_characters,
            self.maximum_title_characters,
            self.minimum_abstract_characters,
            self.maximum_abstract_characters,
            self.minimum_person_name_characters,
            self.maximum_person_name_characters,
            self.maximum_academic_field_characters,
            self.maximum_keyword_items,
        )
        if any(isinstance(value, bool) or value <= 0 for value in positive_limits):
            raise ValueError("validation length and count limits must be positive")
        if self.minimum_title_characters > self.maximum_title_characters:
            raise ValueError("minimum title length cannot exceed maximum title length")
        if self.minimum_abstract_characters > self.maximum_abstract_characters:
            raise ValueError("minimum abstract length cannot exceed maximum abstract length")
        allowed_statuses = {"REVIEW_REQUIRED", "INVALID"}
        if self.unknown_reference_value_status not in allowed_statuses:
            raise ValueError("unknown_reference_value_status must request review or invalidate")
        if self.relation_mismatch_status not in allowed_statuses:
            raise ValueError("relation_mismatch_status must request review or invalidate")
        allowed_criticalities = {"critical", "important", "optional"}
        if any(value not in allowed_criticalities for value in self.criticalities.values()):
            raise ValueError("criticalities must be critical, important, or optional")

    def criticality_for(self, field_name: str) -> str:
        return self.criticalities.get(field_name, "important")


DEFAULT_VALIDATION_CONFIG = ValidationConfig()
