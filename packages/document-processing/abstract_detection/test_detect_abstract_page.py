"""Tests for text-layer abstract page detection."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from abstract_detection.detect_abstract_page import (
    AbstractDetectionError,
    DEFAULT_SCORING_CONFIG,
    _add_pdf_structure_features,
    _apply_structural_context,
    detect_abstract_page,
    detect_from_page_texts,
    normalize_text,
    score_page_text,
)


THAI_BODY = "\n".join(
    [
        "โครงงานนี้มีวัตถุประสงค์เพื่อพัฒนาระบบจัดเก็บและสืบค้นเอกสารภาษาไทยให้มีประสิทธิภาพ",
        "ระบบได้รับการออกแบบให้รองรับข้อมูลจากเอกสารหลายรูปแบบและตรวจสอบผลลัพธ์อย่างเป็นระบบ",
        "วิธีดำเนินงานประกอบด้วยการรวบรวมข้อมูล การออกแบบกระบวนการ และการประเมินผลด้วยชุดทดสอบ",
        "ผลการทดลองแสดงให้เห็นว่าระบบสามารถประมวลผลเอกสารและค้นคืนข้อมูลที่เกี่ยวข้องได้ถูกต้อง",
        "การประเมินครอบคลุมทั้งความถูกต้องของข้อความ ระยะเวลาประมวลผล และข้อจำกัดของระบบ",
        "ผลลัพธ์ที่ได้สามารถนำไปใช้เป็นพื้นฐานสำหรับการพัฒนาระบบสารสนเทศในขั้นต่อไปได้",
    ]
)

ENGLISH_BODY = "\n".join(
    [
        "This project develops a document storage and retrieval system for academic project reports.",
        "The proposed workflow extracts structured information and preserves the original source text.",
        "The method was evaluated with representative documents under a controlled test procedure.",
        "Experimental results show that the system retrieves relevant records with consistent accuracy.",
        "The evaluation covers text quality, processing time, and known limitations of the approach.",
        "These results provide a practical baseline for subsequent document processing improvements.",
    ]
)


class AbstractDetectionTests(unittest.TestCase):
    def test_minimal_text_normalization(self) -> None:
        self.assertEqual(normalize_text("  A\t  B \r\n C  "), "A B\nC")

    def test_thai_abstract_page(self) -> None:
        text = (
            "บทคัดย่อ\nรหัสนักศึกษา 6501234567\n"
            "อาจารย์ที่ปรึกษา: ดร. ตัวอย่าง\n"
            f"{THAI_BODY}\nคำสำคัญ: เอกสาร การค้นคืน"
        )
        page = score_page_text(text, page_index=3)

        self.assertTrue(page.passed_threshold)
        self.assertEqual(page.language, "thai")
        self.assertIn("thai_abstract_heading", page.matched_features)
        self.assertIn("long_paragraph_text", page.matched_features)

    def test_english_abstract_page(self) -> None:
        text = (
            "ABSTRACT\nStudent ID: 6501234567\nAdvisor: Dr. Example\n"
            f"{ENGLISH_BODY}\nKeywords: documents, retrieval"
        )
        page = score_page_text(text, page_index=4)

        self.assertTrue(page.passed_threshold)
        self.assertEqual(page.language, "english")
        self.assertIn("english_abstract_heading", page.matched_features)
        self.assertIn("english_keywords", page.matched_features)

    def test_contents_page_with_abstract_does_not_win(self) -> None:
        contents = "\n".join(
            [
                "สารบัญ",
                "บทคัดย่อ",
                "กิตติกรรมประกาศ ........ ก",
                "บทที่ 1 บทนำ ........ 1",
                "ความเป็นมาและความสำคัญ ........ 2",
                "วัตถุประสงค์ ........ 3",
                "ขอบเขตโครงงาน ........ 4",
                "บทที่ 2 เอกสารที่เกี่ยวข้อง ........ 5",
                "บทที่ 3 วิธีดำเนินงาน ........ 12",
                "บทที่ 4 ผลการดำเนินงาน ........ 25",
                "บทที่ 5 สรุปผล ........ 40",
                "บรรณานุกรม ........ 45",
            ]
        )
        abstract = f"บทคัดย่อ\nอาจารย์ที่ปรึกษา: ดร. ตัวอย่าง\n{THAI_BODY}"

        result = detect_from_page_texts([contents, abstract])

        self.assertEqual(result["page_number"], 2)
        toc_candidate = next(
            item for item in result["candidates"] if item["page_number"] == 1
        )
        self.assertIn("contents_heading", toc_candidate["matched_features"])
        self.assertIn("many_short_headings", toc_candidate["matched_features"])
        self.assertFalse(toc_candidate["passed_threshold"])

    def test_ordinary_page_is_not_a_candidate(self) -> None:
        result = detect_from_page_texts(
            ["บทที่ 1\nบทนำ\n" + ENGLISH_BODY],
        )

        self.assertIsNone(result["page_number"])
        self.assertTrue(result["requires_manual_selection"])
        self.assertEqual(result["abstract_pages"], [])

    def test_no_candidate_above_configured_threshold(self) -> None:
        config = replace(DEFAULT_SCORING_CONFIG, candidate_threshold=20.0)
        result = detect_from_page_texts(
            [f"ABSTRACT\nAdvisor: Dr. Example\n{ENGLISH_BODY}\nKeywords: test"],
            config=config,
        )

        self.assertIsNone(result["page_number"])
        self.assertTrue(result["requires_manual_selection"])

    def test_missing_pdf_has_clear_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing.pdf"
            with self.assertRaisesRegex(AbstractDetectionError, "does not exist"):
                detect_abstract_page(missing)

    def test_reports_thai_and_english_abstract_pages(self) -> None:
        thai = f"บทคัดย่อ\nอาจารย์ที่ปรึกษา: ดร. ตัวอย่าง\n{THAI_BODY}"
        english = f"ABSTRACT\nAdvisor: Dr. Example\n{ENGLISH_BODY}"

        result = detect_from_page_texts([thai, english], top_k=2)

        self.assertEqual(
            {item["page_number"] for item in result["abstract_pages"]},
            {1, 2},
        )
        self.assertEqual(result["primary_candidate"]["page_number"], 1)

    def test_structural_thai_candidate_survives_damaged_text_layer(self) -> None:
        damaged_thai = (
            "ก\nTitle-like metadata\nStudent ID 61050154\n"
            + "\n".join(["legacy encoded paragraph content " * 4] * 6)
        )
        english = f"ABSTRACT\nAdvisor: Dr. Example\n{ENGLISH_BODY}"

        result = detect_from_page_texts(
            ["approval page", damaged_thai, english],
            top_k=3,
        )

        thai_candidate = next(
            item for item in result["abstract_pages"] if item["language"] == "thai"
        )
        self.assertEqual(thai_candidate["page_number"], 2)
        self.assertIn(
            "structural_precedes_english_abstract",
            thai_candidate["matched_features"],
        )
        required_fields = {
            "page_number",
            "page_index",
            "language",
            "score",
            "matched_features",
        }
        self.assertTrue(required_fields.issubset(thai_candidate))

    def test_approval_table_is_not_promoted_as_structural_abstract(self) -> None:
        class ApprovalPage:
            @staticmethod
            def get_drawings() -> list[dict[str, object]]:
                return [{"items": [("l", None, None)] * 10}]

        approval_text = (
            "ก\nStudent ID 61050154\n"
            + "\n".join(["approval paragraph content " * 4] * 6)
        )
        english_text = f"ABSTRACT\nAdvisor: Dr. Example\n{ENGLISH_BODY}"
        approval_score = score_page_text(approval_text, page_index=0)
        approval_score = _add_pdf_structure_features(
            approval_score,
            ApprovalPage(),
            DEFAULT_SCORING_CONFIG,
        )
        english_score = score_page_text(english_text, page_index=1)

        contextual = _apply_structural_context(
            [approval_score, english_score],
            DEFAULT_SCORING_CONFIG,
        )

        self.assertFalse(contextual[0].passed_threshold)
        self.assertIn("approval_table_structure", contextual[0].matched_features)


if __name__ == "__main__":
    unittest.main()
