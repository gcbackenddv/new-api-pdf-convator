"""Make a PDF searchable by adding an invisible OCR text layer."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from app.config import get_settings
from .ocr import ocr_image, page_has_text, ocr_available
from .renderer import render_page_to_image
from .validator import validate_pdf

logger = logging.getLogger(__name__)


def make_searchable(
    src: Path,
    dst: Path,
    *,
    lang: str | None = None,
    force_ocr: bool = False,
) -> dict:
    """
    Produce a new PDF with an invisible text layer on pages that need OCR.
    Preserves original appearance, page size and vector content.
    """
    validate_pdf(src)
    if not ocr_available() and force_ocr:
        raise RuntimeError("OCR requested but pytesseract/Tesseract is not available.")

    settings = get_settings()
    lang = lang or settings.OCR_LANGUAGE
    doc = fitz.open(src)
    ocr_pages = 0
    skipped = 0

    try:
        for i in range(doc.page_count):
            page = doc[i]
            if not force_ocr and page_has_text(page):
                skipped += 1
                continue

            # Render → OCR
            img = render_page_to_image(doc, i, dpi=min(150, settings.MAX_RENDER_DPI))
            text = ocr_image(img, lang=lang)
            if not text:
                continue

            # Insert invisible text (fontsize tiny, render_mode 3 = invisible)
            # Place near top-left; real production systems use word-level bboxes.
            # This is a pragmatic VPS-friendly approach.
            rect = page.rect
            tw = fitz.TextWriter(rect)
            # Simple block – good enough for search; full word boxes need more work
            tw.append(fitz.Point(rect.x0 + 5, rect.y0 + 20), text[:5000], fontsize=8)
            tw.write_text(page, render_mode=3)  # 3 = invisible
            ocr_pages += 1

        doc.save(dst, garbage=4, deflate=True)
        return {
            "pages_total": doc.page_count,
            "pages_ocrd": ocr_pages,
            "pages_skipped": skipped,
        }
    finally:
        doc.close()
