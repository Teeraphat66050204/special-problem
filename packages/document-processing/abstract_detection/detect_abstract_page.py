"""Detect likely Thai and English abstract pages from a PDF text layer."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence


DEFAULT_MAX_PAGES = 15
DEFAULT_TOP_K = 5

THAI_ABSTRACT_HEADING_RE = re.compile(
    r"^(?:บทคัดย่อ|บทคัดย่อภาษาไทย)\s*[:：]?$",
    re.IGNORECASE,
)
ENGLISH_ABSTRACT_HEADING_RE = re.compile(
    r"^(?:abstract|english abstract)\s*[:：]?$",
    re.IGNORECASE,
)
THAI_ABSTRACT_TERM_RE = re.compile(r"บทคัดย่อ", re.IGNORECASE)
ENGLISH_ABSTRACT_TERM_RE = re.compile(r"\babstract\b", re.IGNORECASE)
THAI_ADVISOR_RE = re.compile(r"อาจารย์ที่ปรึกษา", re.IGNORECASE)
ENGLISH_ADVISOR_RE = re.compile(r"\badvis(?:o|e)rs?\b", re.IGNORECASE)
THAI_KEYWORDS_RE = re.compile(r"คำ\s*สำคัญ", re.IGNORECASE)
ENGLISH_KEYWORDS_RE = re.compile(r"\bkey\s*words?\b", re.IGNORECASE)
STUDENT_ID_RE = re.compile(
    r"(?:รหัส(?:นักศึกษา)?|student\s+(?:id|number))\s*[:：]?\s*[A-Z]?\d{7,13}\b"
    r"|(?<!\d)\d{8,13}(?!\d)",
    re.IGNORECASE,
)
CONTENTS_HEADING_RE = re.compile(
    r"^(?:สารบัญ(?:รูป|ตาราง)?|table\s+of\s+contents|contents|"
    r"list\s+of\s+(?:figures|tables))(?:\s*\([^)]*\))?\s*[:：]?$",
    re.IGNORECASE,
)
PAGE_ENTRY_RE = re.compile(
    r"^(?=.{3,160}$).*(?:\s|[.·…])(?:\d{1,3}|[ก-ฮ]|[ivxlcdm]{1,8})$",
    re.IGNORECASE,
)
SHORT_HEADING_RE = re.compile(
    r"^(?:(?:บทที่|chapter|ภาคผนวก|appendix)\s*|"
    r"(?:\d+(?:\.\d+){0,3}|[A-Zก-ฮ])(?:[.)]|\s+)).+",
    re.IGNORECASE,
)


class AbstractDetectionError(Exception):
    """A user-facing abstract detection failure."""


@dataclass(frozen=True)
class ScoringConfig:
    """Tunable feature weights and decision thresholds."""

    thai_abstract_heading_weight: float = 5.5
    english_abstract_heading_weight: float = 5.5
    abstract_term_weight: float = 1.0
    advisor_weight: float = 1.5
    keywords_weight: float = 2.0
    student_id_weight: float = 1.0
    long_paragraph_weight: float = 2.0
    contents_heading_penalty: float = 9.0
    page_entries_penalty: float = 5.0
    short_headings_penalty: float = 2.0
    structural_precedes_english_weight: float = 4.5
    minimum_paragraph_line_length: int = 45
    minimum_paragraph_lines: int = 4
    minimum_paragraph_characters: int = 350
    minimum_page_entries: int = 5
    minimum_short_heading_lines: int = 5
    maximum_short_heading_line_length: int = 80
    maximum_preceding_abstract_pages: int = 3
    minimum_approval_drawing_items: int = 10
    candidate_threshold: float = 6.5
    confidence_scale: float = 1.75


DEFAULT_SCORING_CONFIG = ScoringConfig()


@dataclass(frozen=True)
class PageScore:
    page_index: int
    score: float
    confidence: float
    matched_features: tuple[str, ...]
    language: str
    passed_threshold: bool
    text_length: int

    @property
    def page_number(self) -> int:
        return self.page_index + 1

    def to_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "page_index": self.page_index,
            "score": self.score,
            "confidence": self.confidence,
            "matched_features": list(self.matched_features),
            "language": self.language,
            "passed_threshold": self.passed_threshold,
            "text_length": self.text_length,
        }


def normalize_text(text: str) -> str:
    """Apply minimal normalization while preserving line boundaries."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line)


def _has_matching_line(lines: Sequence[str], pattern: re.Pattern[str]) -> bool:
    return any(pattern.fullmatch(line) is not None for line in lines)


def _language_for_features(features: Sequence[str]) -> str:
    has_thai = any(feature.startswith("thai_") for feature in features)
    has_english = any(feature.startswith("english_") for feature in features)
    if has_thai and has_english:
        return "mixed"
    if has_thai:
        return "thai"
    if has_english:
        return "english"
    return "unknown"


def _has_front_matter_page_marker(lines: Sequence[str]) -> bool:
    if not lines:
        return False
    marker = lines[0].strip()
    return 0 < len(marker) <= 3 and not any(character.isdigit() for character in marker)


def _confidence(score: float, config: ScoringConfig, eligible: bool) -> float:
    exponent = -(score - config.candidate_threshold) / config.confidence_scale
    value = 1.0 / (1.0 + math.exp(max(-60.0, min(60.0, exponent))))
    if not eligible:
        value = min(value, 0.49)
    return round(value, 4)


def score_page_text(
    text: str,
    page_index: int,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> PageScore:
    """Score one page of already-extracted text without opening a PDF."""
    if page_index < 0:
        raise ValueError("page_index must be zero or greater")

    normalized = normalize_text(text)
    lines = normalized.splitlines()
    matched: list[str] = []
    score = 0.0

    thai_heading = _has_matching_line(lines, THAI_ABSTRACT_HEADING_RE)
    english_heading = _has_matching_line(lines, ENGLISH_ABSTRACT_HEADING_RE)

    if _has_front_matter_page_marker(lines):
        matched.append("front_matter_page_marker")

    if thai_heading:
        matched.append("thai_abstract_heading")
        score += config.thai_abstract_heading_weight
    elif THAI_ABSTRACT_TERM_RE.search(normalized):
        matched.append("thai_abstract_term")
        score += config.abstract_term_weight

    if english_heading:
        matched.append("english_abstract_heading")
        score += config.english_abstract_heading_weight
    elif ENGLISH_ABSTRACT_TERM_RE.search(normalized):
        matched.append("english_abstract_term")
        score += config.abstract_term_weight

    if THAI_ADVISOR_RE.search(normalized):
        matched.append("thai_advisor")
        score += config.advisor_weight
    if ENGLISH_ADVISOR_RE.search(normalized):
        matched.append("english_advisor")
        score += config.advisor_weight
    if THAI_KEYWORDS_RE.search(normalized):
        matched.append("thai_keywords")
        score += config.keywords_weight
    if ENGLISH_KEYWORDS_RE.search(normalized):
        matched.append("english_keywords")
        score += config.keywords_weight
    if STUDENT_ID_RE.search(normalized):
        matched.append("student_id")
        score += config.student_id_weight

    paragraph_lines = [
        line
        for line in lines
        if len(line) >= config.minimum_paragraph_line_length
    ]
    paragraph_characters = sum(len(line) for line in paragraph_lines)
    if (
        len(paragraph_lines) >= config.minimum_paragraph_lines
        and paragraph_characters >= config.minimum_paragraph_characters
    ):
        matched.append("long_paragraph_text")
        score += config.long_paragraph_weight

    if _has_matching_line(lines, CONTENTS_HEADING_RE):
        matched.append("contents_heading")
        score -= config.contents_heading_penalty

    page_entry_count = sum(PAGE_ENTRY_RE.fullmatch(line) is not None for line in lines)
    if page_entry_count >= config.minimum_page_entries:
        matched.append("many_page_number_entries")
        score -= config.page_entries_penalty

    short_heading_count = sum(
        len(line) <= config.maximum_short_heading_line_length
        and SHORT_HEADING_RE.match(line) is not None
        for line in lines
    )
    if short_heading_count >= config.minimum_short_heading_lines:
        matched.append("many_short_headings")
        score -= config.short_headings_penalty

    abstract_signal = thai_heading or english_heading or bool(
        THAI_ABSTRACT_TERM_RE.search(normalized)
        or ENGLISH_ABSTRACT_TERM_RE.search(normalized)
    )
    supporting_features = {
        "thai_advisor",
        "english_advisor",
        "thai_keywords",
        "english_keywords",
        "student_id",
        "long_paragraph_text",
    }.intersection(matched)
    has_heading = thai_heading or english_heading
    eligible = abstract_signal and (
        (has_heading and bool(supporting_features))
        or len(supporting_features) >= 3
    )
    rounded_score = round(score, 2)
    passed_threshold = eligible and rounded_score >= config.candidate_threshold

    return PageScore(
        page_index=page_index,
        score=rounded_score,
        confidence=_confidence(rounded_score, config, passed_threshold),
        matched_features=tuple(matched),
        language=_language_for_features(matched),
        passed_threshold=passed_threshold,
        text_length=len(normalized),
    )


def _add_pdf_structure_features(
    page_score: PageScore,
    page: Any,
    config: ScoringConfig,
) -> PageScore:
    drawing_item_count = sum(
        item[0] in {"l", "re"}
        for path in page.get_drawings()
        for item in path.get("items", [])
    )
    if drawing_item_count < config.minimum_approval_drawing_items:
        return page_score
    return replace(
        page_score,
        matched_features=(*page_score.matched_features, "approval_table_structure"),
    )


def _apply_structural_context(
    scores: Sequence[PageScore],
    config: ScoringConfig,
) -> list[PageScore]:
    """Recover likely Thai abstract starts that have a damaged text layer."""
    contextual_scores = list(scores)
    english_abstract_indices = [
        item.page_index
        for item in contextual_scores
        if item.passed_threshold
        and item.language in {"english", "mixed"}
        and "english_abstract_heading" in item.matched_features
    ]

    for english_page_index in english_abstract_indices:
        start = max(0, english_page_index - config.maximum_preceding_abstract_pages)
        possible_starts: list[PageScore] = []
        for candidate in contextual_scores[start:english_page_index]:
            features = set(candidate.matched_features)
            has_thai_result = candidate.passed_threshold and candidate.language in {
                "thai",
                "mixed",
            }
            if has_thai_result:
                continue
            if {
                "front_matter_page_marker",
                "long_paragraph_text",
            }.issubset(features) and not {
                "approval_table_structure",
                "contents_heading",
                "many_page_number_entries",
                "english_abstract_heading",
            }.intersection(features):
                possible_starts.append(candidate)

        if not possible_starts:
            continue

        # The earliest matching page is the abstract start; later pages can be
        # continuations before the English abstract begins.
        candidate = min(possible_starts, key=lambda item: item.page_index)
        matched_features = (
            *candidate.matched_features,
            "structural_precedes_english_abstract",
        )
        score = round(candidate.score + config.structural_precedes_english_weight, 2)
        passed_threshold = score >= config.candidate_threshold
        contextual_scores[candidate.page_index] = replace(
            candidate,
            score=score,
            confidence=_confidence(score, config, passed_threshold),
            matched_features=matched_features,
            language="thai",
            passed_threshold=passed_threshold,
        )

    return contextual_scores


def _build_result(
    scores: Sequence[PageScore],
    *,
    top_k: int,
    document_page_count: int,
) -> dict[str, object]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero")

    ranked = sorted(scores, key=lambda item: (-item.score, item.page_index))
    candidate_dicts = [candidate.to_dict() for candidate in ranked[:top_k]]
    qualifying = [candidate for candidate in ranked if candidate.passed_threshold]
    selected = qualifying[0] if qualifying else None
    best = ranked[0] if ranked else None
    primary_candidate = selected.to_dict() if selected else None

    return {
        "primary_candidate": primary_candidate,
        # Backward-compatible aliases for callers using the original contract.
        "page_number": selected.page_number if selected else None,
        "page_index": selected.page_index if selected else None,
        "score": selected.score if selected else (best.score if best else 0.0),
        "confidence": (
            selected.confidence if selected else (best.confidence if best else 0.0)
        ),
        "matched_features": list(
            selected.matched_features if selected else (best.matched_features if best else ())
        ),
        "language": selected.language if selected else None,
        "requires_manual_selection": selected is None,
        "scanned_pages": len(scores),
        "document_page_count": document_page_count,
        "candidates": candidate_dicts,
        "abstract_pages": [candidate.to_dict() for candidate in qualifying],
    }


def detect_from_page_texts(
    page_texts: Sequence[str],
    *,
    top_k: int = DEFAULT_TOP_K,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> dict[str, object]:
    """Detect abstract pages from page text, primarily for reuse and tests."""
    scores = _apply_structural_context([
        score_page_text(text, page_index, config)
        for page_index, text in enumerate(page_texts)
    ], config)
    return _build_result(
        scores,
        top_k=top_k,
        document_page_count=len(page_texts),
    )


def load_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AbstractDetectionError(
            "PyMuPDF is not installed. Install dependencies with "
            "'python -m pip install -r packages/document-processing/requirements.txt'."
        ) from exc
    return pymupdf


def detect_abstract_page(
    pdf_path: str | Path,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    top_k: int = DEFAULT_TOP_K,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> dict[str, object]:
    """Detect likely abstract pages in the first ``max_pages`` PDF pages."""
    path = Path(pdf_path)
    if max_pages <= 0:
        raise AbstractDetectionError("max_pages must be greater than zero.")
    if top_k <= 0:
        raise AbstractDetectionError("top_k must be greater than zero.")
    if not path.exists():
        raise AbstractDetectionError(f"PDF does not exist: '{path}'.")
    if not path.is_file():
        raise AbstractDetectionError(f"PDF path is not a file: '{path}'.")

    pymupdf = load_pymupdf()
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise AbstractDetectionError(f"Could not open PDF '{path}': {exc}") from exc

    try:
        if not document.is_pdf:
            raise AbstractDetectionError(f"Input file is not a PDF: '{path}'.")
        if document.needs_pass:
            raise AbstractDetectionError(f"PDF requires a password: '{path}'.")
        if document.page_count <= 0:
            raise AbstractDetectionError(f"PDF contains no pages: '{path}'.")

        scanned_page_count = min(max_pages, document.page_count)
        scores: list[PageScore] = []
        for page_index in range(scanned_page_count):
            try:
                page = document.load_page(page_index)
                page_text = page.get_text("text", sort=True)
            except Exception as exc:
                raise AbstractDetectionError(
                    f"Could not read text layer on page {page_index + 1} "
                    f"from '{path}': {exc}"
                ) from exc
            page_score = score_page_text(page_text, page_index, config)
            try:
                page_score = _add_pdf_structure_features(page_score, page, config)
            except Exception:
                # Text-layer detection remains usable when a PDF backend cannot
                # expose vector drawings for structural approval-page checks.
                pass
            scores.append(page_score)

        scores = _apply_structural_context(scores, config)

        return _build_result(
            scores,
            top_k=top_k,
            document_page_count=document.page_count,
        )
    finally:
        document.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect Thai and English abstract pages from a PDF text layer.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to a PDF")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Number of pages to scan from the beginning (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Number of ranked candidates to show (default: {DEFAULT_TOP_K})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    try:
        result = detect_abstract_page(
            args.input,
            max_pages=args.max_pages,
            top_k=args.top_k,
        )
    except AbstractDetectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
