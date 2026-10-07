"""OCR helpers – Tesseract with English + Bengali support."""
from __future__ import annotations

import logging
import re
import shutil
from typing import Optional

from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


class OCRUnavailableError(RuntimeError):
    """The Tesseract executable or requested language data is unavailable."""


class OCRProcessingError(RuntimeError):
    """Tesseract failed to recognize a page."""


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


def get_installed_languages() -> list[str]:
    """Return list of language codes installed in Tesseract (excluding 'osd')."""
    if not _TESSERACT_AVAILABLE or shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
        return []
    try:
        langs = pytesseract.get_languages(config="")
        return [lang for lang in langs if lang != "osd"]
    except Exception:
        return []


def detect_language(img: Image.Image, default: str = "eng") -> str:
    """
    Detect script/language of an image using Tesseract OSD (Orientation and Script Detection)
    or fall back to installed languages.
    """
    installed = get_installed_languages()
    if not installed:
        return default

    # Map Tesseract OSD script names to language codes
    script_to_lang: dict[str, str] = {
        "Latin": "eng",
        "Bengali": "ben",
        "Arabic": "ara",
        "Devanagari": "hin",
        "Cyrillic": "rus",
        "Han": "chi_sim",
        "Japanese": "jpn",
    }

    try:
        osd_data = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        script = osd_data.get("script", "")
        detected_lang = script_to_lang.get(script)
        if detected_lang and detected_lang in installed:
            # If English is also installed and different from detected, combine them for better accuracy
            if detected_lang != "eng" and "eng" in installed:
                return f"{detected_lang}+eng"
            return detected_lang
    except Exception as exc:
        logger.debug("Tesseract OSD script detection failed: %s", exc)

    # If detection failed or not matched, combine prioritized installed languages
    # Prefer eng + ben if available
    preferred = [code for code in ("eng", "ben") if code in installed]
    if preferred:
        return "+".join(preferred)
    return "+".join(installed[:3]) if installed else default


def resolve_ocr_language(lang: str | None, img: Image.Image | None = None) -> str:
    """
    Resolve requested language. If 'auto' or empty, detect from image or installed languages.
    """
    settings = get_settings()
    requested = (lang or "").strip().lower()

    if not requested or requested == "auto":
        if img is not None:
            return detect_language(img, default=settings.OCR_LANGUAGE)
        installed = get_installed_languages()
        if installed:
            preferred = [code for code in ("eng", "ben") if code in installed]
            return "+".join(preferred) if preferred else "+".join(installed[:2])
        return settings.OCR_LANGUAGE

    return lang.strip()


def ocr_image(
    img: Image.Image,
    *,
    lang: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Run Tesseract OCR on a PIL Image.
    Supports 'auto' for automatic language detection.
    Fail explicitly when the engine or requested language data is unavailable.
    """
    settings = get_settings()
    timeout = timeout or settings.OCR_TIMEOUT
    resolved_lang = resolve_ocr_language(lang, img)

    if not ocr_available(resolved_lang):
        raise OCRUnavailableError(
            f"Tesseract OCR or language data '{resolved_lang}' is not available on this server."
        )
    try:
        text = pytesseract.image_to_string(
            img,
            lang=resolved_lang,
            config="--psm 6",
            timeout=timeout,
        )
        recognized = (text or "").strip()
        if not recognized:
            raise OCRProcessingError("Tesseract did not recognize any text on the page.")
        return recognized
    except Exception as exc:
        if isinstance(exc, (OCRProcessingError, OCRUnavailableError)):
            raise
        logger.warning("OCR failed: %s", exc)
        raise OCRProcessingError("Tesseract failed to recognize text on the page.") from exc


def ocr_image_words(
    img: Image.Image,
    *,
    lang: Optional[str] = None,
    timeout: Optional[int] = None,
) -> list[dict[str, object]]:
    """
    Run Tesseract OCR and return word-level bounding boxes and text.
    Returns list of dicts: {"text": str, "left": int, "top": int, "width": int, "height": int, "conf": float}
    """
    settings = get_settings()
    timeout = timeout or settings.OCR_TIMEOUT
    resolved_lang = resolve_ocr_language(lang, img)

    if not ocr_available(resolved_lang):
        raise OCRUnavailableError(
            f"Tesseract OCR or language data '{resolved_lang}' is not available on this server."
        )

    try:
        data = pytesseract.image_to_data(
            img,
            lang=resolved_lang,
            output_type=pytesseract.Output.DICT,
            timeout=timeout,
        )
        words: list[dict[str, object]] = []
        n_boxes = len(data.get("text", []))
        for idx in range(n_boxes):
            word_text = (data["text"][idx] or "").strip()
            conf = float(data["conf"][idx]) if "conf" in data else 0.0
            if not word_text or conf <= 0:
                continue
            words.append({
                "text": word_text,
                "left": int(data["left"][idx]),
                "top": int(data["top"][idx]),
                "width": int(data["width"][idx]),
                "height": int(data["height"][idx]),
                "conf": conf,
            })
        return words
    except Exception as exc:
        if isinstance(exc, (OCRProcessingError, OCRUnavailableError)):
            raise
        logger.warning("OCR word extraction failed: %s", exc)
        raise OCRProcessingError("Tesseract failed to recognize text on the page.") from exc



def ocr_available(lang: str | None = None) -> bool:
    if not _TESSERACT_AVAILABLE or shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
        return False
    if lang is None or lang.strip().lower() == "auto":
        installed = get_installed_languages()
        return len(installed) > 0

    language_codes = lang.split("+")
    if any(not re.fullmatch(r"[A-Za-z0-9_]{2,16}", code) for code in language_codes):
        return False
    try:
        installed_languages = pytesseract.get_languages(config="")
    except Exception:
        return False
    return all(code in installed_languages for code in language_codes)

