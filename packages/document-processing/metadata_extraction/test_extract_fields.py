"""Focused tests for title, academic, advisor, abstract, and keyword fields."""

from __future__ import annotations

import unittest

from metadata_extraction import extract_metadata_from_pages


def page(text: str, *, language: str = "thai", number: int = 4) -> dict[str, object]:
    return {
        "page_number": number,
        "language": language,
        "normalized_text": text,
        "normalization_status": "success",
        "processing_status": "success",
    }


class TitleExtractionTests(unittest.TestCase):
    def test_thai_title_single_line(self) -> None:
        result = extract_metadata_from_pages(
            [page("หัวข้อโครงงาน ระบบจัดเก็บเอกสาร\nชื่อนักศึกษา นาย ก")]
        )

        self.assertEqual(result.metadata["title_th"], "ระบบจัดเก็บเอกสาร")

    def test_thai_title_multiple_lines_stops_before_student_section(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "หัวข้อโครงงาน ระบบจัดเก็บและสืบค้น\n"
                    "เอกสารภาษาไทยสำหรับมหาวิทยาลัย\n"
                    "ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001"
                )
            ]
        )

        self.assertEqual(
            result.metadata["title_th"],
            "ระบบจัดเก็บและสืบค้น เอกสารภาษาไทยสำหรับมหาวิทยาลัย",
        )
        self.assertNotIn("ชื่อนักศึกษา", result.metadata["title_th"])

    def test_english_title_single_line(self) -> None:
        result = extract_metadata_from_pages(
            [page("Title: Document Retrieval System\nStudent Jane Doe", language="english")]
        )

        self.assertEqual(result.metadata["title_en"], "Document Retrieval System")

    def test_english_title_multiple_lines(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "PROJECT TITLE\nA DOCUMENT RETRIEVAL SYSTEM\n"
                    "FOR THAI UNIVERSITIES\nStudent Jane Doe",
                    language="english",
                )
            ]
        )

        self.assertEqual(
            result.metadata["title_en"],
            "A DOCUMENT RETRIEVAL SYSTEM FOR THAI UNIVERSITIES",
        )

    def test_problem_title_variant_and_inline_students_boundary(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "หัวข้อปัญหาพิเศษ ระบบวิเคราะห์ข้อมูล\nชื่อนักศึกษา นาย ก",
                ),
                page(
                    "Title DATA ANALYSIS SYSTEM Students Mr. Kor Student ID 66050001",
                    language="english",
                    number=5,
                ),
            ]
        )

        self.assertEqual(result.metadata["title_th"], "ระบบวิเคราะห์ข้อมูล")
        self.assertEqual(result.metadata["title_en"], "DATA ANALYSIS SYSTEM")

    def test_senior_students_inside_title_is_not_an_inline_boundary(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "Title Employment Decisions of Senior Students, KMITL\n"
                    "Students Mr. Kor Student ID 66050001",
                    language="english",
                )
            ]
        )

        self.assertEqual(
            result.metadata["title_en"],
            "Employment Decisions of Senior Students, KMITL",
        )

    def test_low_confidence_inferred_title_is_retained_with_warning(self) -> None:
        result = extract_metadata_from_pages(
            [page("ระบบต้นแบบสำหรับเอกสาร\nชื่อนักศึกษา นาย ก")]
        )

        self.assertEqual(result.metadata["title_th"], "ระบบต้นแบบสำหรับเอกสาร")
        self.assertIn("low_confidence_title_th", result.warnings)


class AcademicAndAdvisorTests(unittest.TestCase):
    def test_degree_department_faculty_and_year(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "ปริญญา วิทยาศาสตรบัณฑิต (วิทยาการคอมพิวเตอร์)\n"
                    "ภาควิชา วิทยาการคอมพิวเตอร์\n"
                    "คณะ วิทยาศาสตร์\nปีการศึกษา ๒๕๖๙"
                )
            ]
        )

        self.assertEqual(
            result.metadata["degree"],
            "วิทยาศาสตรบัณฑิต (วิทยาการคอมพิวเตอร์)",
        )
        self.assertEqual(result.metadata["department"], "วิทยาการคอมพิวเตอร์")
        self.assertEqual(result.metadata["faculty"], "วิทยาศาสตร์")
        self.assertEqual(result.metadata["academic_year"], "๒๕๖๙")

    def test_label_value_on_next_line(self) -> None:
        result = extract_metadata_from_pages(
            [page("Degree\nBachelor of Science\nDepartment\nComputer Science", language="english")]
        )

        self.assertEqual(result.metadata["degree"], "Bachelor of Science")
        self.assertEqual(result.metadata["department"], "Computer Science")
        self.assertEqual(result.fields["degree"].method, "degree_label_next_line")

    def test_advisor_prefix_is_preserved(self) -> None:
        result = extract_metadata_from_pages(
            [page("อาจารย์ที่ปรึกษา ผศ. ดร. สมชาย ใจดี")]
        )

        self.assertEqual(result.metadata["advisor"], "ผศ. ดร. สมชาย ใจดี")

    def test_english_advisor(self) -> None:
        result = extract_metadata_from_pages(
            [page("Project Advisor: Assoc. Prof. Dr. Jane Doe", language="english")]
        )

        self.assertEqual(result.metadata["advisor"], "Assoc. Prof. Dr. Jane Doe")

    def test_one_co_advisor(self) -> None:
        result = extract_metadata_from_pages(
            [page("อาจารย์ที่ปรึกษาร่วม ดร. สมหญิง ใจดี")]
        )

        self.assertEqual(result.metadata["co_advisors"], ["ดร. สมหญิง ใจดี"])

    def test_multiple_co_advisors(self) -> None:
        result = extract_metadata_from_pages(
            [page("Co-Advisor\nDr. Jane Doe\nAsst. Prof. John Roe", language="english")]
        )

        self.assertEqual(
            result.metadata["co_advisors"],
            ["Dr. Jane Doe", "Asst. Prof. John Roe"],
        )

    def test_co_advisor_translation_is_an_alternative_not_duplicate_value(self) -> None:
        result = extract_metadata_from_pages(
            [
                page("อาจารย์ที่ปรึกษาร่วม รศ. สมชาย ใจดี", number=4),
                page(
                    "Co-Advisor Assoc. Prof. Somchai Jaidee",
                    language="english",
                    number=5,
                ),
            ]
        )

        self.assertEqual(result.metadata["co_advisors"], ["รศ. สมชาย ใจดี"])
        self.assertEqual(len(result.fields["co_advisors"].alternatives), 1)
        self.assertIn("conflicting_co_advisors_candidates", result.warnings)

    def test_advisor_does_not_consume_abstract_heading(self) -> None:
        result = extract_metadata_from_pages(
            [page("อาจารย์ที่ปรึกษา ดร. สมชาย ใจดี\nบทคัดย่อ\nเนื้อหา")]
        )

        self.assertEqual(result.metadata["advisor"], "ดร. สมชาย ใจดี")
        self.assertNotIn("บทคัดย่อ", result.metadata["advisor"])


class AbstractAndKeywordTests(unittest.TestCase):
    def test_thai_abstract_excludes_heading_keywords_and_front_matter(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "หัวข้อโครงงาน ระบบทดสอบ\nชื่อนักศึกษา นาย ก\nบทคัดย่อ\n\n"
                    "ย่อหน้าแรก\nย่อหน้าที่สอง\n\nคำสำคัญ: OCR, ระบบสืบค้น"
                )
            ]
        )

        self.assertEqual(result.metadata["abstract_th"], "ย่อหน้าแรก\nย่อหน้าที่สอง")
        self.assertNotIn("หัวข้อโครงงาน", result.metadata["abstract_th"])
        self.assertNotIn("คำสำคัญ", result.metadata["abstract_th"])

    def test_english_abstract(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(
                    "ABSTRACT\nFirst paragraph.\nSecond paragraph.\nKeywords: OCR",
                    language="english",
                )
            ]
        )

        self.assertEqual(
            result.metadata["abstract_en"],
            "First paragraph.\nSecond paragraph.",
        )

    def test_abstract_without_keywords_ends_at_page_end(self) -> None:
        result = extract_metadata_from_pages(
            [page("บทคัดย่อ\nข้อความบรรทัดแรก\nข้อความบรรทัดสุดท้าย")]
        )

        self.assertEqual(
            result.metadata["abstract_th"],
            "ข้อความบรรทัดแรก\nข้อความบรรทัดสุดท้าย",
        )

    def test_thai_keywords(self) -> None:
        result = extract_metadata_from_pages(
            [page("คำสำคัญ: OCR, ระบบสืบค้น; เอกสารภาษาไทย")]
        )

        self.assertEqual(
            result.metadata["keywords"],
            ["OCR", "ระบบสืบค้น", "เอกสารภาษาไทย"],
        )

    def test_english_multiword_keywords(self) -> None:
        result = extract_metadata_from_pages(
            [page("Key words: OCR, Information Retrieval, Deep Learning", language="english")]
        )

        self.assertEqual(
            result.metadata["keywords"],
            ["OCR", "Information Retrieval", "Deep Learning"],
        )

    def test_keywords_do_not_include_footer(self) -> None:
        result = extract_metadata_from_pages(
            [page("Keywords: OCR, Retrieval\n\n4", language="english")]
        )

        self.assertEqual(result.metadata["keywords"], ["OCR", "Retrieval"])


if __name__ == "__main__":
    unittest.main()
