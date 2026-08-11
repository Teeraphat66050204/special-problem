"""Tests for multi-student extraction, pairing, and cross-page resolution."""

from __future__ import annotations

import unittest

from metadata_extraction import extract_metadata_from_pages


def page(text: str, *, language: str = "thai", number: int = 4) -> dict[str, object]:
    return {
        "page_number": number,
        "language": language,
        "normalized_text": text,
        "normalization_status": "success",
    }


class StudentExtractionTests(unittest.TestCase):
    def test_single_student_same_line(self) -> None:
        result = extract_metadata_from_pages(
            [page("ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001\nปริญญา วท.บ.")]
        )

        self.assertEqual(
            result.metadata["students"],
            [{"name": "นาย ก", "student_id": "66050001"}],
        )

    def test_multiple_students_same_line_format(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001\n"
                    "นางสาว ข รหัสนักศึกษา 66050002\nปริญญา วท.บ."
                )
            ]
        )

        self.assertEqual(
            result.metadata["students"],
            [
                {"name": "นาย ก", "student_id": "66050001"},
                {"name": "นางสาว ข", "student_id": "66050002"},
            ],
        )

    def test_name_and_id_on_separate_lines(self) -> None:
        result = extract_metadata_from_pages(
            [page("ชื่อนักศึกษา นาย ก\nรหัสนักศึกษา 66050001\nปริญญา วท.บ.")]
        )

        self.assertEqual(
            result.metadata["students"],
            [{"name": "นาย ก", "student_id": "66050001"}],
        )
        candidate = result.fields["students"].candidates[0]
        self.assertEqual(candidate.source_line_indexes, (0, 1))
        self.assertEqual(candidate.method, "student_name_id_line_proximity")

    def test_english_student_and_id(self) -> None:
        result = extract_metadata_from_pages(
            [page("Student Jane Doe Student ID 66050001\nDegree B.Sc.", language="english")]
        )

        self.assertEqual(
            result.metadata["students"],
            [{"name": "Jane Doe", "student_id": "66050001"}],
        )

    def test_ambiguous_pairing_is_not_random(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "ชื่อนักศึกษา\nนาย ก\nนางสาว ข\n"
                    "รหัสนักศึกษา 66050001\nปริญญา วท.บ."
                )
            ]
        )

        self.assertIn("ambiguous_student_pairing", result.warnings)
        self.assertTrue(result.requires_manual_review)
        self.assertNotIn(
            {"name": "นาย ก", "student_id": "66050001"},
            result.metadata["students"],
        )

    def test_same_id_across_languages_merges_deterministically(self) -> None:
        result = extract_metadata_from_pages(
            [
                page("ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001", number=4),
                page(
                    "Student Mr. Kor Student ID 66050001",
                    language="english",
                    number=5,
                ),
            ]
        )

        self.assertEqual(
            result.metadata["students"],
            [{"name": "นาย ก", "student_id": "66050001"}],
        )
        self.assertIn("conflicting_student_name_candidates", result.warnings)
        self.assertEqual(len(result.fields["students"].candidates), 2)

    def test_does_not_capture_unrelated_number_outside_student_section(self) -> None:
        result = extract_metadata_from_pages(
            [page("ปีการศึกษา 2569\nบทคัดย่อ\nผลทดสอบจำนวน 12345678 รายการ")]
        )

        self.assertEqual(result.metadata["students"], [])

    def test_incomplete_translation_does_not_duplicate_complete_student(self) -> None:
        result = extract_metadata_from_pages(
            [
                page("ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001", number=4),
                page("Students Mr. Kor\nDegree B.Sc.", language="english", number=5),
            ]
        )

        self.assertEqual(
            result.metadata["students"],
            [{"name": "นาย ก", "student_id": "66050001"}],
        )
        self.assertIn("unpaired_student_candidate_ignored", result.warnings)


if __name__ == "__main__":
    unittest.main()
