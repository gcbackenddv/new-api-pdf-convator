"""Apply image enhancements page-by-page and rebuild PDF."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from app.config import get_settings
from .enhancement import enhance_image
from .renderer import render_page_to_image
from .validator import validate_pdf

logger = logging.getLogger(__name__)


def enhance_pdf(
    src: Path,
    dst: Path,
    *,
    grayscale: bool = False,
    contrast: float = 1.15,
    brightness: float = 1.05,
    sharpen: float = 0.3,
    denoise: bool = False,
    threshold: bool = False,
    background_cleanup: bool = False,
) -> dict:
    validate_pdf(src)
    settings = get_settings()
    src_doc = fitz.open(src)
    out_doc = fitz.open()

    try:
        for i in range(src_doc.page_count):
            page = src_doc[i]
            img = render_page_to_image(src_doc, i, dpi=min(130, settings.MAX_RENDER_DPI))
            img = enhance_image(
                img,
                grayscale=grayscale,
                contrast=contrast,
                brightness=brightness,
                sharpen=sharpen,
                denoise=denoise,
                threshold=threshold,
                background_cleanup=background_cleanup,
            )
            rect = page.rect
            new_page = out_doc.new_page(width=rect.width, height=rect.height)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            new_page.insert_image(rect, stream=buf.getvalue())

        out_doc.save(dst, garbage=4, deflate=True)
        return {"pages_total": src_doc.page_count, "enhanced": True}
    finally:
        src_doc.close()
        out_doc.close()
