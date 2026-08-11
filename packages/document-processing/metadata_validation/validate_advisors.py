"""Primary and co-advisor validation."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from .comparison import canonical_text
from .config import ValidationConfig
from .models import FieldStatus, FieldValidationResult, ReasonSeverity
from .reference_data import ValidationReferenceData
from .validation_utils import (
    common_signal_reasons,
    make_field_result,
    make_reason,
    scalar_conflict_reasons,
)


_ADVISOR_LABEL_RE = re.compile(
    r"^(?:advisor|co[- ]?advisor|อาจารย์ที่ปรึกษา|ที่ปรึกษาร่วม)\s*[:：]",
    re.IGNORECASE,
)


def _person_structure_reasons(
    value: Any,
    config: ValidationConfig,
    *,
    field_name: str,
) -> list:
    reasons = []
    text = "" if value is None else str(value).strip()
    if not text:
        return reasons
    if not (
        config.minimum_person_name_characters
        <= len(text)
        <= config.maximum_person_name_characters
    ):
        reasons.append(
            make_reason(
                "suspicious_advisor_name_length",
                ReasonSeverity.WARNING,
                "Advisor name has a suspicious length.",
                details={"field": field_name, "length": len(text)},
            )
        )
    if _ADVISOR_LABEL_RE.search(text):
        reasons.append(
            make_reason(
                "advisor_label_contamination",
                ReasonSeverity.ERROR,
                "Advisor value still contains a structural label.",
                details={"field": field_name},
            )
        )
    return reasons


def validate_advisor(
    value: Any,
    field: Mapping[str, Any],
    config: ValidationConfig,
    reference_data: ValidationReferenceData | None,
) -> FieldValidationResult:
    reasons = common_signal_reasons("advisor", field, config)
    conflict_reasons, details = scalar_conflict_reasons("advisor", field)
    reasons.extend(conflict_reasons)
    text = "" if value is None else str(value).strip()
    if not text:
        reasons.append(
            make_reason(
                "missing_required_field",
                ReasonSeverity.WARNING,
                "Primary advisor is required but missing.",
                details={"field": "advisor"},
            )
        )
    reasons.extend(_person_structure_reasons(value, config, field_name="advisor"))

    if reference_data is None:
        reference_check = "skipped_unavailable"
        if "advisor" in config.reference_required_fields:
            reasons.append(
                make_reason(
                    "reference_data_unavailable",
                    ReasonSeverity.WARNING,
                    "Required advisor reference lookup could not be performed.",
                    details={"field": "advisor"},
                )
            )
    elif text:
        reference_check = "performed"
        if not reference_data.contains("advisors", text):
            severity = (
                ReasonSeverity.ERROR
                if config.unknown_reference_value_status == "INVALID"
                else ReasonSeverity.WARNING
            )
            reasons.append(
                make_reason(
                    "advisor_not_in_reference_data",
                    severity,
                    "Advisor was not found in supplied reference data.",
                )
            )
    else:
        reference_check = "not_performed_missing_value"
    return make_field_result(
        "advisor",
        value,
        field,
        config,
        reasons,
        reference_check=reference_check,
        details=details,
    )


def validate_co_advisors(
    value: Any,
    field: Mapping[str, Any],
    advisor: Any,
    config: ValidationConfig,
    reference_data: ValidationReferenceData | None,
) -> FieldValidationResult:
    reasons = common_signal_reasons("co_advisors", field, config)
    values = value if isinstance(value, list) else []
    if value is not None and not isinstance(value, list):
        reasons.append(
            make_reason(
                "invalid_co_advisor_structure",
                ReasonSeverity.ERROR,
                "Co-advisors must be represented as a list.",
            )
        )
    canonical_values = [canonical_text(item) for item in values if str(item).strip()]
    counts = Counter(canonical_values)
    duplicates = [item for item, count in counts.items() if count > 1]
    if duplicates:
        reasons.append(
            make_reason(
                "duplicate_co_advisor",
                ReasonSeverity.WARNING,
                "A co-advisor appears more than once.",
                details={"duplicate_count": len(duplicates)},
            )
        )
    advisor_key = canonical_text(advisor)
    if advisor_key and advisor_key in canonical_values:
        reasons.append(
            make_reason(
                "advisor_also_listed_as_co_advisor",
                ReasonSeverity.ERROR,
                "The primary advisor is also listed as a co-advisor.",
            )
        )
    for item in values:
        reasons.extend(_person_structure_reasons(item, config, field_name="co_advisors"))

    warnings = [str(item) for item in field.get("warnings", [])]
    conflict_received = int(
        any(warning.startswith("conflicting_co_advisor") for warning in warnings)
    )
    details = {
        "candidate_conflicts_received": conflict_received,
        "candidate_conflicts_resolved": 0,
        "candidate_conflicts_unresolved": conflict_received,
        "semantic_equivalence_resolutions": 0,
    }
    if conflict_received:
        reasons.append(
            make_reason(
                "candidate_conflict",
                ReasonSeverity.WARNING,
                "Co-advisor candidate lists differ and cannot be merged by validation.",
                details={"field": "co_advisors"},
            )
        )

    reference_check = "not_applicable"
    if values:
        if reference_data is None:
            reference_check = "skipped_unavailable"
        else:
            reference_check = "performed"
            missing = [
                item for item in values if not reference_data.contains("advisors", item)
            ]
            if missing:
                severity = (
                    ReasonSeverity.ERROR
                    if config.unknown_reference_value_status == "INVALID"
                    else ReasonSeverity.WARNING
                )
                reasons.append(
                    make_reason(
                        "co_advisor_not_in_reference_data",
                        severity,
                        "One or more co-advisors are absent from supplied reference data.",
                        details={"count": len(missing)},
                    )
                )
    return make_field_result(
        "co_advisors",
        values,
        field,
        config,
        reasons,
        reference_check=reference_check,
        details=details,
        missing_status=FieldStatus.VALID,
    )
