"""Service for repairing corrupted or damaged PDF documents."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pymupdf as fitz

from app.config import get_settings
from .validator import PDFValidationError

logger = logging.getLogger(__name__)


def repair_pdf(src: Path, dst: Path) -> dict[str, Any]:
    """Repair damaged or malformed PDF using MuPDF's reconstruction engine.

    Rebuilds broken XREF tables, restores missing headers/trailers, fixes damaged
    object streams, and rewrites clean PDF structures.
    """
    settings = get_settings()
    if not src.exists() or not src.is_file():
        raise PDFValidationError("File does not exist.")

    if src.stat().st_size == 0:
        raise PDFValidationError("The uploaded file is empty.")

    if src.stat().st_size > settings.max_pdf_size_bytes:
        raise PDFValidationError(
            f"PDF exceeds maximum allowed size of {settings.MAX_PDF_SIZE_MB} MB."
        )

    try:
        doc = fitz.open(src)
    except Exception as exc:
        logger.warning("fitz.open failed during repair: %s", exc)
        raise PDFValidationError("File is severely corrupted and cannot be repaired.") from exc

    try:
        if doc.is_encrypted:
            raise PDFValidationError("Encrypted PDFs cannot be repaired without a password.")

        page_count = doc.page_count
        if page_count == 0:
            raise PDFValidationError("PDF contains no readable pages.")

        was_repaired = bool(doc.is_repaired)
        dst.parent.mkdir(parents=True, exist_ok=True)
        doc.save(dst, garbage=4, deflate=True, clean=True)

        return {
            "page_count": page_count,
            "was_repaired": was_repaired,
        }
    finally:
        doc.close()

