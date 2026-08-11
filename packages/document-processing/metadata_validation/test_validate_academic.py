from __future__ import annotations

import unittest

from metadata_validation import (
    DEFAULT_VALIDATION_CONFIG,
    FieldStatus,
    ValidationReferenceData,
    normalize_academic_year_candidate,
    validate_metadata,
)
from metadata_validation._test_support import set_field, valid_extraction


class AcademicValidationTests(unittest.TestCase):
    def test_be_academic_year(self) -> None:
        result = normalize_academic_year_candidate("2569", DEFAULT_VALIDATION_CONFIG)
        self.assertEqual(result["calendar"], "BE")
        self.assertEqual(result["equivalent_ce"], 2026)

    def test_ce_academic_year(self) -> None:
        result = normalize_academic_year_candidate("2026 CE", DEFAULT_VALIDATION_CONFIG)
        self.assertEqual(result["calendar"], "CE")
        self.assertEqual(result["equivalent_ce"], 2026)

    def test_be_ce_candidates_are_equivalent(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["academic_year"]
        field["candidates"] = [{"value": "2569"}, {"value": "2026"}]
        field["alternatives"] = [{"value": "2026"}]
        field["warnings"] = ["conflicting_academic_year_candidates"]
        extraction["warnings"] = ["conflicting_academic_year_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["academic_year"].status, FieldStatus.VALID)
        self.assertFalse(result.requires_manual_review)
        self.assertEqual(result.stats["semantic_equivalence_resolutions"], 1)

    def test_non_equivalent_year_candidates_require_review(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["academic_year"]
        field["candidates"] = [{"value": "2569"}, {"value": "2025"}]
        field["warnings"] = ["conflicting_academic_year_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(
            result.fields["academic_year"].status,
            FieldStatus.REVIEW_REQUIRED,
        )

    def test_malformed_year_is_invalid(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "academic_year", "year 69")
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["academic_year"].status, FieldStatus.INVALID)

    def test_degree_basic_validation_without_reference(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["degree"].status, FieldStatus.VALID)
        self.assertEqual(result.fields["degree"].reference_check, "skipped_unavailable")

    def test_degree_label_artifact_is_invalid(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "degree", "Degree")
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["degree"].status, FieldStatus.INVALID)

    def test_reference_data_lookup_success(self) -> None:
        references = ValidationReferenceData.from_mapping(
            {
                "departments": {"วิทยาการคอมพิวเตอร์": {"faculty": "วิทยาศาสตร์"}},
                "faculties": ["วิทยาศาสตร์"],
                "degrees": ["วิทยาศาสตรบัณฑิต"],
                "advisors": ["ดร. อาจารย์ ตัวอย่าง"],
            }
        )
        result = validate_metadata(valid_extraction(), reference_data=references)
        self.assertEqual(result.fields["department"].status, FieldStatus.VALID)
        self.assertEqual(result.fields["faculty"].status, FieldStatus.VALID)

    def test_department_faculty_mismatch_is_invalid_at_field_level(self) -> None:
        references = ValidationReferenceData.from_mapping(
            {
                "departments": {"วิทยาการคอมพิวเตอร์": {"faculty": "วิศวกรรมศาสตร์"}},
                "faculties": ["วิทยาศาสตร์"],
                "degrees": ["วิทยาศาสตรบัณฑิต"],
                "advisors": ["ดร. อาจารย์ ตัวอย่าง"],
            }
        )
        result = validate_metadata(valid_extraction(), reference_data=references)
        self.assertEqual(result.fields["department"].status, FieldStatus.INVALID)
        self.assertIn(
            "department_faculty_mismatch",
            [reason.code for reason in result.fields["faculty"].reasons],
        )

    def test_missing_academic_field(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "faculty", None)
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["faculty"].status, FieldStatus.MISSING)


if __name__ == "__main__":
    unittest.main()
