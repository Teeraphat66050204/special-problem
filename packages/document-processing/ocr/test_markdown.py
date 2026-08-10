"""Tests for deterministic Typhoon Markdown conversion."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from markdown_it import MarkdownIt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.markdown import markdown_to_plain_text


class MarkdownConversionTests(unittest.TestCase):
    def test_visible_content_and_table_order_are_deterministic(self) -> None:
        markdown = (
            "# ABSTRACT\n\n"
            "| Field | Value |\n|---|---|\n| Advisor | Jane |\n\n"
            "<page_number>4</page_number>"
        )
        first = markdown_to_plain_text(markdown, MarkdownIt)
        second = markdown_to_plain_text(markdown, MarkdownIt)
        self.assertEqual(first, second)
        self.assertIn("ABSTRACT", first)
        self.assertLess(first.index("Field"), first.index("Advisor"))
        self.assertTrue(first.rstrip().endswith("4"))


if __name__ == "__main__":
    unittest.main()
