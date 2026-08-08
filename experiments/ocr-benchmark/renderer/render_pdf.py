"""Render one PDF page to a fixed PNG for OCR benchmarking."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any, Sequence


DPI = 300
HASH_CHUNK_SIZE = 1024 * 1024


class RendererError(Exception):
    """A user-facing renderer failure."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render one 1-based PDF page as a 300 DPI RGB PNG.",
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Path to the source PDF")
    parser.add_argument(
        "--page",
        required=True,
        type=int,
        help="Page number to render (1-based)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory for the PNG and render metadata",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing PNG and metadata file",
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RendererError(
            "PyMuPDF is not installed. Install renderer dependencies with "
            "'python -m pip install -r "
            "experiments/ocr-benchmark/renderer/requirements.txt'."
        ) from exc
    return pymupdf


def pymupdf_version(pymupdf: Any) -> str:
    try:
        return metadata.version("PyMuPDF")
    except metadata.PackageNotFoundError:
        return str(getattr(pymupdf, "VersionBind", "unknown"))


def output_paths(pdf_path: Path, page_number: int, output_dir: Path) -> tuple[Path, Path]:
    output_stem = f"{pdf_path.stem}_page_{page_number:03d}"
    return (
        output_dir / f"{output_stem}.png",
        output_dir / f"{output_stem}.render.json",
    )


def ensure_outputs_available(paths: Sequence[Path], overwrite: bool) -> None:
    if overwrite:
        return

    existing = [path.name for path in paths if path.exists()]
    if existing:
        names = ", ".join(existing)
        raise RendererError(
            f"Output already exists: {names}. Use --overwrite to replace it."
        )


def create_temp_path(output_dir: Path, output_stem: str, suffix: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=f".{output_stem}.",
            suffix=suffix,
            delete=False,
        ) as temp_file:
            return Path(temp_file.name)
    except OSError as exc:
        raise RendererError(
            f"Could not create a temporary output file in '{output_dir}': {exc}"
        ) from exc


def validate_rendered_pixmap(pixmap: Any) -> None:
    if bool(pixmap.alpha):
        raise RendererError("Rendered image unexpectedly contains an alpha channel.")
    if pixmap.width <= 0 or pixmap.height <= 0:
        raise RendererError(
            f"Rendered image has invalid dimensions: {pixmap.width}x{pixmap.height}."
        )
    if pixmap.colorspace is None or pixmap.colorspace.n != 3:
        raise RendererError("Rendered image is not in the required RGB color space.")


def build_metadata(
    *,
    pdf_path: Path,
    source_sha256: str,
    page_number: int,
    png_path: Path,
    output_sha256: str,
    width_px: int,
    height_px: int,
    pymupdf: Any,
) -> dict[str, object]:
    return {
        "source_pdf": pdf_path.name,
        "source_pdf_sha256": source_sha256,
        "page_number": page_number,
        "page_index": page_number - 1,
        "dpi": DPI,
        "color_space": "RGB",
        "format": "PNG",
        "alpha": False,
        "preprocessing": False,
        "width_px": width_px,
        "height_px": height_px,
        "output_file": png_path.name,
        "output_sha256": output_sha256,
        "renderer": "PyMuPDF",
        "pymupdf_version": pymupdf_version(pymupdf),
    }


def render_pdf_page(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    if page_number <= 0:
        raise RendererError(
            f"Invalid page number {page_number}. Page numbers must start at 1."
        )
    if not pdf_path.exists():
        raise RendererError(f"PDF does not exist: '{pdf_path}'.")
    if not pdf_path.is_file():
        raise RendererError(f"PDF path is not a file: '{pdf_path}'.")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RendererError(
            f"Could not create output directory '{output_dir}': {exc}"
        ) from exc
    if not output_dir.is_dir():
        raise RendererError(f"Output path is not a directory: '{output_dir}'.")

    png_path, metadata_path = output_paths(pdf_path, page_number, output_dir)
    ensure_outputs_available((png_path, metadata_path), overwrite)

    pymupdf = load_pymupdf()
    try:
        source_sha256 = sha256_file(pdf_path)
    except OSError as exc:
        raise RendererError(f"Could not read PDF '{pdf_path}': {exc}") from exc

    try:
        document = pymupdf.open(str(pdf_path))
    except Exception as exc:
        raise RendererError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    temp_png: Path | None = None
    temp_metadata: Path | None = None
    try:
        if not document.is_pdf:
            raise RendererError(f"Input file is not a PDF: '{pdf_path}'.")
        if document.page_count <= 0:
            raise RendererError(f"PDF contains no pages: '{pdf_path}'.")
        if page_number > document.page_count:
            raise RendererError(
                f"Invalid page number {page_number}. PDF has "
                f"{document.page_count} page(s)."
            )

        page_index = page_number - 1
        try:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(
                dpi=DPI,
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            validate_rendered_pixmap(pixmap)
        except RendererError:
            raise
        except Exception as exc:
            raise RendererError(
                f"Could not render page {page_number} from '{pdf_path}': {exc}"
            ) from exc

        temp_png = create_temp_path(output_dir, png_path.stem, ".tmp.png")
        try:
            pixmap.save(str(temp_png))
            saved_pixmap = pymupdf.Pixmap(str(temp_png))
            validate_rendered_pixmap(saved_pixmap)
            width_px = saved_pixmap.width
            height_px = saved_pixmap.height
            output_sha256 = sha256_file(temp_png)
        except RendererError:
            raise
        except Exception as exc:
            raise RendererError(f"Could not write rendered PNG: {exc}") from exc

        render_metadata = build_metadata(
            pdf_path=pdf_path,
            source_sha256=source_sha256,
            page_number=page_number,
            png_path=png_path,
            output_sha256=output_sha256,
            width_px=width_px,
            height_px=height_px,
            pymupdf=pymupdf,
        )

        temp_metadata = create_temp_path(
            output_dir, metadata_path.stem, ".tmp.json"
        )
        try:
            temp_metadata.write_text(
                json.dumps(render_metadata, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise RendererError(f"Could not write render metadata: {exc}") from exc

        ensure_outputs_available((png_path, metadata_path), overwrite)
        try:
            os.replace(temp_png, png_path)
            temp_png = None
            os.replace(temp_metadata, metadata_path)
            temp_metadata = None
        except OSError as exc:
            raise RendererError(f"Could not publish renderer outputs: {exc}") from exc

        return png_path, metadata_path
    finally:
        document.close()
        for temp_path in (temp_png, temp_metadata):
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        png_path, metadata_path = render_pdf_page(
            pdf_path=args.pdf,
            page_number=args.page,
            output_dir=args.output,
            overwrite=args.overwrite,
        )
    except RendererError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Rendered PNG: {png_path}")
    print(f"Render metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
