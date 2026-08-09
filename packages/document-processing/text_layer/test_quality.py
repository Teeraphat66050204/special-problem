"""Tests for rule-based PDF text-layer quality assessment."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from text_layer.quality import assess_text_quality


THAI_BODY = "\n".join(
    [
        "โครงงานนี้มีวัตถุประสงค์เพื่อพัฒนาระบบจัดเก็บและค้นคืนเอกสารภาษาไทยให้มีประสิทธิภาพ",
        "ระบบรองรับข้อมูลจากเอกสารหลายรูปแบบและตรวจสอบผลลัพธ์อย่างเป็นระบบ",
        "วิธีดำเนินงานประกอบด้วยการรวบรวมข้อมูล การออกแบบ และการประเมินผล",
        "ผลการทดลองแสดงว่าระบบประมวลผลเอกสารและค้นคืนข้อมูลได้อย่างถูกต้อง",
        "การประเมินครอบคลุมคุณภาพข้อความ ระยะเวลาประมวลผล และข้อจำกัด",
        "ผลลัพธ์ใช้เป็นพื้นฐานสำหรับการพัฒนาระบบสารสนเทศในขั้นต่อไปได้",
    ]
)

ENGLISH_BODY = "\n".join(
    [
        "This project develops a document storage and retrieval system for academic reports.",
        "The workflow extracts information while preserving the original source text.",
        "The method was evaluated with representative documents and controlled tests.",
        "Results show that the system retrieves relevant records consistently.",
        "The evaluation covers text quality, processing time, and limitations.",
        "These findings provide a practical baseline for subsequent improvements.",
    ]
)


class TextLayerQualityTests(unittest.TestCase):
    def test_readable_thai_abstract_is_good(self) -> None:
        text = (
            "บทคัดย่อ\nรหัสนักศึกษา 6501234567\nอาจารย์ที่ปรึกษา: ดร. ตัวอย่าง\n"
            f"{THAI_BODY}\nคำสำคัญ: เอกสาร การค้นคืน คุณภาพ"
        )

        result = assess_text_quality(text, language="thai")

        self.assertEqual(result["quality"], "good")
        self.assertFalse(result["requires_ocr"])

    def test_readable_english_abstract_is_good(self) -> None:
        text = (
            "ABSTRACT\nStudent ID: 6501234567\nAdvisor: Dr. Example\n"
            f"{ENGLISH_BODY}\nKeywords: documents, retrieval, quality"
        )

        result = assess_text_quality(text, language="english")

        self.assertEqual(result["quality"], "good")
        self.assertFalse(result["requires_ocr"])

    def test_empty_text_layer_is_missing(self) -> None:
        result = assess_text_quality(" \r\n\t", language="thai")

        self.assertFalse(result["available"])
        self.assertEqual(result["quality"], "missing")
        self.assertTrue(result["requires_ocr"])
        self.assertEqual(result["reasons"], ["empty_text_layer"])

    def test_abnormally_short_text_is_poor(self) -> None:
        result = assess_text_quality("ABSTRACT\nshort", language="english")

        self.assertEqual(result["quality"], "poor")
        self.assertIn("short_text_layer", result["reasons"])

    def test_replacement_and_control_characters_reduce_quality(self) -> None:
        corrupt = "ABSTRACT\n" + ("text\ufffd\x00" * 120)

        result = assess_text_quality(corrupt, language="english")

        self.assertEqual(result["quality"], "poor")
        self.assertIn("replacement_characters", result["reasons"])
        self.assertIn("control_characters", result["reasons"])

    def test_broken_thai_intraword_sequences_are_poor(self) -> None:
        corrupt = "บทคัดย่อ\n" + " ".join(["ข%อ", "ค:า", "ป(ญ"] * 100)

        result = assess_text_quality(corrupt, language="thai")

        self.assertEqual(result["quality"], "poor")
        self.assertIn("broken_thai_intraword_sequences", result["reasons"])

    def test_valid_mixed_thai_english_is_not_rejected(self) -> None:
        text = (
            "บทคัดย่อ ABSTRACT\nอาจารย์ที่ปรึกษา Advisor: Dr. Example\n"
            f"{THAI_BODY}\n{ENGLISH_BODY}\nคำสำคัญ Keywords: document quality"
        )

        result = assess_text_quality(text, language="mixed")

        self.assertEqual(result["quality"], "good")
        self.assertFalse(result["requires_ocr"])

    def test_low_quality_requires_ocr(self) -> None:
        result = assess_text_quality("damaged", language="english")

        self.assertTrue(result["requires_ocr"])

    def test_good_quality_does_not_require_ocr(self) -> None:
        text = f"ABSTRACT\nAdvisor: Example\n{ENGLISH_BODY}\nKeywords: evaluation"

        result = assess_text_quality(text, language="english")

        self.assertFalse(result["requires_ocr"])


if __name__ == "__main__":
    unittest.main()
