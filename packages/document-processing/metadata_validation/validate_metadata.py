"""Orchestrate deterministic validation over a Metadata Extraction result."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from metadata_validation.config import (  # type: ignore[import-not-found]
        DEFAULT_VALIDATION_CONFIG,
        ValidationConfig,
    )
    from metadata_validation.models import (  # type: ignore[import-not-found]
        DocumentStatus,
        FieldStatus,
        ReasonSeverity,
        ValidationReason,
        ValidationResult,
    )
    from metadata_validation.reference_data import (  # type: ignore[import-not-found]
        ValidationReferenceData,
        coerce_reference_data,
    )
    from metadata_validation.validate_academic import (  # type: ignore[import-not-found]
        validate_academic_field,
        validate_academic_year,
    )
    from metadata_validation.validate_advisors import (  # type: ignore[import-not-found]
        validate_advisor,
        validate_co_advisors,
    )
    from metadata_validation.validate_consistency import (  # type: ignore[import-not-found]
        validate_department_faculty_consistency,
    )
    from metadata_validation.validate_content import (  # type: ignore[import-not-found]
        validate_abstract,
        validate_keywords,
        validate_title,
    )
    from metadata_validation.validate_students import (  # type: ignore[import-not-found]
        validate_students,
    )
    from metadata_validation.validation_utils import (  # type: ignore[import-not-found]
        field_mapping,
        make_reason,
    )
else:
    from .config import DEFAULT_VALIDATION_CONFIG, ValidationConfig
    from .models import (
        DocumentStatus,
        FieldStatus,
        ReasonSeverity,
        ValidationReason,
        ValidationResult,
    )
    from .reference_data import ValidationReferenceData, coerce_reference_data
    from .validate_academic import validate_academic_field, validate_academic_year
    from .validate_advisors import validate_advisor, validate_co_advisors
    from .validate_consistency import validate_department_faculty_consistency
    from .validate_content import validate_abstract, validate_keywords, validate_title
    from .validate_students import validate_students
    from .validation_utils import field_mapping, make_reason


METADATA_FIELDS = (
    "title_th",
    "title_en",
    "students",
    "degree",
    "department",
    "faculty",
    "academic_year",
    "advisor",
    "co_advisors",
    "abstract_th",
    "abstract_en",
    "keywords",
)


def _empty_metadata() -> dict[str, Any]:
    return {
        field: [] if field in {"students", "co_advisors", "keywords"} else None
        for field in METADATA_FIELDS
    }


def _coerce_extraction_result(value: Any) -> tuple[dict[str, Any], bool]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        return {}, False
    return deepcopy(dict(value)), True


def _propagate_document_warnings(warnings: Any) -> list[ValidationReason]:
    if not isinstance(warnings, list):
        return []
    results: list[ValidationReason] = []
    for warning_value in dict.fromkeys(str(item) for item in warnings):
        if warning_value.startswith("conflicting_") or warning_value.startswith(
            "low_confidence_"
        ):
            severity = ReasonSeverity.INFO
            message = "Extraction warning is retained and resolved at field scope when safe."
        elif warning_value in {"missing_title_th", "missing_title_en"}:
            severity = ReasonSeverity.INFO
            message = (
                "A language-specific title is missing; the title-group policy "
                "decides impact."
            )
        elif warning_value in {
            "missing_student",
            "missing_advisor",
            "ambiguous_student_pairing",
            "unusable_normalized_page",
            "suspicious_thai_character_spacing",
            "source_processing_failed",
            "missing_source_text",
            "upstream_requires_manual_review",
        }:
            severity = ReasonSeverity.WARNING
            message = "An extraction or upstream warning requires validation review."
        else:
            severity = ReasonSeverity.WARNING
            message = "An unclassified extraction warning was preserved conservatively."
        results.append(
            make_reason(
                "upstream_warning",
                severity,
                message,
                details={"upstream_warning": warning_value},
            )
        )
    return results


def _group_policy_reasons(
    metadata: Mapping[str, Any],
) -> list[ValidationReason]:
    reasons: list[ValidationReason] = []
    if not metadata.get("title_th") and not metadata.get("title_en"):
        reasons.append(
            make_reason(
                "missing_required_title",
                ReasonSeverity.WARNING,
                "At least one Thai or English title is required.",
                details={"fields": ["title_th", "title_en"]},
            )
        )
    if not metadata.get("abstract_th") and not metadata.get("abstract_en"):
        reasons.append(
            make_reason(
                "missing_required_abstract",
                ReasonSeverity.WARNING,
                "At least one Thai or English abstract is required.",
                details={"fields": ["abstract_th", "abstract_en"]},
            )
        )
    return reasons


def _document_status(
    extraction_status: str,
    metadata: Mapping[str, Any],
    fields: Mapping[str, Any],
    warnings: Sequence[ValidationReason],
    config: ValidationConfig,
) -> DocumentStatus:
    meaningful = any(
        bool(value) if isinstance(value, list) else value is not None
        for value in metadata.values()
    )
    if extraction_status == "failed" or not meaningful:
        return DocumentStatus.FAILED
    invalid_critical = any(
        result.status is FieldStatus.INVALID and result.criticality == "critical"
        for result in fields.values()
    )
    if invalid_critical:
        return DocumentStatus.INVALID
    required_missing = any(
        name in config.required_fields and result.status is FieldStatus.MISSING
        for name, result in fields.items()
    )
    group_missing = (
        not metadata.get("title_th") and not metadata.get("title_en")
    ) or (
        not metadata.get("abstract_th") and not metadata.get("abstract_en")
    )
    field_review = any(
        result.status in {FieldStatus.REVIEW_REQUIRED, FieldStatus.INVALID}
        for result in fields.values()
    )
    warning_review = any(
        warning.severity in {ReasonSeverity.WARNING, ReasonSeverity.ERROR}
        for warning in warnings
    )
    if required_missing or group_missing or field_review or warning_review:
        return DocumentStatus.REVIEW_REQUIRED
    return DocumentStatus.VALID


def validate_metadata(
    extraction_result: Any,
    reference_data: Any = None,
    config: ValidationConfig = DEFAULT_VALIDATION_CONFIG,
) -> ValidationResult:
    """Validate only a supplied extraction result and never mutate it."""
    if not isinstance(config, ValidationConfig):
        raise TypeError("config must be a ValidationConfig")
    extraction, valid_input = _coerce_extraction_result(extraction_result)
    references = coerce_reference_data(reference_data)
    metadata_value = extraction.get("metadata", {}) if valid_input else {}
    fields_value = extraction.get("fields", {}) if valid_input else {}
    metadata = (
        {**_empty_metadata(), **deepcopy(dict(metadata_value))}
        if isinstance(metadata_value, Mapping)
        else _empty_metadata()
    )
    extraction_fields = fields_value if isinstance(fields_value, Mapping) else {}
    extraction_status = str(extraction.get("extraction_status", "failed"))
    if not valid_input or not isinstance(metadata_value, Mapping):
        extraction_status = "failed"

    results: dict[str, Any] = {}
    for name in ("title_th", "title_en"):
        results[name] = validate_title(
            name,
            metadata.get(name),
            field_mapping(extraction_fields, name),
            config,
        )
    students, student_ids = validate_students(
        metadata.get("students"),
        field_mapping(extraction_fields, "students"),
        config,
    )
    results["students"] = students
    results["student_id"] = student_ids
    for name in ("degree", "department", "faculty"):
        results[name] = validate_academic_field(
            name,
            metadata.get(name),
            field_mapping(extraction_fields, name),
            config,
            references,
        )
    results["academic_year"] = validate_academic_year(
        metadata.get("academic_year"),
        field_mapping(extraction_fields, "academic_year"),
        config,
    )
    results["advisor"] = validate_advisor(
        metadata.get("advisor"),
        field_mapping(extraction_fields, "advisor"),
        config,
        references,
    )
    results["co_advisors"] = validate_co_advisors(
        metadata.get("co_advisors"),
        field_mapping(extraction_fields, "co_advisors"),
        metadata.get("advisor"),
        config,
        references,
    )
    for name in ("abstract_th", "abstract_en"):
        results[name] = validate_abstract(
            name,
            metadata.get(name),
            field_mapping(extraction_fields, name),
            config,
        )
    results["keywords"] = validate_keywords(
        metadata.get("keywords"),
        field_mapping(extraction_fields, "keywords"),
        config,
    )
    results["department"], results["faculty"], relation_checks = (
        validate_department_faculty_consistency(
            results["department"],
            results["faculty"],
            config,
            references,
        )
    )

    document_warnings = _propagate_document_warnings(extraction.get("warnings", []))
    document_warnings.extend(_group_policy_reasons(metadata))
    if not valid_input:
        document_warnings.append(
            make_reason(
                "invalid_extraction_input",
                ReasonSeverity.ERROR,
                "Input is not a Metadata Extraction result mapping.",
            )
        )
    elif not isinstance(metadata_value, Mapping) or not isinstance(fields_value, Mapping):
        document_warnings.append(
            make_reason(
                "invalid_extraction_contract",
                ReasonSeverity.ERROR,
                "Extraction result has invalid metadata or fields structure.",
            )
        )

    document_status = _document_status(
        extraction_status,
        metadata,
        results,
        document_warnings,
        config,
    )
    status_counts = Counter(result.status.value for result in results.values())
    extracted_count = sum(
        bool(result.value) if isinstance(result.value, list) else result.value is not None
        for result in results.values()
    )
    conflict_keys = (
        "candidate_conflicts_received",
        "candidate_conflicts_resolved",
        "candidate_conflicts_unresolved",
        "semantic_equivalence_resolutions",
    )
    conflict_stats = {
        key: sum(int(result.details.get(key, 0)) for result in results.values())
        for key in conflict_keys
    }
    reference_counts = Counter(result.reference_check for result in results.values())
    summary = {
        "valid": status_counts[FieldStatus.VALID.value],
        "review_required": status_counts[FieldStatus.REVIEW_REQUIRED.value],
        "invalid": status_counts[FieldStatus.INVALID.value],
        "missing": status_counts[FieldStatus.MISSING.value],
    }
    stats = {
        "fields_extracted": extracted_count,
        "fields_validated": extracted_count,
        "validation_coverage": 1.0 if extracted_count else 0.0,
        **conflict_stats,
        "reference_checks": dict(reference_counts),
        "department_faculty_relation_checks": relation_checks,
    }
    return ValidationResult(
        metadata=metadata,
        fields=results,
        document_status=document_status,
        requires_manual_review=document_status is not DocumentStatus.VALID,
        warnings=tuple(document_warnings),
        summary=summary,
        stats=stats,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a stored Metadata Extraction result locally.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Metadata Extraction result JSON; omit to read JSON from stdin",
    )
    parser.add_argument(
        "--reference-data",
        type=Path,
        help="Optional injected reference-data JSON; no database or network is used",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        if args.input_json is None:
            payload = json.load(sys.stdin)
        else:
            payload = json.loads(args.input_json.read_text(encoding="utf-8-sig"))
        references = (
            ValidationReferenceData.from_json(args.reference_data)
            if args.reference_data is not None
            else None
        )
        result = validate_metadata(payload, reference_data=references)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 1 if result.document_status is DocumentStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
