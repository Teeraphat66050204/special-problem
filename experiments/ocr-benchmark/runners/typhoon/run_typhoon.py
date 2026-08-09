"""Run Typhoon OCR on shared benchmark PNG images."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from html.parser import HTMLParser
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


HASH_CHUNK_SIZE = 1024 * 1024
MODEL = "typhoon-ocr"
BASE_URL = "https://api.opentyphoon.ai/v1"
TASK_TYPE = "v1.5"
FIGURE_LANGUAGE = "Thai"
MAX_TOKENS = 16384
TEMPERATURE = 0.1
TOP_P = 0.6
REPETITION_PENALTY = 1.1
DEFAULT_REQUEST_INTERVAL_SECONDS = 3.1
PLAIN_TEXT_CONVERSION = "commonmark-html-text-v1"
API_KEY_ENVIRONMENTS = (
    "TYPHOON_OCR_API_KEY",
    "TYPHOON_API_KEY",
    "OPENAI_API_KEY",
)
DOCUMENT_PAGE_PATTERN = re.compile(r"^(?P<document_id>.+)_page_\d+$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RunnerError(Exception):
    """A user-facing Typhoon runner failure."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Typhoon OCR on one rendered PNG or a directory, preserving raw "
            "Markdown and producing deterministic plain text."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Rendered benchmark PNG file or directory containing PNG files",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for Typhoon .md, .txt and .json outputs",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Process only the first N images after sorting by filename",
    )
    parser.add_argument(
        "--request-interval-seconds",
        type=nonnegative_float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help=(
            "Delay between API requests for rate-limit compliance "
            f"(default: {DEFAULT_REQUEST_INTERVAL_SECONDS})"
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing .md, .txt and .json outputs",
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_images(input_path: Path, limit: int | None) -> list[Path]:
    if not input_path.exists():
        raise RunnerError(f"Input path does not exist: '{input_path}'.")
    if input_path.is_file():
        if input_path.suffix.lower() != ".png":
            raise RunnerError(f"Input file is not a PNG: '{input_path}'.")
        images = [input_path]
    elif input_path.is_dir():
        images = sorted(
            (
                path
                for path in input_path.iterdir()
                if path.is_file() and path.suffix.lower() == ".png"
            ),
            key=lambda path: path.name.casefold(),
        )
        if not images:
            raise RunnerError(f"No PNG files found in '{input_path}'.")
    else:
        raise RunnerError(f"Input path is not a file or directory: '{input_path}'.")
    return images[:limit] if limit is not None else images


def render_metadata_path(image_path: Path) -> Path:
    return image_path.with_suffix(".render.json")


def load_render_metadata(image_path: Path, input_sha256: str) -> dict[str, Any]:
    sidecar_path = render_metadata_path(image_path)
    if not sidecar_path.is_file():
        raise RunnerError(
            f"Missing Common PDF Renderer metadata for '{image_path.name}': "
            f"'{sidecar_path}'."
        )
    try:
        render_metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Could not read render metadata '{sidecar_path}': {exc}") from exc
    if not isinstance(render_metadata, dict):
        raise RunnerError(f"Render metadata is not a JSON object: '{sidecar_path}'.")

    expected_values = {
        "dpi": 300,
        "color_space": "RGB",
        "format": "PNG",
        "preprocessing": False,
        "output_file": image_path.name,
        "output_sha256": input_sha256,
    }
    mismatches = [
        f"{key}={render_metadata.get(key)!r} (expected {expected!r})"
        for key, expected in expected_values.items()
        if render_metadata.get(key) != expected
    ]
    if mismatches:
        raise RunnerError(
            f"Input '{image_path.name}' does not match benchmark render metadata: "
            + "; ".join(mismatches)
            + "."
        )
    if not isinstance(render_metadata.get("width_px"), int) or not isinstance(
        render_metadata.get("height_px"), int
    ):
        raise RunnerError(
            f"Render metadata has invalid image dimensions: '{sidecar_path}'."
        )
    try:
        with image_path.open("rb") as file_handle:
            signature = file_handle.read(len(PNG_SIGNATURE))
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc
    if signature != PNG_SIGNATURE:
        raise RunnerError(f"Input file is not valid PNG data: '{image_path}'.")
    return render_metadata


def output_paths(image_path: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    return (
        output_dir / f"{image_path.stem}.md",
        output_dir / f"{image_path.stem}.txt",
        output_dir / f"{image_path.stem}.json",
    )


def ensure_outputs_available(
    images: Sequence[Path], output_dir: Path, overwrite: bool
) -> None:
    if overwrite:
        return
    existing = [
        output_path.name
        for image_path in images
        for output_path in output_paths(image_path, output_dir)
        if output_path.exists()
    ]
    if existing:
        preview = ", ".join(existing[:5])
        if len(existing) > 5:
            preview += f", and {len(existing) - 5} more"
        raise RunnerError(
            f"Output already exists: {preview}. Use --overwrite to replace it."
        )


def resolve_api_key() -> tuple[str, str]:
    for environment_name in API_KEY_ENVIRONMENTS:
        api_key = os.environ.get(environment_name)
        if api_key:
            return api_key, environment_name
    accepted = ", ".join(API_KEY_ENVIRONMENTS)
    raise RunnerError(
        f"Typhoon OCR API key is missing. Set one of: {accepted}."
    )


def package_version(package_name: str, module: Any) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return str(getattr(module, "__version__", "unknown"))


def load_dependencies() -> tuple[Any, Callable[..., str], Any, str, str, str]:
    try:
        import markdown_it  # type: ignore[import-not-found]
        import openai  # type: ignore[import-not-found]
        import typhoon_ocr  # type: ignore[import-not-found]
        from markdown_it import MarkdownIt  # type: ignore[import-not-found]
        from openai import OpenAI  # type: ignore[import-not-found]
        from typhoon_ocr import get_prompt  # type: ignore[import-not-found]
    except Exception as exc:
        raise RunnerError(
            "Typhoon OCR dependencies are unavailable. Install them with "
            "'python -m pip install -r "
            "experiments/ocr-benchmark/runners/typhoon/requirements.txt'."
        ) from exc
    return (
        OpenAI,
        get_prompt,
        MarkdownIt,
        package_version("typhoon-ocr", typhoon_ocr),
        package_version("openai", openai),
        package_version("markdown-it-py", markdown_it),
    )


class PlainHTMLExtractor(HTMLParser):
    """Collect visible HTML text while preserving block and table order."""

    BLOCK_END_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "page_number",
        "pre",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def append_line_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "br":
            self.append_line_break()
        elif tag in {"td", "th"} and self.parts and not self.parts[-1].endswith(
            ("\n", "\t")
        ):
            self.parts.append("\t")
        elif tag == "img":
            alt_text = dict(attrs).get("alt")
            if alt_text:
                self.parts.append(alt_text)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            if self.ignored_depth:
                self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag in {"td", "th"}:
            if self.parts and not self.parts[-1].endswith(("\n", "\t")):
                self.parts.append("\t")
        elif tag in self.BLOCK_END_TAGS:
            self.append_line_break()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth and not data.isspace():
            self.parts.append(data)

    def plain_text(self) -> str:
        lines = [line.strip() for line in "".join(self.parts).splitlines()]
        nonempty_lines = [line for line in lines if line]
        return "\n".join(nonempty_lines) + ("\n" if nonempty_lines else "")


def markdown_to_plain_text(raw_markdown: str, markdown_it_class: Any) -> str:
    parser = markdown_it_class("commonmark", {"html": True}).enable("table")
    parseable_markdown = raw_markdown.replace(
        "<page_number>", '<span data-typhoon-page-number="true">'
    ).replace("</page_number>", "</span>")
    rendered_html = parser.render(parseable_markdown)
    extractor = PlainHTMLExtractor()
    extractor.feed(rendered_html)
    extractor.close()
    return extractor.plain_text()


def build_prompt(get_prompt: Callable[..., Any]) -> str:
    try:
        prompt_factory = get_prompt(TASK_TYPE)
        prompt = prompt_factory(figure_language=FIGURE_LANGUAGE)
    except Exception as exc:
        raise RunnerError(f"Could not build the official Typhoon OCR prompt: {exc}") from exc
    if not isinstance(prompt, str) or not prompt:
        raise RunnerError("The official Typhoon OCR prompt is empty or invalid.")
    return prompt


def create_client(openai_class: Any, api_key: str) -> Any:
    try:
        return openai_class(api_key=api_key, base_url=BASE_URL, timeout=180.0)
    except Exception as exc:
        raise RunnerError(f"Could not initialize the Typhoon API client: {exc}") from exc


def response_metadata(response: Any) -> dict[str, object]:
    usage = getattr(response, "usage", None)
    if usage is not None and hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, Mapping):
        usage = None
    choice = response.choices[0]
    return {
        "response_id": getattr(response, "id", None),
        "response_model": getattr(response, "model", None),
        "finish_reason": getattr(choice, "finish_reason", None),
        "usage": dict(usage) if usage is not None else None,
    }


def call_typhoon(client: Any, prompt: str, image_path: Path) -> tuple[str, float, dict[str, object]]:
    try:
        encoded_png = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded_png}"},
                },
            ],
        }
    ]
    started_at = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            extra_body={
                "repetition_penalty": REPETITION_PENALTY,
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
            },
        )
    except Exception as exc:
        raise RunnerError(f"Typhoon API request failed for '{image_path.name}': {exc}") from exc
    processing_ms = round((time.perf_counter() - started_at) * 1000, 3)
    if not getattr(response, "choices", None):
        raise RunnerError(f"Typhoon API returned no choices for '{image_path.name}'.")
    raw_markdown = response.choices[0].message.content
    if not isinstance(raw_markdown, str):
        raise RunnerError(
            f"Typhoon API returned no Markdown content for '{image_path.name}'."
        )
    return raw_markdown, processing_ms, response_metadata(response)


def document_id_for(image_path: Path) -> str:
    match = DOCUMENT_PAGE_PATTERN.fullmatch(image_path.stem)
    return match.group("document_id") if match else image_path.stem


def create_temp_path(output_dir: Path, output_name: str) -> Path:
    suffix = "".join(Path(output_name).suffixes) or ".tmp"
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=f".{Path(output_name).stem}.",
            suffix=f".tmp{suffix}",
            delete=False,
        ) as temp_file:
            return Path(temp_file.name)
    except OSError as exc:
        raise RunnerError(
            f"Could not create a temporary file in '{output_dir}': {exc}"
        ) from exc


def write_outputs(
    markdown_path: Path,
    text_path: Path,
    json_path: Path,
    raw_markdown: str,
    plain_text: str,
    result_metadata: dict[str, object],
    overwrite: bool,
) -> None:
    paths = (markdown_path, text_path, json_path)
    if not overwrite:
        existing = [path.name for path in paths if path.exists()]
        if existing:
            raise RunnerError(
                f"Output already exists: {', '.join(existing)}. "
                "Use --overwrite to replace it."
            )
    temp_paths: list[Path | None] = [
        create_temp_path(path.parent, path.name) for path in paths
    ]
    try:
        temp_paths[0].write_bytes(raw_markdown.encode("utf-8"))  # type: ignore[union-attr]
        temp_paths[1].write_bytes(plain_text.encode("utf-8"))  # type: ignore[union-attr]
        temp_paths[2].write_text(  # type: ignore[union-attr]
            json.dumps(result_metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if not overwrite:
            existing = [path.name for path in paths if path.exists()]
            if existing:
                raise RunnerError(
                    f"Output already exists: {', '.join(existing)}. "
                    "Use --overwrite to replace it."
                )
        for index, destination in enumerate(paths):
            os.replace(temp_paths[index], destination)
            temp_paths[index] = None
    except OSError as exc:
        raise RunnerError(f"Could not write Typhoon output: {exc}") from exc
    finally:
        for temp_path in temp_paths:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def run_image(
    *,
    client: Any,
    prompt: str,
    markdown_it_class: Any,
    image_path: Path,
    output_dir: Path,
    api_key_environment: str,
    typhoon_ocr_version: str,
    openai_version: str,
    markdown_it_version: str,
    overwrite: bool,
) -> tuple[Path, Path, Path, float]:
    try:
        input_sha256 = sha256_file(image_path)
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc
    render_metadata = load_render_metadata(image_path, input_sha256)
    raw_markdown, processing_ms, api_metadata = call_typhoon(
        client, prompt, image_path
    )
    plain_text = markdown_to_plain_text(raw_markdown, markdown_it_class)
    markdown_path, text_path, json_path = output_paths(image_path, output_dir)
    raw_markdown_sha256 = hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()
    output_sha256 = hashlib.sha256(plain_text.encode("utf-8")).hexdigest()
    result_metadata: dict[str, object] = {
        "document_id": document_id_for(image_path),
        "engine": "typhoon",
        "typhoon_ocr_version": typhoon_ocr_version,
        "openai_version": openai_version,
        "model": MODEL,
        "input_file": image_path.name,
        "input_sha256": input_sha256,
        "raw_markdown_file": markdown_path.name,
        "raw_markdown_sha256": raw_markdown_sha256,
        "output_file": text_path.name,
        "output_sha256": output_sha256,
        "processing_ms": processing_ms,
        "status": "success",
        "preprocessing": "none",
        "configuration": {
            "base_url": BASE_URL,
            "task_type": TASK_TYPE,
            "figure_language": FIGURE_LANGUAGE,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "repetition_penalty": REPETITION_PENALTY,
            "input_transport": "original PNG bytes as base64 data URI",
            "api_key_environment": api_key_environment,
            "plain_text_conversion": PLAIN_TEXT_CONVERSION,
            "markdown_it_version": markdown_it_version,
        },
        "render": {
            "metadata_file": render_metadata_path(image_path).name,
            "dpi": render_metadata["dpi"],
            "color_space": render_metadata["color_space"],
            "format": render_metadata["format"],
            "preprocessing": render_metadata["preprocessing"],
            "width_px": render_metadata["width_px"],
            "height_px": render_metadata["height_px"],
        },
        "api_response": api_metadata,
    }
    write_outputs(
        markdown_path,
        text_path,
        json_path,
        raw_markdown,
        plain_text,
        result_metadata,
        overwrite,
    )
    return markdown_path, text_path, json_path, processing_ms


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        images = collect_images(args.input, args.limit)
        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise RunnerError(f"Output path is not a directory: '{args.output}'.")
        ensure_outputs_available(images, args.output, args.overwrite)
        api_key, api_key_environment = resolve_api_key()
        (
            openai_class,
            get_prompt,
            markdown_it_class,
            typhoon_ocr_version,
            openai_version,
            markdown_it_version,
        ) = load_dependencies()
        prompt = build_prompt(get_prompt)
        client = create_client(openai_class, api_key)
        print(
            f"Typhoon OCR package={typhoon_ocr_version}, model={MODEL}, "
            f"input=original PNG bytes, plain_text={PLAIN_TEXT_CONVERSION}"
        )

        failures = 0
        total_processing_ms = 0.0
        for index, image_path in enumerate(images, start=1):
            try:
                markdown_path, text_path, json_path, processing_ms = run_image(
                    client=client,
                    prompt=prompt,
                    markdown_it_class=markdown_it_class,
                    image_path=image_path,
                    output_dir=args.output,
                    api_key_environment=api_key_environment,
                    typhoon_ocr_version=typhoon_ocr_version,
                    openai_version=openai_version,
                    markdown_it_version=markdown_it_version,
                    overwrite=args.overwrite,
                )
                total_processing_ms += processing_ms
                print(
                    f"[{index}/{len(images)}] {image_path.name} -> "
                    f"{markdown_path.name}, {text_path.name}, {json_path.name} "
                    f"({processing_ms:.3f} ms)"
                )
            except RunnerError as exc:
                failures += 1
                print(f"Error: {exc}", file=sys.stderr)
            if index < len(images) and args.request_interval_seconds:
                time.sleep(args.request_interval_seconds)

        if failures:
            raise RunnerError(f"Typhoon failed for {failures} of {len(images)} image(s).")
        print(
            f"Completed {len(images)} image(s) in {total_processing_ms:.3f} ms. "
            f"Failures: {failures}. Outputs: {args.output}"
        )
        return 0
    except (OSError, RunnerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
