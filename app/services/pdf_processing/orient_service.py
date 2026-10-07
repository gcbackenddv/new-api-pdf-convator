"""Auto-rotate PDF pages to upright orientation."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz

from app.config import get_settings
from .orientation import detect_orientation
from .renderer import render_page_to_image
from .validator import validate_pdf

logger = logging.getLogger(__name__)


def auto_rotate_pdf(src: Path, dst: Path, *, min_confidence: float = 0.5) -> dict:
    validate_pdf(src)
    settings = get_settings()
    doc = fitz.open(src)
    rotated = 0

    try:
        for i in range(doc.page_count):
            page = doc[i]
            img = render_page_to_image(doc, i, dpi=min(100, settings.MAX_RENDER_DPI))
            degrees, conf = detect_orientation(img)
            if conf >= min_confidence and degrees != 0:
                # PyMuPDF rotate is clockwise
                page.set_rotation((page.rotation + degrees) % 360)
                rotated += 1
                logger.debug("Page %d rotated %d° (conf=%.2f)", i + 1, degrees, conf)

        doc.save(dst, garbage=4, deflate=True)
        return {"pages_total": doc.page_count, "pages_rotated": rotated}
    finally:
        doc.close()
