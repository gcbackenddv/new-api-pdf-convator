"""Safe page rendering with DPI and pixel limits for VPS."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import pymupdf as fitz
import numpy as np
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


def render_page_to_image(
    doc: fitz.Document,
    page_index: int,
    *,
    dpi: Optional[int] = None,
    colorspace: str = "rgb",
) -> Image.Image:
    """
    Render a single page to a PIL Image.
    Enforces MAX_RENDER_DPI and MAX_PAGE_PIXELS to protect RAM.
    """
    settings = get_settings()
    dpi = min(dpi or settings.MAX_RENDER_DPI, settings.MAX_RENDER_DPI)
    page = doc[page_index]

    # Scale matrix
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    # Estimate pixels and clamp if necessary
    rect = page.rect
    est_w = int(rect.width * zoom)
    est_h = int(rect.height * zoom)
    if est_w * est_h > settings.MAX_PAGE_PIXELS:
        scale = (settings.MAX_PAGE_PIXELS / (est_w * est_h)) ** 0.5
        mat = fitz.Matrix(zoom * scale, zoom * scale)
        logger.debug(
            "Clamped render scale for page %d (%.0fx%.0f px)",
            page_index + 1, est_w * scale, est_h * scale,
        )

    pix = page.get_pixmap(matrix=mat, alpha=False)
    mode = "RGB" if pix.n < 4 else "RGBA"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    if colorspace == "gray" and img.mode != "L":
        img = img.convert("L")
    return img


def image_to_numpy(img: Image.Image) -> np.ndarray:
    return np.array(img)
