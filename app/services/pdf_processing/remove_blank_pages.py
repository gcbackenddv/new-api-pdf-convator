"""Service for detecting and removing blank pages from PDF documents.

Handles both normal text-based PDFs and scanned/raster PDFs:
- Fast text analysis for pages with printable text.
- Fast visual object checks for completely empty PDF pages.
- Pixel density analysis for scanned/raster pages and vector backgrounds.
- Edge margin filtering to prevent scanner feeder lines/shadows from causing false negatives.
- Preserves original page order, bookmarks/vector data, and quality.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf as fitz

from app.config import get_settings
from .validator import validate_pdf, PDFValidationError, UnsupportedPDFError

logger = logging.getLogger(__name__)


class PDFAllPagesBlankError(Exception):
    """Raised when every page in the document is blank and removing them would result in an empty PDF."""


class PDFTimeoutError(Exception):
    """Raised when processing exceeds the configured timeout."""


class PDFProcessingError(Exception):
    """Raised on internal PDF processing failures."""


def is_page_blank(
    page: fitz.Page,
    threshold: float | None = None,
    dpi: int | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Determine whether a single PDF page is blank.

    Returns:
        (is_blank, metadata_dict)
    """
    settings = get_settings()
    eff_threshold = threshold if threshold is not None else settings.BLANK_PAGE_THRESHOLD
    eff_dpi = dpi if dpi is not None else settings.BLANK_PAGE_DPI

    # 1. Fast text check: if printable non-whitespace text exists, page is NOT blank.
    text = page.get_text().strip()
    printable_text = "".join(c for c in text if c.isprintable() and not c.isspace())
    if len(printable_text) > 0:
        return False, {"reason": "text_detected", "ratio": 1.0}

    # 2. Check for visual PDF objects
    images = page.get_images()
    drawings = page.get_drawings()
    annots = list(page.annots())
    widgets = list(page.widgets())

    # If literally no objects exist on the page, it is 100% blank
    if not images and not drawings and not annots and not widgets:
        return True, {"reason": "empty_objects", "ratio": 0.0}

    # 3. Pixel analysis for scanned pages, full-page images, or vector drawings/backgrounds
    try:
        pix = page.get_pixmap(dpi=eff_dpi, colorspace=fitz.csGRAY, alpha=False, annots=True)
        arr = np.frombuffer(pix.samples, dtype=np.uint8)
        if arr.size == 0:
            return True, {"reason": "empty_pixmap", "ratio": 0.0}

        # Background brightness (median of page pixels)
        bg = float(np.median(arr))
        diff_full = np.abs(arr.astype(np.int16) - int(bg))
        # Significant deviation from background: contrast difference > 35
        full_significant = np.sum(diff_full > 35)
        full_ratio = float(full_significant / arr.size)

        # Check interior pixels excluding 1.5% outer margin (helps ignore scanner feed shadows)
        h, w = pix.height, pix.width
        margin_y = min(15, max(4, int(h * 0.015)))
        margin_x = min(15, max(4, int(w * 0.015)))

        if h > 2 * margin_y and w > 2 * margin_x:
            interior = arr.reshape((h, w))[margin_y:h - margin_y, margin_x:w - margin_x]
            bg_int = float(np.median(interior))
            diff_int = np.abs(interior.astype(np.int16) - int(bg_int))
            interior_significant = np.sum(diff_int > 35)
            interior_ratio = float(interior_significant / interior.size)
            effective_ratio = min(full_ratio, interior_ratio)
        else:
            effective_ratio = full_ratio

        is_blank = effective_ratio < eff_threshold
        reason = "scanned_or_image_blank" if is_blank else "image_or_drawing_content"
        return is_blank, {"reason": reason, "ratio": effective_ratio}
    except Exception as exc:
        logger.warning("Pixel analysis failed on page: %s", exc)
        # Conservative fallback: if error occurs on non-empty page, do not delete it
        return False, {"reason": "analysis_error", "ratio": 1.0}


def remove_blank_pages(
    src: Path,
    dst: Path,
    *,
    threshold: float | None = None,
    dpi: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Inspect all pages in src PDF and remove genuinely blank ones, saving to dst.

    Returns:
        dict with keys:
            - original_page_count: int
            - removed_page_count: int
            - remaining_page_count: int
            - removed_page_numbers: list[int] (1-indexed)
    """
    settings = get_settings()
    validate_pdf(src)

    eff_timeout = timeout if timeout is not None else settings.PROCESSING_TIMEOUT
    deadline = time.monotonic() + eff_timeout

    doc = fitz.open(src)
    try:
        original_page_count = doc.page_count
        if original_page_count == 0:
            raise PDFValidationError("PDF contains no pages.")

        kept_indices: list[int] = []
        removed_page_numbers: list[int] = []

        for idx in range(original_page_count):
            if time.monotonic() > deadline:
                raise PDFTimeoutError(
                    f"Processing timed out after {eff_timeout} seconds."
                )

            page = doc[idx]
            is_blank, meta = is_page_blank(page, threshold=threshold, dpi=dpi)

            if is_blank:
                removed_page_numbers.append(idx + 1)
                logger.debug(
                    "Page %d identified as blank (%s, ratio=%s)",
                    idx + 1,
                    meta.get("reason"),
                    meta.get("ratio"),
                )
            else:
                kept_indices.append(idx)

        # If every page is blank, raise an error because a 0-page PDF cannot be saved
        if not kept_indices:
            raise PDFAllPagesBlankError(
                "Cannot remove all pages: all pages in the PDF are blank."
            )

        # Retain only non-blank pages preserving original order
        if len(kept_indices) < original_page_count:
            doc.select(kept_indices)

        dst.parent.mkdir(parents=True, exist_ok=True)
        doc.save(dst, garbage=4, deflate=True)

        return {
            "original_page_count": original_page_count,
            "removed_page_count": len(removed_page_numbers),
            "remaining_page_count": len(kept_indices),
            "removed_page_numbers": removed_page_numbers,
        }
    finally:
        doc.close()
