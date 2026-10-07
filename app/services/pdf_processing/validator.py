"""Secure PDF validation – magic bytes, size, pages, encryption."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz

from app.config import get_settings

logger = logging.getLogger(__name__)


class PDFValidationError(Exception):
    """Client-facing validation failure."""


class UnsupportedPDFError(Exception):
    """Encrypted or otherwise unsupported PDF."""


def validate_pdf(path: Path, *, check_pages: bool = True) -> int:
    """
    Validate a PDF on disk.
    Returns page count on success.
    Raises PDFValidationError / UnsupportedPDFError.
    """
    settings = get_settings()

    if not path.exists() or not path.is_file():
        raise PDFValidationError("File does not exist.")

    size = path.stat().st_size
    if size == 0:
        raise PDFValidationError("Uploaded file is empty.")
    if size > settings.max_pdf_size_bytes:
        raise PDFValidationError(
            f"PDF exceeds maximum allowed size of {settings.MAX_PDF_SIZE_MB} MB."
        )

    # Magic bytes
    with open(path, "rb") as f:
        header = f.read(8)
    if not header.startswith(b"%PDF"):
        raise PDFValidationError("File does not appear to be a valid PDF (bad signature).")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        logger.warning("fitz.open failed: %s", exc)
        raise PDFValidationError("Unable to open PDF. File may be corrupted.") from exc

    try:
        if doc.is_encrypted:
            raise UnsupportedPDFError("Encrypted PDFs are not supported.")
        page_count = doc.page_count
        if check_pages and page_count > settings.MAX_PDF_PAGES:
            raise PDFValidationError(
                f"PDF has {page_count} pages; maximum allowed is {settings.MAX_PDF_PAGES}."
            )
        if page_count == 0:
            raise PDFValidationError("PDF contains no pages.")
        return page_count
    finally:
        doc.close()
