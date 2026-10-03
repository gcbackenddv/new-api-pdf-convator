import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()
logger = logging.getLogger(__name__)


class LongImageError(Exception):
    """Client-safe failure. The router converts it to an HTTPException."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class OutputFormat:
    pil_format: str
    extension: str
    media_type: str


_FORMATS = {
    "png": OutputFormat("PNG", "png", "image/png"),
    "jpg": OutputFormat("JPEG", "jpg", "image/jpeg"),
    "jpeg": OutputFormat("JPEG", "jpg", "image/jpeg"),
    "heic": OutputFormat("HEIF", "heic", "image/heic"),
}


@dataclass(frozen=True)
class LongImageResult:
    path: Path
    fmt: OutputFormat
    width: int
    height: int
    page_count: int


def resolve_format(name: str) -> OutputFormat:
    fmt = _FORMATS.get(name.strip().lower())
    if fmt is None:
        raise LongImageError(
            f"Unsupported format '{name}'. Supported: png, jpg, jpeg, heic.", 400
        )
    return fmt


def _ensure_pdf_header(pdf_path: Path) -> None:
    with pdf_path.open("rb") as fh:
        if b"%PDF-" not in fh.read(1024):
            raise LongImageError("The file is not a valid PDF.", 400)


def _plan_layout(
    doc: fitz.Document, zoom: float, *, max_pixels: int, max_dimension: int
) -> tuple[list[tuple[int, int]], int, int]:
    """Compute every page's pixel size WITHOUT rendering anything."""
    matrix = fitz.Matrix(zoom, zoom)
    sizes: list[tuple[int, int]] = []
    for index in range(doc.page_count):
        irect = (doc.load_page(index).rect * matrix).irect
        sizes.append((max(irect.width, 1), max(irect.height, 1)))
    width = max(w for w, _ in sizes)
    height = sum(h for _, h in sizes)
    if width > max_dimension or height > max_dimension or width * height > max_pixels:
        raise LongImageError(
            f"The resulting image would be {width}x{height} px, which exceeds the "
            "allowed size. Lower the DPI or use a PDF with fewer pages.",
            413,
        )
    return sizes, width, height


def convert_pdf_to_long_image(
    pdf_path: Path,
    work_dir: Path,
    fmt: OutputFormat,
    *,
    dpi: int,
    quality: int,
    max_pages: int,
    max_pixels: int,
    max_dimension: int,
) -> LongImageResult:
    started = time.perf_counter()
    _ensure_pdf_header(pdf_path)
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.warning("Could not open PDF: %s", exc)
        raise LongImageError("The file is not a valid or readable PDF.", 400) from exc

    with doc:
        if not doc.is_pdf:
            raise LongImageError("The file is not a valid PDF.", 400)
        if doc.needs_pass:
            raise LongImageError("Password-protected PDFs are not supported.", 400)
        total = doc.page_count
        if total < 1:
            raise LongImageError("The PDF has no pages.", 400)
        if total > max_pages:
            raise LongImageError(f"PDF has {total} pages; the maximum is {max_pages}.", 413)

        zoom = dpi / 72.0
        try:
            sizes, width, height = _plan_layout(
                doc, zoom, max_pixels=max_pixels, max_dimension=max_dimension
            )
        except LongImageError:
            raise
        except Exception as exc:
            logger.exception("Page size planning failed")
            raise LongImageError("Unable to read the PDF page sizes.", 422) from exc

        logger.info("Long image started: pages=%d canvas=%dx%d dpi=%d", total, width, height, dpi)

        try:
            canvas = Image.new("RGB", (width, height), "white")
        except Exception as exc:
            logger.exception("Canvas allocation failed")
            raise LongImageError("Not enough memory to build the image.", 413) from exc

        try:
            matrix = fitz.Matrix(zoom, zoom)
            y = 0
            for index in range(total):
                try:
                    page = doc.load_page(index)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    page_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                except Exception as exc:
                    logger.exception("Rendering failed on page %d", index + 1)
                    raise LongImageError("Unable to render the PDF.", 422) from exc
                try:
                    canvas.paste(page_img, ((width - pix.width) // 2, y))  # centered
                except Exception as exc:
                    logger.exception("Stitching failed on page %d", index + 1)
                    raise LongImageError("Unable to stitch the PDF pages.", 500) from exc
                finally:
                    page_img.close()
                    del pix, page, page_img
                y += sizes[index][1]
                logger.info("Stitched page %d/%d", index + 1, total)

            out_path = work_dir / f"{uuid.uuid4().hex}.{fmt.extension}"
            save_kwargs: dict = {}
            if fmt.pil_format in ("JPEG", "HEIF"):
                save_kwargs["quality"] = quality
            try:
                canvas.save(out_path, format=fmt.pil_format, **save_kwargs)
            except Exception as exc:
                logger.exception("Saving %s failed", fmt.pil_format)
                if fmt.pil_format == "HEIF":
                    raise LongImageError("HEIC conversion failed.", 500) from exc
                raise LongImageError(f"Unable to save the image as {fmt.extension}.", 500) from exc
        finally:
            canvas.close()

    logger.info(
        "Long image completed: %dx%d bytes=%d seconds=%.2f",
        width, height, out_path.stat().st_size, time.perf_counter() - started,
    )
    return LongImageResult(out_path, fmt, width, height, total)