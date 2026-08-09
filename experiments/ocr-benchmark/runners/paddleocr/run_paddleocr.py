"""Run PaddleOCR on shared benchmark PNG images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence


HASH_CHUNK_SIZE = 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".paddleocr-cache"
LANGUAGE = "th"
OCR_VERSION = "PP-OCRv5"
DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "th_PP-OCRv5_mobile_rec"
PIPELINE_SETTINGS = {
    "text_detection_model_name": DETECTION_MODEL,
    "text_recognition_model_name": RECOGNITION_MODEL,
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    "text_rec_score_thresh": 0.0,
    "return_word_box": False,
    "device": "cpu",
    "enable_mkldnn": False,
}
DOCUMENT_PAGE_PATTERN = re.compile(r"^(?P<document_id>.+)_page_\d+$")


class RunnerError(Exception):
    """A user-facing PaddleOCR runner failure."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run official Thai PaddleOCR on one PNG or a directory of "
            "benchmark PNGs."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="PNG file or directory containing PNG files",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for PaddleOCR .txt and .json outputs",
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


def sha256_directory(path: Path) -> str:
    if not path.is_dir():
        raise RunnerError(f"Official PaddleOCR model directory is missing: '{path}'.")
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise RunnerError(f"Official PaddleOCR model directory is empty: '{path}'.")
    digest = hashlib.sha256()
    for file_path in files:
        relative_path = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        with file_path.open("rb") as file_handle:
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


def configure_runtime_environment(cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    cache_dir = cache_dir.resolve()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RunnerError(f"Could not create PaddleOCR model cache: {exc}") from exc
    environment = {
        "HOME": cache_dir / "home",
        "USERPROFILE": cache_dir / "home",
        "PADDLE_PDX_CACHE_HOME": cache_dir / "paddlex",
        "HF_HOME": cache_dir / "huggingface",
        "MODELSCOPE_CACHE": cache_dir / "modelscope",
    }
    for name, value in environment.items():
        os.environ[name] = str(value)
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = "huggingface"
    return cache_dir


def load_dependencies() -> tuple[Any, Any, str, str]:
    try:
        import paddle  # type: ignore[import-not-found]
        import paddleocr  # type: ignore[import-not-found]
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]
    except Exception as exc:
        raise RunnerError(
            "PaddleOCR dependencies are unavailable. Create the dedicated "
            "environment and install them with 'python -m pip install -r "
            "experiments/ocr-benchmark/runners/paddleocr/requirements.txt'."
        ) from exc
    return (
        PaddleOCR,
        paddle,
        package_version("paddleocr", paddleocr),
        package_version("paddlepaddle", paddle),
    )


def package_version(package_name: str, module: Any) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return str(getattr(module, "__version__", "unknown"))


def initialize_ocr(paddle_ocr_class: Any) -> Any:
    try:
        return paddle_ocr_class(**PIPELINE_SETTINGS)
    except Exception as exc:
        raise RunnerError(
            "Could not initialize official PaddleOCR models "
            f"'{DETECTION_MODEL}' and '{RECOGNITION_MODEL}'. Check network "
            f"access and the model cache at '{DEFAULT_CACHE_DIR}': {exc}"
        ) from exc


def model_hashes(cache_dir: Path) -> dict[str, str]:
    official_models = cache_dir / "paddlex" / "official_models"
    try:
        return {
            DETECTION_MODEL: sha256_directory(official_models / DETECTION_MODEL),
            RECOGNITION_MODEL: sha256_directory(official_models / RECOGNITION_MODEL),
        }
    except OSError as exc:
        raise RunnerError(f"Could not hash official PaddleOCR models: {exc}") from exc


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
    raw_text: str,
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
        temp_text.write_text(raw_text, encoding="utf-8", newline="\n")
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
        raise RunnerError(f"Could not write PaddleOCR output: {exc}") from exc
    finally:
        for temp_path in (temp_text, temp_json):
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def result_payload(result: Any) -> Mapping[str, Any]:
    try:
        serialized = result.json
    except Exception as exc:
        raise RunnerError(f"Could not serialize PaddleOCR result: {exc}") from exc
    if not isinstance(serialized, Mapping):
        raise RunnerError("PaddleOCR returned an unexpected result format.")
    payload = serialized.get("res", serialized)
    if not isinstance(payload, Mapping):
        raise RunnerError("PaddleOCR returned an unexpected result payload.")
    return payload


def sequence_value(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if value is not None else []


def extract_recognitions(results: Sequence[Any]) -> list[dict[str, object]]:
    if len(results) != 1:
        raise RunnerError(
            f"PaddleOCR returned {len(results)} results for one input image."
        )
    payload = result_payload(results[0])
    texts = sequence_value(payload, "rec_texts")
    scores = sequence_value(payload, "rec_scores")
    polygons = sequence_value(payload, "rec_polys")
    boxes = sequence_value(payload, "rec_boxes")
    recognitions: list[dict[str, object]] = []
    for index, text in enumerate(texts):
        recognitions.append(
            {
                "text": str(text),
                "confidence": float(scores[index]) if index < len(scores) else None,
                "polygon": polygons[index] if index < len(polygons) else None,
                "box": boxes[index] if index < len(boxes) else None,
            }
        )
    return recognitions


def run_image(
    *,
    ocr: Any,
    image_path: Path,
    output_dir: Path,
    paddleocr_version: str,
    paddlepaddle_version: str,
    official_model_hashes: Mapping[str, str],
    overwrite: bool,
) -> tuple[Path, Path, float, int]:
    try:
        input_sha256 = sha256_file(image_path)
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc

    started_at = time.perf_counter()
    try:
        results = ocr.predict(str(image_path))
    except Exception as exc:
        raise RunnerError(f"PaddleOCR failed for '{image_path.name}': {exc}") from exc
    processing_ms = round((time.perf_counter() - started_at) * 1000, 3)
    recognitions = extract_recognitions(results)
    raw_text = "\n".join(str(item["text"]) for item in recognitions)
    if recognitions:
        raw_text += "\n"

    text_path, json_path = output_paths(image_path, output_dir)
    output_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    configuration: dict[str, object] = {
        "language": LANGUAGE,
        "supported_text": ["Thai", "English", "numbers"],
        "ocr_version": OCR_VERSION,
        "text_detection_model": DETECTION_MODEL,
        "text_recognition_model": RECOGNITION_MODEL,
        "model_source": "official PaddleOCR via Hugging Face",
        "model_sha256": dict(official_model_hashes),
        **PIPELINE_SETTINGS,
        "input_format": "PNG",
        "input_dpi": 300,
        "input_color_mode": "RGB",
        "external_preprocessing": "none",
        "text_postprocessing": "none",
    }
    result_metadata: dict[str, object] = {
        "document_id": document_id_for(image_path),
        "engine": "paddleocr",
        "paddleocr_version": paddleocr_version,
        "paddlepaddle_version": paddlepaddle_version,
        "input_file": image_path.name,
        "input_sha256": input_sha256,
        "output_file": text_path.name,
        "output_sha256": output_sha256,
        "processing_ms": processing_ms,
        "status": "success",
        "preprocessing": "none",
        "configuration": configuration,
        "recognition_count": len(recognitions),
        "recognitions": recognitions,
    }
    write_outputs(text_path, json_path, raw_text, result_metadata, overwrite)
    return text_path, json_path, processing_ms, len(recognitions)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        images = collect_images(args.input, args.limit)
        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise RunnerError(f"Output path is not a directory: '{args.output}'.")
        ensure_outputs_available(images, args.output, args.overwrite)

        cache_dir = configure_runtime_environment()
        paddle_ocr_class, paddle, paddleocr_version, paddlepaddle_version = (
            load_dependencies()
        )
        if bool(paddle.device.is_compiled_with_cuda()):
            device_description = "cpu (CUDA-capable PaddlePaddle build)"
        else:
            device_description = "cpu"
        print(
            f"Initializing PaddleOCR {paddleocr_version}, PaddlePaddle "
            f"{paddlepaddle_version}, device={device_description}..."
        )
        ocr = initialize_ocr(paddle_ocr_class)
        official_model_hashes = model_hashes(cache_dir)
        print(
            f"Models: detection={DETECTION_MODEL}, "
            f"recognition={RECOGNITION_MODEL}, language={LANGUAGE}"
        )
        print(
            "Benchmark configuration: PNG 300 DPI RGB, preprocessing=none, "
            "postprocessing=none"
        )

        failures = 0
        total_processing_ms = 0.0
        for index, image_path in enumerate(images, start=1):
            try:
                text_path, json_path, processing_ms, recognition_count = run_image(
                    ocr=ocr,
                    image_path=image_path,
                    output_dir=args.output,
                    paddleocr_version=paddleocr_version,
                    paddlepaddle_version=paddlepaddle_version,
                    official_model_hashes=official_model_hashes,
                    overwrite=args.overwrite,
                )
                total_processing_ms += processing_ms
                print(
                    f"[{index}/{len(images)}] {image_path.name} -> "
                    f"{text_path.name}, {json_path.name} "
                    f"({recognition_count} lines, {processing_ms:.3f} ms)"
                )
            except RunnerError as exc:
                failures += 1
                print(f"Error: {exc}", file=sys.stderr)

        if failures:
            raise RunnerError(
                f"PaddleOCR failed for {failures} of {len(images)} image(s)."
            )
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
