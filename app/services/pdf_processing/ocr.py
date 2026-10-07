"""OCR helpers – Tesseract with English + Bengali support."""
from __future__ import annotations

import logging
from typing import Optional

from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)

_TESSERACT_AVAILABLE = False
try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    logger.warning("pytesseract not installed – OCR features disabled")


def page_has_text(page) -> bool:
    """Return True if the page has a usable text layer."""
    try:
        text = page.get_text("text") or ""
        return len(text.strip()) > 20
    except Exception:
        return False


def ocr_image(
    img: Image.Image,
    *,
    lang: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Run Tesseract OCR on a PIL Image.
    Returns empty string if OCR is unavailable or fails.
    """
    if not _TESSERACT_AVAILABLE:
        return ""

    settings = get_settings()
    lang = lang or settings.OCR_LANGUAGE
    timeout = timeout or settings.OCR_TIMEOUT

    try:
        # pytesseract timeout is in seconds (requires tesseract >= 4)
        config = f"--psm 6"
        text = pytesseract.image_to_string(
            img,
            lang=lang,
            config=config,
            timeout=timeout,
        )
        return (text or "").strip()
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""


def ocr_available() -> bool:
    return _TESSERACT_AVAILABLE
