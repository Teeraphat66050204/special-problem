"""Orchestrate deterministic metadata extraction from normalized page text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from metadata_extraction.extract_academic import (  # type: ignore[import-not-found]
        extract_academic_candidates,
    )
    from metadata_extraction.extract_advisors import (  # type: ignore[import-not-found]
        extract_advisor_candidates,
    )
    from metadata_extraction.extract_sections import (  # type: ignore[import-not-found]
        extract_abstract_candidates,
        extract_keyword_candidates,
    )
    from metadata_extraction.extract_students import (  # type: ignore[import-not-found]
        extract_student_candidates,
    )
    from metadata_extraction.extract_titles import (  # type: ignore[import-not-found]
        extract_title_candidates,
    )
    from metadata_extraction.line_utils import (  # type: ignore[import-not-found]
        page_context_from_mapping,
    )
    from metadata_extraction.models import (  # type: ignore[import-not-found]
        DEFAULT_EXTRACTION_CONFIG,
        ExtractionConfig,
        ExtractionResult,
        FieldResult,
        PageContext,
    )
    from metadata_extraction.resolution import (  # type: ignore[import-not-found]
        resolve_scalar_candidates,
        resolve_page_scoped_string_list,
        resolve_string_list,
        resolve_students,
    )
else:
    from .extract_academic import extract_academic_candidates
    from .extract_advisors import extract_advisor_candidates
    from .extract_sections import (
        extract_abstract_candidates,
        extract_keyword_candidates,
    )
    from .extract_students import extract_student_candidates
    from .extract_titles import extract_title_candidates
    from .line_utils import page_context_from_mapping
    from .models import (
        DEFAULT_EXTRACTION_CONFIG,
        ExtractionConfig,
        ExtractionResult,
        FieldResult,
        PageContext,
    )
    from .resolution import (
        resolve_scalar_candidates,
        resolve_page_scoped_string_list,
        resolve_string_list,
        resolve_students,
    )


def _empty_metadata() -> dict[str, Any]:
    return {
        "title_th": None,
        "title_en": None,
        "students": [],
        "degree": None,
        "department": None,
        "faculty": None,
        "academic_year": None,
        "advisor": None,
        "co_advisors": [],
        "abstract_th": None,
        "abstract_en": None,
        "keywords": [],
    }


def _failed_result(
    warning: str,
    *,
    pages_received: int,
    pages_skipped: int,
) -> ExtractionResult:
    metadata = _empty_metadata()
    fields = {
        name: FieldResult.missing([] if name in {"students", "co_advisors", "keywords"} else None)
        for name in metadata
    }
    return ExtractionResult(
        metadata=metadata,
        fields=fields,
        warnings=(warning,),
        extraction_status="failed",
        requires_manual_review=True,
        stats={
            "pages_received": pages_received,
            "pages_processed": 0,
            "pages_skipped": pages_skipped,
            "fields_extracted": 0,
            "candidate_count": 0,
        },
    )


def _usable_pages(
    pages: Sequence[Mapping[str, Any]],
) -> tuple[list[PageContext], int, list[str]]:
    contexts: list[PageContext] = []
    skipped = 0
    warnings: list[str] = []
    for page in pages:
        context = page_context_from_mapping(page)
        if context is None:
            skipped += 1
            continue
        contexts.append(context)
        warnings.extend(context.upstream_warnings)
        if context.upstream_requires_review:
            warnings.append("upstream_requires_manual_review")
    if skipped:
        warnings.append("unusable_normalized_page")
    return contexts, skipped, list(dict.fromkeys(warnings))


def extract_metadata_from_pages(
    normalized_pages: Sequence[Mapping[str, Any]],
    config: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG,
) -> ExtractionResult:
    """Extract metadata from every usable normalized page without mutation."""
    if not isinstance(config, ExtractionConfig):
        raise TypeError("config must be an ExtractionConfig")
    if isinstance(normalized_pages, (str, bytes)) or not isinstance(
        normalized_pages, Sequence
    ):
        return _failed_result(
            "invalid_abstract_pages",
            pages_received=0,
            pages_skipped=0,
        )
    if any(not isinstance(page, Mapping) for page in normalized_pages):
        return _failed_result(
            "invalid_abstract_page",
            pages_received=len(normalized_pages),
            pages_skipped=len(normalized_pages),
        )

    pages, skipped, warnings = _usable_pages(normalized_pages)
    if not pages:
        return _failed_result(
            "no_usable_normalized_text",
            pages_received=len(normalized_pages),
            pages_skipped=skipped,
        )

    title_candidates = extract_title_candidates(pages, config)
    student_candidates, student_warnings = extract_student_candidates(pages, config)
    academic_candidates = extract_academic_candidates(pages, config)
    advisor_candidates, co_advisor_candidates = extract_advisor_candidates(pages, config)
    abstract_candidates = extract_abstract_candidates(pages, config)
    keyword_candidates = extract_keyword_candidates(pages, config)

    fields: dict[str, FieldResult] = {
        "title_th": resolve_scalar_candidates(
            "title_th",
            title_candidates["title_th"],
            config,
            preferred_languages=("thai", "mixed", "english", "unknown"),
        ),
        "title_en": resolve_scalar_candidates(
            "title_en",
            title_candidates["title_en"],
            config,
            preferred_languages=("english", "mixed", "thai", "unknown"),
        ),
        "students": resolve_students(student_candidates, config),
        "degree": resolve_scalar_candidates("degree", academic_candidates["degree"], config),
        "department": resolve_scalar_candidates(
            "department", academic_candidates["department"], config
        ),
        "faculty": resolve_scalar_candidates("faculty", academic_candidates["faculty"], config),
        "academic_year": resolve_scalar_candidates(
            "academic_year", academic_candidates["academic_year"], config
        ),
        "advisor": resolve_scalar_candidates("advisor", advisor_candidates, config),
        "co_advisors": resolve_page_scoped_string_list(
            "co_advisors",
            co_advisor_candidates,
        ),
        "abstract_th": resolve_scalar_candidates(
            "abstract_th",
            abstract_candidates["abstract_th"],
            config,
            preferred_languages=("thai", "mixed", "english", "unknown"),
        ),
        "abstract_en": resolve_scalar_candidates(
            "abstract_en",
            abstract_candidates["abstract_en"],
            config,
            preferred_languages=("english", "mixed", "thai", "unknown"),
        ),
        "keywords": resolve_string_list(
            keyword_candidates,
            method="merged_keyword_sections",
        ),
    }

    metadata = {name: result.value for name, result in fields.items()}
    warnings.extend(student_warnings)
    warnings.extend(
        warning for result in fields.values() for warning in result.warnings
    )
    languages = {page.language for page in pages}
    if "thai" in languages and metadata["title_th"] is None:
        warnings.append("missing_title_th")
    if "english" in languages and metadata["title_en"] is None:
        warnings.append("missing_title_en")
    if not metadata["students"]:
        warnings.append("missing_student")
    if metadata["advisor"] is None:
        warnings.append("missing_advisor")
    warnings = list(dict.fromkeys(warnings))

    fields_extracted = sum(
        bool(value) if isinstance(value, list) else value is not None
        for value in metadata.values()
    )
    candidate_count = sum(len(result.candidates) for result in fields.values())
    if fields_extracted == 0:
        status = "failed"
        warnings.append("no_metadata_extracted")
    elif warnings:
        status = "partial"
    else:
        status = "success"
    return ExtractionResult(
        metadata=metadata,
        fields=fields,
        warnings=tuple(dict.fromkeys(warnings)),
        extraction_status=status,
        requires_manual_review=status != "success",
        stats={
            "pages_received": len(normalized_pages),
            "pages_processed": len(pages),
            "pages_skipped": skipped,
            "fields_extracted": fields_extracted,
            "candidate_count": candidate_count,
        },
    )


def extract_metadata(
    normalized_document: Mapping[str, Any],
    config: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG,
) -> ExtractionResult:
    """Consume ``normalize_processed_document`` output directly."""
    if not isinstance(normalized_document, Mapping):
        return _failed_result(
            "invalid_normalized_document",
            pages_received=0,
            pages_skipped=0,
        )
    pages = normalized_document.get("abstract_pages", [])
    if not isinstance(pages, list):
        return _failed_result(
            "invalid_abstract_pages",
            pages_received=0,
            pages_skipped=0,
        )
    return extract_metadata_from_pages(pages, config)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract metadata locally from a normalized document JSON object.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Normalized document JSON; omit to read JSON from stdin",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    try:
        if args.input_json is None:
            payload = json.load(sys.stdin)
        else:
            payload = json.loads(args.input_json.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    result = extract_metadata(payload)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.extraction_status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
