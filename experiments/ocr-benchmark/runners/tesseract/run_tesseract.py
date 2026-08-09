"""Run Tesseract OCR on shared benchmark PNG images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


HASH_CHUNK_SIZE = 1024 * 1024
DEFAULT_LANGUAGE_EXPRESSION = "tha+eng"
TESSERACT_SETTINGS = {
    "oem": 1,
    "psm": 3,
    "dpi": 300,
    "input_format": "PNG",
    "preprocessing": "none",
}
DOCUMENT_PAGE_PATTERN = re.compile(r"^(?P<document_id>.+)_page_\d+$")


class RunnerError(Exception):
    """A user-facing Tesseract runner failure."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def language_expression(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\+[A-Za-z0-9_-]+)*", value):
        raise argparse.ArgumentTypeError(
            "languages must be Tesseract model names separated by '+', "
            "for example tha+eng"
        )
    languages = value.split("+")
    if len(set(languages)) != len(languages):
        raise argparse.ArgumentTypeError("languages must not contain duplicates")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Tesseract OCR with fixed benchmark settings and configurable "
            "language models on PNG files or directories."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        nargs="+",
        type=Path,
        help="One or more PNG files or directories containing PNG files",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for Tesseract .txt and .json outputs",
    )
    parser.add_argument(
        "--tesseract",
        type=Path,
        help=(
            "Path to tesseract.exe; otherwise PATH and the standard Windows "
            "installation directories are searched"
        ),
    )
    parser.add_argument(
        "--languages",
        type=language_expression,
        default=DEFAULT_LANGUAGE_EXPRESSION,
        help=(
            "Tesseract language expression, such as ocr_train+eng "
            f"(default: {DEFAULT_LANGUAGE_EXPRESSION})"
        ),
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Process only the first N images after sorting by filename",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing .txt and .json outputs",
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_images(input_paths: Sequence[Path], limit: int | None) -> list[Path]:
    images: list[Path] = []
    for input_path in input_paths:
        if not input_path.exists():
            raise RunnerError(f"Input path does not exist: '{input_path}'.")
        if input_path.is_file():
            if input_path.suffix.lower() != ".png":
                raise RunnerError(f"Input file is not a PNG: '{input_path}'.")
            images.append(input_path)
        elif input_path.is_dir():
            directory_images = [
                path
                for path in input_path.iterdir()
                if path.is_file() and path.suffix.lower() == ".png"
            ]
            if not directory_images:
                raise RunnerError(f"No PNG files found in '{input_path}'.")
            images.extend(directory_images)
        else:
            raise RunnerError(
                f"Input path is not a file or directory: '{input_path}'."
            )

    unique_images = {path.resolve(): path for path in images}
    sorted_images = sorted(
        unique_images.values(), key=lambda path: (path.name.casefold(), str(path))
    )
    selected_images = sorted_images[:limit] if limit is not None else sorted_images

    stems: dict[str, Path] = {}
    for image_path in selected_images:
        key = image_path.stem.casefold()
        if key in stems and stems[key].resolve() != image_path.resolve():
            raise RunnerError(
                "Inputs would create duplicate output names: "
                f"'{stems[key]}' and '{image_path}'."
            )
        stems[key] = image_path
    return selected_images


def output_paths(image_path: Path, output_dir: Path) -> tuple[Path, Path]:
    return (
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


def resolve_tesseract(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        candidate = explicit_path.expanduser()
        if not candidate.is_file():
            raise RunnerError(
                f"Tesseract executable does not exist: '{explicit_path}'."
            )
        return candidate.resolve()

    path_match = shutil.which("tesseract.exe") or shutil.which("tesseract")
    candidates = [Path(path_match)] if path_match else []
    for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(environment_name)
        if root:
            candidates.append(Path(root) / "Tesseract-OCR" / "tesseract.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RunnerError(
        "Tesseract executable was not found. Install Tesseract for Windows, add "
        "it to PATH, or pass --tesseract 'C:\\Program Files\\Tesseract-OCR\\"
        "tesseract.exe'."
    )


def resolve_tessdata_directory(executable: Path) -> Path:
    tessdata_directory = executable.parent / "tessdata"
    if not tessdata_directory.is_dir():
        raise RunnerError(
            "The standard tessdata directory was not found beside the Tesseract "
            f"executable: '{tessdata_directory}'."
        )
    return tessdata_directory.resolve()


def clean_subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("TESSDATA_PREFIX", None)
    return environment


def run_text_command(command: Sequence[str], label: str) -> str:
    try:
        completed = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=clean_subprocess_environment(),
        )
    except OSError as exc:
        raise RunnerError(f"Could not run Tesseract {label}: {exc}") from exc
    output = completed.stdout + completed.stderr
    decoded = output.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        detail = decoded or f"exit code {completed.returncode}"
        raise RunnerError(f"Tesseract {label} failed: {detail}")
    return decoded


def get_tesseract_version(executable: Path) -> str:
    output = run_text_command((str(executable), "--version"), "version check")
    first_line = output.splitlines()[0] if output else ""
    match = re.search(r"tesseract\s+v?([^\s]+)", first_line, re.IGNORECASE)
    if not match:
        raise RunnerError(
            f"Could not parse the Tesseract version from: '{first_line}'."
        )
    return match.group(1)


def get_installed_languages(executable: Path, tessdata_directory: Path) -> list[str]:
    output = run_text_command(
        (
            str(executable),
            "--tessdata-dir",
            str(tessdata_directory),
            "--list-langs",
        ),
        "language check",
    )
    languages = [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    ]
    return sorted(set(languages), key=str.casefold)


def validate_required_languages(
    requested_languages: Sequence[str], installed_languages: Sequence[str]
) -> None:
    installed = set(installed_languages)
    missing = [language for language in requested_languages if language not in installed]
    if missing:
        raise RunnerError(
            "Missing required Tesseract language model(s): "
            f"{', '.join(missing)}. Install the official standard "
            f"{', '.join(language + '.traineddata' for language in missing)} "
            "file(s) in the tessdata directory beside tesseract.exe."
        )


def traineddata_hashes(
    tessdata_directory: Path, languages: Sequence[str]
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for language in languages:
        model_path = tessdata_directory / f"{language}.traineddata"
        try:
            hashes[language] = sha256_file(model_path)
        except OSError as exc:
            raise RunnerError(
                f"Could not read language model '{model_path}': {exc}"
            ) from exc
    return hashes


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
    text_path: Path,
    json_path: Path,
    raw_text: bytes,
    result_metadata: dict[str, object],
    overwrite: bool,
) -> None:
    if not overwrite:
        existing = [path.name for path in (text_path, json_path) if path.exists()]
        if existing:
            raise RunnerError(
                f"Output already exists: {', '.join(existing)}. "
                "Use --overwrite to replace it."
            )

    temp_text = create_temp_path(text_path.parent, text_path.name)
    temp_json = create_temp_path(json_path.parent, json_path.name)
    try:
        temp_text.write_bytes(raw_text)
        temp_json.write_text(
            json.dumps(result_metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp_text, text_path)
        temp_text = None
        os.replace(temp_json, json_path)
        temp_json = None
    except OSError as exc:
        raise RunnerError(f"Could not write Tesseract output: {exc}") from exc
    finally:
        for temp_path in (temp_text, temp_json):
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def run_image(
    *,
    executable: Path,
    tessdata_directory: Path,
    image_path: Path,
    output_dir: Path,
    tesseract_version: str,
    language_expression: str,
    languages: Sequence[str],
    model_hashes: dict[str, str],
    overwrite: bool,
) -> tuple[Path, Path, float]:
    try:
        input_sha256 = sha256_file(image_path)
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc

    command = (
        str(executable),
        str(image_path),
        "stdout",
        "--tessdata-dir",
        str(tessdata_directory),
        "-l",
        language_expression,
        "--oem",
        str(TESSERACT_SETTINGS["oem"]),
        "--psm",
        str(TESSERACT_SETTINGS["psm"]),
        "--dpi",
        str(TESSERACT_SETTINGS["dpi"]),
    )
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=clean_subprocess_environment(),
        )
    except OSError as exc:
        raise RunnerError(
            f"Could not start Tesseract for '{image_path.name}': {exc}"
        ) from exc
    processing_ms = round((time.perf_counter() - started_at) * 1000, 3)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RunnerError(
            f"Tesseract failed for '{image_path.name}': "
            f"{detail or f'exit code {completed.returncode}'}"
        )

    raw_text = completed.stdout
    text_path, json_path = output_paths(image_path, output_dir)
    output_sha256 = hashlib.sha256(raw_text).hexdigest()
    configuration = dict(TESSERACT_SETTINGS)
    configuration.update(
        {
            "languages": language_expression,
            "executable": str(executable),
            "tessdata_directory": str(tessdata_directory),
            "traineddata_source": "tessdata beside executable",
            "traineddata_sha256": model_hashes,
        }
    )
    result_metadata: dict[str, object] = {
        "document_id": document_id_for(image_path),
        "engine": "tesseract",
        "tesseract_version": tesseract_version,
        "languages": list(languages),
        "input_file": image_path.name,
        "input_sha256": input_sha256,
        "output_file": text_path.name,
        "output_sha256": output_sha256,
        "processing_ms": processing_ms,
        "status": "success",
        "configuration": configuration,
    }
    write_outputs(text_path, json_path, raw_text, result_metadata, overwrite)
    return text_path, json_path, processing_ms


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        images = collect_images(args.input, args.limit)
        executable = resolve_tesseract(args.tesseract)
        tessdata_directory = resolve_tessdata_directory(executable)
        tesseract_version = get_tesseract_version(executable)
        installed_languages = get_installed_languages(executable, tessdata_directory)
        requested_languages = args.languages.split("+")
        validate_required_languages(requested_languages, installed_languages)
        model_hashes = traineddata_hashes(tessdata_directory, requested_languages)

        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise RunnerError(f"Output path is not a directory: '{args.output}'.")
        ensure_outputs_available(images, args.output, args.overwrite)

        print(f"Tesseract version: {tesseract_version}")
        print(f"Installed languages: {', '.join(installed_languages)}")
        print(
            "Benchmark configuration: "
            f"languages={args.languages}, OEM={TESSERACT_SETTINGS['oem']}, "
            f"PSM={TESSERACT_SETTINGS['psm']}, DPI={TESSERACT_SETTINGS['dpi']}, "
            "preprocessing=none"
        )

        failures = 0
        total_processing_ms = 0.0
        for index, image_path in enumerate(images, start=1):
            try:
                text_path, json_path, processing_ms = run_image(
                    executable=executable,
                    tessdata_directory=tessdata_directory,
                    image_path=image_path,
                    output_dir=args.output,
                    tesseract_version=tesseract_version,
                    language_expression=args.languages,
                    languages=requested_languages,
                    model_hashes=model_hashes,
                    overwrite=args.overwrite,
                )
                total_processing_ms += processing_ms
                print(
                    f"[{index}/{len(images)}] {image_path.name} -> "
                    f"{text_path.name}, {json_path.name} ({processing_ms:.3f} ms)"
                )
            except RunnerError as exc:
                failures += 1
                print(f"Error: {exc}", file=sys.stderr)

        if failures:
            raise RunnerError(
                f"Tesseract failed for {failures} of {len(images)} image(s)."
            )
        print(
            f"Completed {len(images)} image(s) in {total_processing_ms:.3f} ms. "
            f"Outputs: {args.output}"
        )
        return 0
    except (OSError, RunnerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
