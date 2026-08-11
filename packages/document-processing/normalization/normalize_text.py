"""Conservative Unicode and whitespace normalization for extracted text."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from normalization.models import (  # type: ignore[import-not-found]
        DEFAULT_NORMALIZATION_CONFIG,
        NormalizationConfig,
        NormalizationResult,
        NormalizationStats,
    )
else:
    from .models import (
        DEFAULT_NORMALIZATION_CONFIG,
        NormalizationConfig,
        NormalizationResult,
        NormalizationStats,
    )


UNICODE_LINE_ENDINGS = ("\u0085", "\u2028", "\u2029")
UNICODE_HORIZONTAL_SPACES = frozenset(
    {
        "\u00a0",  # no-break space
        "\u1680",  # ogham space mark
        "\u2000",
        "\u2001",
        "\u2002",
        "\u2003",
        "\u2004",
        "\u2005",
        "\u2006",
        "\u2007",
        "\u2008",
        "\u2009",
        "\u200a",
        "\u202f",
        "\u205f",
        "\u3000",
    }
)
THAI_ONLY_RE = re.compile(r"^[\u0e00-\u0e7f]+$")


def _record_change(
    current: str,
    replacement: str,
    operation: str,
    operations: list[str],
) -> str:
    if replacement != current:
        operations.append(operation)
    return replacement


def _normalize_line_endings(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for character in UNICODE_LINE_ENDINGS:
        normalized = normalized.replace(character, "\n")
    return normalized


def _normalize_unicode_spaces(text: str) -> str:
    return "".join(
        " " if character in UNICODE_HORIZONTAL_SPACES else character
        for character in text
    )


def _limit_blank_lines(lines: list[str], maximum: int) -> list[str]:
    limited: list[str] = []
    blank_count = 0
    for line in lines:
        if line:
            blank_count = 0
            limited.append(line)
            continue
        blank_count += 1
        if blank_count <= maximum:
            limited.append(line)
    return limited


def _has_suspicious_thai_character_spacing(text: str) -> bool:
    """Detect likely character fragments without attempting reconstruction."""
    for line in text.splitlines():
        run_length = 0
        for token in line.split():
            if THAI_ONLY_RE.fullmatch(token) and len(token) <= 2:
                run_length += 1
                if run_length >= 5:
                    return True
            else:
                run_length = 0
    return False


def normalize_text(
    text: str,
    config: NormalizationConfig = DEFAULT_NORMALIZATION_CONFIG,
) -> NormalizationResult:
    """Return canonical formatting without linguistic or OCR correction."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(config, NormalizationConfig):
        raise TypeError("config must be a NormalizationConfig")

    original_text = text
    operations: list[str] = []

    normalized = _record_change(
        text,
        unicodedata.normalize(config.unicode_form, text),
        f"unicode_{config.unicode_form.lower()}",
        operations,
    )
    normalized = _record_change(
        normalized,
        _normalize_line_endings(normalized),
        "normalized_line_endings",
        operations,
    )

    if config.remove_bom:
        normalized = _record_change(
            normalized,
            normalized.replace("\ufeff", ""),
            "removed_bom",
            operations,
        )
    if config.remove_zero_width_characters:
        translation = {ord(character): None for character in config.zero_width_characters}
        normalized = _record_change(
            normalized,
            normalized.translate(translation),
            "removed_zero_width_characters",
            operations,
        )
    if config.normalize_unicode_whitespace:
        normalized = _record_change(
            normalized,
            _normalize_unicode_spaces(normalized),
            "normalized_unicode_whitespace",
            operations,
        )
    if config.replace_tabs:
        normalized = _record_change(
            normalized,
            normalized.replace("\t", " "),
            "replaced_tabs",
            operations,
        )

    lines = normalized.split("\n")
    stripped_lines = [line.strip(" \t") for line in lines]
    if stripped_lines != lines:
        operations.append("trimmed_line_whitespace")
    lines = stripped_lines

    if config.collapse_horizontal_whitespace:
        collapsed_lines = [re.sub(r" {2,}", " ", line) for line in lines]
        if collapsed_lines != lines:
            operations.append("collapsed_horizontal_whitespace")
        lines = collapsed_lines

    limited_lines = _limit_blank_lines(lines, config.max_consecutive_blank_lines)
    if limited_lines != lines:
        operations.append("limited_blank_lines")
    lines = list(limited_lines)
    before_document_trim = "\n".join(lines)

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    document_trimmed = "\n".join(lines)
    if document_trimmed != before_document_trim:
        operations.append("trimmed_document_whitespace")
    normalized = document_trimmed

    warnings: list[str] = []
    if _has_suspicious_thai_character_spacing(normalized):
        warnings.append("suspicious_thai_character_spacing")

    line_count = normalized.count("\n") + 1 if normalized else 0
    return NormalizationResult(
        original_text=original_text,
        normalized_text=normalized,
        changed=normalized != original_text,
        operations=tuple(operations),
        warnings=tuple(warnings),
        stats=NormalizationStats(
            original_length=len(original_text),
            normalized_length=len(normalized),
            line_count=line_count,
        ),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize extracted text without linguistic correction.",
    )
    parser.add_argument(
        "--input-text-file",
        type=Path,
        help="UTF-8 input file; omit to read UTF-8 text from stdin",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete structured normalization result",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    try:
        if args.input_text_file is None:
            source_text = sys.stdin.read()
        else:
            source_text = args.input_text_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result = normalize_text(source_text)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.normalized_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
