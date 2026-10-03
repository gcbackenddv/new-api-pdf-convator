import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()
logger = logging.getLogger(__name__)


class PdfToHeicError(Exception):
    """Business-rule failure. The router maps it to the project's error format."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ConversionResult:
    zip_path: Path
    page_count: int
    zip_size: int


def convert_pdf_to_heic_zip(
    pdf_path: Path,
    work_dir: Path,
    *,
    dpi: int,
    quality: int,
    max_pages: int,
    max_pixels: int = 150_000_000,
) -> ConversionResult:
    """Render each PDF page to one HEIC and package them into a ZIP.

    Pages are processed one at a time; each HEIC is added to the ZIP and
    deleted immediately, so peak memory/disk is about one page.
    """
    started = time.perf_counter()
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # fitz raises several types for bad files
        raise PdfToHeicError("The file is not a valid PDF.") from exc

    with doc:
        if not doc.is_pdf:
            raise PdfToHeicError("The file is not a valid PDF.")
        if doc.needs_pass:
            raise PdfToHeicError("Password-protected PDFs are not supported.")
        total = doc.page_count
        if total < 1:
            raise PdfToHeicError("The PDF has no pages.")
        if total > max_pages:
            raise PdfToHeicError(
                f"PDF has {total} pages; the maximum is {max_pages}.", 413
            )

        logger.info("PDF conversion started: pages=%d dpi=%d quality=%d", total, dpi, quality)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        zip_path = work_dir / "converted-pages.zip"
        width_digits = max(3, len(str(total)))

        try:
            # HEIC is already compressed, so STORED avoids pointless CPU work.
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for index in range(total):
                    name = f"page-{index + 1:0{width_digits}d}.heic"
                    heic_path = work_dir / name
                    page = doc.load_page(index)
                    rect = page.rect
                    if (rect.width * zoom) * (rect.height * zoom) > max_pixels:
                        raise PdfToHeicError(
                            f"Page {index + 1} is too large to render at {dpi} DPI.", 413
                        )
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    try:
                        img.save(heic_path, format="HEIF", quality=quality)
                    finally:
                        img.close()
                        del pix, page
                    zf.write(heic_path, arcname=name)  # flat name, no directories
                    heic_path.unlink()
                    logger.info("Converted page %d/%d", index + 1, total)
        except PdfToHeicError:
            raise
        except Exception as exc:
            logger.exception("PDF conversion failed")
            raise PdfToHeicError("The PDF could not be converted (it may be corrupted).") from exc

    size = zip_path.stat().st_size
    logger.info(
        "PDF conversion completed: pages=%d output_bytes=%d seconds=%.2f",
        total, size, time.perf_counter() - started,
    )
    return ConversionResult(zip_path, total, size)