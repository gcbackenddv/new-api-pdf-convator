"""Deskew entire PDF page-by-page."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz

from app.config import get_settings
from .deskew import detect_skew, deskew_image
from .renderer import render_page_to_image
from .validator import validate_pdf

logger = logging.getLogger(__name__)


def deskew_pdf(
    src: Path,
    dst: Path,
    *,
    min_confidence: float = 0.4,
    manual_angle: float | None = None,
    manual_angles: list[float] | None = None,
) -> dict:
    validate_pdf(src)
    settings = get_settings()
    src_doc = fitz.open(src)
    out_doc = fitz.open()
    corrected = 0

    try:
        for i in range(src_doc.page_count):
            page = src_doc[i]
            img = render_page_to_image(src_doc, i, dpi=min(120, settings.MAX_RENDER_DPI))
            original_size = img.size
            page_angle = manual_angles[i] if manual_angles is not None else manual_angle
            if page_angle is not None:
                if abs(page_angle) > 0.1:
                    img = deskew_image(img, page_angle, expand=True)
                    corrected += 1
                    logger.debug("Page %d manually rotated by %.2f°", i + 1, page_angle)
            else:
                angle, conf = detect_skew(img)
                if conf >= min_confidence and abs(angle) > 0.3:
                    img = deskew_image(img, angle)
                    corrected += 1
                    logger.debug("Page %d deskewed by %.2f° (conf=%.2f)", i + 1, angle, conf)

            # Insert as full-page image (preserves visual; loses vector)
            # For mixed vector+scan docs a more sophisticated approach is needed.
            rect = page.rect
            page_width = rect.width * img.width / original_size[0]
            page_height = rect.height * img.height / original_size[1]
            new_page = out_doc.new_page(width=page_width, height=page_height)
            # Save temp image bytes
            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            new_page.insert_image(new_page.rect, stream=buf.getvalue())

        out_doc.save(dst, garbage=4, deflate=True)
        return {"pages_total": src_doc.page_count, "pages_corrected": corrected}
    finally:
        src_doc.close()
        out_doc.close()
