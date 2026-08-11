"""Integration tests over normalized page objects and extraction contracts."""

from __future__ import annotations

import copy
import unittest

from metadata_extraction import extract_metadata, extract_metadata_from_pages
from normalization import normalize_processed_document


def page(
    text: str | None,
    *,
    language: str,
    number: int,
    status: str = "success",
    warnings: list[str] | None = None,
) -> dict[str, object]:
    return {
        "page_number": number,
        "language": language,
        "normalized_text": text,
        "normalization_status": "success" if text else "skipped",
        "processing_status": status,
        "requires_manual_review": status != "success",
        "normalization": {
            "warnings": warnings or [],
        },
    }


THAI_PAGE = """หัวข้อโครงงาน ระบบสืบค้นเอกสาร
ชื่อนักศึกษา นาย ก รหัสนักศึกษา 66050001
ปริญญา วิทยาศาสตรบัณฑิต
ภาควิชา วิทยาการคอมพิวเตอร์
คณะ วิทยาศาสตร์
ปีการศึกษา 2569
อาจารย์ที่ปรึกษา ดร. สมชาย ใจดี
บทคัดย่อ
ข้อความบทคัดย่อภาษาไทย
คำสำคัญ: OCR, ระบบสืบค้น"""

ENGLISH_PAGE = """Title: DOCUMENT RETRIEVAL SYSTEM
Student Mr. Kor Student ID 66050001
Degree Bachelor of Science
Department Computer Science
Faculty Science
Academic Year 2026
Advisor Dr. Somchai Jaidee
ABSTRACT
English abstract body.
Keywords: OCR, Information Retrieval"""


class MetadataIntegrationTests(unittest.TestCase):
    def test_thai_and_english_pages_are_processed_separately_then_merged(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(THAI_PAGE, language="thai", number=4),
                page(ENGLISH_PAGE, language="english", number=5),
            ]
        )

        self.assertEqual(result.metadata["title_th"], "ระบบสืบค้นเอกสาร")
        self.assertEqual(result.metadata["title_en"], "DOCUMENT RETRIEVAL SYSTEM")
        self.assertEqual(result.metadata["abstract_th"], "ข้อความบทคัดย่อภาษาไทย")
        self.assertEqual(result.metadata["abstract_en"], "English abstract body.")
        self.assertEqual(result.fields["title_th"].source_pages, (4,))
        self.assertEqual(result.fields["title_en"].source_pages, (5,))

    def test_conflicting_academic_candidates_are_retained(self) -> None:
        result = extract_metadata_from_pages(
            [
                page("ปีการศึกษา 2569", language="thai", number=4),
                page("Academic Year 2026", language="english", number=5),
            ]
        )

        self.assertEqual(result.metadata["academic_year"], "2569")
        self.assertIn("conflicting_academic_year_candidates", result.warnings)
        self.assertEqual(
            [item.value for item in result.fields["academic_year"].alternatives],
            ["2026"],
        )

    def test_preferred_language_is_stable_even_when_value_is_on_next_line(self) -> None:
        result = extract_metadata_from_pages(
            [
                page("ปีการศึกษา\n2569", language="thai", number=4),
                page("Academic Year 2026", language="english", number=5),
            ]
        )

        self.assertEqual(result.metadata["academic_year"], "2569")

    def test_evidence_tracks_page_language_and_lines(self) -> None:
        result = extract_metadata_from_pages(
            [page(THAI_PAGE, language="thai", number=4)]
        )

        year = result.fields["academic_year"]
        self.assertEqual(year.source_pages, (4,))
        self.assertEqual(year.source_languages, ("thai",))
        self.assertEqual(year.candidates[0].source_line_indexes, (5,))
        self.assertEqual(year.candidates[0].evidence, ("ปีการศึกษา 2569",))

    def test_missing_optional_fields_are_empty_not_errors(self) -> None:
        result = extract_metadata_from_pages(
            [page(THAI_PAGE, language="thai", number=4)]
        )

        self.assertEqual(result.metadata["co_advisors"], [])
        self.assertNotIn("missing_co_advisors", result.warnings)

    def test_missing_important_fields_warns_without_crashing(self) -> None:
        result = extract_metadata_from_pages(
            [page("บทคัดย่อ\nเฉพาะเนื้อหา", language="thai", number=4)]
        )

        self.assertIn("missing_title_th", result.warnings)
        self.assertIn("missing_student", result.warnings)
        self.assertIn("missing_advisor", result.warnings)
        self.assertEqual(result.extraction_status, "partial")

    def test_suspicious_thai_spacing_is_propagated_not_corrected(self) -> None:
        broken = "ห ั ว ข้ อ ส ห ก ิ จ ศึ ก ษ า"
        result = extract_metadata_from_pages(
            [
                page(
                    broken,
                    language="thai",
                    number=4,
                    warnings=["suspicious_thai_character_spacing"],
                )
            ]
        )

        self.assertIn("suspicious_thai_character_spacing", result.warnings)
        self.assertNotEqual(result.metadata["title_th"], "หัวข้อสหกิจศึกษา")

    def test_failed_and_empty_upstream_pages_return_controlled_failure(self) -> None:
        result = extract_metadata_from_pages(
            [page(None, language="thai", number=4, status="ocr_failed")]
        )

        self.assertEqual(result.extraction_status, "failed")
        self.assertEqual(result.metadata["students"], [])
        self.assertIn("no_usable_normalized_text", result.warnings)

    def test_failed_page_does_not_use_stale_normalized_text(self) -> None:
        failed = page(
            "หัวข้อโครงงาน ข้อความที่ไม่ควรใช้",
            language="thai",
            number=4,
            status="ocr_failed",
        )
        failed["normalization_status"] = "success"

        result = extract_metadata_from_pages([failed])

        self.assertEqual(result.extraction_status, "failed")
        self.assertIsNone(result.metadata["title_th"])

    def test_one_failed_page_does_not_block_other_abstract_page(self) -> None:
        result = extract_metadata_from_pages(
            [
                page(None, language="thai", number=4, status="ocr_failed"),
                page(ENGLISH_PAGE, language="english", number=5),
            ]
        )

        self.assertEqual(result.metadata["title_en"], "DOCUMENT RETRIEVAL SYSTEM")
        self.assertEqual(result.stats["pages_processed"], 1)
        self.assertEqual(result.stats["pages_skipped"], 1)
        self.assertIn("unusable_normalized_page", result.warnings)

    def test_normalization_output_integrates_without_mutating_source(self) -> None:
        processing = {
            "abstract_pages": [
                {
                    "page_number": 4,
                    "language": "thai",
                    "text_source": "ocr",
                    "text": "  หัวข้อโครงงาน  ระบบทดสอบ\r\nบทคัดย่อ\r\nเนื้อหา  ",
                    "processing_status": "success",
                }
            ]
        }
        normalized = normalize_processed_document(processing)
        snapshot = copy.deepcopy(normalized)

        result = extract_metadata(normalized)

        self.assertEqual(result.metadata["title_th"], "ระบบทดสอบ")
        self.assertEqual(normalized, snapshot)
        self.assertEqual(
            normalized["abstract_pages"][0]["normalized_text"],
            "หัวข้อโครงงาน ระบบทดสอบ\nบทคัดย่อ\nเนื้อหา",
        )

    def test_same_input_produces_deterministic_output(self) -> None:
        pages = [
            page(THAI_PAGE, language="thai", number=4),
            page(ENGLISH_PAGE, language="english", number=5),
        ]

        first = extract_metadata_from_pages(pages).to_dict()
        second = extract_metadata_from_pages(pages).to_dict()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
