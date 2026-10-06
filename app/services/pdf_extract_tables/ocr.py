"""OCR backend abstraction. Default backend: Tesseract via PyMuPDF (no extra Python package)."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Protocol

import pymupdf

from app.services.pdf_extract_tables.errors import OCRProcessingError, OCRUnavailableError

logger = logging.getLogger(__name__)

_LANG_RE = re.compile(r"^[A-Za-z0-9_]{2,16}(\+[A-Za-z0-9_]{2,16})*$")
MIN_OCR_DPI = 72


class OcrBackend(Protocol):
    def is_available(self, language: str) -> bool: ...

    def page_to_searchable_pdf(self, page: pymupdf.Page, *, dpi: int, language: str) -> bytes:
        """Return a one-page PDF (same page size) that carries an OCR text layer."""
        ...


def effective_dpi(width_pt: float, height_pt: float, dpi: int, max_pixels: int) -> int:
    """Lower the render resolution so one page never exceeds ``max_pixels``."""
    pixels = (width_pt * dpi / 72) * (height_pt * dpi / 72)
    if pixels <= max_pixels:
        return dpi
    return max(MIN_OCR_DPI, int(dpi * math.sqrt(max_pixels / pixels)))


def _tessdata_dir() -> Path | None:
    try:
        value = pymupdf.get_tessdata()
    except Exception:
        return None
    return Path(value) if value else None


class TesseractOcr:
    """Needs Tesseract language data on disk (``TESSDATA_PREFIX`` or a standard location)."""

    def is_available(self, language: str) -> bool:
        if not _LANG_RE.match(language):
            return False
        tessdata = _tessdata_dir()
        if tessdata is None:
            return False
        return all((tessdata / f"{lang}.traineddata").is_file() for lang in language.split("+"))

    def page_to_searchable_pdf(self, page: pymupdf.Page, *, dpi: int, language: str) -> bytes:
        tessdata = _tessdata_dir()
        if tessdata is None:
            raise OCRUnavailableError("OCR is not available on this server.")
        try:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            return pix.pdfocr_tobytes(language=language, tessdata=str(tessdata))
        except Exception as exc:
            logger.warning("pdf_tables.ocr_failed error_type=%s", type(exc).__name__)
            raise OCRProcessingError("OCR processing failed for a page.") from exc