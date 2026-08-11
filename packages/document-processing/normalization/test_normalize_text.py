"""Tests for conservative canonical text formatting."""

from __future__ import annotations

import sys
import unittest
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization import NormalizationConfig, normalize_text


class NormalizeTextTests(unittest.TestCase):
    def test_unicode_nfc(self) -> None:
        result = normalize_text("Cafe\u0301")

        self.assertEqual(result.normalized_text, "Caf\u00e9")
        self.assertIn("unicode_nfc", result.operations)

    def test_normalizes_crlf_cr_and_unicode_line_endings(self) -> None:
        result = normalize_text("one\r\ntwo\rthree\u2028four")

        self.assertEqual(result.normalized_text, "one\ntwo\nthree\nfour")
        self.assertIn("normalized_line_endings", result.operations)

    def test_collapses_repeated_horizontal_spaces(self) -> None:
        result = normalize_text("  A   mixed  line  ")

        self.assertEqual(result.normalized_text, "A mixed line")
        self.assertIn("collapsed_horizontal_whitespace", result.operations)

    def test_replaces_tabs_by_default_and_can_preserve_them(self) -> None:
        self.assertEqual(normalize_text("A\t\tB").normalized_text, "A B")

        preserved = normalize_text("A\tB", NormalizationConfig(replace_tabs=False))
        self.assertEqual(preserved.normalized_text, "A\tB")

    def test_normalizes_nbsp_and_unicode_horizontal_space(self) -> None:
        result = normalize_text("Thai\u00a0English\u2003Title")

        self.assertEqual(result.normalized_text, "Thai English Title")
        self.assertIn("normalized_unicode_whitespace", result.operations)

    def test_removes_bom_and_selected_zero_width_characters(self) -> None:
        result = normalize_text("\ufeffab\u200bcd\u2060ef")

        self.assertEqual(result.normalized_text, "abcdef")
        self.assertIn("removed_bom", result.operations)
        self.assertIn("removed_zero_width_characters", result.operations)

    def test_does_not_remove_joiners_by_default(self) -> None:
        result = normalize_text("A\u200cB\u200dC")

        self.assertEqual(result.normalized_text, "A\u200cB\u200dC")

    def test_limits_blank_lines_and_preserves_paragraph_structure(self) -> None:
        result = normalize_text("\n\nfirst\n\n\n\nsecond\n\n")

        self.assertEqual(result.normalized_text, "first\n\n\nsecond")
        self.assertEqual(result.lines, ["first", "", "", "second"])
        self.assertIn("limited_blank_lines", result.operations)
        self.assertIn("trimmed_document_whitespace", result.operations)

    def test_thai_english_mixed_text_keeps_content_and_lines(self) -> None:
        source = "บทคัดย่อ: ระบบทดสอบ\nABSTRACT: A Test/System (2026)"

        self.assertEqual(normalize_text(source).normalized_text, source)

    def test_preserves_student_id_and_academic_year(self) -> None:
        source = "รหัสนักศึกษา: 6501234567\nปีการศึกษา 2569/2026"

        self.assertEqual(normalize_text(source).normalized_text, source)

    def test_preserves_english_title_punctuation(self) -> None:
        source = "Title: Design, Build & Test - A/B (Version #2)"

        self.assertEqual(normalize_text(source).normalized_text, source)

    def test_preserves_keywords_and_advisor(self) -> None:
        source = "คำสำคัญ: OCR, PDF/เอกสาร; ภาษาไทย-อังกฤษ\nอาจารย์ที่ปรึกษา: ดร. สมชาย ใจดี"

        self.assertEqual(normalize_text(source).normalized_text, source)

    def test_thai_combining_marks_remain_unicode_correct(self) -> None:
        source = "กำลังศึกษาเรื่องน้ำ"
        result = normalize_text(source)

        self.assertEqual(result.normalized_text, unicodedata.normalize("NFC", source))
        self.assertEqual(
            [unicodedata.name(character) for character in result.normalized_text],
            [unicodedata.name(character) for character in source],
        )

    def test_suspicious_thai_character_spacing_warns_without_reconstruction(self) -> None:
        broken = "ห ั ว ข้ อ ส ห ก ิ จ ศึ ก ษ า"
        result = normalize_text(broken)

        self.assertEqual(result.normalized_text, broken)
        self.assertIn("suspicious_thai_character_spacing", result.warnings)
        self.assertNotEqual(result.normalized_text, "หัวข้อสหกิจศึกษา")

    def test_normal_thai_name_spacing_is_not_flagged(self) -> None:
        result = normalize_text("นาย  ธีรภัทร   ผลเจริญ")

        self.assertEqual(result.normalized_text, "นาย ธีรภัทร ผลเจริญ")
        self.assertEqual(result.warnings, ())

    def test_empty_text_has_zero_lines(self) -> None:
        result = normalize_text("")

        self.assertEqual(result.normalized_text, "")
        self.assertEqual(result.lines, [])
        self.assertEqual(result.stats.line_count, 0)
        self.assertFalse(result.changed)

    def test_rejects_none_instead_of_stringifying_it(self) -> None:
        with self.assertRaisesRegex(TypeError, "text must be a string"):
            normalize_text(None)  # type: ignore[arg-type]

    def test_config_controls_blank_lines_and_zero_width_removal(self) -> None:
        config = NormalizationConfig(
            max_consecutive_blank_lines=0,
            remove_zero_width_characters=False,
        )
        result = normalize_text("a\u200b\n\n\nb", config)

        self.assertEqual(result.normalized_text, "a\u200b\nb")

    def test_normalization_is_idempotent(self) -> None:
        source = "\ufeff  Cafe\u0301\t\u00a0title \r\n\r\n\r\n\r\nไทย  English  "
        once = normalize_text(source)
        twice = normalize_text(once.normalized_text)

        self.assertEqual(twice.normalized_text, once.normalized_text)
        self.assertFalse(twice.changed)
        self.assertEqual(twice.operations, ())

    def test_result_is_structured_and_retains_original(self) -> None:
        source = "  text  "
        data = normalize_text(source).to_dict()

        self.assertEqual(data["original_text"], source)
        self.assertEqual(data["normalized_text"], "text")
        self.assertTrue(data["changed"])
        self.assertEqual(data["stats"]["original_length"], len(source))


if __name__ == "__main__":
    unittest.main()
