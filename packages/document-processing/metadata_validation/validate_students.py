"""Student-record and student-identity validation."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Mapping

from .comparison import canonical_text
from .config import ValidationConfig
from .models import FieldValidationResult, ReasonSeverity
from .validation_utils import (
    candidate_values,
    common_signal_reasons,
    make_field_result,
    make_reason,
)


def _candidate_student_records(field: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for value in candidate_values(field):
        if isinstance(value, Mapping):
            records.append(value)
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, Mapping))
    return records


def validate_students(
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
) -> tuple[FieldValidationResult, FieldValidationResult]:
    student_reasons = common_signal_reasons("students", field, config)
    id_reasons = common_signal_reasons("student_id", field, config)
    records = value if isinstance(value, list) else []
    if not records:
        missing = make_reason(
            "missing_required_field",
            ReasonSeverity.WARNING,
            "No student record was extracted.",
            details={"field": "students"},
        )
        student_reasons.append(missing)
        id_reasons.append(
            make_reason(
                "missing_student_id",
                ReasonSeverity.WARNING,
                "No student ID is available because no student record was extracted.",
            )
        )
        return (
            make_field_result("students", [], field, config, student_reasons),
            make_field_result("student_id", [], field, config, id_reasons),
        )

    normalized_records: list[tuple[str, str]] = []
    student_ids: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            student_reasons.append(
                make_reason(
                    "invalid_student_record",
                    ReasonSeverity.ERROR,
                    "A student item is not a structured name/ID record.",
                    details={"index": index},
                )
            )
            continue
        name = record.get("name")
        student_id = record.get("student_id")
        normalized_name = canonical_text(name)
        normalized_id = canonical_text(student_id, casefold=False)
        normalized_records.append((normalized_name, normalized_id))
        if not normalized_name:
            student_reasons.append(
                make_reason(
                    "missing_student_name",
                    ReasonSeverity.WARNING,
                    "A student record has no name.",
                    details={"index": index},
                )
            )
        elif not (
            config.minimum_person_name_characters
            <= len(normalized_name)
            <= config.maximum_person_name_characters
        ):
            student_reasons.append(
                make_reason(
                    "suspicious_student_name_length",
                    ReasonSeverity.WARNING,
                    "A student name has a suspicious length.",
                    details={"index": index, "length": len(normalized_name)},
                )
            )
        if not normalized_id:
            id_reasons.append(
                make_reason(
                    "missing_student_id",
                    ReasonSeverity.WARNING,
                    "A student record has no student ID.",
                    details={"index": index},
                )
            )
        else:
            student_ids.append(str(student_id).strip())
            if re.fullmatch(config.student_id_pattern, str(student_id).strip()) is None:
                id_reasons.append(
                    make_reason(
                        "invalid_student_id_format",
                        ReasonSeverity.ERROR,
                        "Student ID does not match the configured numeric format.",
                        details={"index": index, "value": student_id},
                    )
                )

    record_counts = Counter(normalized_records)
    duplicate_records = [record for record, count in record_counts.items() if count > 1]
    if duplicate_records:
        student_reasons.append(
            make_reason(
                "duplicate_student_record",
                ReasonSeverity.WARNING,
                "The same student record appears more than once.",
                details={"duplicate_count": len(duplicate_records)},
            )
        )
    id_to_names: dict[str, set[str]] = defaultdict(set)
    name_to_ids: dict[str, set[str]] = defaultdict(set)
    for name, student_id in normalized_records:
        if student_id:
            id_to_names[student_id].add(name)
        if name:
            name_to_ids[name].add(student_id)
    id_counts = Counter(student_id for _, student_id in normalized_records if student_id)
    duplicate_ids = [student_id for student_id, count in id_counts.items() if count > 1]
    identical_name_duplicate_ids = [
        student_id for student_id in duplicate_ids if len(id_to_names[student_id]) == 1
    ]
    multilingual_identity_ids = [
        student_id for student_id in duplicate_ids if len(id_to_names[student_id]) > 1
    ]
    if identical_name_duplicate_ids:
        id_reasons.append(
            make_reason(
                "duplicate_student_id",
                ReasonSeverity.WARNING,
                "A student ID is repeated by an identical selected record.",
                details={"student_ids": identical_name_duplicate_ids},
            )
        )
    if multilingual_identity_ids:
        student_reasons.append(
            make_reason(
                "semantic_match_by_student_id",
                ReasonSeverity.INFO,
                "Different selected name strings share the same strong student-ID identity key.",
                details={"student_ids": multilingual_identity_ids},
            )
        )
    conflicting_names = [name for name, ids in name_to_ids.items() if len(ids - {""}) > 1]
    if conflicting_names:
        student_reasons.append(
            make_reason(
                "student_identity_conflict",
                ReasonSeverity.WARNING,
                "The same normalized name is associated with different student IDs.",
                details={"names": conflicting_names},
            )
        )

    candidates = _candidate_student_records(field)
    candidate_ids: dict[str, set[str]] = defaultdict(set)
    candidate_names: dict[str, set[str]] = defaultdict(set)
    for record in candidates:
        student_id = canonical_text(record.get("student_id"), casefold=False)
        name = canonical_text(record.get("name"))
        if student_id and name:
            candidate_ids[student_id].add(name)
            candidate_names[name].add(student_id)
    semantic_matches = sum(len(names) > 1 for names in candidate_ids.values())
    identity_conflicts = sum(len(ids) > 1 for ids in candidate_names.values())
    conflict_received = int(
        any(
            str(warning).startswith("conflicting_student")
            for warning in field.get("warnings", [])
        )
    )
    resolved = int(bool(conflict_received and semantic_matches and not identity_conflicts))
    unresolved = int(bool(conflict_received and not resolved))
    if semantic_matches:
        student_reasons.append(
            make_reason(
                "semantic_match_by_student_id",
                ReasonSeverity.INFO,
                "Different name strings share the same strong student-ID identity key.",
                details={"identity_groups": semantic_matches},
            )
        )
    if identity_conflicts:
        student_reasons.append(
            make_reason(
                "student_identity_conflict",
                ReasonSeverity.WARNING,
                "Candidate records associate one normalized name with different IDs.",
                details={"conflict_groups": identity_conflicts},
            )
        )

    details = {
        "student_count": len(records),
        "candidate_conflicts_received": conflict_received,
        "candidate_conflicts_resolved": resolved,
        "candidate_conflicts_unresolved": unresolved,
        "semantic_equivalence_resolutions": semantic_matches + len(multilingual_identity_ids),
    }
    return (
        make_field_result("students", records, field, config, student_reasons, details=details),
        make_field_result(
            "student_id",
            student_ids,
            field,
            config,
            id_reasons,
            details={"student_id_count": len(student_ids)},
        ),
    )
