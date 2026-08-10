"""Rule-based quality assessment for extracted PDF text layers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .extract_text_layer import normalize_for_quality


THAI_HEADING_RE = re.compile(r"(?:^|\n)\s*บทคัดย่อ(?:ภาษาไทย)?\s*(?:\n|$)", re.I)
ENGLISH_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:english\s+)?abstract\s*(?:\n|$)",
    re.I,
)
THAI_ADVISOR_RE = re.compile(r"อาจารย์ที่ปรึกษา", re.I)
ENGLISH_ADVISOR_RE = re.compile(r"\badvis(?:o|e)rs?\b", re.I)
THAI_KEYWORDS_RE = re.compile(r"คำ\s*สำคัญ", re.I)
ENGLISH_KEYWORDS_RE = re.compile(r"\bkey\s*words?\b", re.I)
STUDENT_ID_RE = re.compile(
    r"(?:รหัส(?:นักศึกษา)?|student\s+(?:id|number))\s*[:：]?\s*[A-Z]?\d{7,13}\b"
    r"|(?<!\d)\d{8,13}(?!\d)",
    re.I,
)
THAI_BRIDGE_RE = re.compile(
    r"[\u0e00-\u0e7f][^\s\u0e00-\u0e7f]{1,2}[\u0e00-\u0e7f]"
)


@dataclass(frozen=True)
class QualityConfig:
    """Tunable component weights, thresholds, and corruption penalties."""

    amount_weight: float = 0.25
    readability_weight: float = 0.30
    language_weight: float = 0.25
    structure_weight: float = 0.20
    amount_character_weight: float = 0.80
    amount_line_weight: float = 0.20
    readability_replacement_penalty: float = 4.0
    readability_control_penalty: float = 4.0
    readability_unusual_symbol_penalty: float = 2.0
    heading_structure_weight: float = 0.30
    advisor_structure_weight: float = 0.15
    keywords_structure_weight: float = 0.20
    student_id_structure_weight: float = 0.10
    paragraph_structure_weight: float = 0.25
    minimum_acceptable_characters: int = 120
    minimum_good_characters: int = 400
    minimum_good_lines: int = 5
    minimum_paragraph_characters: int = 300
    minimum_paragraph_lines: int = 4
    minimum_readable_ratio: float = 0.96
    maximum_replacement_ratio: float = 0.005
    maximum_control_ratio: float = 0.005
    maximum_unusual_symbol_ratio: float = 0.08
    latin_extended_warning_ratio: float = 0.02
    latin_extended_poor_ratio: float = 0.08
    latin_extended_severe_ratio: float = 0.20
    thai_bridge_warning_ratio: float = 0.01
    thai_bridge_poor_ratio: float = 0.02
    minimum_thai_script_ratio: float = 0.25
    minimum_english_script_ratio: float = 0.55
    minimum_structure_score: float = 0.45
    good_quality_threshold: float = 0.70
    latin_extended_warning_penalty: float = 0.10
    latin_extended_poor_penalty: float = 0.20
    latin_extended_severe_penalty: float = 0.35
    thai_bridge_warning_penalty: float = 0.12
    thai_bridge_poor_penalty: float = 0.25


DEFAULT_QUALITY_CONFIG = QualityConfig()


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _amount_score(
    non_whitespace_count: int,
    line_count: int,
    config: QualityConfig,
) -> float:
    if non_whitespace_count >= config.minimum_good_characters:
        character_score = 1.0
    elif non_whitespace_count >= config.minimum_acceptable_characters:
        span = config.minimum_good_characters - config.minimum_acceptable_characters
        character_score = 0.4 + 0.6 * (
            (non_whitespace_count - config.minimum_acceptable_characters) / span
        )
    else:
        character_score = 0.4 * (
            non_whitespace_count / config.minimum_acceptable_characters
        )
    line_score = min(1.0, line_count / config.minimum_good_lines)
    return (
        config.amount_character_weight * character_score
        + config.amount_line_weight * line_score
    )


def _language_score(
    language: str,
    thai_ratio: float,
    english_ratio: float,
    config: QualityConfig,
) -> float:
    normalized_language = language.casefold()
    if normalized_language in {"thai", "th", "tha"}:
        return min(1.0, thai_ratio / config.minimum_thai_script_ratio)
    if normalized_language in {"english", "en", "eng"}:
        return min(1.0, english_ratio / config.minimum_english_script_ratio)
    if normalized_language == "mixed":
        combined = min(
            1.0,
            (thai_ratio + english_ratio)
            / (config.minimum_thai_script_ratio + 0.25),
        )
        both_present = min(1.0, min(thai_ratio, english_ratio) / 0.05)
        return 0.7 * combined + 0.3 * both_present
    return min(1.0, (thai_ratio + english_ratio) / 0.55)


def _structure_features(
    normalized: str,
    line_count: int,
    non_whitespace_count: int,
    language: str,
    config: QualityConfig,
) -> tuple[float, list[str]]:
    normalized_language = language.casefold()
    wants_thai = normalized_language in {"thai", "th", "tha", "mixed", "unknown"}
    wants_english = normalized_language in {
        "english",
        "en",
        "eng",
        "mixed",
        "unknown",
    }
    features: list[str] = []
    heading = (wants_thai and THAI_HEADING_RE.search(normalized)) or (
        wants_english and ENGLISH_HEADING_RE.search(normalized)
    )
    advisor = (wants_thai and THAI_ADVISOR_RE.search(normalized)) or (
        wants_english and ENGLISH_ADVISOR_RE.search(normalized)
    )
    keywords = (wants_thai and THAI_KEYWORDS_RE.search(normalized)) or (
        wants_english and ENGLISH_KEYWORDS_RE.search(normalized)
    )
    student_id = STUDENT_ID_RE.search(normalized)
    paragraph = (
        non_whitespace_count >= config.minimum_paragraph_characters
        and line_count >= config.minimum_paragraph_lines
    )

    score = 0.0
    for present, feature, weight in (
        (heading, "abstract_heading", config.heading_structure_weight),
        (advisor, "advisor", config.advisor_structure_weight),
        (keywords, "keywords", config.keywords_structure_weight),
        (student_id, "student_id", config.student_id_structure_weight),
        (paragraph, "paragraph_like_text", config.paragraph_structure_weight),
    ):
        if present:
            features.append(feature)
            score += weight
    return score, features


def assess_text_quality(
    raw_text: str,
    *,
    language: str = "unknown",
    normalized_text: str | None = None,
    config: QualityConfig = DEFAULT_QUALITY_CONFIG,
) -> dict[str, object]:
    """Classify a raw text layer as good, poor, or missing."""
    normalized = (
        normalize_for_quality(raw_text) if normalized_text is None else normalized_text
    )
    non_whitespace_count = sum(not character.isspace() for character in raw_text)
    line_count = sum(bool(line.strip()) for line in raw_text.splitlines())
    approximate_word_count = len(re.findall(r"\S+", normalized))
    available = non_whitespace_count > 0

    if not available:
        return {
            "available": False,
            "quality_score": 0.0,
            "quality": "missing",
            "requires_ocr": True,
            "reasons": ["empty_text_layer"],
            "line_count": 0,
            "approximate_word_count": 0,
            "features": {},
        }

    denominator = non_whitespace_count
    replacement_count = raw_text.count("\ufffd")
    control_count = sum(
        not character.isspace()
        and unicodedata.category(character) in {"Cc", "Cf"}
        for character in raw_text
    )
    unusual_symbol_count = sum(
        not character.isspace()
        and (
            unicodedata.category(character) in {"Co", "Cn", "Cs"}
            or unicodedata.category(character).startswith("S")
        )
        for character in raw_text
    )
    readable_count = sum(
        not character.isspace()
        and character.isprintable()
        and character != "\ufffd"
        and unicodedata.category(character) not in {"Cc", "Cf", "Co", "Cn", "Cs"}
        for character in raw_text
    )
    thai_count = sum("\u0e00" <= character <= "\u0e7f" for character in raw_text)
    english_count = sum(
        character.isascii() and character.isalpha() for character in raw_text
    )
    latin_extended_count = sum(
        "\u00c0" <= character <= "\u024f" for character in raw_text
    )
    thai_bridge_count = len(THAI_BRIDGE_RE.findall(raw_text))

    readable_ratio = _ratio(readable_count, denominator)
    replacement_ratio = _ratio(replacement_count, denominator)
    control_ratio = _ratio(control_count, denominator)
    unusual_symbol_ratio = _ratio(unusual_symbol_count, denominator)
    thai_ratio = _ratio(thai_count, denominator)
    english_ratio = _ratio(english_count, denominator)
    latin_extended_ratio = _ratio(latin_extended_count, denominator)
    thai_bridge_ratio = _ratio(thai_bridge_count, denominator)

    amount_score = _amount_score(non_whitespace_count, line_count, config)
    readability_score = max(
        0.0,
        min(
            1.0,
            readable_ratio
            - config.readability_replacement_penalty * replacement_ratio
            - config.readability_control_penalty * control_ratio
            - config.readability_unusual_symbol_penalty * unusual_symbol_ratio,
        ),
    )
    language_score = _language_score(
        language,
        thai_ratio,
        english_ratio,
        config,
    )
    structure_score, structure_features = _structure_features(
        normalized,
        line_count,
        non_whitespace_count,
        language,
        config,
    )

    score = (
        config.amount_weight * amount_score
        + config.readability_weight * readability_score
        + config.language_weight * language_score
        + config.structure_weight * structure_score
    )
    reasons: list[str] = []

    if non_whitespace_count < config.minimum_acceptable_characters:
        reasons.append("short_text_layer")
    elif non_whitespace_count < config.minimum_good_characters:
        reasons.append("limited_text_amount")
    if readable_ratio < config.minimum_readable_ratio:
        reasons.append("low_readable_character_ratio")
    if replacement_ratio > config.maximum_replacement_ratio:
        reasons.append("replacement_characters")
    if control_ratio > config.maximum_control_ratio:
        reasons.append("control_characters")
    if unusual_symbol_ratio > config.maximum_unusual_symbol_ratio:
        reasons.append("high_unusual_symbol_ratio")

    if latin_extended_ratio >= config.latin_extended_severe_ratio:
        score -= config.latin_extended_severe_penalty
        reasons.append("suspicious_latin_extended_characters")
    elif latin_extended_ratio >= config.latin_extended_poor_ratio:
        score -= config.latin_extended_poor_penalty
        reasons.append("suspicious_latin_extended_characters")
    elif latin_extended_ratio >= config.latin_extended_warning_ratio:
        score -= config.latin_extended_warning_penalty
        reasons.append("suspicious_latin_extended_characters")

    normalized_language = language.casefold()
    expects_thai = normalized_language in {"thai", "th", "tha", "mixed"}
    expects_english = normalized_language in {"english", "en", "eng", "mixed"}
    if expects_thai and thai_bridge_ratio >= config.thai_bridge_poor_ratio:
        score -= config.thai_bridge_poor_penalty
        reasons.append("broken_thai_intraword_sequences")
    elif expects_thai and thai_bridge_ratio >= config.thai_bridge_warning_ratio:
        score -= config.thai_bridge_warning_penalty
        reasons.append("broken_thai_intraword_sequences")
    if expects_thai and thai_ratio < config.minimum_thai_script_ratio:
        reasons.append("low_thai_script_ratio")
    if expects_english and english_ratio < config.minimum_english_script_ratio:
        reasons.append("low_english_script_ratio")
    if structure_score < config.minimum_structure_score:
        reasons.append("missing_expected_abstract_structure")

    quality_score = round(max(0.0, min(1.0, score)), 4)
    quality = "good" if quality_score >= config.good_quality_threshold else "poor"
    if quality == "poor" and not reasons:
        reasons.append("quality_score_below_threshold")
    if quality == "good" and not reasons:
        reasons.append("quality_checks_passed")

    return {
        "available": True,
        "quality_score": quality_score,
        "quality": quality,
        "requires_ocr": quality != "good",
        "reasons": reasons,
        "line_count": line_count,
        "approximate_word_count": approximate_word_count,
        "structure_features": structure_features,
        "features": {
            "amount_score": round(amount_score, 4),
            "readability_score": round(readability_score, 4),
            "language_score": round(language_score, 4),
            "structure_score": round(structure_score, 4),
            "readable_character_ratio": round(readable_ratio, 4),
            "replacement_character_ratio": round(replacement_ratio, 4),
            "control_character_ratio": round(control_ratio, 4),
            "unusual_symbol_ratio": round(unusual_symbol_ratio, 4),
            "thai_script_ratio": round(thai_ratio, 4),
            "english_script_ratio": round(english_ratio, 4),
            "latin_extended_ratio": round(latin_extended_ratio, 4),
            "thai_intraword_sequence_ratio": round(thai_bridge_ratio, 4),
        },
    }
