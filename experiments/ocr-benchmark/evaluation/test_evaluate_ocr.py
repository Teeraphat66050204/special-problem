"""Tests for Thai-aware OCR evaluation."""

from __future__ import annotations

import unittest

from evaluate_ocr import (
    levenshtein_distance,
    load_thai_tokenizer,
    normalize_text,
    tokenize_thai_words,
)


class ThaiWordEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tokenizer, _ = load_thai_tokenizer()
        cls.tokenizer = staticmethod(tokenizer)

    def test_tokenizes_thai_sentence_without_whitespace(self) -> None:
        text = normalize_text("ฉันรักภาษาไทย")

        tokens = tokenize_thai_words(text, self.tokenizer)

        self.assertGreater(len(tokens), 1)
        self.assertNotEqual(tokens, [text])
        self.assertEqual("".join(tokens), text)

    def test_thai_wer_uses_segmented_words(self) -> None:
        reference = tokenize_thai_words(
            normalize_text("ฉันรักภาษาไทย"), self.tokenizer
        )
        hypothesis = tokenize_thai_words(
            normalize_text("ฉันชอบภาษาไทย"), self.tokenizer
        )

        edits = levenshtein_distance(reference, hypothesis)
        wer = edits / len(reference)

        self.assertEqual(edits, 1)
        self.assertGreater(len(reference), 1)
        self.assertLess(wer, 1.0)


if __name__ == "__main__":
    unittest.main()
