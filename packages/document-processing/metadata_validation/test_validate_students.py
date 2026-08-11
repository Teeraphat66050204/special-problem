from __future__ import annotations

import unittest

from metadata_validation import FieldStatus, validate_metadata
from metadata_validation._test_support import set_field, valid_extraction


class StudentValidationTests(unittest.TestCase):
    def test_valid_student_id(self) -> None:
        result = validate_metadata(valid_extraction())
        self.assertEqual(result.fields["student_id"].status, FieldStatus.VALID)

    def test_invalid_student_id(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "students", [{"name": "Test", "student_id": "ABC66050204"}])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["student_id"].status, FieldStatus.INVALID)
        self.assertIn(
            "invalid_student_id_format",
            [reason.code for reason in result.fields["student_id"].reasons],
        )

    def test_short_student_id_is_invalid(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "students", [{"name": "Test", "student_id": "6605"}])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["student_id"].status, FieldStatus.INVALID)

    def test_missing_student_id(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "students", [{"name": "Test", "student_id": None}])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["student_id"].status, FieldStatus.MISSING)

    def test_missing_student_name(self) -> None:
        extraction = valid_extraction()
        set_field(extraction, "students", [{"name": None, "student_id": "66050204"}])
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.REVIEW_REQUIRED)

    def test_duplicate_identical_student_record(self) -> None:
        extraction = valid_extraction()
        record = {"name": "Test Student", "student_id": "66050204"}
        set_field(extraction, "students", [record, record])
        result = validate_metadata(extraction)
        codes = [reason.code for reason in result.fields["students"].reasons]
        self.assertIn("duplicate_student_record", codes)
        self.assertEqual(result.fields["student_id"].status, FieldStatus.REVIEW_REQUIRED)

    def test_multiple_language_names_with_same_selected_id_use_strong_identity(self) -> None:
        extraction = valid_extraction()
        set_field(
            extraction,
            "students",
            [
                {"name": "ชื่อ ภาษาไทย", "student_id": "66050204"},
                {"name": "English Name", "student_id": "66050204"},
            ],
        )
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.VALID)
        self.assertIn(
            "semantic_match_by_student_id",
            [reason.code for reason in result.fields["students"].reasons],
        )

    def test_cross_language_candidates_with_same_id_are_semantically_matched(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["students"]
        field["candidates"] = [
            {"value": {"name": "นายทดสอบ ระบบ", "student_id": "66050204"}},
            {"value": {"name": "Test System", "student_id": "66050204"}},
        ]
        field["alternatives"] = [field["candidates"][1]]
        field["warnings"] = ["conflicting_student_name_candidates"]
        extraction["warnings"] = ["conflicting_student_name_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.VALID)
        self.assertIn(
            "semantic_match_by_student_id",
            [reason.code for reason in result.fields["students"].reasons],
        )
        self.assertFalse(result.requires_manual_review)

    def test_same_candidate_name_with_different_ids_is_unresolved(self) -> None:
        extraction = valid_extraction()
        field = extraction["fields"]["students"]
        field["candidates"] = [
            {"value": {"name": "Test Student", "student_id": "66050204"}},
            {"value": {"name": "Test Student", "student_id": "66050205"}},
        ]
        field["warnings"] = ["conflicting_student_name_candidates"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.REVIEW_REQUIRED)

    def test_ambiguous_pairing_warning_is_propagated(self) -> None:
        extraction = valid_extraction()
        extraction["fields"]["students"]["warnings"] = ["ambiguous_student_pairing"]
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.REVIEW_REQUIRED)

    def test_multiple_distinct_students_are_valid(self) -> None:
        extraction = valid_extraction()
        set_field(
            extraction,
            "students",
            [
                {"name": "Student One", "student_id": "66050204"},
                {"name": "Student Two", "student_id": "66050205"},
            ],
        )
        result = validate_metadata(extraction)
        self.assertEqual(result.fields["students"].status, FieldStatus.VALID)
        self.assertEqual(result.fields["student_id"].status, FieldStatus.VALID)


if __name__ == "__main__":
    unittest.main()
