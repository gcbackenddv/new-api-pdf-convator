import io
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
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
    """Render each PDF page to HEIC and package directly into a ZIP archive.

    Optimized with ThreadPoolExecutor and in-memory byte streams to eliminate
    costly disk I/O per page, significantly speeding up API response times.
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

        # Validate page dimensions first
        for i in range(total):
            rect = doc[i].rect
            if (rect.width * zoom) * (rect.height * zoom) > max_pixels:
                raise PdfToHeicError(
                    f"Page {i + 1} is too large to render at {dpi} DPI.", 413
                )

    def _convert_page(page_idx: int) -> tuple[str, bytes]:
        page_doc = fitz.open(pdf_path)
        try:
            page = page_doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            img.save(buf, format="HEIF", quality=quality, encopts={"preset": "faster"})
            img.close()
            del pix, page
            name = f"page-{page_idx + 1:0{width_digits}d}.heic"
            return name, buf.getvalue()
        finally:
            page_doc.close()

    try:
        max_workers = min(os.cpu_count() or 4, 4, total) if total > 1 else 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            encoded_pages = list(executor.map(_convert_page, range(total)))

        # HEIC is already compressed; ZIP_STORED avoids pointless CPU re-compression.
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for name, data in encoded_pages:
                zf.writestr(name, data)

    except PdfToHeicError:
        raise
    except Exception as exc:
        logger.exception("PDF conversion failed")
        raise PdfToHeicError("The PDF could not be converted (it may be corrupted).") from exc

    size = zip_path.stat().st_size
    duration = time.perf_counter() - started
    logger.info(
        "PDF conversion completed: pages=%d output_bytes=%d seconds=%.2f (%.2f s/page)",
        total, size, duration, duration / max(total, 1),
    )
    return ConversionResult(zip_path, total, size)