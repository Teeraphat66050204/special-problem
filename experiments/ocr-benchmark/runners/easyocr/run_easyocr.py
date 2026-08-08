"""Run EasyOCR on shared benchmark PNG images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Sequence


HASH_CHUNK_SIZE = 1024 * 1024
DEFAULT_LANGUAGES = ("th", "en")
EASYOCR_SETTINGS = {
    "decoder": "greedy",
    "batch_size": 1,
    "workers": 0,
    "detail": 1,
    "paragraph": False,
    "min_size": 10,
    "rotation_info": None,
    "contrast_ths": 0.1,
    "adjust_contrast": 0.5,
    "text_threshold": 0.7,
    "low_text": 0.4,
    "link_threshold": 0.4,
    "canvas_size": 2560,
    "mag_ratio": 1.0,
    "slope_ths": 0.1,
    "ycenter_ths": 0.5,
    "height_ths": 0.5,
    "width_ths": 0.5,
    "add_margin": 0.1,
    "threshold": 0.2,
    "bbox_min_score": 0.2,
    "bbox_min_size": 3,
    "max_candidates": 0,
}


class RunnerError(Exception):
    """A user-facing EasyOCR runner failure."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run EasyOCR on one PNG or a directory of benchmark PNGs.",
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
        help="Directory for EasyOCR .txt and .json outputs",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=list(DEFAULT_LANGUAGES),
        help="EasyOCR language codes (default: th en)",
    )
    parser.add_argument(
        "--gpu",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="Processing device (default: auto)",
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

    existing: list[str] = []
    for image_path in images:
        for output_path in output_paths(image_path, output_dir):
            if output_path.exists():
                existing.append(output_path.name)
    if existing:
        preview = ", ".join(existing[:5])
        if len(existing) > 5:
            preview += f", and {len(existing) - 5} more"
        raise RunnerError(
            f"Output already exists: {preview}. Use --overwrite to replace it."
        )


def load_dependencies() -> tuple[Any, Any]:
    try:
        import easyocr  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        raise RunnerError(
            "EasyOCR dependencies are unavailable. Install them with "
            "'python -m pip install -r "
            "experiments/ocr-benchmark/runners/easyocr/requirements.txt'."
        ) from exc
    return easyocr, torch


def resolve_gpu(requested_gpu: str, torch: Any) -> tuple[bool, str]:
    cuda_available = bool(torch.cuda.is_available())
    if requested_gpu == "cuda" and not cuda_available:
        raise RunnerError("CUDA was requested, but PyTorch cannot access a CUDA GPU.")
    use_gpu = cuda_available if requested_gpu == "auto" else requested_gpu == "cuda"
    return use_gpu, "cuda" if use_gpu else "cpu"


def normalize_detection(detection: Sequence[Any]) -> dict[str, object]:
    bounding_box, text, confidence = detection
    return {
        "bounding_box": [
            [float(point[0]), float(point[1])] for point in bounding_box
        ],
        "text": str(text),
        "confidence": float(confidence),
    }


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
        raise RunnerError(f"Could not write EasyOCR output: {exc}") from exc
    finally:
        for temp_path in (temp_text, temp_json):
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def run_image(
    *,
    reader: Any,
    image_path: Path,
    output_dir: Path,
    languages: Sequence[str],
    requested_gpu: str,
    device: str,
    easyocr_version: str,
    torch_version: str,
    overwrite: bool,
) -> tuple[Path, Path, float, int]:
    try:
        input_sha256 = sha256_file(image_path)
    except OSError as exc:
        raise RunnerError(f"Could not read image '{image_path}': {exc}") from exc

    started_at = time.perf_counter()
    try:
        raw_detections = reader.readtext(str(image_path), **EASYOCR_SETTINGS)
    except Exception as exc:
        raise RunnerError(f"EasyOCR failed for '{image_path.name}': {exc}") from exc
    processing_time_seconds = time.perf_counter() - started_at

    detections = [normalize_detection(detection) for detection in raw_detections]
    recognized_lines = [str(detection[1]) for detection in raw_detections]
    raw_text = "\n".join(recognized_lines)
    if raw_text:
        raw_text += "\n"

    text_path, json_path = output_paths(image_path, output_dir)
    text_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    result_metadata: dict[str, object] = {
        "engine": "EasyOCR",
        "easyocr_version": easyocr_version,
        "torch_version": torch_version,
        "input_file": image_path.name,
        "input_sha256": input_sha256,
        "output_text_file": text_path.name,
        "output_text_sha256": text_sha256,
        "languages": list(languages),
        "gpu_requested": requested_gpu,
        "device_used": device,
        "processing_time_seconds": processing_time_seconds,
        "settings": EASYOCR_SETTINGS,
        "detection_count": len(detections),
        "text": raw_text,
        "detections": detections,
    }
    write_outputs(text_path, json_path, raw_text, result_metadata, overwrite)
    return text_path, json_path, processing_time_seconds, len(detections)


def package_version(package_name: str, module: Any) -> str:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return str(getattr(module, "__version__", "unknown"))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        images = collect_images(args.input, args.limit)
        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise RunnerError(f"Output path is not a directory: '{args.output}'.")
        ensure_outputs_available(images, args.output, args.overwrite)

        easyocr, torch = load_dependencies()
        use_gpu, device = resolve_gpu(args.gpu, torch)
        print(
            f"Initializing EasyOCR languages={','.join(args.languages)} "
            f"device={device}..."
        )
        try:
            reader = easyocr.Reader(args.languages, gpu=use_gpu, verbose=False)
        except Exception as exc:
            raise RunnerError(f"Could not initialize EasyOCR: {exc}") from exc

        failures = 0
        for index, image_path in enumerate(images, start=1):
            try:
                text_path, json_path, elapsed, detections = run_image(
                    reader=reader,
                    image_path=image_path,
                    output_dir=args.output,
                    languages=args.languages,
                    requested_gpu=args.gpu,
                    device=device,
                    easyocr_version=package_version("easyocr", easyocr),
                    torch_version=package_version("torch", torch),
                    overwrite=args.overwrite,
                )
                print(
                    f"[{index}/{len(images)}] {image_path.name} -> "
                    f"{text_path.name}, {json_path.name} "
                    f"({detections} detections, {elapsed:.3f}s)"
                )
            except RunnerError as exc:
                failures += 1
                print(f"Error: {exc}", file=sys.stderr)

        if failures:
            raise RunnerError(
                f"EasyOCR failed for {failures} of {len(images)} image(s)."
            )
        print(f"Completed {len(images)} image(s). Outputs: {args.output}")
        return 0
    except (OSError, RunnerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
