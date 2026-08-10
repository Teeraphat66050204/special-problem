"""Tests for selective in-memory PDF page rendering."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr.render import PNG_SIGNATURE, PageRenderError, render_page_for_ocr


class RenderTests(unittest.TestCase):
    def test_selected_page_is_rendered_as_300_dpi_rgb_png(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "two-pages.pdf"
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "first")
            document.new_page().insert_text((72, 72), "second")
            document.save(path)
            document.close()

            result = render_page_for_ocr(path, 1, page_number=2)

        self.assertTrue(result.data.startswith(PNG_SIGNATURE))
        self.assertEqual(result.page_index, 1)
        self.assertEqual(result.page_number, 2)
        self.assertEqual(result.dpi, 300)
        self.assertEqual(result.color_space, "RGB")
        self.assertEqual(result.preprocessing, "none")

    def test_invalid_page_is_controlled_error(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "one-page.pdf"
            document = pymupdf.open()
            document.new_page()
            document.save(path)
            document.close()
            with self.assertRaises(PageRenderError):
                render_page_for_ocr(path, 1)


if __name__ == "__main__":
    unittest.main()
